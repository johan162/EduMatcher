# GENERATED FROM spec/messages/sim.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``sim`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/sim.yaml``; edit the
spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
../../../../docs/books/architecture-and-development/part-4-developing/040-message-
generation.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, cast

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "sim"
FAMILY_VERSION = 1


_NEWS_REQUEST_SCOPE_VALUES = ("SYMBOL", "SECTOR", "MARKET")
NewsRequestScope = Literal["SYMBOL", "SECTOR", "MARKET"]
_NEWS_REQUEST_KIND_VALUES = (
    "EARNINGS",
    "GUIDANCE",
    "MNA",
    "REGULATORY",
    "PRODUCT",
    "LEGAL",
    "MANAGEMENT",
    "MACRO",
)
NewsRequestKind = Literal[
    "EARNINGS",
    "GUIDANCE",
    "MNA",
    "REGULATORY",
    "PRODUCT",
    "LEGAL",
    "MANAGEMENT",
    "MACRO",
]


@dataclass(frozen=True, slots=True)
class NewsRequest:
    """A headline the instructor wants published (NEWS_INJECT)."""

    scope: NewsRequestScope
    targets: list[str]
    kind: NewsRequestKind
    sentiment: float  # unit: dimensionless
    impact: float  # unit: dimensionless
    headline: str = ""
    rumour: bool = False
    credibility: float | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.scope not in _NEWS_REQUEST_SCOPE_VALUES:
            raise MessageValidationError(
                f"scope: {self.scope!r} is not one of {_NEWS_REQUEST_SCOPE_VALUES!r}"
            )
        if self.kind not in _NEWS_REQUEST_KIND_VALUES:
            raise MessageValidationError(
                f"kind: {self.kind!r} is not one of {_NEWS_REQUEST_KIND_VALUES!r}"
            )
        if self.sentiment < -1:
            raise MessageValidationError(f"sentiment: {self.sentiment!r} must be >= -1")
        if self.sentiment > 1:
            raise MessageValidationError(f"sentiment: {self.sentiment!r} must be <= 1")
        if self.impact < -1:
            raise MessageValidationError(f"impact: {self.impact!r} must be >= -1")
        if self.impact > 1:
            raise MessageValidationError(f"impact: {self.impact!r} must be <= 1")
        if len(self.headline) > 200:
            raise MessageValidationError(
                f"headline: length {len(self.headline)} exceeds max_len 200"
            )
        if self.credibility is not None:
            if self.credibility < 0:
                raise MessageValidationError(
                    f"credibility: {self.credibility!r} must be >= 0"
                )
            if self.credibility > 1:
                raise MessageValidationError(
                    f"credibility: {self.credibility!r} must be <= 1"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "NewsRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            scope=cast(NewsRequestScope, str(p["scope"])),
            targets=[str(item) for item in p["targets"]],
            kind=cast(NewsRequestKind, str(p["kind"])),
            sentiment=float(p["sentiment"]),
            impact=float(p["impact"]),
            headline=str(p.get("headline", "")),
            rumour=bool(p.get("rumour", False)),
            credibility=(
                None if p.get("credibility") is None else float(p["credibility"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "scope": self.scope,
            "targets": self.targets,
            "kind": self.kind,
            "sentiment": self.sentiment,
            "impact": self.impact,
            "headline": self.headline,
            "rumour": self.rumour,
        }
        if self.credibility is not None:
            payload["credibility"] = self.credibility
        return payload


@dataclass(frozen=True, slots=True)
class SymbolValue:
    """One symbol's true value at the step's simulated time."""

    symbol: str
    value: float  # unit: display_price

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
        if self.value <= 0:
            raise MessageValidationError(f"value: {self.value!r} must be > 0")

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SymbolValue":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            value=float(p["value"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbol": self.symbol,
            "value": self.value,
        }


TOPIC_SIM_VALUE = "sim.value"
_TOPIC_SIM_VALUE_BYTES = "sim.value".encode()


_SIM_VALUE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "Step counter; continues across a pm-market-sim restart.",
        "constraints": {"gt": 0},
    },
    {
        "name": "ts_ns",
        "type": "int",
        "unit": "epoch_nanos",
        "required": True,
        "doc": "Publication time.",
    },
    {
        "name": "values",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class SimValue:
    """pm-market-sim to the bots, the market makers that anchor to it and the
    instructor's tools: every symbol's true value after one model step.

    Batched: one message per step carries every symbol (300 symbols are about 11 KB), so
    a subscriber sees one consistent cross-section rather than 300 messages from
    different instants. Published during continuous trading only: that is when the model
    steps. A trading day's variance accrues over the continuous phase as the engine
    reports it, so a day compressed by `pm-scheduler --speed` moves as much as a real
    one.
    """

    seq: int  # unit: dimensionless
    ts_ns: int  # unit: epoch_nanos
    values: list[SymbolValue]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.seq <= 0:
            raise MessageValidationError(f"seq: {self.seq!r} must be > 0")
        if len(self.values) < 1:
            raise MessageValidationError("values: fewer than 1 item(s)")
        for values_item in self.values:
            values_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SimValue":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            seq=int(p["seq"]),
            ts_ns=int(p["ts_ns"]),
            values=[SymbolValue.from_dict(item) for item in p["values"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "seq": self.seq,
            "ts_ns": self.ts_ns,
            "values": [item.to_dict() for item in self.values],
        }


def is_sim_value(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_SIM_VALUE


def make_sim_value(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SimValue.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_SIM_VALUE, obj.to_dict())


def parse_sim_value(frames: list[bytes]) -> "SimValue":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = SimValue.from_dict(payload)
    obj.validate()
    return obj


def describe_sim_value() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SIM_VALUE_FIELDS


TOPIC_SIM_STATE = "sim.state"
_TOPIC_SIM_STATE_BYTES = "sim.state".encode()
_SIM_STATE_STATE_VALUES = ("RUNNING", "PAUSED")
SimStateState = Literal["RUNNING", "PAUSED"]


_SIM_STATE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "state",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "RUNNING during continuous trading, PAUSED otherwise.",
        "values": _SIM_STATE_STATE_VALUES,
    },
    {
        "name": "session",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "The engine session state the model follows.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "The last sim.value published (0 = none yet).",
    },
    {
        "name": "ts_ns",
        "type": "int",
        "unit": "epoch_nanos",
        "required": True,
        "doc": "",
    },
    {
        "name": "step_ns",
        "type": "int",
        "unit": "duration_nanos",
        "required": True,
        "doc": "Time between steps while running.",
        "constraints": {"gt": 0},
    },
    {
        "name": "symbols",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "seed",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class SimState:
    """pm-market-sim's heartbeat: whether the model is stepping and how far it has
    got.

    Published once a second whatever the session, so a subscriber can tell "the exchange
    is closed" (PAUSED) from "pm-market-sim is gone" (no heartbeat).
    """

    state: SimStateState
    session: str
    seq: int  # unit: dimensionless
    ts_ns: int  # unit: epoch_nanos
    step_ns: int  # unit: duration_nanos
    symbols: int  # unit: dimensionless
    seed: int  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.state not in _SIM_STATE_STATE_VALUES:
            raise MessageValidationError(
                f"state: {self.state!r} is not one of {_SIM_STATE_STATE_VALUES!r}"
            )
        if len(self.session) > 32:
            raise MessageValidationError(
                f"session: length {len(self.session)} exceeds max_len 32"
            )
        if self.step_ns <= 0:
            raise MessageValidationError(f"step_ns: {self.step_ns!r} must be > 0")

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SimState":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            state=cast(SimStateState, str(p["state"])),
            session=str(p["session"]),
            seq=int(p["seq"]),
            ts_ns=int(p["ts_ns"]),
            step_ns=int(p["step_ns"]),
            symbols=int(p["symbols"]),
            seed=int(p["seed"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "state": self.state,
            "session": self.session,
            "seq": self.seq,
            "ts_ns": self.ts_ns,
            "step_ns": self.step_ns,
            "symbols": self.symbols,
            "seed": self.seed,
        }


def is_sim_state(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_SIM_STATE


def make_sim_state(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SimState.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_SIM_STATE, obj.to_dict())


def make_sim_state_unchecked(
    *,
    state: SimStateState,
    session: str,
    seq: int,
    ts_ns: int,
    step_ns: int,
    symbols: int,
    seed: int,
) -> list[bytes]:
    """Identical frames to ``make_sim_state``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_SIM_STATE_BYTES,
        _msg.dumps(
            {
                "state": str(state),
                "session": str(session),
                "seq": int(seq),
                "ts_ns": int(ts_ns),
                "step_ns": int(step_ns),
                "symbols": int(symbols),
                "seed": int(seed),
            }
        ),
    ]


def parse_sim_state(frames: list[bytes]) -> "SimState":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = SimState.from_dict(payload)
    obj.validate()
    return obj


def describe_sim_state() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SIM_STATE_FIELDS


TOPIC_SIM_COMMAND = "sim.command"
_TOPIC_SIM_COMMAND_BYTES = "sim.command".encode()
_SIM_COMMAND_ACTION_VALUES = ("STATUS", "NEWS_INJECT", "NEWS_CONFIRM", "NEWS_RETRACT")
SimCommandAction = Literal["STATUS", "NEWS_INJECT", "NEWS_CONFIRM", "NEWS_RETRACT"]


_SIM_COMMAND_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "command_id",
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
        "doc": "The sender; the reply goes to sim.command_ack.<gateway_id>.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "action",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _SIM_COMMAND_ACTION_VALUES,
    },
    {
        "name": "news",
        "type": "nested",
        "unit": None,
        "required": False,
        "doc": "The headline to publish (NEWS_INJECT).",
    },
    {
        "name": "news_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "The rumour to confirm or retract.",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class SimCommand:
    """Instructor tooling to pm-market-sim: one command.

    pm-market-sim binds its PULL socket to loopback and accepts a command only when
    `gateway_id` is an ADMIN participant of the deployed configuration.
    """

    command_id: str
    gateway_id: str
    action: SimCommandAction
    news: NewsRequest | None = None
    news_id: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if self.action not in _SIM_COMMAND_ACTION_VALUES:
            raise MessageValidationError(
                f"action: {self.action!r} is not one of {_SIM_COMMAND_ACTION_VALUES!r}"
            )
        if self.news is not None:
            self.news.validate()
        if len(self.news_id) > 32:
            raise MessageValidationError(
                f"news_id: length {len(self.news_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SimCommand":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            command_id=str(p["command_id"]),
            gateway_id=str(p["gateway_id"]),
            action=cast(SimCommandAction, str(p["action"])),
            news=None if p.get("news") is None else NewsRequest.from_dict(p["news"]),
            news_id=str(p.get("news_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "command_id": self.command_id,
            "gateway_id": self.gateway_id,
            "action": self.action,
            "news_id": self.news_id,
        }
        if self.news is not None:
            payload["news"] = self.news.to_dict()
        return payload


def is_sim_command(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_SIM_COMMAND


def make_sim_command(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SimCommand.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_SIM_COMMAND, obj.to_dict())


def parse_sim_command(frames: list[bytes]) -> "SimCommand":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = SimCommand.from_dict(payload)
    obj.validate()
    return obj


def describe_sim_command() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SIM_COMMAND_FIELDS


TOPIC_SIM_COMMAND_ACK = "sim.command_ack.{gateway_id}"
PREFIX_SIM_COMMAND_ACK = "sim.command_ack."
_SIM_COMMAND_ACK_RE = re.compile("sim\\.command_ack\\.(?P<gateway_id>[^.]+)")


_SIM_COMMAND_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "command_id",
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
        "doc": "Refusal detail, or what was done.",
        "constraints": {"max_len": 256},
    },
    {
        "name": "news_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "The news.event published, if any.",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class SimCommandAck:
    """pm-market-sim to the commanding tool: the outcome of one command."""

    gateway_id: str
    command_id: str
    accepted: bool
    reason: str = ""
    news_id: str = ""

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
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )
        if len(self.reason) > 256:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 256"
            )
        if len(self.news_id) > 32:
            raise MessageValidationError(
                f"news_id: length {len(self.news_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SimCommandAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            command_id=str(p["command_id"]),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
            news_id=str(p.get("news_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "command_id": self.command_id,
            "accepted": self.accepted,
            "reason": self.reason,
            "news_id": self.news_id,
        }


def topic_sim_command_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"sim.command_ack.{gateway_id}"


def match_sim_command_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _SIM_COMMAND_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_sim_command_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SimCommandAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_sim_command_ack(obj.gateway_id), obj.to_dict())


def make_sim_command_ack_unchecked(
    *,
    gateway_id: str,
    command_id: str,
    accepted: bool,
    reason: str = "",
    news_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_sim_command_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_sim_command_ack(gateway_id).encode(),
        _msg.dumps(
            {
                "command_id": str(command_id),
                "accepted": bool(accepted),
                "reason": str(reason),
                "news_id": str(news_id),
            }
        ),
    ]


def parse_sim_command_ack(frames: list[bytes]) -> "SimCommandAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_sim_command_ack(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_SIM_COMMAND_ACK!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = SimCommandAck.from_dict(payload)
    obj.validate()
    return obj


def describe_sim_command_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SIM_COMMAND_ACK_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_SIM_VALUE,
    TOPIC_SIM_STATE,
    TOPIC_SIM_COMMAND,
    TOPIC_SIM_COMMAND_ACK,
)
