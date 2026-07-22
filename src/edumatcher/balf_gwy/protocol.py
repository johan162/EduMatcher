"""BALF gateway protocol validation and reject-code classification.

Two responsibilities:
1. Validate decoded BALF field values (side, order_type, tif, smp, quantities)
   and raise ``BalfValidationError`` with a BALF reject code.
2. Classify engine ``reason`` strings into compact ORDER_ACK reject codes
   (see spec §5.5 — Deterministic classifier v1.0.0).
"""

from __future__ import annotations

from typing import Any

from edumatcher.balf_gwy.codec import (
    ORDER_TYPE_TO_STR,
    SIDE_TO_STR,
    SMP_TO_STR,
    TIF_TO_STR,
)

# ---------------------------------------------------------------------------
# Reject codes for ORDER_ACK — matches spec §5.5
# ---------------------------------------------------------------------------

RC_ACCEPTED: int = 0x00
RC_GW_NOT_CONFIGURED: int = 0x01
RC_GW_NOT_CONNECTED: int = 0x02
RC_SYMBOL_NOT_CONFIGURED: int = 0x03
RC_MARKET_CLOSED: int = 0x04
RC_ATO_OUTSIDE_OPENING: int = 0x05
RC_ATC_OUTSIDE_CLOSING: int = 0x06
RC_HALT_REJECTION: int = 0x07
RC_PHASE_REJECTION: int = 0x08
RC_TRAILING_STOP_NO_PRICE: int = 0x09
RC_INSUFFICIENT_LIQUIDITY: int = 0x0A
RC_PRICE_COLLAR: int = 0x0B
RC_INVALID_FIELD: int = 0x0C
RC_OTHER: int = 0xFF

# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------


class BalfValidationError(Exception):
    """Raised for invalid BALF message field values.

    Carries a BALF reject code and a short ASCII reason string (max 25 bytes).
    """

    def __init__(self, reject_code: int, reason: str) -> None:
        super().__init__(reason)
        self.reject_code = reject_code
        self.reason = reason[:25]


# ---------------------------------------------------------------------------
# Engine reason -> reject code classifier
# Deterministic, ordered, first-match-wins — spec §5.5
# ---------------------------------------------------------------------------


def classify_engine_reason(reason: str) -> int:
    """Map an engine rejection reason string to a BALF ORDER_ACK reject code.

    Matching is case-sensitive to match exact engine strings.
    """
    if reason.startswith("Gateway not configured:"):
        return RC_GW_NOT_CONFIGURED
    if reason.startswith("Gateway not connected:"):
        return RC_GW_NOT_CONNECTED
    if reason.startswith("Symbol not configured:"):
        return RC_SYMBOL_NOT_CONFIGURED
    if reason == "Market is closed":
        return RC_MARKET_CLOSED
    if reason.startswith("ATO orders only accepted during"):
        return RC_ATO_OUTSIDE_OPENING
    if reason.startswith("ATC orders only accepted during"):
        return RC_ATC_OUTSIDE_CLOSING
    if "orders rejected during circuit breaker halt" in reason:
        return RC_HALT_REJECTION
    if "orders not accepted during" in reason:
        return RC_PHASE_REJECTION
    if reason == "Trailing stop requires STOP= or a prior trade price":
        return RC_TRAILING_STOP_NO_PRICE
    if reason == "Insufficient liquidity":
        return RC_INSUFFICIENT_LIQUIDITY
    if "collar" in reason:
        return RC_PRICE_COLLAR
    return RC_OTHER


# ---------------------------------------------------------------------------
# Field validation helpers
# ---------------------------------------------------------------------------


def validate_side(code: int) -> str:
    """Return the canonical side string or raise BalfValidationError."""
    s = SIDE_TO_STR.get(code)
    if s is None:
        raise BalfValidationError(RC_INVALID_FIELD, f"invalid side 0x{code:02X}")
    return s


