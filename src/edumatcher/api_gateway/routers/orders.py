"""Order, OCO, combo, quote, and risk REST endpoints."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from edumatcher.api_gateway.schemas import (
    AmendRequest,
    CancelAccepted,
    ComboRequest,
    MassCancelRequest,
    OcoRequest,
    OrderAccepted,
    OrderRequest,
    PendingIdResponse,
    QuoteRequest,
    ReplaceResponse,
)
from edumatcher.api_gateway.sessions import Session, auth, require_trading
from edumatcher.api_gateway.translate import (
    wire_value,
    build_combo_payload,
    build_oco_payload,
    build_order,
    build_quote_payload,
)

router = APIRouter(prefix="/api/v1", tags=["orders"])


def _check_rate_limit(request: Request, session: Session) -> None:
    """Raise 429 if the per-key write rate is exceeded."""
    if not request.app.state.rate_limiter.allow(session.api_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "RATE_LIMIT", "message": "Write rate exceeded"}},
        )


async def _await_order_event(
    request: Request,
    topic: str,
    order_id: str,
    wait: str | None,
) -> dict[str, Any] | None:
    """Optionally wait for an order-specific ack event matching *order_id*."""
    if wait != "ack":
        return None
    try:
        return cast(
            dict[str, Any],
            await request.app.state.engine.await_event(
                topic,
                match={"order_id": order_id},
                timeout=request.app.state.config.timeouts.wait_ack_sec,
            ),
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc


def _check_duplicate_client_order_id(
    request: Request, gateway_id: str, client_order_id: str | None
) -> None:
    """Raise 409 if client_order_id already exists in the session cache."""
    if not client_order_id:
        return
    for cached in request.app.state.engine.get_caches(gateway_id).orders.values():
        if cached.get("client_order_id") == client_order_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": {
                        "code": "DUPLICATE",
                        "message": "Duplicate client_order_id in session",
                        "field": "client_order_id",
                    }
                },
            )


@router.post(
    "/orders", response_model=OrderAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def submit_order(
    body: OrderRequest,
    request: Request,
    session: Annotated[Session, Depends(auth)],
    wait: Annotated[str | None, Query(pattern="^ack$")] = None,
) -> OrderAccepted:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    _check_duplicate_client_order_id(request, gateway_id, body.client_order_id)
    order = build_order(body, gateway_id)
    request.app.state.engine.get_caches(gateway_id).orders[order.id] = {
        "order_id": order.id,
        "client_order_id": body.client_order_id,
        "symbol": body.symbol,
        "side": wire_value(body.side),
        "order_type": wire_value(body.order_type),
        "quantity": body.quantity,
        "status": "PENDING",
    }
    request.app.state.engine.send_new_order(order)
    event = await _await_order_event(request, f"order.ack.{gateway_id}", order.id, wait)
    return OrderAccepted(
        order_id=order.id,
        client_order_id=body.client_order_id,
        status="PENDING" if event is None else "ACKED",
        accepted=None if event is None else bool(event.get("accepted")),
        event=event,
    )


@router.delete(
    "/orders/{order_id}",
    response_model=CancelAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_order(
    order_id: str,
    request: Request,
    session: Annotated[Session, Depends(auth)],
    wait: Annotated[str | None, Query(pattern="^ack$")] = None,
) -> CancelAccepted:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_cancel(order_id, gateway_id)
    event = await _await_order_event(
        request, f"order.cancelled.{gateway_id}", order_id, wait
    )
    return CancelAccepted(order_id=order_id, status="PENDING_CANCEL", event=event)


@router.patch("/orders/{order_id}", status_code=status.HTTP_202_ACCEPTED)
async def amend_order(
    order_id: str,
    body: AmendRequest,
    request: Request,
    session: Annotated[Session, Depends(auth)],
    wait: Annotated[str | None, Query(pattern="^ack$")] = None,
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_amend(order_id, gateway_id, body.price, body.quantity)
    event = await _await_order_event(
        request, f"order.amended.{gateway_id}", order_id, wait
    )
    return {"order_id": order_id, "status": "PENDING_AMEND", "event": event}


@router.post(
    "/orders/{order_id}/replace",
    response_model=ReplaceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replace_order(
    order_id: str,
    body: OrderRequest,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> ReplaceResponse:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_cancel(order_id, gateway_id)
    try:
        await request.app.state.engine.await_event(
            f"order.cancelled.{gateway_id}",
            match={"order_id": order_id},
            timeout=request.app.state.config.timeouts.wait_ack_sec,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc
    replacement = build_order(body, gateway_id)
    request.app.state.engine.send_new_order(replacement)
    return ReplaceResponse(
        cancelled_order_id=order_id,
        replacement_order_id=replacement.id,
        status="PENDING",
    )


@router.get("/orders")
async def list_orders(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    request.app.state.engine.request_orders(gateway_id)
    try:
        return cast(
            dict[str, Any],
            await request.app.state.engine.await_topic(
                f"order.orders.{gateway_id}",
                request.app.state.config.timeouts.engine_reply_sec,
            ),
        )
    except TimeoutError:
        return {
            "orders": list(
                request.app.state.engine.get_caches(gateway_id).orders.values()
            )
        }


@router.get("/orders/{order_id}")
async def get_order(
    order_id: str, request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    order = request.app.state.engine.get_caches(gateway_id).orders.get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown order"
        )
    return cast(dict[str, Any], order)


@router.post(
    "/oco", response_model=PendingIdResponse, status_code=status.HTTP_202_ACCEPTED
)
async def submit_oco(
    body: OcoRequest, request: Request, session: Annotated[Session, Depends(auth)]
) -> PendingIdResponse:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_oco(build_oco_payload(body, gateway_id))
    return PendingIdResponse(id=body.oco_id, status="PENDING")


@router.delete("/oco/{oco_id}", status_code=status.HTTP_202_ACCEPTED)
async def cancel_oco(
    oco_id: str, request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, str]:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_oco_cancel(oco_id, gateway_id)
    return {"oco_id": oco_id, "status": "PENDING_CANCEL"}


@router.post(
    "/combos", response_model=PendingIdResponse, status_code=status.HTTP_202_ACCEPTED
)
async def submit_combo(
    body: ComboRequest, request: Request, session: Annotated[Session, Depends(auth)]
) -> PendingIdResponse:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_combo(build_combo_payload(body, gateway_id))
    return PendingIdResponse(id=body.combo_id, status="PENDING")


@router.delete("/combos/{combo_id}", status_code=status.HTTP_202_ACCEPTED)
async def cancel_combo(
    combo_id: str, request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, str]:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_combo_cancel(combo_id, gateway_id)
    return {"combo_id": combo_id, "status": "PENDING_CANCEL"}


@router.post(
    "/quotes", response_model=PendingIdResponse, status_code=status.HTTP_202_ACCEPTED
)
async def submit_quote(
    body: QuoteRequest, request: Request, session: Annotated[Session, Depends(auth)]
) -> PendingIdResponse:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_quote(build_quote_payload(body, gateway_id))
    return PendingIdResponse(id=body.quote_id or body.symbol, status="PENDING")


@router.delete("/quotes/{symbol}", status_code=status.HTTP_202_ACCEPTED)
async def cancel_quote(
    symbol: str, request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, str]:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_quote_cancel(gateway_id, symbol.upper())
    return {"symbol": symbol.upper(), "status": "PENDING_CANCEL"}


@router.post("/mass-cancel")
@router.post("/kill-switch")
async def mass_cancel(
    body: MassCancelRequest,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_mass_cancel(gateway_id, body.symbol or "")
    try:
        event = await request.app.state.engine.await_topic(
            f"risk.kill_switch_ack.{gateway_id}",
            request.app.state.config.timeouts.wait_ack_sec,
        )
        return cast(dict[str, Any], event)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc
