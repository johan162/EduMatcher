"""Order, OCO, combo, quote, and risk REST endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any, cast

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

from edumatcher.api_gateway import openapi_docs as docs
from edumatcher.api_gateway.idempotency import idempotent
from edumatcher.api_gateway.responses import (
    AmendAccepted,
    CachedOrder,
    ComboCancelPending,
    OcoCancelPending,
    OrderList,
    QuoteCancelPending,
)
from edumatcher.api_gateway.routing import ContractRoute
from edumatcher.api_gateway.params import (
    ComboIdPath,
    IdempotencyKey,
    OcoIdPath,
    OrderIdPath,
    SymbolPath,
)
from edumatcher.api_gateway.schemas import (
    AmendRequest,
    CancelAccepted,
    ComboRequest,
    MassCancelRequest,
    OcoRequest,
    OrderAccepted,
    ComboAccepted,
    OcoAccepted,
    OrderRequest,
    QuoteAccepted,
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
from edumatcher.models.generated.rest.risk import KillSwitchAck
from edumatcher.models.price import has_tick_decimals
from edumatcher.models.generated.quote import topic_quote_ack
from edumatcher.models.generated.structure import topic_combo_ack, topic_oco_ack
from edumatcher.models.generated.order import (
    topic_order_ack,
    topic_order_amended,
    topic_order_cancelled,
    topic_orders,
)

router = APIRouter(prefix="/api/v1", tags=["orders"], route_class=ContractRoute)

log = logging.getLogger(__name__)


def _check_rate_limit(request: Request, session: Session) -> None:
    """Raise 429 if the per-key write rate is exceeded."""
    if not request.app.state.rate_limiter.allow(session.api_key):
        # Never the api_key: it is the bearer credential itself.
        log.debug("rate limit exceeded gateway_id=%s", session.gateway_id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "RATE_LIMIT", "message": "Write rate exceeded"}},
        )


def _check_symbol_ready(symbol: str) -> None:
    """Raise 503 until this symbol's tick precision has arrived from the engine.

    The gateway learns tick precision from the engine's symbols snapshot,
    requested when it authenticates. Until that lands, converting a price
    applies the two-decimal default: on a 4-decimal instrument that is a
    hundredfold error, and on a 0-decimal one the price loses its meaning --
    silently, because rounding never fails. ALF has always refused this window
    with SYMBOLS_NOT_READY; REST had no equivalent gate and would happily take
    the order. 503 rather than 400: the client did nothing wrong and should
    retry.
    """
    if not has_tick_decimals(symbol):
        log.debug("symbol not ready symbol=%s", symbol)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "SYMBOLS_NOT_READY",
                    "message": f"Reference data for {symbol} is not loaded yet",
                    "reject_code": "SYMBOL_NOT_READY",
                }
            },
        )


async def _await_ack(
    request: Request, topic: str, match: dict[str, str], wait: str | None
) -> tuple[dict[str, Any] | None, bool]:
    """With ``?wait=ack``, wait for the engine's event on *topic*.

    Returns ``(event, timed_out)``. A timeout is not an error: the request was
    sent, so the reply must still carry its id (E7) -- answering 503 here used
    to leave the client unable to cancel or track a live order, and its
    natural retry made a second one.
    """
    if wait != "ack":
        return None, False
    try:
        event = await request.app.state.engine.await_event(
            topic, match=match, timeout=request.app.state.config.timeouts.wait_ack_sec
        )
    except TimeoutError:
        return None, True
    return cast(dict[str, Any], event), False


async def _await_cancel_or_amend_event(
    request: Request,
    *,
    success_topic: str,
    gateway_id: str,
    order_id: str,
    wait: str | None,
    request_tag: str | None,
) -> tuple[dict[str, Any] | None, bool]:
    """Wait for a cancel/amend, reporting a reject rather than timing out on it.

    Without a request_tag there is nothing to safely race the reject topic
    on (see EngineClient.await_cancel_or_amend_outcome), so this waits on the
    success topic alone, and a reject then shows as a timeout. Returns
    ``(event, timed_out)`` like ``_await_ack``.
    """
    if wait != "ack":
        return None, False
    if request_tag is None:
        return await _await_ack(request, success_topic, {"order_id": order_id}, wait)
    try:
        event = await request.app.state.engine.await_cancel_or_amend_outcome(
            success_topic=success_topic,
            gateway_id=gateway_id,
            order_id=order_id,
            request_tag=request_tag,
            timeout=request.app.state.config.timeouts.wait_ack_sec,
        )
    except TimeoutError:
        return None, True
    return cast(dict[str, Any], event), False


def _ok_when_answered(response: Response, event: dict[str, Any] | None) -> None:
    """200 when the body carries the engine's outcome, else the route's 202."""
    if event is not None:
        response.status_code = status.HTTP_200_OK


def _structure_verdict(
    response: Response, event: dict[str, Any] | None, timed_out: bool
) -> dict[str, Any]:
    """The verdict fields shared by the OCO, combo and quote submit replies."""
    _ok_when_answered(response, event)
    accepted = None if event is None else bool(event.get("accepted"))
    return {
        "status": "PENDING" if event is None else "ACKED",
        "accepted": accepted,
        "reason": (event.get("reason") or None) if event is not None else None,
        "event": event,
        "ack_timeout": timed_out,
    }


def _with_client_tag(order: dict[str, Any]) -> dict[str, Any]:
    """Return an order response carrying the canonical tag key."""
    result = dict(order)
    result.setdefault("client_tag", None)
    return result


def _cache_submitted(
    request: Request, gateway_id: str, order_id: str, body: OrderRequest
) -> None:
    """Seed the gateway's view of an order it is about to send."""
    request.app.state.engine.get_caches(gateway_id).orders[order_id] = {
        "order_id": order_id,
        "client_tag": body.client_tag,
        "symbol": body.symbol,
        "side": wire_value(body.side),
        "order_type": wire_value(body.order_type),
        "quantity": body.quantity,
        "status": "PENDING",
    }


@router.post(
    "/orders",
    response_model=OrderAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an order",
    description=(
        "Send a new order to the matching engine under the caller's gateway. "
        "Which fields are required depends on `order_type`: LIMIT/FOK/IOC "
        "need `price`; MARKET forbids price; STOP needs `stop_price`; "
        "STOP_LIMIT needs both; ICEBERG needs `price` and a smaller "
        "`visible_qty`; TRAILING_STOP needs `trail_offset` and may set an "
        "initial `stop_price`. Any other of these fields is rejected. Prices must lie "
        "on the symbol's tick grid. `client_tag` is an opaque label echoed "
        "on every event for this order. Returns `202` (`PENDING`); with "
        "`?wait=ack`, `200` and the engine's verdict in the same response, or "
        "`202` with `ack_timeout: true` if the verdict did not come in time. "
        "Send an `Idempotency-Key` to make a retry safe."
    ),
    responses=docs.merge(
        docs.ok_or_acked(
            docs.ORDER_SUBMITTED,
            "Order handed to the engine (`PENDING`); the verdict follows on the "
            "private WebSocket.",
            "With `?wait=ack`: the engine's verdict.",
        ),
        docs.errors(
            *docs.TRADING_KEY,
            "IDEMPOTENCY_KEY_REUSED",
            "RATE_LIMIT",
            "SYMBOLS_NOT_READY",
            "VALIDATION",
            examples={"VALIDATION": docs.ORDER_VALIDATION},
        ),
    ),
)
async def submit_order(
    body: Annotated[OrderRequest, Body(openapi_examples=docs.ORDER_REQUEST_EXAMPLES)],
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(auth)],
    wait: Annotated[
        str | None, Query(pattern="^ack$", description=docs.WAIT_ACK)
    ] = None,
    idempotency_key: IdempotencyKey = None,
) -> OrderAccepted:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    _check_symbol_ready(body.symbol)

    async def run() -> OrderAccepted:
        log.debug(
            "[%s] submit_order symbol=%s side=%s order_type=%s qty=%s",
            gateway_id,
            body.symbol,
            wire_value(body.side),
            wire_value(body.order_type),
            body.quantity,
        )
        order = build_order(body, gateway_id)
        _cache_submitted(request, gateway_id, order.id, body)
        request.app.state.engine.send_new_order(order)
        event, timed_out = await _await_ack(
            request, topic_order_ack(gateway_id), {"order_id": order.id}, wait
        )
        _ok_when_answered(response, event)
        return OrderAccepted(
            order_id=order.id,
            client_tag=body.client_tag,
            status="PENDING" if event is None else "ACKED",
            accepted=None if event is None else bool(event.get("accepted")),
            reject_code=None if event is None else event.get("reject_code"),
            event=event,
            ack_timeout=timed_out,
        )

    return cast(
        OrderAccepted,
        await idempotent(request, response, gateway_id, idempotency_key, run),
    )


@router.delete(
    "/orders/{order_id}",
    response_model=CancelAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel an order",
    description=(
        "Cancel one resting order of the caller's gateway. `request_tag` "
        "(query) is echoed on the resulting event so the cancel can be "
        "matched to its outcome, and lets `?wait=ack` report a refusal."
    ),
    responses=docs.merge(
        docs.ok_or_acked(
            docs.ORDER_CANCEL_RESULT,
            "Cancel sent (`PENDING_CANCEL`); the outcome follows on the private "
            "WebSocket.",
            "With `?wait=ack`: the cancel's outcome.",
        ),
        docs.errors(*docs.TRADING_KEY, "RATE_LIMIT", "VALIDATION"),
    ),
)
async def cancel_order(
    order_id: OrderIdPath,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(auth)],
    wait: Annotated[
        str | None, Query(pattern="^ack$", description=docs.WAIT_ACK)
    ] = None,
    request_tag: Annotated[
        str | None,
        Query(
            max_length=64,
            description="Caller label echoed on the cancel's outcome event.",
        ),
    ] = None,
) -> CancelAccepted:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    log.debug(
        "[%s] cancel_order order_id=%s request_tag=%s",
        gateway_id,
        order_id,
        request_tag,
    )
    request.app.state.engine.send_cancel(order_id, gateway_id, request_tag=request_tag)
    event, timed_out = await _await_cancel_or_amend_event(
        request,
        success_topic=topic_order_cancelled(gateway_id),
        gateway_id=gateway_id,
        order_id=order_id,
        wait=wait,
        request_tag=request_tag,
    )
    _ok_when_answered(response, event)
    rejected = event is not None and event.get("accepted") is False
    return CancelAccepted(
        order_id=order_id,
        request_tag=request_tag,
        status=(
            "PENDING_CANCEL" if event is None else "REJECTED" if rejected else "ACKED"
        ),
        accepted=None if event is None else not rejected,
        reject_code=(
            event.get("reject_code") if event is not None and rejected else None
        ),
        event=event,
        ack_timeout=timed_out,
    )


@router.patch(
    "/orders/{order_id}",
    response_model=AmendAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Amend an order",
    description=(
        "Change the price and/or quantity of a resting order. At least one "
        "of `price` and `quantity` is required. A price change or a quantity "
        "increase loses time priority (`priority_reset` on the event)."
    ),
    responses=docs.merge(
        docs.ok_or_acked(
            docs.ORDER_AMEND_RESULT,
            "Amend sent (`PENDING_AMEND`); the outcome follows on the private "
            "WebSocket.",
            "With `?wait=ack`: the amend's outcome.",
        ),
        docs.errors(
            *docs.TRADING_KEY,
            "RATE_LIMIT",
            "VALIDATION",
            examples={"VALIDATION": docs.ORDER_VALIDATION},
        ),
    ),
)
async def amend_order(
    order_id: OrderIdPath,
    body: AmendRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(auth)],
    wait: Annotated[
        str | None, Query(pattern="^ack$", description=docs.WAIT_ACK)
    ] = None,
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    log.debug(
        "[%s] amend_order order_id=%s price=%s qty=%s request_tag=%s",
        gateway_id,
        order_id,
        body.price,
        body.quantity,
        body.request_tag,
    )
    request.app.state.engine.send_amend(
        order_id,
        gateway_id,
        body.price,
        body.quantity,
        request_tag=body.request_tag,
    )
    event, timed_out = await _await_cancel_or_amend_event(
        request,
        success_topic=topic_order_amended(gateway_id),
        gateway_id=gateway_id,
        order_id=order_id,
        wait=wait,
        request_tag=body.request_tag,
    )
    _ok_when_answered(response, event)
    rejected = event is not None and event.get("accepted") is False
    return {
        "order_id": order_id,
        "request_tag": body.request_tag,
        "status": (
            "PENDING_AMEND" if event is None else "REJECTED" if rejected else "ACKED"
        ),
        "accepted": None if event is None else not rejected,
        "reject_code": (
            event.get("reject_code") if event is not None and rejected else None
        ),
        "event": event,
        "ack_timeout": timed_out,
    }


@router.post(
    "/orders/{order_id}/replace",
    response_model=ReplaceResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Replace an order",
    description=(
        "Cancel an order and submit a new one in a single call. The body is "
        "a full order, exactly as for `POST /orders`, on the same symbol. The "
        "replacement is only sent once the engine has confirmed the cancel; a "
        "refused cancel (the order already filled, say) is `409 "
        "REPLACE_REJECTED` and nothing is sent. The replacement is a new order "
        "(new id, new time priority); `?wait=ack` waits for its verdict too. "
        "Send an `Idempotency-Key` to make a retry safe."
    ),
    responses=docs.merge(
        docs.ok_or_acked(
            docs.ORDER_REPLACED,
            "Original cancelled; replacement sent to the engine.",
            "With `?wait=ack`: the replacement's verdict.",
        ),
        docs.errors(
            *docs.TRADING_KEY,
            "ENGINE_TIMEOUT",
            "IDEMPOTENCY_KEY_REUSED",
            "RATE_LIMIT",
            "REPLACE_REJECTED",
            "SYMBOLS_NOT_READY",
            "VALIDATION",
            examples={
                "REPLACE_REJECTED": {"reject_code": "ORDER_ALREADY_TERMINAL"},
                "VALIDATION": docs.ORDER_VALIDATION,
            },
        ),
    ),
)
async def replace_order(
    order_id: OrderIdPath,
    body: OrderRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(auth)],
    wait: Annotated[
        str | None, Query(pattern="^ack$", description=docs.WAIT_ACK)
    ] = None,
    idempotency_key: IdempotencyKey = None,
) -> ReplaceResponse:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    # Checked before the cancel: refusing the replacement after cancelling
    # would leave the caller with no order at all.
    _check_symbol_ready(body.symbol)
    known = request.app.state.engine.get_caches(gateway_id).orders.get(order_id, {})
    if known.get("symbol") and known["symbol"] != body.symbol:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "VALIDATION",
                    "message": f"A replacement keeps the order's symbol "
                    f"({known['symbol']}); cancel and submit for another one.",
                    "field": "symbol",
                }
            },
        )

    async def run() -> ReplaceResponse:
        engine = request.app.state.engine
        # A request_tag of our own lets the cancel's refusal be raced, so a
        # replace of an already-filled order is a 409, not a timeout.
        tag = f"replace-{uuid.uuid4().hex}"
        engine.send_cancel(order_id, gateway_id, request_tag=tag)
        try:
            outcome = cast(
                dict[str, Any],
                await engine.await_cancel_or_amend_outcome(
                    success_topic=topic_order_cancelled(gateway_id),
                    gateway_id=gateway_id,
                    order_id=order_id,
                    request_tag=tag,
                    timeout=request.app.state.config.timeouts.wait_ack_sec,
                ),
            )
        except TimeoutError as exc:
            # The cancel's fate is unknown, so no replacement is sent.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
            ) from exc
        if outcome.get("accepted") is False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": {
                        "code": "REPLACE_REJECTED",
                        "message": str(outcome.get("reason") or "Cancel refused"),
                        "reject_code": str(outcome.get("reject_code") or "UNKNOWN"),
                    }
                },
            )
        replacement = build_order(body, gateway_id)
        _cache_submitted(request, gateway_id, replacement.id, body)
        engine.send_new_order(replacement)
        event, timed_out = await _await_ack(
            request, topic_order_ack(gateway_id), {"order_id": replacement.id}, wait
        )
        _ok_when_answered(response, event)
        return ReplaceResponse(
            cancelled_order_id=order_id,
            replacement_order_id=replacement.id,
            status="PENDING" if event is None else "ACKED",
            accepted=None if event is None else bool(event.get("accepted")),
            reject_code=None if event is None else event.get("reject_code"),
            event=event,
            ack_timeout=timed_out,
        )

    return cast(
        ReplaceResponse,
        await idempotent(request, response, gateway_id, idempotency_key, run),
    )


