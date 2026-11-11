"""Read-only clearing endpoints over ``pm-clearing``'s ``clearing.db``.

Every route reads the ledger pm-clearing writes, opened read-only on a worker
thread; nothing here writes, and nothing is derived that the ledger does not
hold (no margin, equity or open interest). Rows are scoped by
``clearing_scope``: ADMIN reads the venue, a TRADER or MARKET_MAKER its own
gateway.

Units: a money column of a row is returned as the stored tick value
(``*_ticks``) beside ``tick_decimals`` and as the row's display-currency value.
Only display values are ever summed across rows, because one tick is a
different amount of money per symbol.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import sqlite3
from collections.abc import Callable
from contextlib import closing
from typing import Annotated, Any, Literal, TypeVar
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from edumatcher.api_gateway import openapi_docs as docs
from edumatcher.api_gateway.clearing_scope import ClearingScope, clearing_scope
from edumatcher.api_gateway.params import GatewayIdPath
from edumatcher.api_gateway.responses import (
    ClearingDaily,
    ClearingHealth,
    ClearingPositions,
    ClearingSummary,
    ClearingSymbols,
    ClearingTradePage,
    CloseSnapshots,
    Exposure,
    Balances,
    GatewaySessions,
    ParticipantDetail,
    Participants,
    Reconciliation,
    SessionEvents,
    Settlements,
)
from edumatcher.api_gateway.routing import ContractRoute
from edumatcher.api_gateway.sessions import Session, auth, require_admin
from edumatcher.clearing.query import day_bounds_ns, open_readonly_connection
from edumatcher.clearing.store import (
    query_close_snapshots,
    query_daily,
    query_exposure,
    query_feed_gaps,
    query_freshness,
    query_health,
    query_participants,
    query_positions,
    query_reconcile,
    query_retained_from,
    query_session_events,
    query_sessions,
    query_symbols,
    query_trades,
)
from edumatcher.config import CLEARING_HEALTH_ADDR
from edumatcher.healthcheck import ping_health_endpoint
from edumatcher.eod.ledger import (
    balances,
    last_settled_on_or_before,
    open_ledger_readonly,
    query_runs,
    query_settlements,
    run_for,
    runs,
)
from edumatcher.eod.report import fmt_minor
from edumatcher.eod.roster import RosterError, load_roster
from edumatcher.eod.settle import EXCHANGE
from edumatcher.stats.query import validate_date

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/clearing", tags=["clearing"], route_class=ContractRoute
)

#: How long a read waits out pm-clearing's write lock before answering 503.
_BUSY_TIMEOUT_MS = 5000
#: pm-clearing's health socket -- the one `pm-clearing-cli health` pings.
_HEALTH_ADDR = CLEARING_HEALTH_ADDR
#: Bound on the liveness ping, so a dead process costs one short wait.
_HEALTH_TIMEOUT_MS = 500

_T = TypeVar("_T")

_Limit = Annotated[int, Query(ge=1, le=5000, description="Maximum rows (1-5000).")]
_Gateway = Annotated[
    str | None,
    Query(
        description=(
            "Only this gateway (case-insensitive). ADMIN only: a participant "
            "key may name only itself, and is scoped to itself without it."
        )
    ),
]
_Symbol = Annotated[
    str | None, Query(description="Only this symbol (case-insensitive).")
]
_Date = Annotated[
    str | None,
    Query(description="One trading day, `YYYY-MM-DD`, in the session timezone."),
]
_FromDate = Annotated[
    str | None,
    Query(alias="from", description="First trading day, `YYYY-MM-DD`, inclusive."),
]
_ToDate = Annotated[
    str | None,
    Query(alias="to", description="Last trading day, `YYYY-MM-DD`, inclusive."),
]
_ExposureSort = Annotated[
    Literal[
        "gross_notional", "net_notional", "realized_pnl", "unrealized_pnl", "total_pnl"
    ],
    Query(description="Rank by this measure, largest first, in display currency."),
]

_POSITION_MONEY = (
    "avg_cost",
    "mark_price",
    "realized_pnl",
    "unrealized_pnl",
    "buy_notional",
    "sell_notional",
)
_EXPOSURE_MONEY = (
    "mark_price",
    "net_notional",
    "gross_notional",
    "realized_pnl",
    "unrealized_pnl",
    "total_pnl",
)
_DAILY_MONEY = (
    "traded_notional",
    "buy_notional",
    "sell_notional",
    "net_amount",
    "realized_pnl",
    "end_avg_cost",
    "end_unrealized_pnl",
)
_CLOSE_MONEY = ("realized_pnl", "unrealized_pnl", "mark_price")
_RECONCILE_MONEY = ("raw_notional", "summary_notional", "notional_diff")
_EVENT_TYPES = ("EOD", "PHASE", "GAP")
_SYMBOL_MONEY = ("traded_notional", "realized_pnl", "open_unrealized_pnl")


# ---------------------------------------------------------------------------
# Store access
# ---------------------------------------------------------------------------


def _unavailable(code: str, what: str, exc: Exception) -> HTTPException:
    """``503`` naming the store, never its path: the reply may reach a browser."""
    reason = "not found" if isinstance(exc, FileNotFoundError) else str(exc)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": {"code": code, "message": f"{what} unavailable: {reason}"}},
    )


async def _in_clearing_db(
    request: Request, work: Callable[[sqlite3.Connection], _T]
) -> _T:
    """Run *work* against ``clearing.db`` on a worker thread.

    A missing, locked or unreadable ledger is ``503 CLEARING_DB``: never an
    empty answer, which a client could not tell from "no positions".
    """
    path = request.app.state.config.clearing_db

    def _run() -> _T:
        with closing(open_readonly_connection(path, _BUSY_TIMEOUT_MS)) as conn:
            return work(conn)

    try:
        return await asyncio.to_thread(_run)
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        log.warning("clearing: cannot read %s: %s", path, exc)
        raise _unavailable("CLEARING_DB", "Clearing ledger", exc) from exc


async def _in_eod_db(request: Request, work: Callable[[sqlite3.Connection], _T]) -> _T:
    """Run *work* against ``eod.db`` on a worker thread; ``503 EOD_DB`` when the
    ledger is missing or unreadable -- which is not the same answer as a day
    pm-eod has not settled (an empty list)."""
    path = request.app.state.config.eod_db

    def _run() -> _T:
        with closing(open_ledger_readonly(path)) as conn:
            return work(conn)

    try:
        return await asyncio.to_thread(_run)
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        log.warning("clearing: cannot read %s: %s", path, exc)
        raise _unavailable("EOD_DB", "EOD ledger", exc) from exc


def _invalid(field: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": {"code": "VALIDATION", "message": message, "field": field}},
    )


def _check_dates(
    date: str | None = None, from_date: str | None = None, to_date: str | None = None
) -> None:
    """``400`` for a malformed date, or a range that ends before it starts."""
    for field, value in (("date", date), ("from", from_date), ("to", to_date)):
        if value is not None:
            try:
                validate_date(value)
            except ValueError as exc:
                raise _invalid(field, str(exc)) from exc
    if from_date is not None and to_date is not None and from_date > to_date:
        raise _invalid("from", f"from {from_date} is after to {to_date}")


def _upper(value: str | None) -> str | None:
    """A filter value as stored; blank is no filter."""
    return (value or "").strip().upper() or None


def _with_money(row: dict[str, Any], money: tuple[str, ...]) -> dict[str, Any]:
    """*row* with each *money* column as ``<name>_ticks`` (stored) and ``<name>``
    (display currency, this row's own precision)."""
    out = dict(row)
    if not money:
        return out
    scale = 10 ** int(row["tick_decimals"])
    for name in money:
        value = row[name]
        out[f"{name}_ticks"] = value
        out[name] = None if value is None else value / scale
    return out


def _bounded(
    key: str, found: list[dict[str, Any]], limit: int, money: tuple[str, ...]
) -> dict[str, Any]:
    """The list envelope of a query run with ``limit + 1``: the extra row only
    says that more match."""
    shown = [_with_money(r, money) for r in found[:limit]]
    return {key: shown, "count": len(shown), "has_more": len(found) > limit}


def _encode_cursor(row: dict[str, Any]) -> str:
    """The ``query_trades`` sort key of *row*, opaque to the client."""
    raw = f"{row['ts_ns']}:{row['ingest_ts_ns']}:{row['id']}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, int, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        text = base64.urlsafe_b64decode(padded).decode()
        ts_text, ingest_text, trade_id = text.split(":", 2)
        return int(ts_text), int(ingest_text), trade_id
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise _invalid("after", "Invalid cursor; pass back `next_cursor`") from exc


def _trade_row(row: dict[str, Any], scope: ClearingScope) -> dict[str, Any]:
    """One trade as the caller may see it: a participant gets its own side
    only, never the counterparty's gateway or order id."""
    trade = _with_money(row, ("price",))
    trade["trade_id"] = trade.pop("id")
    if not scope.admin:
        for side in ("buy", "sell"):
            if trade[f"{side}_gateway_id"] != scope.caller:
                trade[f"{side}_gateway_id"] = None
                trade[f"{side}_order_id"] = None
    return trade


def _event_row(row: dict[str, Any]) -> dict[str, Any]:
    """A ``session_events`` row with its payload decoded into the one field
    its type names; the raw JSON is not part of the contract."""
    payload = json.loads(row["payload_json"] or "{}")
    event: dict[str, Any] = {
        "id": row["id"],
        "event_type": row["event_type"],
        "ts_ns": row["ts_ns"],
        "trade_date": row["trade_date"],
    }
    if row["event_type"] == "PHASE":
        event["phase"] = {
            "state": payload.get("state", ""),
            "prev_state": payload.get("prev_state") or None,
        }
    elif row["event_type"] == "GAP":
        event["gap"] = {
            key: payload.get(key)
            for key in ("run_seq", "last_seq", "next_seq", "missing_trades")
        }
    elif row["event_type"] == "EOD":
        # The marks are ticks without their precision; the closing marks are
        # in the close snapshots, with it.
        marked = sorted(payload.get("eod_marks") or {})
        event["eod"] = {
            "symbols_count": int(payload.get("symbols_count", len(marked))),
            "marked_symbols": marked,
        }
    return event


def _database_health(request: Request) -> dict[str, Any]:
    """``clearing.db``'s own facts, or why it could not be read."""
    path = request.app.state.config.clearing_db
    try:
        with closing(open_readonly_connection(path, _BUSY_TIMEOUT_MS)) as conn:
            facts = query_health(conn, path)[0]
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        log.warning("clearing: cannot read %s: %s", path, exc)
        reason = "not found" if isinstance(exc, FileNotFoundError) else str(exc)
        return {
            "available": False,
            "detail": reason,
            "wal_mode": None,
            "trade_events_rows": None,
            "gateway_symbol_positions_rows": None,
            "gateway_daily_summary_rows": None,
            "last_trade_ts_ns": None,
            "last_flush_ts_ns": None,
        }
    facts.pop("db_path")  # never to a client
    return {"available": True, "detail": "readable", **facts}


def _links(gateway_id: str) -> dict[str, str]:
    base = router.prefix
    query = f"?gateway={quote(gateway_id, safe='')}"
    return {
        "positions": f"{base}/positions{query}",
        "exposure": f"{base}/exposure{query}",
        "trades": f"{base}/trades{query}",
        "daily": f"{base}/daily{query}",
        "close_snapshots": f"{base}/close-snapshots{query}",
        "gateway_sessions": f"{base}/gateway-sessions{query}",
        "settlements": f"{base}/settlements{query}",
        "balances": f"{base}/balances{query}",
    }


def _last_eod_run(request: Request) -> tuple[bool, dict[str, Any] | None]:
    """pm-eod's newest run, and whether its ledger could be read at all."""
    path = request.app.state.config.eod_db
    try:
        with closing(open_ledger_readonly(path)) as conn:
            newest = runs(conn, limit=1)
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        log.warning("clearing summary: cannot read %s: %s", path, exc)
        return False, None
    return True, (_eod_run(newest[0]) if newest else None)


def _eod_run(row: dict[str, Any], steps: bool = True) -> dict[str, Any]:
    """A run as the API shows it; its step messages are for operators only."""
    run = {
        "trade_date": row["trade_date"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }
    if steps:
        run["steps"] = json.loads(row["steps_json"])
    return run


def _openings(request: Request) -> dict[str, int]:
    """Opening balances from pm-eod's roster, minor units; none without one."""
    path = request.app.state.config.eod_roster
    try:
        roster = load_roster(path)
    except (RosterError, OSError, ValueError) as exc:
        # The reason names the file and line: logged, not sent to a browser.
        log.warning("clearing: cannot read the EOD roster: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "EOD_DB",
                    "message": "EOD roster unreadable; see the gateway log",
                }
            },
        ) from exc
    return {gateway: trader.opening_minor for gateway, trader in roster.items()}


