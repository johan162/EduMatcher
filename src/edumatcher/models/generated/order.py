# GENERATED FROM spec/messages/order.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``order`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/order.yaml``; edit
the spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
docs/developer/06-msgen.md.
"""

from __future__ import annotations

import re
import struct as _struct
from dataclasses import dataclass
from typing import Any, Literal, Mapping, cast

from edumatcher.models.generated._runtime import (
    MessageValidationError,
    balf_header as _msg_header,
    check_balf_frame as _check_frame,
)

FAMILY = "order"
FAMILY_VERSION = 1


_EXECUTION_REPORT_SYMBOL_RE = re.compile("^[A-Z0-9._]+$")
_EXECUTION_REPORT_SIDE_VALUES = ("BUY", "SELL")
_EXECUTION_REPORT_STATUS_VALUES = ("PARTIAL", "FILLED")


_EXECUTION_REPORT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "client_order_id",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "Echoed from the original NEW_ORDER so a client can correlate.",
    },
    {
        "name": "order_id",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "Session-scoped BALF order id assigned by the gateway. A u64 on the wire, not a string - this is the field the reference example got wrong.",
    },
    {
        "name": "fill_price",
        "type": "float",
        "unit": "display_price",
        "required": True,
        "doc": "Execution price in display money. On the wire it is an i64 scaled by the fixed BALF PRICE_SCALE of 10^8, never by the instrument's tick_decimals.",
        "constraints": {"gt": 0},
    },
    {
        "name": "fill_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Quantity matched in this event, not cumulatively.",
        "constraints": {"gt": 0},
    },
    {
        "name": "remaining_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Unfilled quantity after this fill; zero means the order is done.",
        "constraints": {"ge": 0},
    },
    {
        "name": "timestamp_ns",
        "type": "int",
        "unit": "epoch_nanos",
        "required": True,
        "doc": "Trade time in nanoseconds since the Unix epoch.",
        "constraints": {"ge": 0},
    },
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Instrument, echoed for convenience; matches the original order.",
        "constraints": {"max_len": 8, "pattern": "^[A-Z0-9._]+$"},
    },
    {
        "name": "side",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "Side of the filled order.",
        "values": _EXECUTION_REPORT_SIDE_VALUES,
    },
    {
        "name": "status",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "Whether this fill completed the order. Only these two values exist on BALF - there is no NEW or CANCELLED execution report.",
        "values": _EXECUTION_REPORT_STATUS_VALUES,
    },
)


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    """Private per-order fill notification, sent to the gateway session that owns the
    order. Both sides of a match receive their own report.

    Sent for every partial or full fill, so a single order may produce several.
    remaining_qty reaching zero is what marks the order done; status FILLED says the
    same thing and the two must agree.
    """

    client_order_id: int  # unit: dimensionless
    order_id: int  # unit: dimensionless
    fill_price: float  # unit: display_price
    fill_qty: int  # unit: shares
    remaining_qty: int  # unit: shares
    timestamp_ns: int  # unit: epoch_nanos
    symbol: str
    side: Literal["BUY", "SELL"]
    status: Literal["PARTIAL", "FILLED"]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.fill_price <= 0:
            raise MessageValidationError(f"fill_price: {self.fill_price!r} must be > 0")
        if self.fill_qty <= 0:
            raise MessageValidationError(f"fill_qty: {self.fill_qty!r} must be > 0")
        if self.remaining_qty < 0:
            raise MessageValidationError(
                f"remaining_qty: {self.remaining_qty!r} must be >= 0"
            )
        if self.timestamp_ns < 0:
            raise MessageValidationError(
                f"timestamp_ns: {self.timestamp_ns!r} must be >= 0"
            )
        if len(self.symbol) > 8:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 8"
            )
        if not _EXECUTION_REPORT_SYMBOL_RE.fullmatch(self.symbol):
            raise MessageValidationError(
                f"symbol: {self.symbol!r} does not match {_EXECUTION_REPORT_SYMBOL_RE.pattern!r}"
            )
        if self.side not in _EXECUTION_REPORT_SIDE_VALUES:
            raise MessageValidationError(
                f"side: {self.side!r} is not one of {_EXECUTION_REPORT_SIDE_VALUES!r}"
            )
        if self.status not in _EXECUTION_REPORT_STATUS_VALUES:
            raise MessageValidationError(
                f"status: {self.status!r} is not one of {_EXECUTION_REPORT_STATUS_VALUES!r}"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ExecutionReport":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            client_order_id=int(p["client_order_id"]),
            order_id=int(p["order_id"]),
            fill_price=float(p["fill_price"]),
            fill_qty=int(p["fill_qty"]),
            remaining_qty=int(p["remaining_qty"]),
            timestamp_ns=int(p["timestamp_ns"]),
            symbol=str(p["symbol"]),
            side=cast(Literal["BUY", "SELL"], str(p["side"])),
            status=cast(Literal["PARTIAL", "FILLED"], str(p["status"])),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "client_order_id": self.client_order_id,
            "order_id": self.order_id,
            "fill_price": self.fill_price,
            "fill_qty": self.fill_qty,
            "remaining_qty": self.remaining_qty,
            "timestamp_ns": self.timestamp_ns,
            "symbol": self.symbol,
            "side": self.side,
            "status": self.status,
        }


def describe_execution_report() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _EXECUTION_REPORT_FIELDS


MSGTYPE_EXECUTION_REPORT_BALF = 0x20
FRAME_SIZE_EXECUTION_REPORT_BALF = 64
_EXECUTION_REPORT_BALF_FMT = "<QQqIIQ8sBB6x"
_EXECUTION_REPORT_BALF_STRUCT = _struct.Struct(_EXECUTION_REPORT_BALF_FMT)
PRICE_SCALE_EXECUTION_REPORT_BALF = 100000000
_EXECUTION_REPORT_BALF_SIDE_TO_WIRE = {"BUY": 1, "SELL": 2}
_EXECUTION_REPORT_BALF_SIDE_FROM_WIRE = {
    v: k for k, v in _EXECUTION_REPORT_BALF_SIDE_TO_WIRE.items()
}
_EXECUTION_REPORT_BALF_STATUS_TO_WIRE = {"PARTIAL": 1, "FILLED": 2}
_EXECUTION_REPORT_BALF_STATUS_FROM_WIRE = {
    v: k for k, v in _EXECUTION_REPORT_BALF_STATUS_TO_WIRE.items()
}


def serialise_execution_report_balf(
    payload: Mapping[str, Any],
    *,
    seq_no: int,
    flags: int = 0,
) -> bytes:
    """Serialise a payload into one BALF frame.

    Returns exactly FRAME_SIZE_EXECUTION_REPORT_BALF bytes: the fixed 8-byte header
    followed by the body laid out in the spec. The header is the generator's, not the
    spec's — it must not be declared in `layout` (design section B.13).

    Reads only the laid-out fields, and coerces each to its declared type, so this and
    the typed binding never disagree.
    """
    return _msg_header(
        MSGTYPE_EXECUTION_REPORT_BALF, seq_no, flags
    ) + _EXECUTION_REPORT_BALF_STRUCT.pack(
        int(payload["client_order_id"]),
        int(payload["order_id"]),
        round(float(payload["fill_price"]) * 100000000),
        int(payload["fill_qty"]),
        int(payload["remaining_qty"]),
        int(payload["timestamp_ns"]),
        str(payload["symbol"]).encode(),
        _EXECUTION_REPORT_BALF_SIDE_TO_WIRE[str(payload["side"])],
        _EXECUTION_REPORT_BALF_STATUS_TO_WIRE[str(payload["status"])],
    )


def parse_execution_report_balf(frame: bytes) -> "ExecutionReport":
    """Parse one BALF frame into this message.

    Validates the header (magic, version, msg_type) and the frame length, because a
    wrong-length frame is not this message and reading it as one would silently produce
    nonsense. Field values are coerced but their declared rules are not checked — call
    ``validate()`` for that (design section 5.1.1).

    Raises MessageValidationError on a header or length mismatch.
    """
    _check_frame(frame, MSGTYPE_EXECUTION_REPORT_BALF, FRAME_SIZE_EXECUTION_REPORT_BALF)
    (
        client_order_id,
        order_id,
        fill_price,
        fill_qty,
        remaining_qty,
        timestamp_ns,
        symbol,
        side,
        status,
    ) = _EXECUTION_REPORT_BALF_STRUCT.unpack_from(frame, 8)
    return ExecutionReport(
        client_order_id=client_order_id,
        order_id=order_id,
        fill_price=fill_price / 100000000,
        fill_qty=fill_qty,
        remaining_qty=remaining_qty,
        timestamp_ns=timestamp_ns,
        symbol=symbol.split(b"\x00")[0].decode(),
        side=cast(
            Literal["BUY", "SELL"], _EXECUTION_REPORT_BALF_SIDE_FROM_WIRE.get(side, "")
        ),
        status=cast(
            Literal["PARTIAL", "FILLED"],
            _EXECUTION_REPORT_BALF_STATUS_FROM_WIRE.get(status, ""),
        ),
    )


FAMILY_TOPICS: tuple[str, ...] = ()
