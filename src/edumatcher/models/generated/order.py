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

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import (
    MessageValidationError,
    balf_header as _msg_header,
    check_balf_frame as _check_frame,
)

FAMILY = "order"
FAMILY_VERSION = 1


_OCO_LEG_SIDE_VALUES = ("BUY", "SELL")
OcoLegSide = Literal["BUY", "SELL"]
_OCO_LEG_ORDER_TYPE_VALUES = (
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
)
OcoLegOrderType = Literal[
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
]


@dataclass(frozen=True, slots=True)
class OcoLeg:
    """One side of an OCO pair. It has no symbol or quantity of its own: both legs
    trade the same instrument in the same size, and the OCO carries those. That is
    what makes it a different record from a combo leg, which does own a symbol and
    a quantity.
    """

    side: OcoLegSide
    order_type: OcoLegOrderType
    price: int | None = None  # unit: ticks
    stop_price: int | None = None  # unit: ticks
    trail_offset: int | None = None  # unit: ticks

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.side not in _OCO_LEG_SIDE_VALUES:
            raise MessageValidationError(
                f"side: {self.side!r} is not one of {_OCO_LEG_SIDE_VALUES!r}"
            )
        if self.order_type not in _OCO_LEG_ORDER_TYPE_VALUES:
            raise MessageValidationError(
                f"order_type: {self.order_type!r} is not one of {_OCO_LEG_ORDER_TYPE_VALUES!r}"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OcoLeg":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            side=cast(OcoLegSide, str(p["side"])),
            order_type=cast(OcoLegOrderType, str(p["order_type"])),
            price=None if p.get("price") is None else int(p["price"]),
            stop_price=None if p.get("stop_price") is None else int(p["stop_price"]),
            trail_offset=(
                None if p.get("trail_offset") is None else int(p["trail_offset"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "side": self.side,
            "order_type": self.order_type,
        }
        if self.price is not None:
            payload["price"] = self.price
        if self.stop_price is not None:
            payload["stop_price"] = self.stop_price
        if self.trail_offset is not None:
            payload["trail_offset"] = self.trail_offset
        return payload


_COMBO_LEG_SIDE_VALUES = ("BUY", "SELL")
ComboLegSide = Literal["BUY", "SELL"]
_COMBO_LEG_ORDER_TYPE_VALUES = (
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
)
ComboLegOrderType = Literal[
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
]
_COMBO_LEG_SMP_ACTION_VALUES = (
    "NONE",
    "CANCEL_AGGRESSOR",
    "CANCEL_RESTING",
    "CANCEL_BOTH",
)
ComboLegSmpAction = Literal["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"]


@dataclass(frozen=True, slots=True)
class ComboLeg:
    """One leg of a combo. Unlike an OcoLeg it owns a symbol and a quantity: the legs
    of a combo trade different instruments, in sizes that need not match. That is
    why the two are separate types rather than one shared `leg` - an early draft
    of design section 15 assumed they could be merged and was wrong.
    """

    symbol: str
    side: ComboLegSide
    order_type: ComboLegOrderType
    quantity: int  # unit: shares
    price: int | None = None  # unit: ticks
    stop_price: int | None = None  # unit: ticks
    smp_action: ComboLegSmpAction | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.side not in _COMBO_LEG_SIDE_VALUES:
            raise MessageValidationError(
                f"side: {self.side!r} is not one of {_COMBO_LEG_SIDE_VALUES!r}"
            )
        if self.order_type not in _COMBO_LEG_ORDER_TYPE_VALUES:
            raise MessageValidationError(
                f"order_type: {self.order_type!r} is not one of {_COMBO_LEG_ORDER_TYPE_VALUES!r}"
            )
        if self.quantity <= 0:
            raise MessageValidationError(f"quantity: {self.quantity!r} must be > 0")
        if self.smp_action is not None:
            if self.smp_action not in _COMBO_LEG_SMP_ACTION_VALUES:
                raise MessageValidationError(
                    f"smp_action: {self.smp_action!r} is not one of {_COMBO_LEG_SMP_ACTION_VALUES!r}"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ComboLeg":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            side=cast(ComboLegSide, str(p["side"])),
            order_type=cast(ComboLegOrderType, str(p["order_type"])),
            quantity=int(p["quantity"]),
            price=None if p.get("price") is None else int(p["price"]),
            stop_price=None if p.get("stop_price") is None else int(p["stop_price"]),
            smp_action=cast(
                ComboLegSmpAction | None,
                None if p.get("smp_action") is None else str(p["smp_action"]),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "price": self.price,
            "stop_price": self.stop_price,
            "smp_action": self.smp_action,
        }


_ORDER_DISPLAY_SIDE_VALUES = ("BUY", "SELL")
OrderDisplaySide = Literal["BUY", "SELL"]
_ORDER_DISPLAY_ORDER_TYPE_VALUES = (
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
)
OrderDisplayOrderType = Literal[
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
]
_ORDER_DISPLAY_TIF_VALUES = ("DAY", "GTC", "ATO", "ATC")
OrderDisplayTif = Literal["DAY", "GTC", "ATO", "ATC"]
_ORDER_DISPLAY_STATUS_VALUES = (
    "NEW",
    "PARTIAL",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
)
OrderDisplayStatus = Literal[
    "NEW",
    "PARTIAL",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
]
_ORDER_DISPLAY_SMP_ACTION_VALUES = (
    "NONE",
    "CANCEL_AGGRESSOR",
    "CANCEL_RESTING",
    "CANCEL_BOTH",
)
OrderDisplaySmpAction = Literal[
    "NONE",
    "CANCEL_AGGRESSOR",
    "CANCEL_RESTING",
    "CANCEL_BOTH",
]
_ORDER_DISPLAY_ORIGIN_VALUES = ("ORDER", "QUOTE", "IMPLIED")
OrderDisplayOrigin = Literal["ORDER", "QUOTE", "IMPLIED"]


@dataclass(frozen=True, slots=True)
class OrderDisplay:
    """One resting order as the engine reports it in an `order.orders` snapshot, in
    display units. It is `Order.to_dict()` with price, stop_price and trail_offset
    converted from ticks to display money and timestamp expressed in seconds - the
    projection `order_to_display_dict` builds so an operator reads prices in the
    same money the book shows, not raw ticks. Gateway_id is not included here; it
    is topic-only (part of the message topic as order.orders.{gateway_id}, not
    part of the record). The record contains the order state (id, symbol, side,
    etc.) exactly as Order.to_dict() produces, minus gateway_id; the eleven
    nullable ones ride as null when unset.
    """

    id: str
    symbol: str
    side: OrderDisplaySide
    order_type: OrderDisplayOrderType
    tif: OrderDisplayTif
    quantity: int  # unit: shares
    remaining_qty: int  # unit: shares
    timestamp: float  # unit: epoch_seconds
    status: OrderDisplayStatus
    trail_offset: float | None = None  # unit: display_price
    oco_group_id: str | None = None
    price: float | None = None  # unit: display_price
    stop_price: float | None = None  # unit: display_price
    visible_qty: int | None = None  # unit: shares
    displayed_qty: int | None = None  # unit: shares
    smp_action: OrderDisplaySmpAction | None = None
    combo_parent_id: str | None = None
    leg_index: int | None = None  # unit: dimensionless
    origin: OrderDisplayOrigin = "ORDER"
    quote_id: str | None = None
    client_tag: str | None = None
    arrival_seq: int = 0  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.id) > 64:
            raise MessageValidationError(
                f"id: length {len(self.id)} exceeds max_len 64"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.side not in _ORDER_DISPLAY_SIDE_VALUES:
            raise MessageValidationError(
                f"side: {self.side!r} is not one of {_ORDER_DISPLAY_SIDE_VALUES!r}"
            )
        if self.order_type not in _ORDER_DISPLAY_ORDER_TYPE_VALUES:
            raise MessageValidationError(
                f"order_type: {self.order_type!r} is not one of {_ORDER_DISPLAY_ORDER_TYPE_VALUES!r}"
            )
        if self.tif not in _ORDER_DISPLAY_TIF_VALUES:
            raise MessageValidationError(
                f"tif: {self.tif!r} is not one of {_ORDER_DISPLAY_TIF_VALUES!r}"
            )
        if self.quantity <= 0:
            raise MessageValidationError(f"quantity: {self.quantity!r} must be > 0")
        if self.remaining_qty < 0:
            raise MessageValidationError(
                f"remaining_qty: {self.remaining_qty!r} must be >= 0"
            )
        if self.oco_group_id is not None:
            if len(self.oco_group_id) > 64:
                raise MessageValidationError(
                    f"oco_group_id: length {len(self.oco_group_id)} exceeds max_len 64"
                )
        if self.timestamp < 0:
            raise MessageValidationError(f"timestamp: {self.timestamp!r} must be >= 0")
        if self.status not in _ORDER_DISPLAY_STATUS_VALUES:
            raise MessageValidationError(
                f"status: {self.status!r} is not one of {_ORDER_DISPLAY_STATUS_VALUES!r}"
            )
        if self.smp_action is not None:
            if self.smp_action not in _ORDER_DISPLAY_SMP_ACTION_VALUES:
                raise MessageValidationError(
                    f"smp_action: {self.smp_action!r} is not one of {_ORDER_DISPLAY_SMP_ACTION_VALUES!r}"
                )
        if self.combo_parent_id is not None:
            if len(self.combo_parent_id) > 64:
                raise MessageValidationError(
                    f"combo_parent_id: length {len(self.combo_parent_id)} exceeds max_len 64"
                )
        if self.origin not in _ORDER_DISPLAY_ORIGIN_VALUES:
            raise MessageValidationError(
                f"origin: {self.origin!r} is not one of {_ORDER_DISPLAY_ORIGIN_VALUES!r}"
            )
        if self.quote_id is not None:
            if len(self.quote_id) > 64:
                raise MessageValidationError(
                    f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
                )
        if self.client_tag is not None:
            if len(self.client_tag) > 64:
                raise MessageValidationError(
                    f"client_tag: length {len(self.client_tag)} exceeds max_len 64"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderDisplay":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            id=str(p["id"]),
            symbol=str(p["symbol"]),
            side=cast(OrderDisplaySide, str(p["side"])),
            order_type=cast(OrderDisplayOrderType, str(p["order_type"])),
            tif=cast(OrderDisplayTif, str(p["tif"])),
            quantity=int(p["quantity"]),
            remaining_qty=int(p["remaining_qty"]),
            trail_offset=(
                None if p.get("trail_offset") is None else float(p["trail_offset"])
            ),
            oco_group_id=(
                None if p.get("oco_group_id") is None else str(p["oco_group_id"])
            ),
            timestamp=float(p["timestamp"]),
            status=cast(OrderDisplayStatus, str(p["status"])),
            price=None if p.get("price") is None else float(p["price"]),
            stop_price=None if p.get("stop_price") is None else float(p["stop_price"]),
            visible_qty=None if p.get("visible_qty") is None else int(p["visible_qty"]),
            displayed_qty=(
                None if p.get("displayed_qty") is None else int(p["displayed_qty"])
            ),
            smp_action=cast(
                OrderDisplaySmpAction | None,
                None if p.get("smp_action") is None else str(p["smp_action"]),
            ),
            combo_parent_id=(
                None if p.get("combo_parent_id") is None else str(p["combo_parent_id"])
            ),
            leg_index=None if p.get("leg_index") is None else int(p["leg_index"]),
            origin=cast(OrderDisplayOrigin, str(p.get("origin", "ORDER"))),
            quote_id=None if p.get("quote_id") is None else str(p["quote_id"]),
            client_tag=None if p.get("client_tag") is None else str(p["client_tag"]),
            arrival_seq=int(p.get("arrival_seq", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "tif": self.tif,
            "quantity": self.quantity,
            "remaining_qty": self.remaining_qty,
            "trail_offset": self.trail_offset,
            "oco_group_id": self.oco_group_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "price": self.price,
            "stop_price": self.stop_price,
            "visible_qty": self.visible_qty,
            "displayed_qty": self.displayed_qty,
            "smp_action": self.smp_action,
            "combo_parent_id": self.combo_parent_id,
            "leg_index": self.leg_index,
            "origin": self.origin,
            "quote_id": self.quote_id,
            "client_tag": self.client_tag,
            "arrival_seq": self.arrival_seq,
        }


_EXECUTION_REPORT_SYMBOL_RE = re.compile("^[A-Z0-9._]+$")
_EXECUTION_REPORT_SIDE_VALUES = ("BUY", "SELL")
ExecutionReportSide = Literal["BUY", "SELL"]
_EXECUTION_REPORT_STATUS_VALUES = ("PARTIAL", "FILLED")
ExecutionReportStatus = Literal["PARTIAL", "FILLED"]


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
    side: ExecutionReportSide
    status: ExecutionReportStatus

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
            side=cast(ExecutionReportSide, str(p["side"])),
            status=cast(ExecutionReportStatus, str(p["status"])),
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
            ExecutionReportSide, _EXECUTION_REPORT_BALF_SIDE_FROM_WIRE.get(side, "")
        ),
        status=cast(
            ExecutionReportStatus,
            _EXECUTION_REPORT_BALF_STATUS_FROM_WIRE.get(status, ""),
        ),
    )


TOPIC_ORDER_ACK = "order.ack.{gateway_id}"
PREFIX_ORDER_ACK = "order.ack."
_ORDER_ACK_RE = re.compile("order\\.ack\\.(?P<gateway_id>[^.]+)")


_ORDER_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "order_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Rejection detail; empty when accepted.",
        "constraints": {"max_len": 256},
    },
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "side",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 8},
    },
    {
        "name": "order_type",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "tif",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 8},
    },
    {
        "name": "qty",
        "type": "int",
        "unit": "shares",
        "required": False,
        "doc": "",
    },
    {
        "name": "price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "Absent for a MARKET order, which has no limit price.",
    },
    {
        "name": "client_tag",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "oco_group_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "combo_parent_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "quote_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "leg_index",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class OrderAck:
    """Acknowledge acceptance or rejection of a new order, addressed to the gateway
    that submitted it.

    The order-detail fields are present only when the engine had the order to hand; on a
    rejection before lookup they are absent. reason is empty on an acceptance.
    """

    gateway_id: str
    order_id: str
    accepted: bool
    reason: str = ""
    symbol: str | None = None
    side: str | None = None
    order_type: str | None = None
    tif: str | None = None
    qty: int | None = None  # unit: shares
    price: float | None = None  # unit: display_price
    client_tag: str | None = None
    oco_group_id: str | None = None
    combo_parent_id: str | None = None
    quote_id: str | None = None
    leg_index: int | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.order_id) > 64:
            raise MessageValidationError(
                f"order_id: length {len(self.order_id)} exceeds max_len 64"
            )
        if len(self.reason) > 256:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 256"
            )
        if self.symbol is not None:
            if len(self.symbol) > 16:
                raise MessageValidationError(
                    f"symbol: length {len(self.symbol)} exceeds max_len 16"
                )
        if self.side is not None:
            if len(self.side) > 8:
                raise MessageValidationError(
                    f"side: length {len(self.side)} exceeds max_len 8"
                )
        if self.order_type is not None:
            if len(self.order_type) > 16:
                raise MessageValidationError(
                    f"order_type: length {len(self.order_type)} exceeds max_len 16"
                )
        if self.tif is not None:
            if len(self.tif) > 8:
                raise MessageValidationError(
                    f"tif: length {len(self.tif)} exceeds max_len 8"
                )
        if self.client_tag is not None:
            if len(self.client_tag) > 64:
                raise MessageValidationError(
                    f"client_tag: length {len(self.client_tag)} exceeds max_len 64"
                )
        if self.oco_group_id is not None:
            if len(self.oco_group_id) > 64:
                raise MessageValidationError(
                    f"oco_group_id: length {len(self.oco_group_id)} exceeds max_len 64"
                )
        if self.combo_parent_id is not None:
            if len(self.combo_parent_id) > 64:
                raise MessageValidationError(
                    f"combo_parent_id: length {len(self.combo_parent_id)} exceeds max_len 64"
                )
        if self.quote_id is not None:
            if len(self.quote_id) > 64:
                raise MessageValidationError(
                    f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            order_id=str(p["order_id"]),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
            symbol=None if p.get("symbol") is None else str(p["symbol"]),
            side=None if p.get("side") is None else str(p["side"]),
            order_type=None if p.get("order_type") is None else str(p["order_type"]),
            tif=None if p.get("tif") is None else str(p["tif"]),
            qty=None if p.get("qty") is None else int(p["qty"]),
            price=None if p.get("price") is None else float(p["price"]),
            client_tag=None if p.get("client_tag") is None else str(p["client_tag"]),
            oco_group_id=(
                None if p.get("oco_group_id") is None else str(p["oco_group_id"])
            ),
            combo_parent_id=(
                None if p.get("combo_parent_id") is None else str(p["combo_parent_id"])
            ),
            quote_id=None if p.get("quote_id") is None else str(p["quote_id"]),
            leg_index=None if p.get("leg_index") is None else int(p["leg_index"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "order_id": self.order_id,
            "accepted": self.accepted,
            "reason": self.reason,
        }
        if self.symbol is not None:
            payload["symbol"] = self.symbol
        if self.side is not None:
            payload["side"] = self.side
        if self.order_type is not None:
            payload["order_type"] = self.order_type
        if self.tif is not None:
            payload["tif"] = self.tif
        if self.qty is not None:
            payload["qty"] = self.qty
        if self.price is not None:
            payload["price"] = self.price
        if self.client_tag is not None:
            payload["client_tag"] = self.client_tag
        if self.oco_group_id is not None:
            payload["oco_group_id"] = self.oco_group_id
        if self.combo_parent_id is not None:
            payload["combo_parent_id"] = self.combo_parent_id
        if self.quote_id is not None:
            payload["quote_id"] = self.quote_id
        if self.leg_index is not None:
            payload["leg_index"] = self.leg_index
        return payload


def topic_order_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"order.ack.{gateway_id}"


def match_order_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _ORDER_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_order_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_order_ack(obj.gateway_id), obj.to_dict())


def make_order_ack_unchecked(
    *,
    gateway_id: str,
    order_id: str,
    accepted: bool,
    reason: str = "",
    symbol: str | None = None,
    side: str | None = None,
    order_type: str | None = None,
    tif: str | None = None,
    qty: int | None = None,
    price: float | None = None,
    client_tag: str | None = None,
    oco_group_id: str | None = None,
    combo_parent_id: str | None = None,
    quote_id: str | None = None,
    leg_index: int | None = None,
) -> list[bytes]:
    """Identical frames to ``make_order_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "order_id": str(order_id),
        "accepted": bool(accepted),
        "reason": str(reason),
    }
    if symbol is not None:
        payload["symbol"] = str(symbol)
    if side is not None:
        payload["side"] = str(side)
    if order_type is not None:
        payload["order_type"] = str(order_type)
    if tif is not None:
        payload["tif"] = str(tif)
    if qty is not None:
        payload["qty"] = int(qty)
    if price is not None:
        payload["price"] = float(price)
    if client_tag is not None:
        payload["client_tag"] = str(client_tag)
    if oco_group_id is not None:
        payload["oco_group_id"] = str(oco_group_id)
    if combo_parent_id is not None:
        payload["combo_parent_id"] = str(combo_parent_id)
    if quote_id is not None:
        payload["quote_id"] = str(quote_id)
    if leg_index is not None:
        payload["leg_index"] = int(leg_index)
    return [
        topic_order_ack(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_order_ack(frames: list[bytes]) -> "OrderAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_order_ack(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_ORDER_ACK!r}")
    payload = {**payload, "gateway_id": matched}
    obj = OrderAck.from_dict(payload)
    obj.validate()
    return obj


def describe_order_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_ACK_FIELDS


TOPIC_ORDER_FILL = "order.fill.{gateway_id}"
PREFIX_ORDER_FILL = "order.fill."
_ORDER_FILL_RE = re.compile("order\\.fill\\.(?P<gateway_id>[^.]+)")


_ORDER_FILL_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "order_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "fill_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "",
    },
    {
        "name": "fill_price",
        "type": "float",
        "unit": "display_price",
        "required": True,
        "doc": "",
    },
    {
        "name": "remaining_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "",
    },
    {
        "name": "status",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "side",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 8},
    },
    {
        "name": "order_type",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "tif",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 8},
    },
    {
        "name": "qty",
        "type": "int",
        "unit": "shares",
        "required": False,
        "doc": "",
    },
    {
        "name": "price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "",
    },
    {
        "name": "client_tag",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "oco_group_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "combo_parent_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "quote_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "leg_index",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class OrderFill:
    """Private fill notification for one order, addressed to the gateway that owns
    it. The public counterpart is trade.executed.
    """

    gateway_id: str
    order_id: str
    fill_qty: int  # unit: shares
    fill_price: float  # unit: display_price
    remaining_qty: int  # unit: shares
    status: str
    symbol: str | None = None
    side: str | None = None
    order_type: str | None = None
    tif: str | None = None
    qty: int | None = None  # unit: shares
    price: float | None = None  # unit: display_price
    client_tag: str | None = None
    oco_group_id: str | None = None
    combo_parent_id: str | None = None
    quote_id: str | None = None
    leg_index: int | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.order_id) > 64:
            raise MessageValidationError(
                f"order_id: length {len(self.order_id)} exceeds max_len 64"
            )
        if len(self.status) > 16:
            raise MessageValidationError(
                f"status: length {len(self.status)} exceeds max_len 16"
            )
        if self.symbol is not None:
            if len(self.symbol) > 16:
                raise MessageValidationError(
                    f"symbol: length {len(self.symbol)} exceeds max_len 16"
                )
        if self.side is not None:
            if len(self.side) > 8:
                raise MessageValidationError(
                    f"side: length {len(self.side)} exceeds max_len 8"
                )
        if self.order_type is not None:
            if len(self.order_type) > 16:
                raise MessageValidationError(
                    f"order_type: length {len(self.order_type)} exceeds max_len 16"
                )
        if self.tif is not None:
            if len(self.tif) > 8:
                raise MessageValidationError(
                    f"tif: length {len(self.tif)} exceeds max_len 8"
                )
        if self.client_tag is not None:
            if len(self.client_tag) > 64:
                raise MessageValidationError(
                    f"client_tag: length {len(self.client_tag)} exceeds max_len 64"
                )
        if self.oco_group_id is not None:
            if len(self.oco_group_id) > 64:
                raise MessageValidationError(
                    f"oco_group_id: length {len(self.oco_group_id)} exceeds max_len 64"
                )
        if self.combo_parent_id is not None:
            if len(self.combo_parent_id) > 64:
                raise MessageValidationError(
                    f"combo_parent_id: length {len(self.combo_parent_id)} exceeds max_len 64"
                )
        if self.quote_id is not None:
            if len(self.quote_id) > 64:
                raise MessageValidationError(
                    f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderFill":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            order_id=str(p["order_id"]),
            fill_qty=int(p["fill_qty"]),
            fill_price=float(p["fill_price"]),
            remaining_qty=int(p["remaining_qty"]),
            status=str(p["status"]),
            symbol=None if p.get("symbol") is None else str(p["symbol"]),
            side=None if p.get("side") is None else str(p["side"]),
            order_type=None if p.get("order_type") is None else str(p["order_type"]),
            tif=None if p.get("tif") is None else str(p["tif"]),
            qty=None if p.get("qty") is None else int(p["qty"]),
            price=None if p.get("price") is None else float(p["price"]),
            client_tag=None if p.get("client_tag") is None else str(p["client_tag"]),
            oco_group_id=(
                None if p.get("oco_group_id") is None else str(p["oco_group_id"])
            ),
            combo_parent_id=(
                None if p.get("combo_parent_id") is None else str(p["combo_parent_id"])
            ),
            quote_id=None if p.get("quote_id") is None else str(p["quote_id"]),
            leg_index=None if p.get("leg_index") is None else int(p["leg_index"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "order_id": self.order_id,
            "fill_qty": self.fill_qty,
            "fill_price": self.fill_price,
            "remaining_qty": self.remaining_qty,
            "status": self.status,
        }
        if self.symbol is not None:
            payload["symbol"] = self.symbol
        if self.side is not None:
            payload["side"] = self.side
        if self.order_type is not None:
            payload["order_type"] = self.order_type
        if self.tif is not None:
            payload["tif"] = self.tif
        if self.qty is not None:
            payload["qty"] = self.qty
        if self.price is not None:
            payload["price"] = self.price
        if self.client_tag is not None:
            payload["client_tag"] = self.client_tag
        if self.oco_group_id is not None:
            payload["oco_group_id"] = self.oco_group_id
        if self.combo_parent_id is not None:
            payload["combo_parent_id"] = self.combo_parent_id
        if self.quote_id is not None:
            payload["quote_id"] = self.quote_id
        if self.leg_index is not None:
            payload["leg_index"] = self.leg_index
        return payload


def topic_order_fill(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"order.fill.{gateway_id}"


def match_order_fill(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _ORDER_FILL_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_order_fill(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderFill.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_order_fill(obj.gateway_id), obj.to_dict())


def make_order_fill_unchecked(
    *,
    gateway_id: str,
    order_id: str,
    fill_qty: int,
    fill_price: float,
    remaining_qty: int,
    status: str,
    symbol: str | None = None,
    side: str | None = None,
    order_type: str | None = None,
    tif: str | None = None,
    qty: int | None = None,
    price: float | None = None,
    client_tag: str | None = None,
    oco_group_id: str | None = None,
    combo_parent_id: str | None = None,
    quote_id: str | None = None,
    leg_index: int | None = None,
) -> list[bytes]:
    """Identical frames to ``make_order_fill``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "order_id": str(order_id),
        "fill_qty": int(fill_qty),
        "fill_price": float(fill_price),
        "remaining_qty": int(remaining_qty),
        "status": str(status),
    }
    if symbol is not None:
        payload["symbol"] = str(symbol)
    if side is not None:
        payload["side"] = str(side)
    if order_type is not None:
        payload["order_type"] = str(order_type)
    if tif is not None:
        payload["tif"] = str(tif)
    if qty is not None:
        payload["qty"] = int(qty)
    if price is not None:
        payload["price"] = float(price)
    if client_tag is not None:
        payload["client_tag"] = str(client_tag)
    if oco_group_id is not None:
        payload["oco_group_id"] = str(oco_group_id)
    if combo_parent_id is not None:
        payload["combo_parent_id"] = str(combo_parent_id)
    if quote_id is not None:
        payload["quote_id"] = str(quote_id)
    if leg_index is not None:
        payload["leg_index"] = int(leg_index)
    return [
        topic_order_fill(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_order_fill(frames: list[bytes]) -> "OrderFill":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_order_fill(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_ORDER_FILL!r}")
    payload = {**payload, "gateway_id": matched}
    obj = OrderFill.from_dict(payload)
    obj.validate()
    return obj


def describe_order_fill() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_FILL_FIELDS


TOPIC_ORDER_CANCELLED = "order.cancelled.{gateway_id}"
PREFIX_ORDER_CANCELLED = "order.cancelled."
_ORDER_CANCELLED_RE = re.compile("order\\.cancelled\\.(?P<gateway_id>[^.]+)")


_ORDER_CANCELLED_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "order_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "client_tag",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "oco_group_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "combo_parent_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "quote_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "leg_index",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class OrderCancelled:
    """Confirm that a resting order has been cancelled."""

    gateway_id: str
    order_id: str
    client_tag: str | None = None
    oco_group_id: str | None = None
    combo_parent_id: str | None = None
    quote_id: str | None = None
    leg_index: int | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.order_id) > 64:
            raise MessageValidationError(
                f"order_id: length {len(self.order_id)} exceeds max_len 64"
            )
        if self.client_tag is not None:
            if len(self.client_tag) > 64:
                raise MessageValidationError(
                    f"client_tag: length {len(self.client_tag)} exceeds max_len 64"
                )
        if self.oco_group_id is not None:
            if len(self.oco_group_id) > 64:
                raise MessageValidationError(
                    f"oco_group_id: length {len(self.oco_group_id)} exceeds max_len 64"
                )
        if self.combo_parent_id is not None:
            if len(self.combo_parent_id) > 64:
                raise MessageValidationError(
                    f"combo_parent_id: length {len(self.combo_parent_id)} exceeds max_len 64"
                )
        if self.quote_id is not None:
            if len(self.quote_id) > 64:
                raise MessageValidationError(
                    f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderCancelled":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            order_id=str(p["order_id"]),
            client_tag=None if p.get("client_tag") is None else str(p["client_tag"]),
            oco_group_id=(
                None if p.get("oco_group_id") is None else str(p["oco_group_id"])
            ),
            combo_parent_id=(
                None if p.get("combo_parent_id") is None else str(p["combo_parent_id"])
            ),
            quote_id=None if p.get("quote_id") is None else str(p["quote_id"]),
            leg_index=None if p.get("leg_index") is None else int(p["leg_index"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "order_id": self.order_id,
        }
        if self.client_tag is not None:
            payload["client_tag"] = self.client_tag
        if self.oco_group_id is not None:
            payload["oco_group_id"] = self.oco_group_id
        if self.combo_parent_id is not None:
            payload["combo_parent_id"] = self.combo_parent_id
        if self.quote_id is not None:
            payload["quote_id"] = self.quote_id
        if self.leg_index is not None:
            payload["leg_index"] = self.leg_index
        return payload


def topic_order_cancelled(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"order.cancelled.{gateway_id}"


def match_order_cancelled(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _ORDER_CANCELLED_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_order_cancelled(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderCancelled.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_order_cancelled(obj.gateway_id), obj.to_dict())


def make_order_cancelled_unchecked(
    *,
    gateway_id: str,
    order_id: str,
    client_tag: str | None = None,
    oco_group_id: str | None = None,
    combo_parent_id: str | None = None,
    quote_id: str | None = None,
    leg_index: int | None = None,
) -> list[bytes]:
    """Identical frames to ``make_order_cancelled``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "order_id": str(order_id),
    }
    if client_tag is not None:
        payload["client_tag"] = str(client_tag)
    if oco_group_id is not None:
        payload["oco_group_id"] = str(oco_group_id)
    if combo_parent_id is not None:
        payload["combo_parent_id"] = str(combo_parent_id)
    if quote_id is not None:
        payload["quote_id"] = str(quote_id)
    if leg_index is not None:
        payload["leg_index"] = int(leg_index)
    return [
        topic_order_cancelled(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_order_cancelled(frames: list[bytes]) -> "OrderCancelled":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_order_cancelled(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_ORDER_CANCELLED!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = OrderCancelled.from_dict(payload)
    obj.validate()
    return obj


def describe_order_cancelled() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_CANCELLED_FIELDS


TOPIC_ORDER_EXPIRED = "order.expired.{gateway_id}"
PREFIX_ORDER_EXPIRED = "order.expired."
_ORDER_EXPIRED_RE = re.compile("order\\.expired\\.(?P<gateway_id>[^.]+)")


_ORDER_EXPIRED_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "order_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "client_tag",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "oco_group_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "combo_parent_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "quote_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "leg_index",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class OrderExpired:
    """A DAY order that never filled has expired at session end. Same shape as
    order.cancelled - the difference is who ended the order, not what the consumer
    needs to know about it.
    """

    gateway_id: str
    order_id: str
    client_tag: str | None = None
    oco_group_id: str | None = None
    combo_parent_id: str | None = None
    quote_id: str | None = None
    leg_index: int | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.order_id) > 64:
            raise MessageValidationError(
                f"order_id: length {len(self.order_id)} exceeds max_len 64"
            )
        if self.client_tag is not None:
            if len(self.client_tag) > 64:
                raise MessageValidationError(
                    f"client_tag: length {len(self.client_tag)} exceeds max_len 64"
                )
        if self.oco_group_id is not None:
            if len(self.oco_group_id) > 64:
                raise MessageValidationError(
                    f"oco_group_id: length {len(self.oco_group_id)} exceeds max_len 64"
                )
        if self.combo_parent_id is not None:
            if len(self.combo_parent_id) > 64:
                raise MessageValidationError(
                    f"combo_parent_id: length {len(self.combo_parent_id)} exceeds max_len 64"
                )
        if self.quote_id is not None:
            if len(self.quote_id) > 64:
                raise MessageValidationError(
                    f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderExpired":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            order_id=str(p["order_id"]),
            client_tag=None if p.get("client_tag") is None else str(p["client_tag"]),
            oco_group_id=(
                None if p.get("oco_group_id") is None else str(p["oco_group_id"])
            ),
            combo_parent_id=(
                None if p.get("combo_parent_id") is None else str(p["combo_parent_id"])
            ),
            quote_id=None if p.get("quote_id") is None else str(p["quote_id"]),
            leg_index=None if p.get("leg_index") is None else int(p["leg_index"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "order_id": self.order_id,
        }
        if self.client_tag is not None:
            payload["client_tag"] = self.client_tag
        if self.oco_group_id is not None:
            payload["oco_group_id"] = self.oco_group_id
        if self.combo_parent_id is not None:
            payload["combo_parent_id"] = self.combo_parent_id
        if self.quote_id is not None:
            payload["quote_id"] = self.quote_id
        if self.leg_index is not None:
            payload["leg_index"] = self.leg_index
        return payload


def topic_order_expired(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"order.expired.{gateway_id}"


def match_order_expired(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _ORDER_EXPIRED_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_order_expired(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderExpired.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_order_expired(obj.gateway_id), obj.to_dict())


def make_order_expired_unchecked(
    *,
    gateway_id: str,
    order_id: str,
    client_tag: str | None = None,
    oco_group_id: str | None = None,
    combo_parent_id: str | None = None,
    quote_id: str | None = None,
    leg_index: int | None = None,
) -> list[bytes]:
    """Identical frames to ``make_order_expired``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "order_id": str(order_id),
    }
    if client_tag is not None:
        payload["client_tag"] = str(client_tag)
    if oco_group_id is not None:
        payload["oco_group_id"] = str(oco_group_id)
    if combo_parent_id is not None:
        payload["combo_parent_id"] = str(combo_parent_id)
    if quote_id is not None:
        payload["quote_id"] = str(quote_id)
    if leg_index is not None:
        payload["leg_index"] = int(leg_index)
    return [
        topic_order_expired(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_order_expired(frames: list[bytes]) -> "OrderExpired":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_order_expired(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_ORDER_EXPIRED!r}")
    payload = {**payload, "gateway_id": matched}
    obj = OrderExpired.from_dict(payload)
    obj.validate()
    return obj


def describe_order_expired() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_EXPIRED_FIELDS


TOPIC_ORDER_AMENDED = "order.amended.{gateway_id}"
PREFIX_ORDER_AMENDED = "order.amended."
_ORDER_AMENDED_RE = re.compile("order\\.amended\\.(?P<gateway_id>[^.]+)")


_ORDER_AMENDED_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "order_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "New limit price, or null for an order that has none.",
    },
    {
        "name": "qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "",
    },
    {
        "name": "remaining_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "",
    },
    {
        "name": "priority_reset",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "True when the amendment lost the order its time priority.",
    },
)


@dataclass(frozen=True, slots=True)
class OrderAmended:
    """Confirm an accepted amendment and report the resulting order.

    price is nullable but always present: a MARKET order has no limit price, and the
    field says so with null rather than by being absent. This is the one message in the
    group that emits null rather than omitting - it is what the hand-written builder
    did.
    """

    gateway_id: str
    order_id: str
    qty: int  # unit: shares
    remaining_qty: int  # unit: shares
    priority_reset: bool
    price: float | None = None  # unit: display_price

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.order_id) > 64:
            raise MessageValidationError(
                f"order_id: length {len(self.order_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderAmended":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            order_id=str(p["order_id"]),
            price=None if p.get("price") is None else float(p["price"]),
            qty=int(p["qty"]),
            remaining_qty=int(p["remaining_qty"]),
            priority_reset=bool(p["priority_reset"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "order_id": self.order_id,
            "price": self.price,
            "qty": self.qty,
            "remaining_qty": self.remaining_qty,
            "priority_reset": self.priority_reset,
        }


def topic_order_amended(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"order.amended.{gateway_id}"


def match_order_amended(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _ORDER_AMENDED_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_order_amended(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderAmended.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_order_amended(obj.gateway_id), obj.to_dict())


def make_order_amended_unchecked(
    *,
    gateway_id: str,
    order_id: str,
    qty: int,
    remaining_qty: int,
    priority_reset: bool,
    price: float | None = None,
) -> list[bytes]:
    """Identical frames to ``make_order_amended``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_order_amended(gateway_id).encode(),
        _msg.dumps(
            {
                "order_id": str(order_id),
                "price": None if price is None else float(price),
                "qty": int(qty),
                "remaining_qty": int(remaining_qty),
                "priority_reset": bool(priority_reset),
            }
        ),
    ]


def parse_order_amended(frames: list[bytes]) -> "OrderAmended":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_order_amended(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_ORDER_AMENDED!r}")
    payload = {**payload, "gateway_id": matched}
    obj = OrderAmended.from_dict(payload)
    obj.validate()
    return obj


def describe_order_amended() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_AMENDED_FIELDS


TOPIC_ORDER_NEW = "order.new"
_TOPIC_ORDER_NEW_BYTES = "order.new".encode()
_ORDER_NEW_SIDE_VALUES = ("BUY", "SELL")
OrderNewSide = Literal["BUY", "SELL"]
_ORDER_NEW_ORDER_TYPE_VALUES = (
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
)
OrderNewOrderType = Literal[
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
]
_ORDER_NEW_TIF_VALUES = ("DAY", "GTC", "ATO", "ATC")
OrderNewTif = Literal["DAY", "GTC", "ATO", "ATC"]
_ORDER_NEW_STATUS_VALUES = (
    "NEW",
    "PARTIAL",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
)
OrderNewStatus = Literal["NEW", "PARTIAL", "FILLED", "CANCELLED", "REJECTED", "EXPIRED"]
_ORDER_NEW_SMP_ACTION_VALUES = (
    "NONE",
    "CANCEL_AGGRESSOR",
    "CANCEL_RESTING",
    "CANCEL_BOTH",
)
OrderNewSmpAction = Literal["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"]
_ORDER_NEW_ORIGIN_VALUES = ("ORDER", "QUOTE", "IMPLIED")
OrderNewOrigin = Literal["ORDER", "QUOTE", "IMPLIED"]


_ORDER_NEW_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Engine order id; a UUID string.",
        "constraints": {"max_len": 64},
    },
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "side",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _ORDER_NEW_SIDE_VALUES,
    },
    {
        "name": "order_type",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _ORDER_NEW_ORDER_TYPE_VALUES,
    },
    {
        "name": "tif",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _ORDER_NEW_TIF_VALUES,
    },
    {
        "name": "quantity",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Total original quantity.",
        "constraints": {"gt": 0},
    },
    {
        "name": "remaining_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Quantity yet to be filled; equals quantity on submission.",
        "constraints": {"ge": 0},
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "trail_offset",
        "type": "ticks",
        "unit": "ticks",
        "required": False,
        "doc": "TRAILING_STOP: fixed distance to trail the market price.",
    },
    {
        "name": "oco_group_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "timestamp",
        "type": "int",
        "unit": "epoch_nanos",
        "required": True,
        "doc": "Client-supplied submission time. NOT what the book uses for time priority - see arrival_seq. BALF has no timestamp field on NEW_ORDER, so balf_gwy stamps one at ingress.",
        "constraints": {"ge": 0},
    },
    {
        "name": "status",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "Always NEW on submission; the enum is the full lifecycle.",
        "values": _ORDER_NEW_STATUS_VALUES,
    },
    {
        "name": "price",
        "type": "ticks",
        "unit": "ticks",
        "required": False,
        "doc": "Limit price in ticks. Null for MARKET, which has none.",
    },
    {
        "name": "stop_price",
        "type": "ticks",
        "unit": "ticks",
        "required": False,
        "doc": "STOP / STOP_LIMIT / TRAILING_STOP trigger.",
    },
    {
        "name": "visible_qty",
        "type": "int",
        "unit": "shares",
        "required": False,
        "doc": "ICEBERG: fixed peak size.",
    },
    {
        "name": "displayed_qty",
        "type": "int",
        "unit": "shares",
        "required": False,
        "doc": "ICEBERG: current visible slice on the book.",
    },
    {
        "name": "smp_action",
        "type": "enum",
        "unit": None,
        "required": False,
        "doc": "Self-match prevention. Null means the client did not specify SMP at all, which is distinct from an explicit NONE: the engine resolves null to the gateway's configured default. See SmpAction's docstring.",
        "values": _ORDER_NEW_SMP_ACTION_VALUES,
    },
    {
        "name": "combo_parent_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "leg_index",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "Position in the parent combo's legs, 0-based.",
    },
    {
        "name": "origin",
        "type": "enum",
        "unit": None,
        "required": False,
        "doc": "Defaulted rather than nullable: from_dict supplies ORDER.",
        "values": _ORDER_NEW_ORIGIN_VALUES,
    },
    {
        "name": "quote_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "client_tag",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Client correlation tag, echoed on every lifecycle event.",
        "constraints": {"max_len": 64},
    },
    {
        "name": "arrival_seq",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "Engine-assigned monotonic arrival sequence; time priority is keyed on this, not on timestamp, so a back-dated payload cannot jump the queue. Zero means unassigned, which is what a submission carries.",
    },
)


@dataclass(frozen=True, slots=True)
class OrderNew:
    """Submit a new order to the matching engine. Sent over PUSH/PULL rather than the
    pub bus, but it carries a topic so the audit log can classify it alongside
    everything else.

    The payload is exactly Order.to_dict(). Eleven fields are nullable and are emitted
    as null when unset rather than omitted - a MARKET order carries "price": null. The
    engine's Order.from_dict reads absent and null alike, so a producer that omits them
    is still accepted.
    """

    id: str
    symbol: str
    side: OrderNewSide
    order_type: OrderNewOrderType
    tif: OrderNewTif
    quantity: int  # unit: shares
    remaining_qty: int  # unit: shares
    gateway_id: str
    timestamp: int  # unit: epoch_nanos
    status: OrderNewStatus
    trail_offset: int | None = None  # unit: ticks
    oco_group_id: str | None = None
    price: int | None = None  # unit: ticks
    stop_price: int | None = None  # unit: ticks
    visible_qty: int | None = None  # unit: shares
    displayed_qty: int | None = None  # unit: shares
    smp_action: OrderNewSmpAction | None = None
    combo_parent_id: str | None = None
    leg_index: int | None = None  # unit: dimensionless
    origin: OrderNewOrigin = "ORDER"
    quote_id: str | None = None
    client_tag: str | None = None
    arrival_seq: int = 0  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.id) > 64:
            raise MessageValidationError(
                f"id: length {len(self.id)} exceeds max_len 64"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.side not in _ORDER_NEW_SIDE_VALUES:
            raise MessageValidationError(
                f"side: {self.side!r} is not one of {_ORDER_NEW_SIDE_VALUES!r}"
            )
        if self.order_type not in _ORDER_NEW_ORDER_TYPE_VALUES:
            raise MessageValidationError(
                f"order_type: {self.order_type!r} is not one of {_ORDER_NEW_ORDER_TYPE_VALUES!r}"
            )
        if self.tif not in _ORDER_NEW_TIF_VALUES:
            raise MessageValidationError(
                f"tif: {self.tif!r} is not one of {_ORDER_NEW_TIF_VALUES!r}"
            )
        if self.quantity <= 0:
            raise MessageValidationError(f"quantity: {self.quantity!r} must be > 0")
        if self.remaining_qty < 0:
            raise MessageValidationError(
                f"remaining_qty: {self.remaining_qty!r} must be >= 0"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if self.oco_group_id is not None:
            if len(self.oco_group_id) > 64:
                raise MessageValidationError(
                    f"oco_group_id: length {len(self.oco_group_id)} exceeds max_len 64"
                )
        if self.timestamp < 0:
            raise MessageValidationError(f"timestamp: {self.timestamp!r} must be >= 0")
        if self.status not in _ORDER_NEW_STATUS_VALUES:
            raise MessageValidationError(
                f"status: {self.status!r} is not one of {_ORDER_NEW_STATUS_VALUES!r}"
            )
        if self.smp_action is not None:
            if self.smp_action not in _ORDER_NEW_SMP_ACTION_VALUES:
                raise MessageValidationError(
                    f"smp_action: {self.smp_action!r} is not one of {_ORDER_NEW_SMP_ACTION_VALUES!r}"
                )
        if self.combo_parent_id is not None:
            if len(self.combo_parent_id) > 64:
                raise MessageValidationError(
                    f"combo_parent_id: length {len(self.combo_parent_id)} exceeds max_len 64"
                )
        if self.origin not in _ORDER_NEW_ORIGIN_VALUES:
            raise MessageValidationError(
                f"origin: {self.origin!r} is not one of {_ORDER_NEW_ORIGIN_VALUES!r}"
            )
        if self.quote_id is not None:
            if len(self.quote_id) > 64:
                raise MessageValidationError(
                    f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
                )
        if self.client_tag is not None:
            if len(self.client_tag) > 64:
                raise MessageValidationError(
                    f"client_tag: length {len(self.client_tag)} exceeds max_len 64"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderNew":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            id=str(p["id"]),
            symbol=str(p["symbol"]),
            side=cast(OrderNewSide, str(p["side"])),
            order_type=cast(OrderNewOrderType, str(p["order_type"])),
            tif=cast(OrderNewTif, str(p["tif"])),
            quantity=int(p["quantity"]),
            remaining_qty=int(p["remaining_qty"]),
            gateway_id=str(p["gateway_id"]),
            trail_offset=(
                None if p.get("trail_offset") is None else int(p["trail_offset"])
            ),
            oco_group_id=(
                None if p.get("oco_group_id") is None else str(p["oco_group_id"])
            ),
            timestamp=int(p["timestamp"]),
            status=cast(OrderNewStatus, str(p["status"])),
            price=None if p.get("price") is None else int(p["price"]),
            stop_price=None if p.get("stop_price") is None else int(p["stop_price"]),
            visible_qty=None if p.get("visible_qty") is None else int(p["visible_qty"]),
            displayed_qty=(
                None if p.get("displayed_qty") is None else int(p["displayed_qty"])
            ),
            smp_action=cast(
                OrderNewSmpAction | None,
                None if p.get("smp_action") is None else str(p["smp_action"]),
            ),
            combo_parent_id=(
                None if p.get("combo_parent_id") is None else str(p["combo_parent_id"])
            ),
            leg_index=None if p.get("leg_index") is None else int(p["leg_index"]),
            origin=cast(OrderNewOrigin, str(p.get("origin", "ORDER"))),
            quote_id=None if p.get("quote_id") is None else str(p["quote_id"]),
            client_tag=None if p.get("client_tag") is None else str(p["client_tag"]),
            arrival_seq=int(p.get("arrival_seq", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "tif": self.tif,
            "quantity": self.quantity,
            "remaining_qty": self.remaining_qty,
            "gateway_id": self.gateway_id,
            "trail_offset": self.trail_offset,
            "oco_group_id": self.oco_group_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "price": self.price,
            "stop_price": self.stop_price,
            "visible_qty": self.visible_qty,
            "displayed_qty": self.displayed_qty,
            "smp_action": self.smp_action,
            "combo_parent_id": self.combo_parent_id,
            "leg_index": self.leg_index,
            "origin": self.origin,
            "quote_id": self.quote_id,
            "client_tag": self.client_tag,
            "arrival_seq": self.arrival_seq,
        }


def is_order_new(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_ORDER_NEW


def make_order_new(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderNew.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_ORDER_NEW, obj.to_dict())


def make_order_new_unchecked(
    *,
    id: str,
    symbol: str,
    side: OrderNewSide,
    order_type: OrderNewOrderType,
    tif: OrderNewTif,
    quantity: int,
    remaining_qty: int,
    gateway_id: str,
    timestamp: int,
    status: OrderNewStatus,
    trail_offset: int | None = None,
    oco_group_id: str | None = None,
    price: int | None = None,
    stop_price: int | None = None,
    visible_qty: int | None = None,
    displayed_qty: int | None = None,
    smp_action: OrderNewSmpAction | None = None,
    combo_parent_id: str | None = None,
    leg_index: int | None = None,
    origin: OrderNewOrigin = "ORDER",
    quote_id: str | None = None,
    client_tag: str | None = None,
    arrival_seq: int = 0,
) -> list[bytes]:
    """Identical frames to ``make_order_new``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_ORDER_NEW_BYTES,
        _msg.dumps(
            {
                "id": str(id),
                "symbol": str(symbol),
                "side": str(side),
                "order_type": str(order_type),
                "tif": str(tif),
                "quantity": int(quantity),
                "remaining_qty": int(remaining_qty),
                "gateway_id": str(gateway_id),
                "trail_offset": None if trail_offset is None else int(trail_offset),
                "oco_group_id": None if oco_group_id is None else str(oco_group_id),
                "timestamp": int(timestamp),
                "status": str(status),
                "price": None if price is None else int(price),
                "stop_price": None if stop_price is None else int(stop_price),
                "visible_qty": None if visible_qty is None else int(visible_qty),
                "displayed_qty": None if displayed_qty is None else int(displayed_qty),
                "smp_action": None if smp_action is None else str(smp_action),
                "combo_parent_id": (
                    None if combo_parent_id is None else str(combo_parent_id)
                ),
                "leg_index": None if leg_index is None else int(leg_index),
                "origin": str(origin),
                "quote_id": None if quote_id is None else str(quote_id),
                "client_tag": None if client_tag is None else str(client_tag),
                "arrival_seq": int(arrival_seq),
            }
        ),
    ]


def parse_order_new(frames: list[bytes]) -> "OrderNew":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = OrderNew.from_dict(payload)
    obj.validate()
    return obj


def describe_order_new() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_NEW_FIELDS


TOPIC_ORDER_CANCEL = "order.cancel"
_TOPIC_ORDER_CANCEL_BYTES = "order.cancel".encode()


_ORDER_CANCEL_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "order_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class OrderCancel:
    """Request cancellation of one resting order by id."""

    order_id: str
    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.order_id) > 64:
            raise MessageValidationError(
                f"order_id: length {len(self.order_id)} exceeds max_len 64"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderCancel":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            order_id=str(p["order_id"]),
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "order_id": self.order_id,
            "gateway_id": self.gateway_id,
        }


def is_order_cancel(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_ORDER_CANCEL


def make_order_cancel(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderCancel.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_ORDER_CANCEL, obj.to_dict())


def make_order_cancel_unchecked(
    *,
    order_id: str,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_order_cancel``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_ORDER_CANCEL_BYTES,
        _msg.dumps(
            {
                "order_id": str(order_id),
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_order_cancel(frames: list[bytes]) -> "OrderCancel":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = OrderCancel.from_dict(payload)
    obj.validate()
    return obj


def describe_order_cancel() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_CANCEL_FIELDS


TOPIC_ORDER_AMEND = "order.amend"
_TOPIC_ORDER_AMEND_BYTES = "order.amend".encode()


_ORDER_AMEND_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "order_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "New limit price; absent means the price is unchanged.",
    },
    {
        "name": "qty",
        "type": "int",
        "unit": "shares",
        "required": False,
        "doc": "New quantity; absent means the quantity is unchanged.",
    },
)


@dataclass(frozen=True, slots=True)
class OrderAmend:
    """Request a price and/or quantity change to a resting order.

    price and qty are omitted when not being changed, and the engine reads that absence
    as "leave this alone" - so unlike order.new these two DO take omit_when_none.
    tests/test_messages.py pins the omission directly. price here is display money, not
    the ticks that order.new carries.
    """

    order_id: str
    gateway_id: str
    price: float | None = None  # unit: display_price
    qty: int | None = None  # unit: shares

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.order_id) > 64:
            raise MessageValidationError(
                f"order_id: length {len(self.order_id)} exceeds max_len 64"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderAmend":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            order_id=str(p["order_id"]),
            gateway_id=str(p["gateway_id"]),
            price=None if p.get("price") is None else float(p["price"]),
            qty=None if p.get("qty") is None else int(p["qty"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "order_id": self.order_id,
            "gateway_id": self.gateway_id,
        }
        if self.price is not None:
            payload["price"] = self.price
        if self.qty is not None:
            payload["qty"] = self.qty
        return payload


def is_order_amend(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_ORDER_AMEND


def make_order_amend(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderAmend.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_ORDER_AMEND, obj.to_dict())


def make_order_amend_unchecked(
    *,
    order_id: str,
    gateway_id: str,
    price: float | None = None,
    qty: int | None = None,
) -> list[bytes]:
    """Identical frames to ``make_order_amend``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "order_id": str(order_id),
        "gateway_id": str(gateway_id),
    }
    if price is not None:
        payload["price"] = float(price)
    if qty is not None:
        payload["qty"] = int(qty)
    return [
        _TOPIC_ORDER_AMEND_BYTES,
        _msg.dumps(payload),
    ]


def parse_order_amend(frames: list[bytes]) -> "OrderAmend":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = OrderAmend.from_dict(payload)
    obj.validate()
    return obj


def describe_order_amend() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_AMEND_FIELDS


TOPIC_ORDER_COMBO_CANCEL = "order.combo_cancel"
_TOPIC_ORDER_COMBO_CANCEL_BYTES = "order.combo_cancel".encode()


_ORDER_COMBO_CANCEL_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "combo_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Client-supplied combo label, not the internal UUID.",
        "constraints": {"max_len": 64},
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class OrderComboCancel:
    """Cancel a combo order and all of its resting child legs."""

    combo_id: str = ""
    gateway_id: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.combo_id) > 64:
            raise MessageValidationError(
                f"combo_id: length {len(self.combo_id)} exceeds max_len 64"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderComboCancel":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            combo_id=str(p.get("combo_id", "")),
            gateway_id=str(p.get("gateway_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "combo_id": self.combo_id,
            "gateway_id": self.gateway_id,
        }


def is_order_combo_cancel(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_ORDER_COMBO_CANCEL


def make_order_combo_cancel(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderComboCancel.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_ORDER_COMBO_CANCEL, obj.to_dict())


def make_order_combo_cancel_unchecked(
    *,
    combo_id: str = "",
    gateway_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_order_combo_cancel``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_ORDER_COMBO_CANCEL_BYTES,
        _msg.dumps(
            {
                "combo_id": str(combo_id),
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_order_combo_cancel(frames: list[bytes]) -> "OrderComboCancel":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = OrderComboCancel.from_dict(payload)
    obj.validate()
    return obj


def describe_order_combo_cancel() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_COMBO_CANCEL_FIELDS


TOPIC_ORDER_COMBO = "order.combo"
_TOPIC_ORDER_COMBO_BYTES = "order.combo".encode()
_ORDER_COMBO_COMBO_TYPE_VALUES = ("AON",)
OrderComboComboType = Literal["AON"]
_ORDER_COMBO_TIF_VALUES = ("DAY", "GTC", "ATO", "ATC")
OrderComboTif = Literal["DAY", "GTC", "ATO", "ATC"]


_ORDER_COMBO_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "combo_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Client-supplied tracking label, not the engine's internal id.",
        "constraints": {"max_len": 64},
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "combo_type",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "All-or-none: the combo completes only when every leg fills.",
        "values": _ORDER_COMBO_COMBO_TYPE_VALUES,
    },
    {
        "name": "tif",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _ORDER_COMBO_TIF_VALUES,
    },
    {
        "name": "legs",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "The child orders. The bounds below were previously enforced only by api_gateway's pydantic schema, which left the ALF console and gateway free to submit a one-legged combo.",
        "constraints": {"max_items": 10},
    },
)


@dataclass(frozen=True, slots=True)
class OrderCombo:
    """Submit a combo: two or more orders on different instruments that the engine
    posts together and tracks as one aggregate.

    This is the message the whole of design section 15 is about. It was unspecifiable
    for three separate reasons, and each turned out to be the wire being wrong rather
    than the IDL being short: leg prices whose unit depended on their runtime type
    (15.2), engine lifecycle state riding on a client submission (15.4), and finally the
    ordinary need for `nested` and `list[T]` (15.5). The payload below is `ComboOrder.
    to_submission_dict()` and carries no engine state at all.
    """

    combo_id: str
    gateway_id: str
    combo_type: OrderComboComboType
    tif: OrderComboTif
    legs: list[ComboLeg]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.combo_id) > 64:
            raise MessageValidationError(
                f"combo_id: length {len(self.combo_id)} exceeds max_len 64"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if self.combo_type not in _ORDER_COMBO_COMBO_TYPE_VALUES:
            raise MessageValidationError(
                f"combo_type: {self.combo_type!r} is not one of {_ORDER_COMBO_COMBO_TYPE_VALUES!r}"
            )
        if self.tif not in _ORDER_COMBO_TIF_VALUES:
            raise MessageValidationError(
                f"tif: {self.tif!r} is not one of {_ORDER_COMBO_TIF_VALUES!r}"
            )
        if len(self.legs) < 2:
            raise MessageValidationError("legs: fewer than 2 item(s)")
        if len(self.legs) > 10:
            raise MessageValidationError("legs: more than 10 item(s)")
        for legs_item in self.legs:
            legs_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderCombo":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            combo_id=str(p["combo_id"]),
            gateway_id=str(p["gateway_id"]),
            combo_type=cast(OrderComboComboType, str(p["combo_type"])),
            tif=cast(OrderComboTif, str(p["tif"])),
            legs=[ComboLeg.from_dict(item) for item in p["legs"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "combo_id": self.combo_id,
            "gateway_id": self.gateway_id,
            "combo_type": self.combo_type,
            "tif": self.tif,
            "legs": [item.to_dict() for item in self.legs],
        }


def is_order_combo(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_ORDER_COMBO


def make_order_combo(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderCombo.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_ORDER_COMBO, obj.to_dict())


def parse_order_combo(frames: list[bytes]) -> "OrderCombo":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = OrderCombo.from_dict(payload)
    obj.validate()
    return obj


def describe_order_combo() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_COMBO_FIELDS


TOPIC_ORDER_OCO = "order.oco"
_TOPIC_ORDER_OCO_BYTES = "order.oco".encode()
_ORDER_OCO_TIF_VALUES = ("DAY", "GTC", "ATO", "ATC")
OrderOcoTif = Literal["DAY", "GTC", "ATO", "ATC"]


_ORDER_OCO_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "oco_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Client-supplied label for the pair.",
        "constraints": {"max_len": 64},
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Both legs trade this instrument.",
        "constraints": {"max_len": 16},
    },
    {
        "name": "quantity",
        "type": "int",
        "unit": "shares",
        "required": False,
        "doc": "Size of each leg; they are equal by construction.",
    },
    {
        "name": "tif",
        "type": "enum",
        "unit": None,
        "required": False,
        "doc": "",
        "values": _ORDER_OCO_TIF_VALUES,
    },
    {
        "name": "leg1",
        "type": "nested",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "leg2",
        "type": "nested",
        "unit": None,
        "required": True,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class OrderOco:
    """Submit a One-Cancels-Other pair: two orders on the same instrument, of which a
    fill on either cancels the other.

    The first message in any spec to use a nested record. Both legs are `OcoLeg`, and
    their prices are engine ticks - the gateway converts. A leg omits a price it does
    not have rather than sending null, which is what the three producing gateways
    already do.
    """

    leg1: OcoLeg
    leg2: OcoLeg
    oco_id: str = ""
    gateway_id: str = ""
    symbol: str = ""
    quantity: int = 0  # unit: shares
    tif: OrderOcoTif = "DAY"

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.oco_id) > 64:
            raise MessageValidationError(
                f"oco_id: length {len(self.oco_id)} exceeds max_len 64"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.tif not in _ORDER_OCO_TIF_VALUES:
            raise MessageValidationError(
                f"tif: {self.tif!r} is not one of {_ORDER_OCO_TIF_VALUES!r}"
            )
        self.leg1.validate()
        self.leg2.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderOco":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            oco_id=str(p.get("oco_id", "")),
            gateway_id=str(p.get("gateway_id", "")),
            symbol=str(p.get("symbol", "")),
            quantity=int(p.get("quantity", 0)),
            tif=cast(OrderOcoTif, str(p.get("tif", "DAY"))),
            leg1=OcoLeg.from_dict(p["leg1"]),
            leg2=OcoLeg.from_dict(p["leg2"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "oco_id": self.oco_id,
            "gateway_id": self.gateway_id,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "tif": self.tif,
            "leg1": self.leg1.to_dict(),
            "leg2": self.leg2.to_dict(),
        }


def is_order_oco(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_ORDER_OCO


def make_order_oco(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderOco.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_ORDER_OCO, obj.to_dict())


def parse_order_oco(frames: list[bytes]) -> "OrderOco":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = OrderOco.from_dict(payload)
    obj.validate()
    return obj


def describe_order_oco() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_OCO_FIELDS


TOPIC_ORDER_OCO_CANCEL = "order.oco_cancel"
_TOPIC_ORDER_OCO_CANCEL_BYTES = "order.oco_cancel".encode()


_ORDER_OCO_CANCEL_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "oco_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Client-supplied OCO label.",
        "constraints": {"max_len": 64},
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class OrderOcoCancel:
    """Cancel an OCO pair and both of its legs."""

    oco_id: str = ""
    gateway_id: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.oco_id) > 64:
            raise MessageValidationError(
                f"oco_id: length {len(self.oco_id)} exceeds max_len 64"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderOcoCancel":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            oco_id=str(p.get("oco_id", "")),
            gateway_id=str(p.get("gateway_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "oco_id": self.oco_id,
            "gateway_id": self.gateway_id,
        }


def is_order_oco_cancel(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_ORDER_OCO_CANCEL


def make_order_oco_cancel(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrderOcoCancel.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_ORDER_OCO_CANCEL, obj.to_dict())


def make_order_oco_cancel_unchecked(
    *,
    oco_id: str = "",
    gateway_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_order_oco_cancel``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_ORDER_OCO_CANCEL_BYTES,
        _msg.dumps(
            {
                "oco_id": str(oco_id),
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_order_oco_cancel(frames: list[bytes]) -> "OrderOcoCancel":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = OrderOcoCancel.from_dict(payload)
    obj.validate()
    return obj


def describe_order_oco_cancel() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDER_OCO_CANCEL_FIELDS


TOPIC_ORDERS_REQUEST = "order.orders_request"
_TOPIC_ORDERS_REQUEST_BYTES = "order.orders_request".encode()


_ORDERS_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Whose resting orders to return, and the reply's correlation key.",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class OrdersRequest:
    """Caller to engine: the resting (unfilled, non-cancelled) orders a gateway
    currently has on the books, across all symbols.
    """

    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrdersRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
        }


def is_orders_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_ORDERS_REQUEST


def make_orders_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OrdersRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_ORDERS_REQUEST, obj.to_dict())


def make_orders_request_unchecked(
    *,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_orders_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_ORDERS_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_orders_request(frames: list[bytes]) -> "OrdersRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = OrdersRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_orders_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDERS_REQUEST_FIELDS


TOPIC_ORDERS = "order.orders.{gateway_id}"
PREFIX_ORDERS = "order.orders."
_ORDERS_RE = re.compile("order\\.orders\\.(?P<gateway_id>[^.]+)")


_ORDERS_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped from the body by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "orders",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Resting orders, as the engine iterates its books.",
    },
)


@dataclass(frozen=True, slots=True)
class Orders:
    """Engine to caller: the gateway's resting orders in display units, one
    OrderDisplay record each. Empty when the gateway is unknown or flat.

    gateway_id names the caller in the topic and is dropped from the body by the default
    projection, so the body is a single `orders` list - the same shape system.symbols
    uses.
    """

    gateway_id: str
    orders: list[OrderDisplay]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        for orders_item in self.orders:
            orders_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "Orders":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            orders=[OrderDisplay.from_dict(item) for item in p["orders"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "orders": [item.to_dict() for item in self.orders],
        }


def topic_orders(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"order.orders.{gateway_id}"


def match_orders(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _ORDERS_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_orders(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = Orders.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_orders(obj.gateway_id), obj.to_dict())


def parse_orders(frames: list[bytes]) -> "Orders":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_orders(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_ORDERS!r}")
    payload = {**payload, "gateway_id": matched}
    obj = Orders.from_dict(payload)
    obj.validate()
    return obj


def describe_orders() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ORDERS_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_ORDER_ACK,
    TOPIC_ORDER_FILL,
    TOPIC_ORDER_CANCELLED,
    TOPIC_ORDER_EXPIRED,
    TOPIC_ORDER_AMENDED,
    TOPIC_ORDER_NEW,
    TOPIC_ORDER_CANCEL,
    TOPIC_ORDER_AMEND,
    TOPIC_ORDER_COMBO_CANCEL,
    TOPIC_ORDER_COMBO,
    TOPIC_ORDER_OCO,
    TOPIC_ORDER_OCO_CANCEL,
    TOPIC_ORDERS_REQUEST,
    TOPIC_ORDERS,
)
