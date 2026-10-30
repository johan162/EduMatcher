"""Read-only history endpoints backed by ``pm-stats`` SQLite data, plus the
one endpoint (``/index-events``) that instead round-trips live to pm-index
over ZMQ for its structural/audit log."""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, tzinfo
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from edumatcher.api_gateway import openapi_docs as docs
from edumatcher.api_gateway.index_client import IndexHistoryError
from edumatcher.api_gateway.responses import (
    DailyPage,
    IndexDailyPage,
    IndexEvents,
    IndexIds,
    IndexSnapshotPage,
    OrderEventPage,
    OrderTimeline,
    PriceSnapshotPage,
    TradePage,
)
from edumatcher.api_gateway.routing import ContractRoute
from edumatcher.api_gateway.params import OrderIdPath
from edumatcher.api_gateway.sessions import Session, auth, require_trading
from edumatcher.index.history import STRUCTURAL_RECORD_TYPES
from edumatcher.audit.archive import session_timezone
from edumatcher.stats.event_types import EVENT_TYPES
from edumatcher.stats.trading_day import normalise_ts_bound
from edumatcher.stats.query import (
    InvalidCursorError,
    open_readonly_connection,
    query_daily,
    query_index_daily,
    query_index_ids,
    query_index_snapshots,
    query_order_events,
    query_order_events_retained_from,
    query_order_lifecycle,
    query_price_snapshots,
    query_trades,
    resolve_session_timezone,
    to_display_prices,
    validate_date,
    validate_iso_ts,
)

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/history", tags=["history"], route_class=ContractRoute
)

_Limit = Annotated[
    int,
    Query(ge=1, le=5000, description="Maximum rows per page (1-5000)."),
]
_After = Annotated[
    str | None,
    Query(
        description=(
            "Pagination cursor: the previous page's `next_cursor`. Opaque -- "
            "pass it back unchanged with the same filters."
        )
    ),
]
_Symbol = Annotated[
    str | None,
    Query(description="Only this symbol (case-insensitive), e.g. `AAPL`."),
]
_Date = Annotated[
    str | None,
    Query(description="One trading day, `YYYY-MM-DD`, in the exchange timezone."),
]
_FromTs = Annotated[
    str | None,
    Query(
        alias="from",
        description=(
            "Start of range, inclusive: an ISO-8601 timestamp or a "
            "`YYYY-MM-DD` date. Ignored if `date` is given."
        ),
    ),
]
_ToTs = Annotated[
    str | None,
    Query(
        alias="to",
        description=(
            "End of range: an ISO-8601 timestamp or a `YYYY-MM-DD` date. "
            "Ignored if `date` is given."
        ),
    ),
]
_FromDate = Annotated[
    str | None,
    Query(
        alias="from",
        description="First day of a series, `YYYY-MM-DD`, inclusive. Optional.",
    ),
]
_ToDate = Annotated[
    str | None,
    Query(
        alias="to",
        description="Last day of a series, `YYYY-MM-DD`, inclusive. Optional.",
    ),
]


def _session_tz(request: Request, conn: sqlite3.Connection) -> tzinfo:
    """Session timezone that ``date`` filters resolve their trading day in.

    Read from the statistics database, which pm-stats recorded using the
    exchange-wide ``session_timezone`` from engine config — so the gateway
    cannot disagree with the recorder about which trading day a ``date``
    refers to.
    """
    resolved, warning = resolve_session_timezone(conn)
    if warning is not None:
        log.warning("history: %s", warning)
    return resolved


def _open_stats(request: Request) -> sqlite3.Connection:
    try:
        return open_readonly_connection(request.app.state.config.stats_db)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "STATS_DB", "message": str(exc)}},
        ) from exc


