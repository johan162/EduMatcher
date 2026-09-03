"""BALF <-> engine message translation.

Converts a validated and decoded BALF parsed-dict into the engine JSON
payload structures expected by ``edumatcher.models.message`` builders,
and maps engine event payloads back to BALF outbound frame parameters.
"""

from __future__ import annotations

import uuid
from typing import Any

from edumatcher.balf_gwy.codec import (
    CANCEL_REASON_CLIENT,
    decode_price,
    encode_price,
)
from edumatcher.balf_gwy.protocol import (
    RC_INVALID_FIELD,
    BalfValidationError,
    validate_new_order_price_logic,
    validate_order_type,
    validate_quantity,
    validate_side,
    validate_smp,
    validate_symbol,
    validate_tif,
)
from edumatcher.models.clock import now_ns
from edumatcher.models.price import TickViolation, to_ticks_exact

# ---------------------------------------------------------------------------
# NEW_ORDER → engine order dict
# ---------------------------------------------------------------------------


def build_engine_new_order(
    parsed: dict[str, Any],
    gateway_id: str,
    engine_order_id: str,
) -> dict[str, Any]:
    """Validate and translate a parsed NEW_ORDER into an engine order dict.

    Raises ``BalfValidationError`` for invalid field values.
    Returns a dict ready to pass to ``make_order_new_msg()``.

    ``engine_order_id`` is a pre-generated UUID string supplied by the caller.
    """
    symbol = str(parsed["symbol"])
    validate_symbol(symbol)

    side_str = validate_side(int(parsed["side"]))
    ot_str = validate_order_type(int(parsed["order_type"]))
    tif_str = validate_tif(int(parsed["tif"]))
    smp_str = validate_smp(int(parsed["smp"]))
    quantity = int(parsed["quantity"])
    validate_quantity(quantity)

    # Decode BALF prices (i64 * PRICE_SCALE) to display floats
    price_display = decode_price(int(parsed["price"])) if parsed["price"] != 0 else None
    stop_price_display = (
        decode_price(int(parsed["stop_price"])) if parsed["stop_price"] != 0 else None
    )
    trail_offset_display = (
        decode_price(int(parsed["trail_offset"]))
        if parsed["trail_offset"] != 0
        else None
    )
    visible_qty = int(parsed["visible_qty"]) if parsed["visible_qty"] != 0 else None

    parsed_with_strs = dict(parsed)
    parsed_with_strs["order_type_str"] = ot_str
    parsed_with_strs["quantity"] = quantity
    parsed_with_strs["visible_qty"] = visible_qty if visible_qty is not None else 0
    validate_new_order_price_logic(parsed_with_strs)

    # Convert display prices to engine ticks. BALF carries prices as
    # fixed-point at scale 1e8, so a client can express far finer values than
    # any symbol's tick grid; rounding them silently would move the price.
    try:
        price_ticks = (
            to_ticks_exact(price_display, symbol) if price_display is not None else None
        )
        stop_price_ticks = (
            to_ticks_exact(stop_price_display, symbol)
            if stop_price_display is not None
            else None
        )
        trail_offset_ticks = (
            to_ticks_exact(trail_offset_display, symbol)
            if trail_offset_display is not None
            else None
        )
    except TickViolation as exc:
        raise BalfValidationError(RC_INVALID_FIELD, "price off tick grid") from exc

    order: dict[str, Any] = {
        "id": engine_order_id,
        "symbol": symbol,
        "side": side_str,
        "order_type": ot_str,
        "tif": tif_str,
        "quantity": quantity,
        "remaining_qty": quantity,
        "gateway_id": gateway_id,
        # BALF NEW_ORDER has no timestamp field; stamp at gateway ingress.
        "timestamp": now_ns(),
        "smp_action": smp_str,
        "status": "NEW",
    }
    if price_ticks is not None:
        order["price"] = price_ticks
    if stop_price_ticks is not None:
        order["stop_price"] = stop_price_ticks
    if trail_offset_ticks is not None:
        order["trail_offset"] = trail_offset_ticks
    if visible_qty is not None:
        order["visible_qty"] = visible_qty
    return order


# ---------------------------------------------------------------------------
# Engine event payloads → BALF frame parameters
# ---------------------------------------------------------------------------


def engine_fill_to_execution_report_dict(
    payload: dict[str, Any],
    balf_order_id: int,
    client_order_id: int,
) -> dict[str, Any]:
    """Map an engine fill payload to a spec-level execution_report dict.

    Returns the logical field values (display-float price, "BUY"/"SELL" side);
    ``serialise_execution_report_balf`` owns the scaling and enum-to-wire coding.
    """
    ts = payload.get("timestamp") or payload.get("fill_timestamp") or 0
    return {
        "client_order_id": client_order_id,
        "order_id": balf_order_id,
        "fill_price": float(payload.get("fill_price") or 0.0),
        "fill_qty": int(payload.get("fill_qty") or 0),
        "remaining_qty": int(payload.get("remaining_qty") or 0),
        "timestamp_ns": int(ts),
        "symbol": str(payload.get("symbol") or ""),
        "side": str(payload.get("side") or "BUY").upper(),
        "status": str(payload.get("status") or "PARTIAL").upper(),
    }


def engine_amended_to_balf_params(
    payload: dict[str, Any],
    balf_order_id: int,
    client_order_id: int,
    symbol: str,
) -> dict[str, Any]:
    """Extract parameters for ``build_amend_ack`` from an engine amended payload."""
    price_display = payload.get("price")
    new_price = encode_price(float(price_display)) if price_display is not None else 0
    new_quantity = int(payload.get("qty") or 0)
    remaining_qty = int(payload.get("remaining_qty") or 0)
    priority_reset = bool(payload.get("priority_reset", False))

    return {
        "client_order_id": client_order_id,
        "balf_order_id": balf_order_id,
        "accepted": True,
        "new_price": new_price,
        "new_quantity": new_quantity,
        "remaining_qty": remaining_qty,
        "priority_reset": priority_reset,
    }


def cancel_reason_from_engine(payload: dict[str, Any]) -> int:
    """Determine the BALF cancel_reason code from an engine cancelled payload."""
    # Engine cancelled events triggered by gateways have no special reason field;
    # all others (SMP, session-end, IOC) come via order.ack with accepted=False.
    # For order.cancelled events we always treat as explicit client request.
    return CANCEL_REASON_CLIENT


def new_engine_order_id() -> str:
    """Generate a fresh UUID string for a new engine order."""
    return str(uuid.uuid4())