@router.get(
    "/orders",
    response_model=OrderList,
    summary="List my orders",
    description=(
        "The caller's orders as the engine holds them: resting orders plus "
        "recently finished ones. Each entry carries `status` (NEW, PARTIAL, "
        "FILLED, CANCELLED, REJECTED, EXPIRED), `remaining_qty` and the "
        "`client_tag` it was submitted with (null if none). `503 "
        "ENGINE_TIMEOUT` if the engine does not answer in time."
    ),
    responses=docs.merge(
        docs.ok(docs.ORDERS_LIST_REPLY, "The caller's orders."),
        docs.errors(*docs.TRADING_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def list_orders(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    request.app.state.engine.request_orders(gateway_id)
    try:
        response = cast(
            dict[str, Any],
            await request.app.state.engine.await_topic(
                topic_orders(gateway_id),
                request.app.state.config.timeouts.engine_reply_sec,
            ),
        )
    except TimeoutError as exc:
        # No silent fallback to the cache: a client could not tell it from the
        # engine's answer, and bootstrap refuses stale orders for that reason.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc
    response["orders"] = [
        _with_client_tag(order)
        for order in response.get("orders", [])
        if isinstance(order, dict)
    ]
    response["count"] = len(response["orders"])
    return response


@router.get(
    "/orders/{order_id}",
    response_model=CachedOrder,
    summary="Get one order",
    description=(
        "The gateway's cached view of one order: the order as submitted, "
        "overlaid with every engine event seen since (ack, fills, amend, "
        "cancel). The shape is therefore a union of those events' fields, "
        "and `status` is the latest state. 404 for an id this gateway has "
        "not seen, or one old enough to have been evicted "
        "(`order_retention_sec`). For the full event timeline use "
        "`GET /history/orders/{order_id}`."
    ),
    responses=docs.merge(
        docs.ok(docs.ORDER_CACHED, "The order."),
        docs.errors(
            *docs.TRADING_KEY,
            "UNKNOWN_ORDER",
            "VALIDATION",
            examples={
                "UNKNOWN_ORDER": {"message": f"Unknown order {docs.ORDER_ID_EXAMPLE}"}
            },
        ),
    ),
)
async def get_order(
    order_id: OrderIdPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    order = request.app.state.engine.get_caches(gateway_id).orders.get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "UNKNOWN_ORDER",
                    "message": f"Unknown order {order_id}",
                }
            },
        )
    return _with_client_tag(cast(dict[str, Any], order))


@router.post(
    "/oco",
    response_model=OcoAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an OCO pair",
    description=(
        "One-cancels-other: two linked legs on the same symbol and "
        "quantity, typically a profit-target limit and a protective stop. "
        "When one leg fills or triggers, the engine cancels the other. "
        "`oco_id` is chosen by the caller and is what `DELETE /oco/{oco_id}` "
        "takes. " + docs.STRUCTURE_ACK
    ),
    responses=docs.merge(
        docs.ok_or_acked(
            docs.OCO_SENT,
            "OCO sent to the engine (`PENDING`).",
            "With `?wait=ack`: the engine's verdict.",
        ),
        docs.errors(
            *docs.TRADING_KEY,
            "IDEMPOTENCY_KEY_REUSED",
            "RATE_LIMIT",
            "SYMBOLS_NOT_READY",
            "VALIDATION",
            examples={"VALIDATION": docs.ORDER_VALIDATION},
        ),
    ),
)
async def submit_oco(
    body: OcoRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(auth)],
    wait: Annotated[
        str | None, Query(pattern="^ack$", description=docs.WAIT_ACK)
    ] = None,
    idempotency_key: IdempotencyKey = None,
) -> OcoAccepted:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    _check_symbol_ready(body.symbol)

    async def run() -> OcoAccepted:
        request.app.state.engine.send_oco(build_oco_payload(body, gateway_id))
        event, timed_out = await _await_ack(
            request, topic_oco_ack(gateway_id), {"oco_id": body.oco_id}, wait
        )
        return OcoAccepted(
            oco_id=body.oco_id, **_structure_verdict(response, event, timed_out)
        )

    return cast(
        OcoAccepted,
        await idempotent(request, response, gateway_id, idempotency_key, run),
    )


@router.delete(
    "/oco/{oco_id}",
    response_model=OcoCancelPending,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel an OCO pair",
    description="Cancel both legs of the OCO group `oco_id`.",
    responses=docs.merge(
        docs.ok(docs.OCO_CANCEL, "Cancel sent to the engine.", 202),
        docs.errors(*docs.TRADING_KEY, "RATE_LIMIT", "VALIDATION"),
    ),
)
async def cancel_oco(
    oco_id: OcoIdPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, str]:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_oco_cancel(oco_id, gateway_id)
    return {"oco_id": oco_id, "status": "PENDING_CANCEL"}


@router.post(
    "/combos",
    response_model=ComboAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a combo order",
    description=(
        "A multi-leg order (2-10 legs, possibly across symbols) handled as "
        "one unit. `combo_type` decides the rule: `AON` fills all legs or "
        "none. `combo_id` is chosen by the caller and is what "
        "`DELETE /combos/{combo_id}` takes. " + docs.STRUCTURE_ACK
    ),
    responses=docs.merge(
        docs.ok_or_acked(
            docs.COMBO_SENT,
            "Combo sent to the engine (`PENDING`).",
            "With `?wait=ack`: the engine's verdict.",
        ),
        docs.errors(
            *docs.TRADING_KEY,
            "IDEMPOTENCY_KEY_REUSED",
            "RATE_LIMIT",
            "SYMBOLS_NOT_READY",
            "VALIDATION",
            examples={"VALIDATION": docs.ORDER_VALIDATION},
        ),
    ),
)
async def submit_combo(
    body: ComboRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(auth)],
    wait: Annotated[
        str | None, Query(pattern="^ack$", description=docs.WAIT_ACK)
    ] = None,
    idempotency_key: IdempotencyKey = None,
) -> ComboAccepted:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    for leg in body.legs:
        _check_symbol_ready(leg.symbol)

    async def run() -> ComboAccepted:
        request.app.state.engine.send_combo(build_combo_payload(body, gateway_id))
        event, timed_out = await _await_ack(
            request, topic_combo_ack(gateway_id), {"combo_id": body.combo_id}, wait
        )
        return ComboAccepted(
            combo_id=body.combo_id, **_structure_verdict(response, event, timed_out)
        )

    return cast(
        ComboAccepted,
        await idempotent(request, response, gateway_id, idempotency_key, run),
    )