def _invalid(field: str, message: str) -> HTTPException:
    """``400 VALIDATION`` naming *field* -- the same answer FastAPI's own query
    validation gives, so a client handles both alike."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": {"code": "VALIDATION", "message": message, "field": field}},
    )


def _check(field: str, value: str | None, validate: Callable[[str], object]) -> None:
    """Run *validate* on an optional query parameter, as a 400 on *field*."""
    if value is None:
        return
    try:
        validate(value)
    except ValueError as exc:
        raise _invalid(field, str(exc)) from exc


def _epoch_seconds(field: str, raw: str, tz: tzinfo) -> float:
    """An ISO-8601 bound as Unix seconds, which is what pm-index takes (D7:
    every history range is ISO on the REST side, whatever the backend wants)."""
    try:
        return datetime.fromisoformat(normalise_ts_bound(raw, tz)).timestamp()
    except ValueError as exc:
        raise _invalid(
            field, f"Invalid timestamp format: {raw} (expected ISO timestamp)"
        ) from exc


def _validate_time_filters(
    date: str | None,
    from_ts: str | None,
    to_ts: str | None,
) -> None:
    """Raise 400 when any time-filter parameter is malformed."""
    _check("date", date, validate_date)
    _check("from", from_ts, validate_iso_ts)
    _check("to", to_ts, validate_iso_ts)


def _validate_event_type(event_type: str | None) -> str | None:
    """Normalize and reject unknown ``event_type`` filters.

    An unrecognised value previously matched nothing and returned an empty
    page, which is indistinguishable from "this gateway had no such events" —
    so a caller using a stale value (say ``COMBO``, which no longer exists)
    would quietly conclude there was no activity.
    """
    if event_type is None:
        return None
    normalized = event_type.upper()
    if normalized not in EVENT_TYPES:
        raise _invalid(
            "event_type",
            f"Unknown event_type {event_type!r}; expected one of "
            + ", ".join(EVENT_TYPES),
        )
    return normalized


def _paginated_envelope(
    key: str, rows: list[dict[str, object]], next_cursor: str | None
) -> dict[str, object]:
    """Build the standard envelope for a keyset-paginated query (D6).

    ``next_cursor`` is always present -- ``null`` on the last page -- and is
    what a caller passes back as ``after``; ``has_more`` says the same thing as
    a boolean.
    """
    return {
        key: rows,
        "count": len(rows),
        "has_more": next_cursor is not None,
        "next_cursor": next_cursor,
    }


@router.get(
    "/orders",
    response_model=OrderEventPage,
    summary="My order events",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_ORDERS_REPLY,
            "One page of the caller's order events, oldest first. With `has_more: true`, `next_cursor` is also present.",
        ),
        docs.errors(
            *docs.TRADING_KEY,
            "STATS_DB",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def history_orders(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: _Symbol = None,
    event_type: Annotated[
        str | None,
        Query(
            description=(
                "Only this event type: ACK, REJECT, FILL, AMEND, CANCEL, "
                "EXPIRE, or a COMBO_/OCO_/QUOTE_ variant (case-insensitive). "
                "Unknown values are a 400, not an empty page."
            )
        ),
    ] = None,
    date: _Date = None,
    from_ts: _FromTs = None,
    to_ts: _ToTs = None,
    limit: _Limit = 500,
    after: _After = None,
) -> dict[str, object]:
    """Order lifecycle events for the calling gateway.

    Set ``after`` to the previous response's ``next_cursor`` to fetch the
    next page — see the History endpoints section of the user guide for
    the full pagination contract.

    ``retained_from`` reports the point pm-stats prunes this gateway's
    order events at, so a caller can tell "no events" apart from "no
    events left". Null when nothing is being pruned.
    """
    gateway_id = require_trading(session)
    _validate_time_filters(date, from_ts, to_ts)
    normalized_event_type = _validate_event_type(event_type)
    with closing(_open_stats(request)) as conn:
        try:
            events, next_cursor = query_order_events(
                conn,
                tz=_session_tz(request, conn),
                gateway_id=gateway_id,
                symbol=symbol.upper() if symbol else None,
                event_type=normalized_event_type,
                date_value=date,
                from_ts=from_ts,
                to_ts=to_ts,
                limit=limit,
                after=after,
            )
        except InvalidCursorError as exc:
            raise _invalid("after", str(exc)) from exc
        retained_from = query_order_events_retained_from(conn, gateway_id=gateway_id)
    envelope = _paginated_envelope("events", events, next_cursor)
    envelope["retained_from"] = retained_from
    return envelope


@router.get(
    "/orders/{order_id}",
    response_model=OrderTimeline,
    summary="One order's event timeline",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_ORDER_LIFECYCLE, "The order's recorded events, oldest first."
        ),
        docs.errors(*docs.TRADING_KEY, "STATS_DB", "VALIDATION"),
    ),
)
async def history_order_lifecycle(
    order_id: OrderIdPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, object]:
    """Return the recorded lifecycle of one order.

    ``retained_from`` reports the point pm-stats prunes this gateway's
    order events from, or ``null`` when nothing is pruned. An order
    placed before that point may show a partial timeline, or none.
    """
    gateway_id = require_trading(session)
    with closing(_open_stats(request)) as conn:
        events = query_order_lifecycle(conn, gateway_id=gateway_id, order_id=order_id)
        retained_from = query_order_events_retained_from(conn, gateway_id=gateway_id)
    return {
        "events": events,
        "count": len(events),
        "retained_from": retained_from,
    }


@router.get(
    "/fills",
    response_model=OrderEventPage,
    summary="My fills",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_FILLS_REPLY, "One page of the caller's fills, oldest first."
        ),
        docs.errors(
            *docs.TRADING_KEY,
            "STATS_DB",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def history_fills(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: _Symbol = None,
    date: _Date = None,
    from_ts: _FromTs = None,
    to_ts: _ToTs = None,
    limit: _Limit = 500,
    after: _After = None,
) -> dict[str, object]:
    """Fill events for the calling gateway.

    Set ``after`` to the previous response's ``next_cursor`` to fetch the
    next page — see the History endpoints section of the user guide for
    the full pagination contract.

    ``retained_from`` reports the point pm-stats prunes this gateway's
    order events at. Fills older than that have been deleted by the
    recorder's retention setting and are gone, so a caller can tell "no
    fills" apart from "no fills left". Null when nothing is being pruned.
    """
    gateway_id = require_trading(session)
    _validate_time_filters(date, from_ts, to_ts)
    with closing(_open_stats(request)) as conn:
        try:
            events, next_cursor = query_order_events(
                conn,
                tz=_session_tz(request, conn),
                gateway_id=gateway_id,
                symbol=symbol.upper() if symbol else None,
                event_type="FILL",
                date_value=date,
                from_ts=from_ts,
                to_ts=to_ts,
                limit=limit,
                after=after,
            )
        except InvalidCursorError as exc:
            raise _invalid("after", str(exc)) from exc
        retained_from = query_order_events_retained_from(conn, gateway_id=gateway_id)
    envelope = _paginated_envelope("events", events, next_cursor)
    envelope["retained_from"] = retained_from
    return envelope


@router.get(
    "/trades",
    response_model=TradePage,
    summary="Executed trades",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_TRADES_REPLY,
            "One page of executed trades, oldest first. Prices are display prices.",
        ),
        docs.errors(
            *docs.ANY_KEY,
            "STATS_DB",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def history_trades(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: _Symbol = None,
    date: _Date = None,
    from_ts: _FromTs = None,
    to_ts: _ToTs = None,
    limit: _Limit = 500,
    after: _After = None,
) -> dict[str, object]:
    """Executed trades — public market data.

    Set ``after`` to the previous response's ``next_cursor`` to fetch the
    next page — see the History endpoints section of the user guide for
    the full pagination contract.
    """
    _ = session
    _validate_time_filters(date, from_ts, to_ts)
    with closing(_open_stats(request)) as conn:
        try:
            trades, next_cursor = query_trades(
                conn,
                tz=_session_tz(request, conn),
                symbol=symbol.upper() if symbol else None,
                date_value=date,
                from_ts=from_ts,
                to_ts=to_ts,
                limit=limit,
                after=after,
            )
        except InvalidCursorError as exc:
            raise _invalid("after", str(exc)) from exc
    return _paginated_envelope(
        "trades", to_display_prices(trades, "trades"), next_cursor
    )


@router.get(
    "/daily",
    response_model=DailyPage,
    summary="Daily OHLC per symbol",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_DAILY_REPLY,
            "One page of daily OHLC rows. Prices are display prices; `turnover / volume` equals `vwap`.",
        ),
        docs.errors(
            *docs.ANY_KEY,
            "STATS_DB",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def history_daily(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: _Symbol = None,
    date: _Date = None,
    from_date: _FromDate = None,
    to_date: _ToDate = None,
    limit: _Limit = 500,
    after: _After = None,
) -> dict[str, object]:
    """Daily instrument OHLC rollup — public market data.

    Omitting every time filter returns the latest available date. Pass
    ``date`` for one specific day, or ``from``/``to`` (inclusive, either may
    be omitted) for a series across days, oldest first — which is what a
    multi-day chart needs. ``date`` wins if combined with a range.

    Set ``after`` to the previous response's ``next_cursor`` to fetch the
    next page — see the History endpoints section of the user guide for
    the full pagination contract.
    """
    _ = session
    _check("date", date, validate_date)
    _check("from", from_date, validate_date)
    _check("to", to_date, validate_date)
    with closing(_open_stats(request)) as conn:
        try:
            rows, next_cursor = query_daily(
                conn,
                date_value=date,
                symbol=symbol.upper() if symbol else None,
                limit=limit,
                after=after,
                from_date=from_date,
                to_date=to_date,
            )
        except InvalidCursorError as exc:
            raise _invalid("after", str(exc)) from exc
    return _paginated_envelope("daily", to_display_prices(rows, "daily"), next_cursor)


@router.get(
    "/price-snapshots",
    response_model=PriceSnapshotPage,
    summary="Intraday price snapshots",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_PRICE_SNAPSHOTS_REPLY,
            "One page of intraday mid/bid/ask rows for the symbol, oldest first.",
        ),
        docs.errors(
            *docs.ANY_KEY,
            "STATS_DB",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def history_price_snapshots(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: Annotated[
        str, Query(min_length=1, description="Symbol to chart, e.g. `AAPL`. Required.")
    ],
    date: _Date = None,
    from_ts: _FromTs = None,
    to_ts: _ToTs = None,
    limit: _Limit = 500,
    after: _After = None,
) -> dict[str, object]:
    """Intraday instrument mid/bid/ask time series — public market data.

    ``symbol`` is required, matching ``pm-stats-cli snapshots``: unlike
    /trades and /daily, there is no "all symbols" mode here, since a full
    multi-symbol tick stream would be an unbounded firehose rather than a
    bounded daily summary.

    Set ``after`` to the previous response's ``next_cursor`` to fetch the
    next page — see the History endpoints section of the user guide for
    the full pagination contract.
    """
    _ = session
    _validate_time_filters(date, from_ts, to_ts)
    with closing(_open_stats(request)) as conn:
        try:
            rows, next_cursor = query_price_snapshots(
                conn,
                tz=_session_tz(request, conn),
                symbol=symbol.upper(),
                date_value=date,
                from_ts=from_ts,
                to_ts=to_ts,
                limit=limit,
                after=after,
            )
        except InvalidCursorError as exc:
            raise _invalid("after", str(exc)) from exc
    return _paginated_envelope(
        "snapshots", to_display_prices(rows, "snapshots"), next_cursor
    )


@router.get(
    "/index-daily",
    response_model=IndexDailyPage,
    summary="Daily OHLC per index",
    responses=docs.merge(
        docs.ok(docs.HISTORY_INDEX_DAILY_REPLY, "One page of daily index OHLC rows."),
        docs.errors(
            *docs.ANY_KEY,
            "STATS_DB",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def history_index_daily(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    index_id: Annotated[
        str | None, Query(description="Only this index, e.g. `EDU3`.")
    ] = None,
    date: _Date = None,
    from_date: _FromDate = None,
    to_date: _ToDate = None,
    limit: _Limit = 500,
    after: _After = None,
) -> dict[str, object]:
    """Daily index OHLC rollup — public market data, same tier as /daily.

    Mirrors /daily's shape and defaulting behaviour, including its
    ``from``/``to`` range for a multi-day series, but for exchange indexes
    rather than instruments. ``close_level``/``close_session_state`` reflect
    the most recently recorded index.update for that date; the row is only
    guaranteed final once ``close_session_state`` is ``CLOSED`` or the
    date has passed — see the Market Index and Statistics & Reporting
    user-guide chapters.

    Set ``after`` to the previous response's ``next_cursor`` to fetch the
    next page — see the History endpoints section of the user guide for
    the full pagination contract.
    """
    _ = session
    _check("date", date, validate_date)
    _check("from", from_date, validate_date)
    _check("to", to_date, validate_date)
    with closing(_open_stats(request)) as conn:
        try:
            rows, next_cursor = query_index_daily(
                conn,
                date_value=date,
                index_id=index_id.upper() if index_id else None,
                limit=limit,
                after=after,
                from_date=from_date,
                to_date=to_date,
            )
        except InvalidCursorError as exc:
            raise _invalid("after", str(exc)) from exc
    # No tick conversion: index levels are computed, dimensionless numbers,
    # not prices on a tick grid.
    return _paginated_envelope("daily", rows, next_cursor)


@router.get(
    "/index-snapshots",
    response_model=IndexSnapshotPage,
    summary="Intraday index levels",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_INDEX_SNAPSHOTS_REPLY,
            "One page of intraday index levels, oldest first.",
        ),
        docs.errors(
            *docs.ANY_KEY,
            "STATS_DB",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def history_index_snapshots(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    index_id: Annotated[
        str, Query(min_length=1, description="Index to chart, e.g. `EDU3`. Required.")
    ],
    date: _Date = None,
    from_ts: _FromTs = None,
    to_ts: _ToTs = None,
    limit: _Limit = 500,
    after: _After = None,
) -> dict[str, object]:
    """Intraday index level time series — public market data.

    ``index_id`` is required, matching ``pm-stats-cli index-snapshots``:
    unlike /trades and /daily, there is no "all indexes" mode here, since
    a full multi-index tick stream would be an unbounded firehose rather
    than a bounded daily summary.

    Set ``after`` to the previous response's ``next_cursor`` to fetch the
    next page — see the History endpoints section of the user guide for
    the full pagination contract.
    """
    _ = session
    _validate_time_filters(date, from_ts, to_ts)
    with closing(_open_stats(request)) as conn:
        try:
            rows, next_cursor = query_index_snapshots(
                conn,
                tz=_session_tz(request, conn),
                index_id=index_id.upper(),
                date_value=date,
                from_ts=from_ts,
                to_ts=to_ts,
                limit=limit,
                after=after,
            )
        except InvalidCursorError as exc:
            raise _invalid("after", str(exc)) from exc
    return _paginated_envelope("snapshots", rows, next_cursor)


@router.get(
    "/indexes",
    response_model=IndexIds,
    summary="Indexes with history",
    responses=docs.merge(
        docs.ok(docs.HISTORY_INDEXES, "Index ids with recorded statistics."),
        docs.errors(
            *docs.ANY_KEY,
            "STATS_DB",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def history_index_ids(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    date: _Date = None,
) -> dict[str, object]:
    """List index IDs with recorded statistics in pm-stats.

    Unlike /symbols (which queries the live engine for configured
    instruments), this queries pm-stats' SQLite data directly, mirroring
    ``pm-stats-cli index-ids``. Unbounded/unpaginated by design: the
    number of distinct exchange indexes is always small (EduMatcher caps
    this at 5 per config file), so no ``limit``/``has_more`` are needed.
    """
    _ = session
    _check("date", date, validate_date)
    with closing(_open_stats(request)) as conn:
        rows = query_index_ids(conn, date_value=date, tz=_session_tz(request, conn))
    index_ids = [row["index_id"] for row in rows]
    return {"index_ids": index_ids, "count": len(index_ids)}


@router.get(
    "/index-events",
    response_model=IndexEvents,
    summary="Index structural events",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_INDEX_EVENTS,
            "Structural events from pm-index, oldest first, and any `warnings` it reported.",
        ),
        docs.errors(
            *docs.ANY_KEY,
            "INDEX_ERROR",
            "INDEX_TIMEOUT",
            "VALIDATION",
            examples={"VALIDATION": docs.FILTER_VALIDATION},
        ),
    ),
)
async def history_index_events(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    index_id: Annotated[
        str, Query(min_length=1, description="Index to inspect, e.g. `EDU3`. Required.")
    ],
    from_ts: Annotated[
        str | None,
        Query(
            alias="from",
            description=(
                "Start: an ISO-8601 timestamp or `YYYY-MM-DD` date, like every "
                "history range (no offset means exchange time). Default: 30 days ago."
            ),
        ),
    ] = None,
    to_ts: Annotated[
        str | None,
        Query(alias="to", description="End, same form. Default: now."),
    ] = None,
    types: Annotated[
        list[str] | None,
        Query(
            description=(
                "Restrict to these record types (repeat the parameter): "
                "INIT, CORP_ACTION, ADD_CONSTITUENT, DELIST, REBALANCE. "
                "Default: all."
            )
        ),
    ] = None,
    max_records: Annotated[
        int, Query(ge=1, le=10_000, description="Cap on records returned.")
    ] = 10_000,
) -> dict[str, object]:
    """Structural index events: creation, corporate actions, constituent changes,
    delistings and rebalances, oldest first.

    Unlike the other history endpoints this is a live query to pm-index, which
    keeps the structural log; it can therefore answer `503 INDEX_TIMEOUT` when
    pm-index is unreachable. `from`/`to` default to the last 30 days; `types`
    restricts to a subset (default: all). Level and end-of-day data are in
    `/history/index-daily` and `/history/index-snapshots`. Each record carries
    `ts_ns` (epoch nanoseconds).
    """
    if types is not None:
        unknown = sorted(set(types) - STRUCTURAL_RECORD_TYPES)
        if unknown:
            raise _invalid(
                "types",
                f"Unknown event type(s): {', '.join(unknown)}. "
                f"Valid types: {', '.join(sorted(STRUCTURAL_RECORD_TYPES))}",
            )
    tz = session_timezone()
    now = time.time()
    resolved_from = (
        _epoch_seconds("from", from_ts, tz) if from_ts is not None else now - 30 * 86400
    )
    resolved_to = _epoch_seconds("to", to_ts, tz) if to_ts is not None else now
    if resolved_to < resolved_from:
        raise _invalid("to", "'to' must be >= 'from'")

    index_client = request.app.state.index_client
    timeout = request.app.state.config.timeouts.engine_reply_sec
    # pm-index echoes request_id back (upper-cased) as the reply-topic
    # suffix, and IndexClient keys its pending futures by that same string.
    # Two fixes are needed here:
    #  - a per-call UUID suffix, since a bare gateway_id/api_key is stable
    #    across a session, so two concurrent calls from the same session
    #    would otherwise both listen on (and resolve from) the same topic;
    #  - upper-casing the whole value ourselves, since pm-index upper-cases
    #    whatever it receives before using it in the reply topic name — a
    #    mixed-case read-only api_key would otherwise never match what
    #    IndexClient is actually listening for, timing out on every call.
    request_id = (
        f"{session.gateway_id or session.api_key}-{uuid.uuid4().hex[:10]}"
    ).upper()
    try:
        reply = await index_client.request_history(
            request_id=request_id,
            index_id=index_id.upper(),
            from_ts=resolved_from,
            to_ts=resolved_to,
            types=types,
            max_records=max_records,
            timeout=timeout,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "INDEX_TIMEOUT", "message": str(exc)}},
        ) from exc
    except IndexHistoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": {"code": "INDEX_ERROR", "message": str(exc)}},
        ) from exc
    records: list[dict[str, Any]] = reply.get("records", [])
    warnings: list[str] = reply.get("warnings", [])
    return {"events": records, "count": len(records), "warnings": warnings}
