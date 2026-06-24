"""Read-only history endpoints backed by ``pm-stats`` SQLite data."""

from __future__ import annotations

from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from edumatcher.api_gateway.sessions import Session, auth, require_trading
from edumatcher.stats.query import (
    open_readonly_connection,
    query_daily,
    query_order_events,
    query_order_lifecycle,
    query_trades,
)

router = APIRouter(prefix="/api/v1/history", tags=["history"])


def _open_stats(request: Request):  # type: ignore[no-untyped-def]
    try:
        return open_readonly_connection(request.app.state.config.stats_db)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "STATS_DB", "message": str(exc)}},
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