@router.delete(
    "/combos/{combo_id}",
    response_model=ComboCancelPending,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel a combo order",
    description="Cancel every leg of the combo `combo_id`.",
    responses=docs.merge(
        docs.ok(docs.COMBO_CANCEL, "Cancel sent to the engine.", 202),
        docs.errors(*docs.TRADING_KEY, "RATE_LIMIT", "VALIDATION"),
    ),
)
async def cancel_combo(
    combo_id: ComboIdPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, str]:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_combo_cancel(combo_id, gateway_id)
    return {"combo_id": combo_id, "status": "PENDING_CANCEL"}


@router.post(
    "/quotes",
    response_model=QuoteAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a two-sided quote",
    description=(
        "A market-maker quote: a bid and an ask on one symbol, managed as a "
        "pair. Submitting a new quote for a symbol replaces the previous "
        "one, and `DELETE /quotes/{symbol}` withdraws it. Per-symbol "
        "obligations (max spread, min size) are listed in `GET /symbols`. "
        + docs.STRUCTURE_ACK
    ),
    responses=docs.merge(
        docs.ok_or_acked(
            docs.QUOTE_SENT,
            "Quote sent to the engine (`PENDING`).",
            "With `?wait=ack`: the engine's verdict.",
        ),
        docs.errors(
            *docs.TRADING_KEY,
            "IDEMPOTENCY_KEY_REUSED",
            "RATE_LIMIT",
            "SYMBOLS_NOT_READY",
            "VALIDATION",
            examples={"VALIDATION": docs.ORDER_VALIDATION},
        ),
    ),
)
async def submit_quote(
    body: QuoteRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(auth)],
    wait: Annotated[
        str | None, Query(pattern="^ack$", description=docs.WAIT_ACK)
    ] = None,
    idempotency_key: IdempotencyKey = None,
) -> QuoteAccepted:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    _check_symbol_ready(body.symbol)

    async def run() -> QuoteAccepted:
        request.app.state.engine.send_quote(build_quote_payload(body, gateway_id))
        # The ack always names the symbol; quote_id is optional on the request.
        event, timed_out = await _await_ack(
            request, topic_quote_ack(gateway_id), {"symbol": body.symbol}, wait
        )
        return QuoteAccepted(
            symbol=body.symbol,
            quote_id=body.quote_id,
            **_structure_verdict(response, event, timed_out),
        )

    return cast(
        QuoteAccepted,
        await idempotent(request, response, gateway_id, idempotency_key, run),
    )


