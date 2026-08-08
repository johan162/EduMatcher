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


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_ORDER_ACK,
    TOPIC_ORDER_FILL,
    TOPIC_ORDER_CANCELLED,
    TOPIC_ORDER_EXPIRED,
    TOPIC_ORDER_AMENDED,
)