def validate_order_type(code: int) -> str:
    """Return the canonical order_type string or raise BalfValidationError."""
    ot = ORDER_TYPE_TO_STR.get(code)
    if ot is None:
        raise BalfValidationError(RC_INVALID_FIELD, f"invalid order_type 0x{code:02X}")
    return ot


def validate_tif(code: int) -> str:
    """Return the canonical TIF string or raise BalfValidationError."""
    t = TIF_TO_STR.get(code)
    if t is None:
        raise BalfValidationError(RC_INVALID_FIELD, f"invalid tif 0x{code:02X}")
    return t


def validate_smp(code: int) -> str:
    """Return the canonical SMP string or raise BalfValidationError."""
    s = SMP_TO_STR.get(code)
    if s is None:
        raise BalfValidationError(RC_INVALID_FIELD, f"invalid smp 0x{code:02X}")
    return s


def validate_quantity(qty: int) -> None:
    """Raise BalfValidationError if quantity is <= 0 or unreasonably large."""
    if qty <= 0:
        raise BalfValidationError(RC_INVALID_FIELD, "quantity must be > 0")
    if qty > 2_000_000_000:
        raise BalfValidationError(RC_INVALID_FIELD, "quantity exceeds limit")


def validate_visible_qty(visible: int, quantity: int) -> None:
    """Raise BalfValidationError if ICEBERG visible_qty is invalid."""
    if visible <= 0:
        raise BalfValidationError(RC_INVALID_FIELD, "visible_qty must be > 0")
    if visible >= quantity:
        raise BalfValidationError(RC_INVALID_FIELD, "visible_qty must be < quantity")


def validate_price_field(price: int, field_name: str) -> None:
    """Raise BalfValidationError if price is zero when required."""
    if price == 0:
        raise BalfValidationError(RC_INVALID_FIELD, f"{field_name} required but zero")


def validate_symbol(sym: str) -> None:
    """Raise BalfValidationError for obviously invalid symbol strings."""
    if not sym:
        raise BalfValidationError(RC_INVALID_FIELD, "symbol is empty")
    if len(sym) > 8:
        raise BalfValidationError(RC_INVALID_FIELD, "symbol exceeds 8 chars")
    if not sym.isalnum():
        raise BalfValidationError(RC_INVALID_FIELD, "symbol contains invalid chars")


def validate_new_order_price_logic(parsed: dict[str, Any]) -> None:
    """Cross-field price validation for NEW_ORDER.

    Maps order_type string -> required / forbidden price fields and raises
    BalfValidationError for violations.
    """
    ot = parsed.get("order_type_str", "")
    price = parsed.get("price", 0)
    stop_price = parsed.get("stop_price", 0)
    trail_offset = parsed.get("trail_offset", 0)
    visible_qty = parsed.get("visible_qty", 0)
    quantity = parsed.get("quantity", 0)

    if ot in {"LIMIT", "IOC", "FOK"}:
        if price == 0:
            raise BalfValidationError(RC_INVALID_FIELD, "price required for " + ot)
    elif ot == "STOP":
        if stop_price == 0:
            raise BalfValidationError(RC_INVALID_FIELD, "stop_price required for STOP")
    elif ot == "STOP_LIMIT":
        if stop_price == 0:
            raise BalfValidationError(
                RC_INVALID_FIELD, "stop_price required for STOP_LIMIT"
            )
        if price == 0:
            raise BalfValidationError(RC_INVALID_FIELD, "price required for STOP_LIMIT")
    elif ot == "ICEBERG":
        if price == 0:
            raise BalfValidationError(RC_INVALID_FIELD, "price required for ICEBERG")
        validate_visible_qty(visible_qty, quantity)
    elif ot == "TRAILING_STOP":
        if trail_offset == 0:
            raise BalfValidationError(
                RC_INVALID_FIELD, "trail_offset required for TRAILING_STOP"
            )


def validate_amend_flags(amend_flags: int) -> None:
    """Raise BalfValidationError if no amend bits are set."""
    if (amend_flags & 0x03) == 0:
        raise BalfValidationError(
            RC_INVALID_FIELD, "amend_flags: at least one bit required"
        )
