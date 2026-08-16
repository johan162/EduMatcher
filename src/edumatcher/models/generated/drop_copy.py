# GENERATED FROM spec/messages/drop_copy.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``drop_copy`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/drop_copy.yaml``;
edit the spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
docs/developer/06-msgen.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, cast

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "drop_copy"
FAMILY_VERSION = 1


TOPIC_DROP_COPY_EVENT = "drop_copy.event.{gateway_id}"
PREFIX_DROP_COPY_EVENT = "drop_copy.event."
_DROP_COPY_EVENT_RE = re.compile("drop_copy\\.event\\.(?P<gateway_id>[^.]+)")
_DROP_COPY_EVENT_EVENT_TYPE_VALUES = ("order.fill",)
DropCopyEventEventType = Literal["order.fill"]
_DROP_COPY_EVENT_LIQUIDITY_FLAG_VALUES = ("MAKER", "TAKER")
DropCopyEventLiquidityFlag = Literal["MAKER", "TAKER"]


_DROP_COPY_EVENT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": 'Process-wide monotone counter, starting at 1 so that 0 can mean "no events yet". Never resets while the engine lives. A recipient detects loss from a gap and a duplicate from a repeat, which is the whole reason the feed is sequenced.',
        "constraints": {"gt": 0},
    },
    {
        "name": "timestamp",
        "type": "int",
        "unit": "epoch_nanos",
        "required": True,
        "doc": "When the engine published the event (`models/clock.py::now_ns`).",
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "The participant whose order executed. Carried in the body as well as in the topic, because `drop_copy.replay` names the *recipient* in its topic instead and a replayed event would otherwise not say whose fill it was.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "event_type",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": 'One value today. An enum rather than a free string so that a second event type is a spec change with a regenerated binding, rather than a new dict key no reader knows about -- `DropCopyPublisher`\'s own docstring promised "every fill and cancel" while only fills existed, which is how the gap went unnoticed. Section 27.3.',
        "values": _DROP_COPY_EVENT_EVENT_TYPE_VALUES,
    },
    {
        "name": "order_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "The resting or aggressing order this execution belongs to.",
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
        "name": "fill_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "",
        "constraints": {"gt": 0},
    },
    {
        "name": "fill_price",
        "type": "float",
        "unit": "display_price",
        "required": True,
        "doc": "Display money, not ticks -- converted once in `_publish_trade`.",
        "constraints": {"gt": 0},
    },
    {
        "name": "liquidity_flag",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "Derived from the trade's aggressor side: the aggressor is the TAKER and the resting side the MAKER. Exactly one of the two events a trade produces is TAKER.",
        "values": _DROP_COPY_EVENT_LIQUIDITY_FLAG_VALUES,
    },
)


