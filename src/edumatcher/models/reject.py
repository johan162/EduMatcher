"""Canonical order rejection codes.

The message spec is the source of truth; this module only gives callers a
stable import path that is not tied to the generated module layout.
"""

from edumatcher.models.generated.order import (
    OrderAckRejectCode as RejectCode,
    _ORDER_ACK_REJECT_CODE_VALUES as REJECT_CODES,  # pyright: ignore[reportPrivateUsage]
)

__all__ = ["RejectCode", "REJECT_CODES"]
