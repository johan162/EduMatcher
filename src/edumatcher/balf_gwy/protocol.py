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
from edumatcher.models.order import OrderType
from edumatcher.models.order_fields import ORDER_FIELDS, check_type_fields

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
#: The session's token bucket was empty (decision Q2 of the BALF review).
#: A request used to be dropped with no answer at all; now it is refused
#: with its own ack type. The engine's reject_code has RATE_LIMITED too.
RC_RATE_LIMITED: int = 0x0D
#: A per-order or per-participant risk control refused the order:
#: max order quantity or value, position limit, or an active kill switch.
RC_RISK_LIMIT: int = 0x0E
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
# Engine reject_code -> BALF reject code
# ---------------------------------------------------------------------------

#: The engine's machine-readable ``order.ack.reject_code`` (stable across
#: every transport, spec/messages/order.yaml) mapped onto BALF's one-byte
#: codes. Codes not listed are RC_OTHER, with the engine's text in ``reason``.
_ENGINE_CODE_TO_RC: dict[str, int] = {
    "GATEWAY_NOT_CONFIGURED": RC_GW_NOT_CONFIGURED,
    # The engine refuses a gateway that has no session with AUTH_REQUIRED
    # ("Gateway not connected: <ID>", engine/main.py _gateway_reject_code).
    "AUTH_REQUIRED": RC_GW_NOT_CONNECTED,
    "UNKNOWN_SYMBOL": RC_SYMBOL_NOT_CONFIGURED,
    "MARKET_CLOSED": RC_MARKET_CLOSED,
    "INSTRUMENT_HALTED": RC_HALT_REJECTION,
    "CIRCUIT_BREAKER_ACTIVE": RC_HALT_REJECTION,
    "INSUFFICIENT_LIQUIDITY": RC_INSUFFICIENT_LIQUIDITY,
    "COLLAR_BREACH": RC_PRICE_COLLAR,
    "MALFORMED_MESSAGE": RC_INVALID_FIELD,
    "MISSING_FIELD": RC_INVALID_FIELD,
    "INVALID_VALUE": RC_INVALID_FIELD,
    "UNSUPPORTED_FIELD": RC_INVALID_FIELD,
    "TICK_VIOLATION": RC_INVALID_FIELD,
    "LOT_VIOLATION": RC_INVALID_FIELD,
    "PRICE_OUT_OF_RANGE": RC_INVALID_FIELD,
    "QTY_OUT_OF_RANGE": RC_INVALID_FIELD,
    "RATE_LIMITED": RC_RATE_LIMITED,
    "MAX_ORDER_QTY": RC_RISK_LIMIT,
    "MAX_ORDER_VALUE": RC_RISK_LIMIT,
    "POSITION_LIMIT": RC_RISK_LIMIT,
    "KILL_SWITCH_ACTIVE": RC_RISK_LIMIT,
}


def classify_engine_reject(reject_code: str | None, reason: str) -> int:
    """Map an engine order rejection to a BALF ORDER_ACK reject code.

    Classifies on the engine's ``reject_code``, not its prose. The prose
    classifier this replaces matched eleven sentences; anything else, a
    reworded sentence included, became RC_OTHER with a 25-byte stump of a
    reason, so a negative price or a risk-limit refusal could not be told
    from an internal error (review C7). The text is still read where BALF
    splits one engine code in two:

    - SESSION_NOT_PERMITTED is ATO outside the opening auction, ATC outside
      the closing auction, or any other type the phase refuses;
    - MISSING_FIELD on a trailing stop with no STOP= and no prior trade has
      its own code, RC_TRAILING_STOP_NO_PRICE.

    A rejection without a code (the spec says every one has it) is RC_OTHER.
    """
    if reject_code == "SESSION_NOT_PERMITTED":
        if reason.startswith("ATO orders only accepted during"):
            return RC_ATO_OUTSIDE_OPENING
        if reason.startswith("ATC orders only accepted during"):
            return RC_ATC_OUTSIDE_CLOSING
        return RC_PHASE_REJECTION
    if reject_code == "MISSING_FIELD" and reason.startswith(
        "Trailing stop requires STOP= or a prior trade price"
    ):
        return RC_TRAILING_STOP_NO_PRICE
    if reject_code is None:
        return RC_OTHER
    return _ENGINE_CODE_TO_RC.get(reject_code, RC_OTHER)


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
    """Cross-field price validation for NEW_ORDER: the shared per-type rule.

    The same table REST, ALF and the engine apply (``models/order_fields``,
    WP-API16), so a field the type does not use is refused rather than
    ignored. A fixed-width BALF field is "absent" when zero. Every verdict is
    ``RC_INVALID_FIELD``, BALF's one code for a field error.
    """
    ot = parsed.get("order_type_str", "")
    present = [name for name in ORDER_FIELDS if parsed.get(name, 0) != 0]
    violation = check_type_fields(OrderType(ot), present, where="on an order")
    if violation is not None:
        raise BalfValidationError(RC_INVALID_FIELD, violation.message)
    if ot == "ICEBERG":
        validate_visible_qty(parsed.get("visible_qty", 0), parsed.get("quantity", 0))


def validate_amend_flags(amend_flags: int) -> None:
    """Raise BalfValidationError if no amend bits are set."""
    if (amend_flags & 0x03) == 0:
        raise BalfValidationError(
            RC_INVALID_FIELD, "amend_flags: at least one bit required"
        )
