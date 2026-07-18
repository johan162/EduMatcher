"""Read-only history endpoints backed by ``pm-stats`` SQLite data."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from edumatcher.api_gateway.sessions import Session, auth, require_trading
from edumatcher.stats.query import (
    open_readonly_connection,
    query_daily,
    query_index_daily,
    query_index_ids,
    query_index_snapshots,
    query_order_events,
    query_order_lifecycle,
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
) -> dict[str, object]:
    gateway_id = require_trading(session)
    _validate_time_filters(date, from_ts, to_ts)
    with closing(_open_stats(request)) as conn:
        events = query_order_events(
            conn,
            gateway_id=gateway_id,
            symbol=symbol.upper() if symbol else None,
            event_type=event_type.upper() if event_type else None,
            date_value=date,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )
    return {"events": events, "count": len(events), "has_more": len(events) == limit}


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
) -> dict[str, object]:
    gateway_id = require_trading(session)
    _validate_time_filters(date, from_ts, to_ts)
    with closing(_open_stats(request)) as conn:
        events = query_order_events(
            conn,
            gateway_id=gateway_id,
            symbol=symbol.upper() if symbol else None,
            event_type="FILL",
            date_value=date,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )
    return {"events": events, "count": len(events), "has_more": len(events) == limit}


@router.get("/trades")
async def history_trades(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: str | None = None,
    date: str | None = None,
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, object]:
    _ = session
    _validate_time_filters(date, from_ts, to_ts)
    with closing(_open_stats(request)) as conn:
        trades = query_trades(
            conn,
            symbol=symbol.upper() if symbol else None,
            date_value=date,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )
    return {"trades": trades, "count": len(trades), "has_more": len(trades) == limit}


@router.get("/daily")
async def history_daily(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: str | None = None,
    date: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, object]:
    _ = session
    with closing(_open_stats(request)) as conn:
        rows = query_daily(
            conn,
            date_value=date,
            symbol=symbol.upper() if symbol else None,
            limit=limit,
        )
    return {"daily": rows, "count": len(rows), "has_more": len(rows) == limit}


@router.get("/index-daily")
async def history_index_daily(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    index_id: str | None = None,
    date: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, object]:
    """Daily index OHLC rollup — public market data, same tier as /daily.

    Mirrors /daily's shape and defaulting behaviour (omitting ``date``
    returns the latest available date), but for exchange indexes rather
    than instruments. ``close_level``/``close_session_state`` reflect the
    most recently recorded index.update for that date; the row is only
    guaranteed final once ``close_session_state`` is ``CLOSED`` or the
    date has passed — see the Market Index and Statistics & Reporting
    user-guide chapters.
    """
    _ = session
    if date is not None:
        _validate_time_filters(date, None, None)
    with closing(_open_stats(request)) as conn:
        rows = query_index_daily(
            conn,
            date_value=date,
            index_id=index_id.upper() if index_id else None,
            limit=limit,
        )
    return {"daily": rows, "count": len(rows), "has_more": len(rows) == limit}


@router.get("/index-snapshots")
async def history_index_snapshots(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    index_id: str = Query(..., min_length=1),
    date: str | None = None,
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, object]:
    """Intraday index level time series — public market data.

    ``index_id`` is required, matching ``pm-stats-cli index-snapshots``:
    unlike /trades and /daily, there is no "all indexes" mode here, since
    a full multi-index tick stream would be an unbounded firehose rather
    than a bounded daily summary.
    """
    _ = session
    _validate_time_filters(date, from_ts, to_ts)
    with closing(_open_stats(request)) as conn:
        rows = query_index_snapshots(
            conn,
            index_id=index_id.upper(),
            date_value=date,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )
    return {"snapshots": rows, "count": len(rows), "has_more": len(rows) == limit}


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
