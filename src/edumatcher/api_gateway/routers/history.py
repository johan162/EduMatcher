"""Read-only history endpoints backed by ``pm-stats`` SQLite data, plus the
one endpoint (``/index-events``) that instead round-trips live to pm-index
over ZMQ for its structural/audit log."""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import closing
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from edumatcher.api_gateway.index_client import IndexHistoryError
from edumatcher.api_gateway.sessions import Session, auth, require_trading
from edumatcher.index.history import STRUCTURAL_RECORD_TYPES
from edumatcher.stats.query import (
    InvalidCursorError,
    open_readonly_connection,
    query_daily,
    query_index_daily,
    query_index_ids,
    query_index_snapshots,
    query_order_events,
    query_order_lifecycle,
    query_price_snapshots,
    query_trades,
    validate_date,
    validate_iso_ts,
)

router = APIRouter(prefix="/api/v1/history", tags=["history"])


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


@router.get("/orders")
async def history_orders(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: str | None = None,
    event_type: str | None = None,
    date: str | None = None,
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    after: str | None = None,
) -> dict[str, object]:
    """Order lifecycle events for the calling gateway.

    Set ``after`` to the previous response's ``next_cursor`` to fetch the
    next page — see the History endpoints section of the user guide for
    the full pagination contract.
    """
    gateway_id = require_trading(session)
    _validate_time_filters(date, from_ts, to_ts)
    with closing(_open_stats(request)) as conn:
        try:
            events, next_cursor = query_order_events(
                conn,
                gateway_id=gateway_id,
                symbol=symbol.upper() if symbol else None,
                event_type=event_type.upper() if event_type else None,
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
    return _paginated_envelope("events", events, next_cursor)


@router.get("/orders/{order_id}")
async def history_order_lifecycle(
    order_id: str,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, object]:
    gateway_id = require_trading(session)
    with closing(_open_stats(request)) as conn:
        events = query_order_lifecycle(conn, gateway_id=gateway_id, order_id=order_id)
    return {"events": events, "count": len(events)}


@router.get("/fills")
async def history_fills(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: str | None = None,
    date: str | None = None,
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    after: str | None = None,
) -> dict[str, object]:
    """Fill events for the calling gateway.

    Set ``after`` to the previous response's ``next_cursor`` to fetch the
    next page — see the History endpoints section of the user guide for
    the full pagination contract.
    """
    gateway_id = require_trading(session)
    _validate_time_filters(date, from_ts, to_ts)
    with closing(_open_stats(request)) as conn:
        try:
            events, next_cursor = query_order_events(
                conn,
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
    return _paginated_envelope("events", events, next_cursor)


@router.get("/trades")
async def history_trades(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: str | None = None,
    date: str | None = None,
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    after: str | None = None,
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
    return _paginated_envelope("trades", trades, next_cursor)


@router.get("/daily")
async def history_daily(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: str | None = None,
    date: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    after: str | None = None,
) -> dict[str, object]:
    """Daily instrument OHLC rollup — public market data.

    Set ``after`` to the previous response's ``next_cursor`` to fetch the
    next page — see the History endpoints section of the user guide for
    the full pagination contract.
    """
    _ = session
    with closing(_open_stats(request)) as conn:
        try:
            rows, next_cursor = query_daily(
                conn,
                date_value=date,
                symbol=symbol.upper() if symbol else None,
                limit=limit,
                after=after,
            )
        except InvalidCursorError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "VALIDATION", "message": str(exc)}},
            ) from exc
    return _paginated_envelope("daily", rows, next_cursor)


@router.get("/price-snapshots")
async def history_price_snapshots(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: str = Query(..., min_length=1),
    date: str | None = None,
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    after: str | None = None,
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
    return _paginated_envelope("snapshots", rows, next_cursor)


@router.get("/index-daily")
async def history_index_daily(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    index_id: str | None = None,
    date: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    after: str | None = None,
) -> dict[str, object]:
    """Daily index OHLC rollup — public market data, same tier as /daily.

    Mirrors /daily's shape and defaulting behaviour (omitting ``date``
    returns the latest available date), but for exchange indexes rather
    than instruments. ``close_level``/``close_session_state`` reflect the
    most recently recorded index.update for that date; the row is only
    guaranteed final once ``close_session_state`` is ``CLOSED`` or the
    date has passed — see the Market Index and Statistics & Reporting
    user-guide chapters.

    Set ``after`` to the previous response's ``next_cursor`` to fetch the
    next page — see the History endpoints section of the user guide for
    the full pagination contract.
    """
    _ = session
    if date is not None:
        _validate_time_filters(date, None, None)
    with closing(_open_stats(request)) as conn:
        try:
            rows, next_cursor = query_index_daily(
                conn,
                date_value=date,
                index_id=index_id.upper() if index_id else None,
                limit=limit,
                after=after,
            )
        except InvalidCursorError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "VALIDATION", "message": str(exc)}},
            ) from exc
    return _paginated_envelope("daily", rows, next_cursor)


@router.get("/index-snapshots")
async def history_index_snapshots(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    index_id: str = Query(..., min_length=1),
    date: str | None = None,
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    after: str | None = None,
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


@router.get("/index-ids")
async def history_index_ids(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    date: str | None = None,
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
        rows = query_index_ids(conn, date_value=date)
    index_ids = [row["index_id"] for row in rows]
    return {"index_ids": index_ids, "count": len(index_ids)}


@router.get("/index-events")
async def history_index_events(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    index_id: str = Query(..., min_length=1),
    from_ts: float | None = Query(default=None, alias="from"),
    to_ts: float | None = Query(default=None, alias="to"),
    types: list[str] | None = Query(default=None),
    max_records: int = Query(default=10_000, ge=1, le=10_000),
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