# ---------------------------------------------------------------------------
# Venue (ADMIN)
# ---------------------------------------------------------------------------


@router.get(
    "/summary",
    response_model=ClearingSummary,
    summary="Clearing overview",
    responses=docs.merge(
        docs.ok(docs.CLEARING_SUMMARY, "The venue's clearing state."),
        docs.errors(*docs.TRADING_KEY, "CLEARING_DB", "ROLE_DENIED"),
    ),
)
async def clearing_summary(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    """Position and P&L totals, freshness, feed gaps and the last EOD run.

    Totals are in display currency, each position converted before the sum.
    `last_flush_ts_ns` is the latest committed clearing write: a fill may take
    up to the flush interval to appear. `gap_count` counts the trade-id jumps
    clearing saw on `session_date`; no gap does not prove the feed was
    complete. A missing EOD ledger is `eod_db_available: false`, not an
    error.
    """
    await require_admin(request, session)

    def _query(conn: sqlite3.Connection) -> dict[str, Any]:
        participants = query_participants(conn, limit=1_000_000)
        fresh = query_freshness(conn)
        row = conn.execute("SELECT MAX(trade_date) FROM session_events").fetchone()
        session_date = row[0] if row else None
        gaps = (
            query_feed_gaps(conn, from_date=session_date, to_date=session_date)
            if session_date
            else []
        )
        latest = query_feed_gaps(conn, limit=1)
        return {
            "participant_count": len(participants),
            "open_position_count": sum(p["open_position_count"] for p in participants),
            "realized_pnl": sum(p["realized_pnl"] for p in participants),
            "unrealized_pnl": sum(p["unrealized_pnl"] for p in participants),
            "last_trade_ts_ns": fresh["last_trade_ts_ns"],
            "last_flush_ts_ns": fresh["last_flush_ts_ns"],
            "session_date": session_date,
            "gap_count": len(gaps),
            "latest_gap": latest[0] if latest else None,
        }

    summary = await _in_clearing_db(request, _query)
    available, last_run = await asyncio.to_thread(_last_eod_run, request)
    return {**summary, "eod_db_available": available, "last_eod_run": last_run}


@router.get(
    "/participants",
    response_model=Participants,
    summary="Participant gateways",
    responses=docs.merge(
        docs.ok(docs.CLEARING_PARTICIPANTS_REPLY, "Every gateway with a position row."),
        docs.errors(*docs.TRADING_KEY, "CLEARING_DB", "ROLE_DENIED", "VALIDATION"),
    ),
)
async def clearing_participants(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    limit: _Limit = 1000,
) -> dict[str, Any]:
    """Each gateway's P&L in display currency, position counts and latest
    update. A gateway that never traded has no row."""
    await require_admin(request, session)

    def _query(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        return query_participants(conn, limit=limit + 1)

    found = await _in_clearing_db(request, _query)
    return _bounded("participants", found, limit, ())


@router.get(
    "/symbols",
    response_model=ClearingSymbols,
    summary="Symbol activity",
    responses=docs.merge(
        docs.ok(docs.CLEARING_SYMBOLS_REPLY, "Per symbol traded in the date range."),
        docs.errors(*docs.TRADING_KEY, "CLEARING_DB", "ROLE_DENIED", "VALIDATION"),
    ),
)
async def clearing_symbols(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    date: _Date = None,
    from_date: _FromDate = None,
    to_date: _ToDate = None,
    limit: _Limit = 1000,
) -> dict[str, Any]:
    """Traded quantity, value and realized P&L per symbol over the days, plus
    the current aggregate net position and its open P&L.

    `open_net_qty` sums signed positions, so it is zero whenever every holder
    is a gateway: it is not open interest.
    """
    await require_admin(request, session)
    _check_dates(date, from_date, to_date)

    def _query(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        return query_symbols(
            conn,
            date_value=date,
            from_date=from_date,
            to_date=to_date,
            limit=limit + 1,
        )

    found = await _in_clearing_db(request, _query)
    return _bounded("symbols", found, limit, _SYMBOL_MONEY)


# ---------------------------------------------------------------------------
# Gateway-scoped (ADMIN, or the caller's own gateway)
# ---------------------------------------------------------------------------


@router.get(
    "/participants/{gateway_id}",
    response_model=ParticipantDetail,
    summary="One participant gateway",
    responses=docs.merge(
        docs.ok(docs.CLEARING_PARTICIPANT, "The gateway's current clearing state."),
        docs.errors(*docs.TRADING_KEY, "CLEARING_DB", "SCOPE_DENIED", "VALIDATION"),
    ),
)
async def clearing_participant(
    gateway_id: GatewayIdPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    """Totals and positions of one gateway, with the routes for its other views.

    A gateway clearing has no rows for answers zeros and an empty list: that
    is a true zero, not an error.
    """
    scope = await clearing_scope(request, session, gateway_id)
    target = scope.gateway or scope.caller

    def _query(conn: sqlite3.Connection) -> dict[str, Any]:
        totals = query_participants(conn, gateway=target)
        positions = query_positions(conn, gateway=target)
        latest = query_close_snapshots(conn, gateway=target, limit=1)
        row: dict[str, Any] = (
            totals[0]
            if totals
            else {
                "gateway_id": target,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "total_pnl": 0.0,
                "position_count": 0,
                "open_position_count": 0,
                "last_update_ts_ns": None,
            }
        )
        return {
            **row,
            "positions": [_with_money(p, _POSITION_MONEY) for p in positions],
            "latest_close_date": latest[0]["trade_date"] if latest else None,
            "links": _links(target),
        }

    return await _in_clearing_db(request, _query)


@router.get(
    "/positions",
    response_model=ClearingPositions,
    summary="Current positions",
    responses=docs.merge(
        docs.ok(docs.CLEARING_POSITIONS_REPLY, "Positions as of the latest flush."),
        docs.errors(*docs.TRADING_KEY, "CLEARING_DB", "SCOPE_DENIED", "VALIDATION"),
    ),
)
async def clearing_positions(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    gateway: _Gateway = None,
    symbol: _Symbol = None,
    limit: _Limit = 1000,
) -> dict[str, Any]:
    """Each gateway/symbol position at its mark, as of the latest clearing
    flush (fills arrive in batches, up to 5 s after the trade by default)."""
    scope = await clearing_scope(request, session, gateway)

    def _query(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        return query_positions(
            conn, gateway=scope.gateway, symbol=_upper(symbol), limit=limit + 1
        )

    found = await _in_clearing_db(request, _query)
    return _bounded("positions", found, limit, _POSITION_MONEY)


@router.get(
    "/exposure",
    response_model=Exposure,
    summary="Marked exposure",
    responses=docs.merge(
        docs.ok(docs.CLEARING_EXPOSURE_REPLY, "Positions valued at their marks."),
        docs.errors(*docs.TRADING_KEY, "CLEARING_DB", "SCOPE_DENIED", "VALIDATION"),
    ),
)
async def clearing_exposure(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    gateway: _Gateway = None,
    symbol: _Symbol = None,
    sort: _ExposureSort = "gross_notional",
    limit: _Limit = 1000,
) -> dict[str, Any]:
    """Net and gross notional and P&L per position, each valued in its own
    precision. A position without a mark has null notionals."""
    scope = await clearing_scope(request, session, gateway)

    def _query(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        return query_exposure(
            conn,
            gateway=scope.gateway,
            symbol=_upper(symbol),
            sort=sort,
            limit=limit + 1,
        )

    found = await _in_clearing_db(request, _query)
    return _bounded("exposure", found, limit, _EXPOSURE_MONEY)


@router.get(
    "/trades",
    response_model=ClearingTradePage,
    summary="Retained trades",
    responses=docs.merge(
        docs.ok(docs.CLEARING_TRADES_REPLY, "One page of trades, newest first."),
        docs.errors(
            *docs.TRADING_KEY,
            "CLEARING_DB",
            "SCOPE_DENIED",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def clearing_trades(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    gateway: _Gateway = None,
    symbol: _Symbol = None,
    date: _Date = None,
    from_date: _FromDate = None,
    to_date: _ToDate = None,
    limit: Annotated[
        int, Query(ge=1, le=5000, description="Maximum rows per page (1-5000).")
    ] = 500,
    after: Annotated[
        str | None,
        Query(
            description="Pagination cursor: the previous page's `next_cursor`, "
            "with the same filters."
        ),
    ] = None,
) -> dict[str, Any]:
    """The raw executions clearing holds, newest first, keyset-paginated.

    Raw trades are pruned after the retention window (90 days by default);
    `retained_from` is the oldest day still held. `ts_ns` is the exchange's
    time of the print and `ingest_ts_ns` clearing's own write time. A
    participant sees its own side of each trade only.
    """
    scope = await clearing_scope(request, session, gateway)
    _check_dates(date, from_date, to_date)
    cursor = _decode_cursor(after) if after is not None else None

    def _query(conn: sqlite3.Connection) -> dict[str, Any]:
        found = query_trades(
            conn,
            gateway=scope.gateway,
            symbol=_upper(symbol),
            date_value=date,
            from_date=from_date,
            to_date=to_date,
            limit=limit + 1,
            after=cursor,
        )
        shown = found[:limit]
        more = len(found) > limit
        return {
            "trades": [_trade_row(t, scope) for t in shown],
            "count": len(shown),
            "has_more": more,
            "next_cursor": _encode_cursor(shown[-1]) if more else None,
            "retained_from": query_retained_from(conn),
        }

    return await _in_clearing_db(request, _query)


@router.get(
    "/daily",
    response_model=ClearingDaily,
    summary="Daily activity and realized P&L",
    responses=docs.merge(
        docs.ok(docs.CLEARING_DAILY_REPLY, "Daily rows, newest day first."),
        docs.errors(
            *docs.TRADING_KEY,
            "CLEARING_DB",
            "SCOPE_DENIED",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def clearing_daily(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    gateway: _Gateway = None,
    symbol: _Symbol = None,
    date: _Date = None,
    from_date: _FromDate = None,
    to_date: _ToDate = None,
    limit: _Limit = 1000,
) -> dict[str, Any]:
    """Per day, gateway and symbol traded: quantities, values, realized P&L
    and the end-of-day position. Kept after the raw trades are pruned."""
    scope = await clearing_scope(request, session, gateway)
    _check_dates(date, from_date, to_date)

    def _query(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        return query_daily(
            conn,
            gateway=scope.gateway,
            symbol=_upper(symbol),
            date_value=date,
            from_date=from_date,
            to_date=to_date,
            limit=limit + 1,
        )

    found = await _in_clearing_db(request, _query)
    return _bounded("daily", found, limit, _DAILY_MONEY)


@router.get(
    "/close-snapshots",
    response_model=CloseSnapshots,
    summary="Positions at each close",
    responses=docs.merge(
        docs.ok(docs.CLEARING_CLOSE_SNAPSHOTS_REPLY, "Close snapshots, newest first."),
        docs.errors(
            *docs.TRADING_KEY,
            "CLEARING_DB",
            "SCOPE_DENIED",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def clearing_close_snapshots(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    gateway: _Gateway = None,
    symbol: _Symbol = None,
    date: _Date = None,
    from_date: _FromDate = None,
    to_date: _ToDate = None,
    limit: _Limit = 1000,
) -> dict[str, Any]:
    """One row per gateway and symbol for every session close: the position,
    cumulative P&L and closing mark. The close-to-close series that EOD
    settlement uses; there is no intraday history."""
    scope = await clearing_scope(request, session, gateway)
    _check_dates(date, from_date, to_date)

    def _query(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        return query_close_snapshots(
            conn,
            gateway=scope.gateway,
            symbol=_upper(symbol),
            date_value=date,
            from_date=from_date,
            to_date=to_date,
            limit=limit + 1,
        )

    found = await _in_clearing_db(request, _query)
    return _bounded("snapshots", found, limit, _CLOSE_MONEY)


# ---------------------------------------------------------------------------
# Operational evidence
# ---------------------------------------------------------------------------


@router.get(
    "/session-events",
    response_model=SessionEvents,
    summary="Session events clearing recorded",
    responses=docs.merge(
        docs.ok(docs.CLEARING_SESSION_EVENTS_REPLY, "Events, newest first."),
        docs.errors(*docs.TRADING_KEY, "CLEARING_DB", "ROLE_DENIED", "VALIDATION"),
    ),
)
async def clearing_session_events(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    event_type: Annotated[
        str | None,
        Query(
            alias="type",
            description="Only `EOD`, `PHASE` or `GAP` (case-insensitive).",
        ),
    ] = None,
    from_date: _FromDate = None,
    to_date: _ToDate = None,
    limit: _Limit = 1000,
) -> dict[str, Any]:
    """Session phases, the engine's end of day, and feed gaps.

    Times are when clearing observed the event, not engine times. A `GAP` is
    a jump in the trade ids clearing received: trades it never got. No gap
    does not prove the feed was complete.
    """
    await require_admin(request, session)
    _check_dates(None, from_date, to_date)
    wanted = event_type.strip().upper() if event_type else None
    if wanted is not None and wanted not in _EVENT_TYPES:
        raise _invalid(
            "type",
            f"Unknown type {event_type!r}; expected one of " + ", ".join(_EVENT_TYPES),
        )

    def _query(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        found = query_session_events(
            conn,
            event_type=wanted,
            from_date=from_date,
            to_date=to_date,
            limit=limit + 1,
        )
        return [_event_row(r) for r in found]

    found = await _in_clearing_db(request, _query)
    return _bounded("events", found, limit, ())


@router.get(
    "/gateway-sessions",
    response_model=GatewaySessions,
    summary="Gateway connect/disconnect history",
    responses=docs.merge(
        docs.ok(docs.CLEARING_GATEWAY_SESSIONS_REPLY, "Sessions, newest first."),
        docs.errors(
            *docs.TRADING_KEY,
            "CLEARING_DB",
            "SCOPE_DENIED",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def clearing_gateway_sessions(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    gateway: _Gateway = None,
    from_date: Annotated[
        str | None,
        Query(
            alias="from",
            description="First trading day of the connect, `YYYY-MM-DD`, "
            "inclusive, in the session timezone.",
        ),
    ] = None,
    to_date: Annotated[
        str | None,
        Query(
            alias="to",
            description="Last trading day of the connect, `YYYY-MM-DD`, inclusive.",
        ),
    ] = None,
    connected_only: Annotated[
        bool,
        Query(description="Only sessions without a recorded disconnect."),
    ] = False,
    limit: _Limit = 1000,
) -> dict[str, Any]:
    """When clearing saw each gateway connect and disconnect, and why.

    Times are clearing's observations. A session without a disconnect is one
    still connected, or one whose disconnect clearing did not see.
    """
    scope = await clearing_scope(request, session, gateway)
    _check_dates(None, from_date, to_date)

    def _query(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        from_ns, to_ns = day_bounds_ns(conn, from_date, to_date)
        found = query_sessions(
            conn,
            gateway=scope.gateway,
            connected_only=connected_only,
            from_ns=from_ns,
            to_ns=to_ns,
            limit=limit + 1,
        )
        return [
            {
                "gateway_id": r["gateway_id"],
                "connected_at_ns": r["connected_at_ns"],
                "disconnected_at_ns": r["disconnected_at_ns"],
                "disconnect_reason": r["disconnect_reason"],
            }
            for r in found
        ]

    found = await _in_clearing_db(request, _query)
    return _bounded("sessions", found, limit, ())


@router.get(
    "/reconciliation",
    response_model=Reconciliation,
    summary="Raw trades against daily rows",
    responses=docs.merge(
        docs.ok(docs.CLEARING_RECONCILIATION_REPLY, "Discrepancies in the range."),
        docs.errors(
            *docs.TRADING_KEY,
            "CLEARING_DB",
            "ROLE_DENIED",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def clearing_reconciliation(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    from_date: Annotated[
        str,
        Query(alias="from", description="First trading day, `YYYY-MM-DD`. Required."),
    ],
    to_date: Annotated[
        str,
        Query(alias="to", description="Last trading day, `YYYY-MM-DD`. Required."),
    ],
    gateway: Annotated[str | None, Query(description="Only this gateway.")] = None,
    symbol: _Symbol = None,
    limit: _Limit = 1000,
) -> dict[str, Any]:
    """Every day, side, gateway and symbol where the quantities or values
    counted from the raw trades differ from the daily rows.

    It scans the raw trades of the range, so it takes an explicit range and is
    not for polling. Raw trades are pruned after the retention window while
    the daily rows stay, so only days from `retained_from` on are compared
    (`compared_from`, `compared_to`). An empty list means no discrepancy in
    the data compared, not a verified complete history.
    """
    await require_admin(request, session)
    _check_dates(None, from_date, to_date)

    def _query(conn: sqlite3.Connection) -> dict[str, Any]:
        retained = query_retained_from(conn)
        start = max(from_date, retained) if retained else None
        window = start is not None and start <= to_date
        found = (
            query_reconcile(
                conn,
                gateway=_upper(gateway),
                symbol=_upper(symbol),
                from_date=start,
                to_date=to_date,
            )
            if window
            else []
        )
        return {
            **_bounded("discrepancies", found, limit, _RECONCILE_MONEY),
            "retained_from": retained,
            "compared_from": start if window else None,
            "compared_to": to_date if window else None,
        }

    return await _in_clearing_db(request, _query)


@router.get(
    "/health",
    response_model=ClearingHealth,
    summary="Clearing database and process health",
    responses=docs.merge(
        docs.ok(docs.CLEARING_HEALTH, "Both health dimensions, always."),
        docs.errors(*docs.TRADING_KEY, "ROLE_DENIED"),
    ),
)
async def clearing_health(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    """Whether `clearing.db` is readable (with its row counts, journal mode
    and latest trade and flush times), and, separately, whether pm-clearing's
    receive loop answers a ping. A readable database does not prove the
    process is alive, and a silent process does not hide the database facts:
    both are reported, in a `200`. Each call pings once, so poll it sparingly.
    """
    await require_admin(request, session)
    database, (alive, detail) = await asyncio.gather(
        asyncio.to_thread(_database_health, request),
        asyncio.to_thread(ping_health_endpoint, _HEALTH_ADDR, _HEALTH_TIMEOUT_MS),
    )
    return {"database": database, "process": {"alive": alive, "detail": detail}}


# ---------------------------------------------------------------------------
# EOD settlement (pm-eod's eod.db)
# ---------------------------------------------------------------------------


@router.get(
    "/settlements",
    response_model=Settlements,
    summary="EOD settlements",
    responses=docs.merge(
        docs.ok(docs.CLEARING_SETTLEMENTS_REPLY, "Settlement rows and runs."),
        docs.errors(
            *docs.TRADING_KEY,
            "EOD_DB",
            "SCOPE_DENIED",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def clearing_settlements(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    gateway: Annotated[
        str | None,
        Query(
            description="Only this account (case-insensitive): a gateway, or "
            "`EXCHANGE` for ADMIN. A participant may name only itself."
        ),
    ] = None,
    date: _Date = None,
    from_date: _FromDate = None,
    to_date: _ToDate = None,
    limit: _Limit = 1000,
) -> dict[str, Any]:
    """pm-eod's daily settlement per account, in integer minor units.

    A settlement is the day's change in the account's close-to-close P&L,
    transferred: positive means the exchange owes the gateway. It is not
    margin, collateral or a completed payment, and exists only for days
    pm-eod has settled; a day without one is an empty list, with its run (if
    any) in `runs`. `EXCHANGE` carries the rounding residual and is ADMIN
    only.
    """
    scope = await clearing_scope(request, session, gateway)
    _check_dates(date, from_date, to_date)

    def _query(conn: sqlite3.Connection) -> dict[str, Any]:
        window = {"date_value": date, "from_date": from_date, "to_date": to_date}
        found = query_settlements(
            conn,
            account=scope.gateway,
            include_exchange=scope.admin,
            limit=limit + 1,
            **window,
        )
        shown = found[:limit]
        status_of = {}
        for day in {r["trade_date"] for r in shown}:
            run = run_for(conn, day)
            status_of[day] = run["status"] if run else None
        settlements = [
            {
                "trade_date": r["trade_date"],
                "account": r["account"],
                "amount_minor": r["amount_minor"],
                "amount": fmt_minor(r["amount_minor"]),
                "detail": json.loads(r["detail_json"]),
                "run_status": status_of[r["trade_date"]],
            }
            for r in shown
        ]
        recorded = query_runs(conn, limit=limit, **window)
        return {
            "settlements": settlements,
            "count": len(settlements),
            "has_more": len(found) > limit,
            "runs": [_eod_run(r, steps=scope.admin) for r in recorded],
        }

    return await _in_eod_db(request, _query)


@router.get(
    "/balances",
    response_model=Balances,
    summary="Derived EOD balances",
    responses=docs.merge(
        docs.ok(docs.CLEARING_BALANCES_REPLY, "Balance per account."),
        docs.errors(*docs.TRADING_KEY, "EOD_DB", "SCOPE_DENIED", "VALIDATION"),
    ),
)
async def clearing_balances(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    gateway: Annotated[
        str | None,
        Query(
            description="Only this account (case-insensitive): a gateway, or "
            "`EXCHANGE` for ADMIN. A participant may name only itself."
        ),
    ] = None,
    as_of: Annotated[
        str | None,
        Query(
            description="Sum settlements up to and including this trading day, "
            "`YYYY-MM-DD`; all of them without it."
        ),
    ] = None,
) -> dict[str, Any]:
    """Each account's opening balance (pm-eod's roster), the sum of its
    settlements up to `as_of`, and their total, in integer minor units.

    The balance is derived here; pm-eod stores none. It is a running total of
    mark-to-market settlements, not cash, equity or collateral. A gateway on
    neither the roster nor the ledger has zeros. `EXCHANGE` is ADMIN only.
    """
    scope = await clearing_scope(request, session, gateway)
    if as_of is not None:
        try:
            validate_date(as_of)
        except ValueError as exc:
            raise _invalid("as_of", str(exc)) from exc
    openings = await asyncio.to_thread(_openings, request)

    def _query(conn: sqlite3.Connection) -> dict[str, Any]:
        settled = balances(conn, as_of=as_of)
        if scope.gateway is not None:
            accounts = [scope.gateway]
        else:
            accounts = sorted(set(openings) | set(settled))
        if not scope.admin:
            accounts = [a for a in accounts if a != EXCHANGE]
        rows = []
        for account in accounts:
            opening = openings.get(account, 0)
            total = settled.get(account, 0)
            rows.append(
                {
                    "account": account,
                    "opening_balance_minor": opening,
                    "opening_balance": fmt_minor(opening),
                    "settlement_total_minor": total,
                    "settlement_total": fmt_minor(total),
                    "balance_minor": opening + total,
                    "balance": fmt_minor(opening + total),
                }
            )
        return {
            "balances": rows,
            "count": len(rows),
            "as_of": as_of,
            "last_settled_date": last_settled_on_or_before(conn, as_of),
        }

    return await _in_eod_db(request, _query)
