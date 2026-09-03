"""Canonical order rejection codes and exchange-initiated cancel reasons.

The message spec is the source of truth; this module only gives callers a
stable import path that is not tied to the generated module layout.

``RejectCode`` says why an order was refused; ``CancelReason`` says why the
exchange cancelled one it had already accepted. They are separate vocabularies
on purpose - a cancel is not a rejection, and most reject codes can never
describe one.
"""

from edumatcher.models.generated.order import (
    OrderAckRejectCode as RejectCode,
    OrderCancelledCancelReason as CancelReason,
    _ORDER_ACK_REJECT_CODE_VALUES as REJECT_CODES,  # pyright: ignore[reportPrivateUsage]
    _ORDER_CANCELLED_CANCEL_REASON_VALUES as CANCEL_REASONS,  # pyright: ignore[reportPrivateUsage]
)

__all__ = ["RejectCode", "REJECT_CODES", "CancelReason", "CANCEL_REASONS"]
