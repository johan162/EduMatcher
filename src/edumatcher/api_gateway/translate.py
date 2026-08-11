"""Translation helpers from REST JSON schemas to engine message payloads."""

from __future__ import annotations

from typing import Any

from edumatcher.api_gateway.schemas import (
    ComboRequest,
    OcoLegRequest,
    OcoRequest,
    OrderRequest,
    QuoteRequest,
)
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.order import Order, OrderType, Side, SmpAction, TIF
from edumatcher.models.price import to_ticks


def wire_value(value: object) -> str:
    """Return the JSON/engine wire value for enum-like objects."""
    raw = getattr(value, "value", value)
    return str(raw)


def build_order(request: OrderRequest, gateway_id: str) -> Order:
    """Create an engine ``Order`` from a validated REST request."""
    return Order.create(
        symbol=request.symbol,
        side=Side(request.side),
        order_type=OrderType(request.order_type),
        quantity=request.quantity,
        gateway_id=gateway_id,
        tif=TIF(request.tif),
        price=(
            to_ticks(request.price, request.symbol)
            if request.price is not None
            else None
        ),
        stop_price=(
            to_ticks(request.stop_price, request.symbol)
            if request.stop_price is not None
            else None
        ),
        visible_qty=request.visible_qty,
        # None (omitted in the request) is preserved as None here too -- the
        # engine applies the gateway's configured smp_action default in that
        # case rather than an explicit NONE. See SmpAction's docstring.
        smp_action=(
            SmpAction(request.smp_action) if request.smp_action is not None else None
        ),
        trail_offset=(
            to_ticks(request.trail_offset, request.symbol)
            if request.trail_offset is not None
            else None
        ),
    )


def build_quote_payload(request: QuoteRequest, gateway_id: str) -> dict[str, Any]:
    """Build the quote.new payload, with prices converted to engine ticks.

    The API takes display money from its clients and the wire carries ticks,
    so the conversion belongs here — the same boundary ``_oco_leg_to_payload``
    below draws, and the rule design section 15.2 set for every engine-inbound
    price. Quotes joined it in 6.1b.
    """
    payload: dict[str, Any] = {
        "gateway_id": gateway_id,
        "symbol": request.symbol,
        "bid_price": to_ticks(request.bid_price, request.symbol),
        "bid_qty": request.bid_qty,
        "ask_price": to_ticks(request.ask_price, request.symbol),
        "ask_qty": request.ask_qty,
        "tif": wire_value(request.tif),
    }
    if request.quote_id:
        payload["quote_id"] = request.quote_id
    return payload


def _oco_leg_to_payload(leg: OcoLegRequest, symbol: str) -> dict[str, Any]:
    """Build one OCO leg payload, with prices converted to engine ticks.

    Both legs are on ``symbol``; OCO has no per-leg symbol.
    """
    payload: dict[str, Any] = {
        "side": wire_value(leg.side),
        "order_type": wire_value(leg.order_type),
    }
    if leg.price is not None:
        payload["price"] = to_ticks(leg.price, symbol)
    if leg.stop_price is not None:
        payload["stop_price"] = to_ticks(leg.stop_price, symbol)
    if leg.trail_offset is not None:
        payload["trail_offset"] = to_ticks(leg.trail_offset, symbol)
    return payload


def build_oco_payload(request: OcoRequest, gateway_id: str) -> dict[str, Any]:
    """Build the existing order.oco dict payload."""
    return {
        "oco_id": request.oco_id,
        "gateway_id": gateway_id,
        "symbol": request.symbol,
        "quantity": request.quantity,
        "tif": wire_value(request.tif),
        "leg1": _oco_leg_to_payload(request.leg1, request.symbol),
        "leg2": _oco_leg_to_payload(request.leg2, request.symbol),
    }


def build_combo_payload(request: ComboRequest, gateway_id: str) -> dict[str, Any]:
    """Create a ``ComboOrder`` and return its engine dict payload."""
    legs = [
        ComboLeg(
            symbol=leg.symbol,
            side=Side(leg.side),
            order_type=OrderType(leg.order_type),
            quantity=leg.quantity,
            price=to_ticks(leg.price, leg.symbol) if leg.price is not None else None,
            stop_price=(
                to_ticks(leg.stop_price, leg.symbol)
                if leg.stop_price is not None
                else None
            ),
            # smp_action is combo-level (applies uniformly to every leg,
            # matching the ALF console/gateway combo protocol); None means
            # omitted -- see build_order's comment above.
            smp_action=(
                SmpAction(request.smp_action)
                if request.smp_action is not None
                else None
            ),
        )
        for leg in request.legs
    ]
    combo = ComboOrder.create(
        combo_id=request.combo_id,
        gateway_id=gateway_id,
        combo_type=ComboType(request.combo_type),
        tif=TIF(request.tif),
        legs=legs,
    )
    return combo.to_submission_dict()
