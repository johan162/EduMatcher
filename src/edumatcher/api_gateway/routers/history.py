"""Read-only history endpoints backed by ``pm-stats`` SQLite data, plus the
one endpoint (``/index-events``) that instead round-trips live to pm-index
over ZMQ for its structural/audit log."""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import tzinfo
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from edumatcher.api_gateway import openapi_docs as docs
from edumatcher.api_gateway.index_client import IndexHistoryError
from edumatcher.api_gateway.routers.reference import fetch_reference_bundle
from edumatcher.api_gateway.sessions import Session, auth, require_trading
from edumatcher.index.history import STRUCTURAL_RECORD_TYPES
from edumatcher.stats.event_types import EVENT_TYPES
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
from edumatcher.stats.trading_day import timezone_name, trading_date

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/history", tags=["history"])

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


def _validate_time_filters(
    date: str | None,
    from_ts: str | None,
    to_ts: str | None,
) -> None:
    """Raise HTTP 422 when any time-filter parameter is malformed."""
    try:
        if date is not None:
            validate_date(date)
        if from_ts is not None:
            validate_iso_ts(from_ts)
        if to_ts is not None:
            validate_iso_ts(to_ts)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "VALIDATION", "message": str(exc)}},
        ) from exc


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
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "VALIDATION",
                    "message": (
                        f"Unknown event_type {event_type!r}; expected one of "
                        + ", ".join(EVENT_TYPES)
                    ),
                }
            },
        )
    return normalized


def _paginated_envelope(
    key: str, rows: list[dict[str, object]], next_cursor: str | None
) -> dict[str, object]:
    """Build the standard list-endpoint envelope for a keyset-paginated query.

    ``has_more`` mirrors the pre-existing contract (true whenever another
    page might exist); ``next_cursor`` is the new, additive field a caller
    passes back as ``after`` to actually fetch that page — omitted when
    there isn't one, so existing clients that only look at ``has_more``
    keep working unchanged.
    """
    envelope: dict[str, object] = {
        key: rows,
        "count": len(rows),
        "has_more": next_cursor is not None,
    }
    if next_cursor is not None:
        envelope["next_cursor"] = next_cursor
    return envelope


@router.get(
    "/orders",
    summary="My order events",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_ORDERS,
            "One page of the caller's order events, oldest first. With `has_more: true`, `next_cursor` is also present.",
        ),
        {422: {"description": "Invalid filter, date, event type or cursor."}},
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
                "Unknown values are a 422, not an empty page."
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
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "VALIDATION", "message": str(exc)}},
            ) from exc
        retained_from = query_order_events_retained_from(conn, gateway_id=gateway_id)
    envelope = _paginated_envelope("events", events, next_cursor)
    envelope["retained_from"] = retained_from
    return envelope


@router.get(
    "/orders/{order_id}",
    summary="One order's event timeline",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_ORDER_LIFECYCLE, "The order's recorded events, oldest first."
        ),
        {422: {"description": "Invalid filter, date, event type or cursor."}},
    ),
)
async def history_order_lifecycle(
    order_id: str,
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
    summary="My fills",
    responses=docs.merge(
        docs.ok(docs.HISTORY_FILLS, "One page of the caller's fills, oldest first."),
        {422: {"description": "Invalid filter, date, event type or cursor."}},
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
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "VALIDATION", "message": str(exc)}},
            ) from exc
        retained_from = query_order_events_retained_from(conn, gateway_id=gateway_id)
    envelope = _paginated_envelope("events", events, next_cursor)
    envelope["retained_from"] = retained_from
    return envelope


@router.get(
    "/session",
    summary="Exchange locale and trading date",
    responses=docs.merge(
        docs.ok(docs.HISTORY_SESSION, "The exchange locale and today's trading date."),
        {422: {"description": "Invalid filter, date, event type or cursor."}},
    ),
)
async def history_session(
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, str | None]:
    """The exchange's current locale and trading date — public market data.

    ``session_timezone`` is resolved exactly as every ``date`` filter on this
    router resolves them, from the timezone pm-stats recorded in the
    statistics database, so a client showing "today" or a session clock
    cannot disagree with the ``date`` column of ``/daily``. ``country`` is
    the same value ``GET /reference/schedule`` reports (one engine
    round-trip). The trading date is computed from the gateway's clock at
    the moment of the request.
    """
    with closing(_open_stats(request)) as conn:
        tz = _session_tz(request, conn)
    bundle = await fetch_reference_bundle(request, session)
    schedule = cast(dict[str, Any], bundle["schedule"])
    return {
        "country": schedule["country"],
        "session_timezone": timezone_name(tz),
        "session_date": trading_date(time.time(), tz),
    }


@router.get(
    "/trades",
    summary="Executed trades",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_TRADES,
            "One page of executed trades, oldest first. Prices are display prices.",
        ),
        {422: {"description": "Invalid filter, date, event type or cursor."}},
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
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "VALIDATION", "message": str(exc)}},
            ) from exc
    return _paginated_envelope(
        "trades", to_display_prices(trades, "trades"), next_cursor
    )


@router.get(
    "/daily",
    summary="Daily OHLC per symbol",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_DAILY,
            "One page of daily OHLC rows. Prices are display prices; `turnover / volume` equals `vwap`.",
        ),
        {422: {"description": "Invalid filter, date, event type or cursor."}},
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
    _validate_time_filters(date, None, None)
    for bound in (from_date, to_date):
        if bound is not None:
            _validate_time_filters(bound, None, None)
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
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "VALIDATION", "message": str(exc)}},
            ) from exc
    return _paginated_envelope("daily", to_display_prices(rows, "daily"), next_cursor)


@router.get(
    "/price-snapshots",
    summary="Intraday price snapshots",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_PRICE_SNAPSHOTS,
            "One page of intraday mid/bid/ask rows for the symbol, oldest first.",
        ),
        {422: {"description": "Invalid filter, date, event type or cursor."}},
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
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "VALIDATION", "message": str(exc)}},
            ) from exc
    return _paginated_envelope(
        "snapshots", to_display_prices(rows, "snapshots"), next_cursor
    )


@router.get(
    "/index-daily",
    summary="Daily OHLC per index",
    responses=docs.merge(
        docs.ok(docs.HISTORY_INDEX_DAILY, "One page of daily index OHLC rows."),
        {422: {"description": "Invalid filter, date, event type or cursor."}},
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
    for bound in (date, from_date, to_date):
        if bound is not None:
            _validate_time_filters(bound, None, None)
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
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "VALIDATION", "message": str(exc)}},
            ) from exc
    # No tick conversion: index levels are computed, dimensionless numbers,
    # not prices on a tick grid.
    return _paginated_envelope("daily", rows, next_cursor)


@router.get(
    "/index-snapshots",
    summary="Intraday index levels",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_INDEX_SNAPSHOTS,
            "One page of intraday index levels, oldest first.",
        ),
        {422: {"description": "Invalid filter, date, event type or cursor."}},
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
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "VALIDATION", "message": str(exc)}},
            ) from exc
    return _paginated_envelope("snapshots", rows, next_cursor)


@router.get(
    "/index-ids",
    summary="Indexes with history",
    responses=docs.merge(
        docs.ok(docs.HISTORY_INDEX_IDS, "Index ids with recorded statistics."),
        {422: {"description": "Invalid filter, date, event type or cursor."}},
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
    if date is not None:
        _validate_time_filters(date, None, None)
    with closing(_open_stats(request)) as conn:
        rows = query_index_ids(conn, date_value=date, tz=_session_tz(request, conn))
    index_ids = [row["index_id"] for row in rows]
    return {"index_ids": index_ids, "count": len(index_ids)}


@router.get(
    "/index-events",
    summary="Index structural events",
    responses=docs.merge(
        docs.ok(
            docs.HISTORY_INDEX_EVENTS,
            "Structural events from pm-index, oldest first. `warnings` is present only when pm-index reported any.",
        ),
        {422: {"description": "Invalid filter, date, event type or cursor."}},
    ),
)
async def history_index_events(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    index_id: Annotated[
        str, Query(min_length=1, description="Index to inspect, e.g. `EDU3`. Required.")
    ],
    from_ts: Annotated[
        float | None,
        Query(
            alias="from",
            description="Start, Unix seconds. Defaults to 30 days ago.",
        ),
    ] = None,
    to_ts: Annotated[
        float | None,
        Query(alias="to", description="End, Unix seconds. Defaults to now."),
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
    """Structural/audit index events — live round-trip to pm-index over ZMQ.

    Unlike every other ``/history/*`` endpoint, this does not read pm-stats'
    SQLite data: pm-index's structural log (index creation, corporate
    actions, constituent changes, delistings) is not mirrored into
    pm-stats, so answering this requires a live request/reply exchange with
    the pm-index process itself. This means it can fail with a 503 if
    pm-index is unreachable or slow to reply, unlike the SQLite-backed
    endpoints above which only fail on a missing stats DB file.

    ``from``/``to`` are Unix timestamps (seconds), defaulting to the last 30
    days and now respectively — matching pm-index's own request defaults.
    ``types`` restricts to a subset of INIT/CORP_ACTION/ADD_CONSTITUENT/
    DELIST; omitting it returns all four (there are no level/EOD tick
    records here — see /index-daily and /index-snapshots for those).

    AR-0.3: this endpoint's own request contract (``from``/``to`` in
    seconds) is unchanged, but each record in the response's ``events``
    list is pm-index's ``HistoryRecord`` forwarded as-is, and that record
    now carries ``ts_ns`` (epoch nanoseconds) rather than ``timestamp``
    (epoch seconds) — the wire-protocol change is visible in the response
    body even though the request query params are not.
    """
    if types is not None:
        unknown = sorted(set(types) - STRUCTURAL_RECORD_TYPES)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {
                        "code": "VALIDATION",
                        "message": (
                            f"Unknown event type(s): {', '.join(unknown)}. "
                            f"Valid types: {', '.join(sorted(STRUCTURAL_RECORD_TYPES))}"
                        ),
                    }
                },
            )
    if from_ts is not None and to_ts is not None and to_ts < from_ts:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "VALIDATION",
                    "message": "'to' must be >= 'from'",
                }
            },
        )
    now = time.time()
    resolved_from = from_ts if from_ts is not None else now - 30 * 86400
    resolved_to = to_ts if to_ts is not None else now

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
    result: dict[str, object] = {"events": records, "count": len(records)}
    if warnings:
        result["warnings"] = warnings
    return result
