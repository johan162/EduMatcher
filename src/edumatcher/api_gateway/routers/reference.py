"""Reference-data, status, and health REST endpoints."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from edumatcher.api_gateway.sessions import Session, auth, require_trading

router = APIRouter(prefix="/api/v1", tags=["reference"])


async def _request_reply(
    request: Request, send: str, topic: str, gateway_id: str
) -> dict[str, Any]:
    engine = request.app.state.engine
    if send == "symbols":
        engine.request_symbols(gateway_id)
    elif send == "session":
        engine.request_session(gateway_id)
    elif send == "quote_bootstrap":
        engine.request_quote_bootstrap(gateway_id)
    elif send == "quote_legs":
        engine.request_quote_legs(gateway_id)
    try:
        return cast(
            dict[str, Any],
            await engine.await_topic(
                topic, request.app.state.config.timeouts.engine_reply_sec
            ),
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc


@router.get("/symbols")
async def symbols(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return await _request_reply(
        request, "symbols", f"system.symbols.{gateway_id}", gateway_id
    )


@router.get("/session")
async def session_state(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return await _request_reply(
        request, "session", f"system.session_status.{gateway_id}", gateway_id
    )


@router.get("/quotes/bootstrap")
async def quote_bootstrap(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return await _request_reply(
        request, "quote_bootstrap", f"system.quote_bootstrap.{gateway_id}", gateway_id
    )


@router.get("/quotes/legs")
async def quote_legs(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    cache = request.app.state.engine.get_caches(gateway_id)
    if cache.quote_legs:
        return {"legs": list(cache.quote_legs.values())}
    return await _request_reply(
        request, "quote_legs", f"system.quote_legs.{gateway_id}", gateway_id
    )


@router.get("/positions")
async def positions(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    cache = request.app.state.engine.get_caches(gateway_id)
    positions_payload = []
    for symbol, qty in sorted(cache.positions.items()):
        last_price = cache.last_prices.get(symbol)
        positions_payload.append(
            {"symbol": symbol, "net_qty": qty, "last_price": last_price}
        )
    return {"positions": positions_payload}


@router.get("/status")
async def status_summary(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return cast(
        dict[str, Any], request.app.state.engine.get_caches(gateway_id).status()
    )


@router.get("/healthz", include_in_schema=False)
async def healthz(request: Request) -> dict[str, Any]:
    return {
        "ok": True,
        "enabled": request.app.state.config.enabled,
        "active_gateways": sorted(request.app.state.engine.active_gateways()),
    }
