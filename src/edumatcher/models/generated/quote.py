# GENERATED FROM spec/messages/quote.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``quote`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/quote.yaml``; edit
the spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
docs/developer/06-msgen.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, cast

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "quote"
FAMILY_VERSION = 1


TOPIC_QUOTE_NEW = "quote.new"
_TOPIC_QUOTE_NEW_BYTES = "quote.new".encode()
_QUOTE_NEW_TIF_VALUES = ("DAY", "GTC", "ATO", "ATC")
QuoteNewTif = Literal["DAY", "GTC", "ATO", "ATC"]


_QUOTE_NEW_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
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
        "name": "bid_price",
        "type": "ticks",
        "unit": "ticks",
        "required": True,
        "doc": "",
        "constraints": {"gt": 0},
    },
    {
        "name": "bid_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "",
        "constraints": {"gt": 0},
    },
    {
        "name": "ask_price",
        "type": "ticks",
        "unit": "ticks",
        "required": True,
        "doc": "",
        "constraints": {"gt": 0},
    },
    {
        "name": "ask_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "",
        "constraints": {"gt": 0},
    },
    {
        "name": "tif",
        "type": "enum",
        "unit": None,
        "required": False,
        "doc": "Applies to both legs; the engine reads it once. Same four values as models/order.py::TIF and order.combo's own tif - a quote's legs are ordinary orders once they rest.",
        "values": _QUOTE_NEW_TIF_VALUES,
    },
    {
        "name": "quote_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class QuoteNew:
    """Market maker to engine: submit or replace a two-sided quote on one instrument.
    A quote is a bid and an ask posted as a pair; replacing one cancels the
    previous pair for that gateway and symbol.

    Prices are integer ticks. The engine rejects a float outright rather than converting
    it, because a display price of 150.0 accepted as 150 ticks would post the quote at
    1/100th of the intended level on a two-decimal instrument - silent, and in the wrong
    direction for the side that gets hit. `quote_id` is the client's own handle, echoed
    on every ack and status event. It is optional: a gateway that submits one quote per
    symbol can identify it by symbol alone, and the hand-written builders omitted the
    key entirely rather than sending "".
    """

    gateway_id: str
    symbol: str
    bid_price: int  # unit: ticks
    bid_qty: int  # unit: shares
    ask_price: int  # unit: ticks
    ask_qty: int  # unit: shares
    tif: QuoteNewTif = "DAY"
    quote_id: str = ""

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
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.bid_price <= 0:
            raise MessageValidationError(f"bid_price: {self.bid_price!r} must be > 0")
        if self.bid_qty <= 0:
            raise MessageValidationError(f"bid_qty: {self.bid_qty!r} must be > 0")
        if self.ask_price <= 0:
            raise MessageValidationError(f"ask_price: {self.ask_price!r} must be > 0")
        if self.ask_qty <= 0:
            raise MessageValidationError(f"ask_qty: {self.ask_qty!r} must be > 0")
        if self.tif not in _QUOTE_NEW_TIF_VALUES:
            raise MessageValidationError(
                f"tif: {self.tif!r} is not one of {_QUOTE_NEW_TIF_VALUES!r}"
            )
        if len(self.quote_id) > 64:
            raise MessageValidationError(
                f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "QuoteNew":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            symbol=str(p["symbol"]),
            bid_price=int(p["bid_price"]),
            bid_qty=int(p["bid_qty"]),
            ask_price=int(p["ask_price"]),
            ask_qty=int(p["ask_qty"]),
            tif=cast(QuoteNewTif, str(p.get("tif", "DAY"))),
            quote_id=str(p.get("quote_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "gateway_id": self.gateway_id,
            "symbol": self.symbol,
            "bid_price": self.bid_price,
            "bid_qty": self.bid_qty,
            "ask_price": self.ask_price,
            "ask_qty": self.ask_qty,
            "tif": self.tif,
        }
        if self.quote_id:
            payload["quote_id"] = self.quote_id
        return payload


def is_quote_new(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_QUOTE_NEW


def make_quote_new(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = QuoteNew.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_QUOTE_NEW, obj.to_dict())


def make_quote_new_unchecked(
    *,
    gateway_id: str,
    symbol: str,
    bid_price: int,
    bid_qty: int,
    ask_price: int,
    ask_qty: int,
    tif: QuoteNewTif = "DAY",
    quote_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_quote_new``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "gateway_id": str(gateway_id),
        "symbol": str(symbol),
        "bid_price": int(bid_price),
        "bid_qty": int(bid_qty),
        "ask_price": int(ask_price),
        "ask_qty": int(ask_qty),
        "tif": str(tif),
    }
    if quote_id:
        payload["quote_id"] = str(quote_id)
    return [
        _TOPIC_QUOTE_NEW_BYTES,
        _msg.dumps(payload),
    ]


def parse_quote_new(frames: list[bytes]) -> "QuoteNew":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = QuoteNew.from_dict(payload)
    obj.validate()
    return obj


def describe_quote_new() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _QUOTE_NEW_FIELDS


TOPIC_QUOTE_CANCEL = "quote.cancel"
_TOPIC_QUOTE_CANCEL_BYTES = "quote.cancel".encode()


_QUOTE_CANCEL_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
)


@dataclass(frozen=True, slots=True)
class QuoteCancel:
    """Market maker to engine: pull the active quote on one symbol.

    Addressed by symbol rather than by quote_id: a gateway has at most one active quote
    per instrument, so the pair identifies it. That is also why quote_id is optional on
    submission.
    """

    gateway_id: str
    symbol: str

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
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "QuoteCancel":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            symbol=str(p["symbol"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
            "symbol": self.symbol,
        }


def is_quote_cancel(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_QUOTE_CANCEL


def make_quote_cancel(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = QuoteCancel.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_QUOTE_CANCEL, obj.to_dict())


def make_quote_cancel_unchecked(
    *,
    gateway_id: str,
    symbol: str,
) -> list[bytes]:
    """Identical frames to ``make_quote_cancel``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_QUOTE_CANCEL_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
                "symbol": str(symbol),
            }
        ),
    ]


def parse_quote_cancel(frames: list[bytes]) -> "QuoteCancel":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = QuoteCancel.from_dict(payload)
    obj.validate()
    return obj


def describe_quote_cancel() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _QUOTE_CANCEL_FIELDS


TOPIC_QUOTE_ACK = "quote.ack.{gateway_id}"
PREFIX_QUOTE_ACK = "quote.ack."
_QUOTE_ACK_RE = re.compile("quote\\.ack\\.(?P<gateway_id>[^.]+)")


_QUOTE_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
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
        "doc": "",
        "constraints": {"max_len": 512},
    },
    {
        "name": "bid_order_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "ask_order_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class QuoteAck:
    """Engine to market maker: the quote was accepted or rejected.

    The two order ids are the engine's handles for the resting legs, and are what ties a
    subsequent order.fill to the quote that produced it. Both are always emitted, as ""
    on rejection - the hand-written builder put them in the base payload, and a rejected
    quote rests nothing.
    """

    gateway_id: str
    accepted: bool
    quote_id: str = ""
    reason: str = ""
    bid_order_id: str = ""
    ask_order_id: str = ""

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
        if len(self.quote_id) > 64:
            raise MessageValidationError(
                f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )
        if len(self.bid_order_id) > 64:
            raise MessageValidationError(
                f"bid_order_id: length {len(self.bid_order_id)} exceeds max_len 64"
            )
        if len(self.ask_order_id) > 64:
            raise MessageValidationError(
                f"ask_order_id: length {len(self.ask_order_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "QuoteAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            quote_id=str(p.get("quote_id", "")),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
            bid_order_id=str(p.get("bid_order_id", "")),
            ask_order_id=str(p.get("ask_order_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "quote_id": self.quote_id,
            "accepted": self.accepted,
            "reason": self.reason,
            "bid_order_id": self.bid_order_id,
            "ask_order_id": self.ask_order_id,
        }


def topic_quote_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"quote.ack.{gateway_id}"


def match_quote_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _QUOTE_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_quote_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = QuoteAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_quote_ack(obj.gateway_id), obj.to_dict())


def make_quote_ack_unchecked(
    *,
    gateway_id: str,
    accepted: bool,
    quote_id: str = "",
    reason: str = "",
    bid_order_id: str = "",
    ask_order_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_quote_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_quote_ack(gateway_id).encode(),
        _msg.dumps(
            {
                "quote_id": str(quote_id),
                "accepted": bool(accepted),
                "reason": str(reason),
                "bid_order_id": str(bid_order_id),
                "ask_order_id": str(ask_order_id),
            }
        ),
    ]


def parse_quote_ack(frames: list[bytes]) -> "QuoteAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_quote_ack(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_QUOTE_ACK!r}")
    payload = {**payload, "gateway_id": matched}
    obj = QuoteAck.from_dict(payload)
    obj.validate()
    return obj


def describe_quote_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _QUOTE_ACK_FIELDS


TOPIC_QUOTE_STATUS = "quote.status.{gateway_id}"
PREFIX_QUOTE_STATUS = "quote.status."
_QUOTE_STATUS_RE = re.compile("quote\\.status\\.(?P<gateway_id>[^.]+)")
_QUOTE_STATUS_STATUS_VALUES = (
    "ACTIVE",
    "INACTIVE_BID_FILLED",
    "INACTIVE_ASK_FILLED",
    "CANCELLED",
)
QuoteStatusStatus = Literal[
    "ACTIVE",
    "INACTIVE_BID_FILLED",
    "INACTIVE_ASK_FILLED",
    "CANCELLED",
]


_QUOTE_STATUS_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
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
        "name": "status",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "Mirrors models/quote.py::QuoteState.",
        "values": _QUOTE_STATUS_STATUS_VALUES,
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 512},
    },
)


@dataclass(frozen=True, slots=True)
class QuoteStatus:
    """Engine to market maker: the quote left the book, and why.

    The two INACTIVE_* states say which side was hit, which a market maker needs in
    order to re-quote the other one. They are distinct states rather than one INACTIVE
    plus a side field because models/quote.py::QuoteState is what the engine actually
    holds, and a wire that renames its own state machine is a translation nobody asked
    for.
    """

    gateway_id: str
    status: QuoteStatusStatus
    quote_id: str = ""
    reason: str = ""

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
        if len(self.quote_id) > 64:
            raise MessageValidationError(
                f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
            )
        if self.status not in _QUOTE_STATUS_STATUS_VALUES:
            raise MessageValidationError(
                f"status: {self.status!r} is not one of {_QUOTE_STATUS_STATUS_VALUES!r}"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "QuoteStatus":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            quote_id=str(p.get("quote_id", "")),
            status=cast(QuoteStatusStatus, str(p["status"])),
            reason=str(p.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "quote_id": self.quote_id,
            "status": self.status,
            "reason": self.reason,
        }


def topic_quote_status(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"quote.status.{gateway_id}"


def match_quote_status(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _QUOTE_STATUS_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_quote_status(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = QuoteStatus.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_quote_status(obj.gateway_id), obj.to_dict())


def make_quote_status_unchecked(
    *,
    gateway_id: str,
    status: QuoteStatusStatus,
    quote_id: str = "",
    reason: str = "",
) -> list[bytes]:
    """Identical frames to ``make_quote_status``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_quote_status(gateway_id).encode(),
        _msg.dumps(
            {
                "quote_id": str(quote_id),
                "status": str(status),
                "reason": str(reason),
            }
        ),
    ]


def parse_quote_status(frames: list[bytes]) -> "QuoteStatus":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_quote_status(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_QUOTE_STATUS!r}")
    payload = {**payload, "gateway_id": matched}
    obj = QuoteStatus.from_dict(payload)
    obj.validate()
    return obj


def describe_quote_status() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _QUOTE_STATUS_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_QUOTE_NEW,
    TOPIC_QUOTE_CANCEL,
    TOPIC_QUOTE_ACK,
    TOPIC_QUOTE_STATUS,
)