@dataclass(frozen=True, slots=True)
class DropCopyEvent:
    """Engine to a participant's clearing broker, prime broker or in-house risk
    system: one execution, as it happens.

    Fed from the engine's single trade-publication path, so it covers every fill-
    producing flow -- new orders, quotes, combo legs, OCO legs, auction uncrosses, stop
    cascades and amend-rematches. It was once wired only into the new-order loop, and
    quote and auction fills were invisible to clearing as a result. This is a *derived
    copy* of `order.fill.{GW_ID}`, not the same message: it is sequenced, buffered for
    replay, carries the liquidity flag, and travels on a socket the trading gateway does
    not subscribe to. The two are deliberately allowed to differ. Every trade produces
    two of these, one per counterparty, so a recipient watching both sides of a matched
    pair sees the same execution twice under different `gateway_id`s.
    """

    seq: int  # unit: dimensionless
    timestamp: int  # unit: epoch_nanos
    gateway_id: str
    event_type: DropCopyEventEventType
    order_id: str
    symbol: str
    fill_qty: int  # unit: shares
    fill_price: float  # unit: display_price
    liquidity_flag: DropCopyEventLiquidityFlag

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.seq <= 0:
            raise MessageValidationError(f"seq: {self.seq!r} must be > 0")
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if self.event_type not in _DROP_COPY_EVENT_EVENT_TYPE_VALUES:
            raise MessageValidationError(
                f"event_type: {self.event_type!r} is not one of {_DROP_COPY_EVENT_EVENT_TYPE_VALUES!r}"
            )
        if len(self.order_id) > 64:
            raise MessageValidationError(
                f"order_id: length {len(self.order_id)} exceeds max_len 64"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.fill_qty <= 0:
            raise MessageValidationError(f"fill_qty: {self.fill_qty!r} must be > 0")
        if self.fill_price <= 0:
            raise MessageValidationError(f"fill_price: {self.fill_price!r} must be > 0")
        if self.liquidity_flag not in _DROP_COPY_EVENT_LIQUIDITY_FLAG_VALUES:
            raise MessageValidationError(
                f"liquidity_flag: {self.liquidity_flag!r} is not one of {_DROP_COPY_EVENT_LIQUIDITY_FLAG_VALUES!r}"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "DropCopyEvent":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            seq=int(p["seq"]),
            timestamp=int(p["timestamp"]),
            gateway_id=str(p["gateway_id"]),
            event_type=cast(DropCopyEventEventType, str(p["event_type"])),
            order_id=str(p["order_id"]),
            symbol=str(p["symbol"]),
            fill_qty=int(p["fill_qty"]),
            fill_price=float(p["fill_price"]),
            liquidity_flag=cast(DropCopyEventLiquidityFlag, str(p["liquidity_flag"])),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "gateway_id": self.gateway_id,
            "event_type": self.event_type,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "fill_qty": self.fill_qty,
            "fill_price": self.fill_price,
            "liquidity_flag": self.liquidity_flag,
        }


def topic_drop_copy_event(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"drop_copy.event.{gateway_id}"


def match_drop_copy_event(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _DROP_COPY_EVENT_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_drop_copy_event(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = DropCopyEvent.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_drop_copy_event(obj.gateway_id), obj.to_dict())


def make_drop_copy_event_unchecked(
    *,
    seq: int,
    timestamp: int,
    gateway_id: str,
    event_type: DropCopyEventEventType,
    order_id: str,
    symbol: str,
    fill_qty: int,
    fill_price: float,
    liquidity_flag: DropCopyEventLiquidityFlag,
) -> list[bytes]:
    """Identical frames to ``make_drop_copy_event``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_drop_copy_event(gateway_id).encode(),
        _msg.dumps(
            {
                "seq": int(seq),
                "timestamp": int(timestamp),
                "gateway_id": str(gateway_id),
                "event_type": str(event_type),
                "order_id": str(order_id),
                "symbol": str(symbol),
                "fill_qty": int(fill_qty),
                "fill_price": float(fill_price),
                "liquidity_flag": str(liquidity_flag),
            }
        ),
    ]


def parse_drop_copy_event(frames: list[bytes]) -> "DropCopyEvent":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_drop_copy_event(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_DROP_COPY_EVENT!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = DropCopyEvent.from_dict(payload)
    obj.validate()
    return obj


def describe_drop_copy_event() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _DROP_COPY_EVENT_FIELDS


TOPIC_DROP_COPY_REPLAY = "drop_copy.replay.{recipient_id}"
PREFIX_DROP_COPY_REPLAY = "drop_copy.replay."
_DROP_COPY_REPLAY_RE = re.compile("drop_copy\\.replay\\.(?P<recipient_id>[^.]+)")
_DROP_COPY_REPLAY_EVENT_TYPE_VALUES = ("order.fill",)
DropCopyReplayEventType = Literal["order.fill"]
_DROP_COPY_REPLAY_LIQUIDITY_FLAG_VALUES = ("MAKER", "TAKER")
DropCopyReplayLiquidityFlag = Literal["MAKER", "TAKER"]


_DROP_COPY_REPLAY_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "recipient_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Who asked for the replay. Topic-only — deliberately not in the body, which is byte-identical to the live event.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
        "constraints": {"gt": 0},
    },
    {
        "name": "timestamp",
        "type": "int",
        "unit": "epoch_nanos",
        "required": True,
        "doc": "",
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Whose fill this was — not the recipient the topic names.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "event_type",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _DROP_COPY_REPLAY_EVENT_TYPE_VALUES,
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
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "fill_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "",
        "constraints": {"gt": 0},
    },
    {
        "name": "fill_price",
        "type": "float",
        "unit": "display_price",
        "required": True,
        "doc": "",
        "constraints": {"gt": 0},
    },
    {
        "name": "liquidity_flag",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _DROP_COPY_REPLAY_LIQUIDITY_FLAG_VALUES,
    },
)


@dataclass(frozen=True, slots=True)
class DropCopyReplay:
    """Engine to one named recipient: buffered events re-published on request, so a
    participant that reconnects mid-session can close its sequence gap.

    The body is byte-identical to the live event, including the original `seq` and
    `timestamp` -- a replayed fill is the same fill, not a new one. Only the topic
    differs, and it names the *recipient* rather than the gateway, so two simultaneous
    replays do not interleave. `recipient_id` is therefore not the same thing as
    `gateway_id`, which is why the body keeps carrying the latter. There is no request
    message. `DropCopyPublisher.replay()` is in-process only, callable from the engine
    and reachable by no protocol -- the module docstring described a
    `drop_copy.replay_request` that was never built. Section 27.3.
    """

    recipient_id: str
    seq: int  # unit: dimensionless
    timestamp: int  # unit: epoch_nanos
    gateway_id: str
    event_type: DropCopyReplayEventType
    order_id: str
    symbol: str
    fill_qty: int  # unit: shares
    fill_price: float  # unit: display_price
    liquidity_flag: DropCopyReplayLiquidityFlag

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.recipient_id) > 32:
            raise MessageValidationError(
                f"recipient_id: length {len(self.recipient_id)} exceeds max_len 32"
            )
        if self.seq <= 0:
            raise MessageValidationError(f"seq: {self.seq!r} must be > 0")
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if self.event_type not in _DROP_COPY_REPLAY_EVENT_TYPE_VALUES:
            raise MessageValidationError(
                f"event_type: {self.event_type!r} is not one of {_DROP_COPY_REPLAY_EVENT_TYPE_VALUES!r}"
            )
        if len(self.order_id) > 64:
            raise MessageValidationError(
                f"order_id: length {len(self.order_id)} exceeds max_len 64"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.fill_qty <= 0:
            raise MessageValidationError(f"fill_qty: {self.fill_qty!r} must be > 0")
        if self.fill_price <= 0:
            raise MessageValidationError(f"fill_price: {self.fill_price!r} must be > 0")
        if self.liquidity_flag not in _DROP_COPY_REPLAY_LIQUIDITY_FLAG_VALUES:
            raise MessageValidationError(
                f"liquidity_flag: {self.liquidity_flag!r} is not one of {_DROP_COPY_REPLAY_LIQUIDITY_FLAG_VALUES!r}"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "DropCopyReplay":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            recipient_id=str(p.get("recipient_id", "")),
            seq=int(p["seq"]),
            timestamp=int(p["timestamp"]),
            gateway_id=str(p["gateway_id"]),
            event_type=cast(DropCopyReplayEventType, str(p["event_type"])),
            order_id=str(p["order_id"]),
            symbol=str(p["symbol"]),
            fill_qty=int(p["fill_qty"]),
            fill_price=float(p["fill_price"]),
            liquidity_flag=cast(DropCopyReplayLiquidityFlag, str(p["liquidity_flag"])),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "gateway_id": self.gateway_id,
            "event_type": self.event_type,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "fill_qty": self.fill_qty,
            "fill_price": self.fill_price,
            "liquidity_flag": self.liquidity_flag,
        }


def topic_drop_copy_replay(recipient_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"drop_copy.replay.{recipient_id}"


def match_drop_copy_replay(topic: str) -> str | None:
    """Return ``recipient_id`` when ``topic`` matches, else None."""
    m = _DROP_COPY_REPLAY_RE.fullmatch(topic)
    return m.group("recipient_id") if m else None


def make_drop_copy_replay(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = DropCopyReplay.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_drop_copy_replay(obj.recipient_id), obj.to_dict())


def make_drop_copy_replay_unchecked(
    *,
    recipient_id: str,
    seq: int,
    timestamp: int,
    gateway_id: str,
    event_type: DropCopyReplayEventType,
    order_id: str,
    symbol: str,
    fill_qty: int,
    fill_price: float,
    liquidity_flag: DropCopyReplayLiquidityFlag,
) -> list[bytes]:
    """Identical frames to ``make_drop_copy_replay``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_drop_copy_replay(recipient_id).encode(),
        _msg.dumps(
            {
                "seq": int(seq),
                "timestamp": int(timestamp),
                "gateway_id": str(gateway_id),
                "event_type": str(event_type),
                "order_id": str(order_id),
                "symbol": str(symbol),
                "fill_qty": int(fill_qty),
                "fill_price": float(fill_price),
                "liquidity_flag": str(liquidity_flag),
            }
        ),
    ]


def parse_drop_copy_replay(frames: list[bytes]) -> "DropCopyReplay":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_drop_copy_replay(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_DROP_COPY_REPLAY!r}"
        )
    payload = {**payload, "recipient_id": matched}
    obj = DropCopyReplay.from_dict(payload)
    obj.validate()
    return obj


def describe_drop_copy_replay() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _DROP_COPY_REPLAY_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (TOPIC_DROP_COPY_EVENT, TOPIC_DROP_COPY_REPLAY)