@router.delete(
    "/quotes/{symbol}",
    response_model=QuoteCancelPending,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel my quote on a symbol",
    description="Withdraw the caller's active quote on `symbol`.",
    responses=docs.merge(
        docs.ok(docs.QUOTE_CANCEL, "Cancel sent to the engine.", 202),
        docs.errors(*docs.TRADING_KEY, "RATE_LIMIT", "VALIDATION"),
    ),
)
async def cancel_quote(
    symbol: SymbolPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, str]:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_quote_cancel(gateway_id, symbol.upper())
    return {"symbol": symbol.upper(), "status": "PENDING_CANCEL"}


@router.post(
    "/mass-cancel",
    response_model=KillSwitchAck,
    summary="Cancel all my orders",
    description=(
        "Cancel every resting order and quote of the caller's own gateway, "
        "optionally limited to one `symbol`. Waits for the engine's "
        "acknowledgement. To act on another gateway or the whole market, an "
        "ADMIN uses `POST /admin/gateways/{gateway_id}/kill-switch` or "
        "`POST /admin/market/kill-switch`."
    ),
    responses=docs.merge(
        docs.ok(docs.MASS_CANCEL_REPLY, "What the engine cancelled."),
        docs.errors(*docs.TRADING_KEY, "ENGINE_TIMEOUT", "RATE_LIMIT", "VALIDATION"),
    ),
)
async def mass_cancel(
    body: MassCancelRequest,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    _check_rate_limit(request, session)
    try:
        event = await request.app.state.engine.send_and_await_kill_switch(
            gateway_id,
            body.symbol or "",
            request.app.state.config.timeouts.wait_ack_sec,
        )
        return cast(dict[str, Any], event)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc
