# GENERATED FROM spec/messages/circuit_breaker.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``circuit_breaker`` message family.

Family version 1. Every symbol here is derived from
``spec/messages/circuit_breaker.yaml``; edit the spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
docs/developer/06-msgen.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, cast

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "circuit_breaker"
FAMILY_VERSION = 1


TOPIC_CIRCUIT_BREAKER_HALT = "circuit_breaker.halt.{symbol}"
PREFIX_CIRCUIT_BREAKER_HALT = "circuit_breaker.halt."
_CIRCUIT_BREAKER_HALT_RE = re.compile("circuit_breaker\\.halt\\.(?P<symbol>[^.]+)")
_CIRCUIT_BREAKER_HALT_HALT_SOURCE_VALUES = ("CB", "ADMIN")
CircuitBreakerHaltHaltSource = Literal["CB", "ADMIN"]


_CIRCUIT_BREAKER_HALT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "trigger_price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "The trade price that breached the level. Null on an ADMIN halt.",
        "constraints": {"gt": 0},
    },
    {
        "name": "reference_price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "The price the breach was measured against. Null on an ADMIN halt.",
        "constraints": {"gt": 0},
    },
    {
        "name": "resume_at_ns",
        "type": "int",
        "unit": "epoch_nanos",
        "required": False,
        "doc": "When the current call phase ends. Null means indefinite: the halt lasts until an operator resumes it. ACE moves this on every extension, so a consumer that ignores `circuit_breaker.extend` will hold a value that has already passed.",
    },
    {
        "name": "halt_source",
        "type": "enum",
        "unit": None,
        "required": False,
        "doc": "What put the symbol into the halt. Mirrors `CircuitBreakerState.halt_source`, which is `None` only while no halt is in effect -- so the key is present on every halt event.",
        "values": _CIRCUIT_BREAKER_HALT_HALT_SOURCE_VALUES,
    },
    {
        "name": "level",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Which rung of the ladder fired -- a name from the symbol's `circuit_breaker.levels` config -- or `ADMIN_ALL` / `ADMIN_SYMBOL` for an operator halt. Not an enum: the ladder is configuration, so the value set differs per deployment.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "corridor_low",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "Lower bound of the ACE reopening corridor. Absent when the halt has no corridor: either ACE is disabled or the halt began with no reference price to centre one on.",
        "constraints": {"gt": 0},
    },
    {
        "name": "corridor_high",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "Upper bound of the ACE reopening corridor. Absent with the low.",
        "constraints": {"gt": 0},
    },
    {
        "name": "expansion",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "Rungs of the expansion ladder consumed so far; 0 in the initial call phase. Absent whenever the corridor is, because a halt that cannot have a corridor can never widen one.",
        "constraints": {"ge": 0},
    },
)


@dataclass(frozen=True, slots=True)
class CircuitBreakerHalt:
    """Engine to all: one symbol has stopped trading. New orders rest rather than
    match until the halt ends, and every resting quote on the symbol has already
    been cancelled by the time this is published.

    `halt_source` says what caused the halt, not how it will end: every halt ends in a
    reopening auction call, because LIMIT orders accumulate freely while a symbol is
    halted and resuming without an uncross would start continuous trading on a crossed
    book. `trigger_price` and `reference_price` are the price that fired the breaker and
    the price it was measured against. Both are null on an ADMIN halt, which fires on an
    operator's decision rather than on a price, and both may be null on a price-
    triggered halt that had no reference to latch. `resume_at_ns` is null for an
    indefinite halt -- `halt_all` and a per-symbol halt named without a level both
    produce one, and it lasts until an explicit resume.
    """

    symbol: str
    trigger_price: float | None = None  # unit: display_price
    reference_price: float | None = None  # unit: display_price
    resume_at_ns: int | None = None  # unit: epoch_nanos
    halt_source: CircuitBreakerHaltHaltSource | None = None
    level: str | None = None
    corridor_low: float | None = None  # unit: display_price
    corridor_high: float | None = None  # unit: display_price
    expansion: int | None = None  # unit: dimensionless

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
        if self.trigger_price is not None:
            if self.trigger_price <= 0:
                raise MessageValidationError(
                    f"trigger_price: {self.trigger_price!r} must be > 0"
                )
        if self.reference_price is not None:
            if self.reference_price <= 0:
                raise MessageValidationError(
                    f"reference_price: {self.reference_price!r} must be > 0"
                )
        if self.halt_source is not None:
            if self.halt_source not in _CIRCUIT_BREAKER_HALT_HALT_SOURCE_VALUES:
                raise MessageValidationError(
                    f"halt_source: {self.halt_source!r} is not one of {_CIRCUIT_BREAKER_HALT_HALT_SOURCE_VALUES!r}"
                )
        if self.level is not None:
            if len(self.level) > 32:
                raise MessageValidationError(
                    f"level: length {len(self.level)} exceeds max_len 32"
                )
        if self.corridor_low is not None:
            if self.corridor_low <= 0:
                raise MessageValidationError(
                    f"corridor_low: {self.corridor_low!r} must be > 0"
                )
        if self.corridor_high is not None:
            if self.corridor_high <= 0:
                raise MessageValidationError(
                    f"corridor_high: {self.corridor_high!r} must be > 0"
                )
        if self.expansion is not None:
            if self.expansion < 0:
                raise MessageValidationError(
                    f"expansion: {self.expansion!r} must be >= 0"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "CircuitBreakerHalt":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            trigger_price=(
                None if p.get("trigger_price") is None else float(p["trigger_price"])
            ),
            reference_price=(
                None
                if p.get("reference_price") is None
                else float(p["reference_price"])
            ),
            resume_at_ns=(
                None if p.get("resume_at_ns") is None else int(p["resume_at_ns"])
            ),
            halt_source=(
                None
                if p.get("halt_source") is None
                else cast(CircuitBreakerHaltHaltSource, str(p["halt_source"]))
            ),
            level=None if p.get("level") is None else str(p["level"]),
            corridor_low=(
                None if p.get("corridor_low") is None else float(p["corridor_low"])
            ),
            corridor_high=(
                None if p.get("corridor_high") is None else float(p["corridor_high"])
            ),
            expansion=None if p.get("expansion") is None else int(p["expansion"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "trigger_price": self.trigger_price,
            "reference_price": self.reference_price,
            "resume_at_ns": self.resume_at_ns,
        }
        if self.halt_source is not None:
            payload["halt_source"] = self.halt_source
        if self.level is not None:
            payload["level"] = self.level
        if self.corridor_low is not None:
            payload["corridor_low"] = self.corridor_low
        if self.corridor_high is not None:
            payload["corridor_high"] = self.corridor_high
        if self.expansion is not None:
            payload["expansion"] = self.expansion
        return payload


def topic_circuit_breaker_halt(symbol: str) -> str:
    """Build this message's topic without a string literal."""
    return f"circuit_breaker.halt.{symbol}"


def match_circuit_breaker_halt(topic: str) -> str | None:
    """Return ``symbol`` when ``topic`` matches, else None."""
    m = _CIRCUIT_BREAKER_HALT_RE.fullmatch(topic)
    return m.group("symbol") if m else None


def make_circuit_breaker_halt(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = CircuitBreakerHalt.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_circuit_breaker_halt(obj.symbol), obj.to_dict())


def make_circuit_breaker_halt_unchecked(
    *,
    symbol: str,
    trigger_price: float | None = None,
    reference_price: float | None = None,
    resume_at_ns: int | None = None,
    halt_source: CircuitBreakerHaltHaltSource | None = None,
    level: str | None = None,
    corridor_low: float | None = None,
    corridor_high: float | None = None,
    expansion: int | None = None,
) -> list[bytes]:
    """Identical frames to ``make_circuit_breaker_halt``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "symbol": str(symbol),
        "trigger_price": None if trigger_price is None else float(trigger_price),
        "reference_price": None if reference_price is None else float(reference_price),
        "resume_at_ns": None if resume_at_ns is None else int(resume_at_ns),
    }
    if halt_source is not None:
        payload["halt_source"] = str(halt_source)
    if level is not None:
        payload["level"] = str(level)
    if corridor_low is not None:
        payload["corridor_low"] = float(corridor_low)
    if corridor_high is not None:
        payload["corridor_high"] = float(corridor_high)
    if expansion is not None:
        payload["expansion"] = int(expansion)
    return [
        topic_circuit_breaker_halt(symbol).encode(),
        _msg.dumps(payload),
    ]


def parse_circuit_breaker_halt(frames: list[bytes]) -> "CircuitBreakerHalt":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_circuit_breaker_halt(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_CIRCUIT_BREAKER_HALT!r}"
        )
    payload = {**payload, "symbol": matched}
    obj = CircuitBreakerHalt.from_dict(payload)
    obj.validate()
    return obj


def describe_circuit_breaker_halt() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _CIRCUIT_BREAKER_HALT_FIELDS


TOPIC_CIRCUIT_BREAKER_EXTEND = "circuit_breaker.extend.{symbol}"
PREFIX_CIRCUIT_BREAKER_EXTEND = "circuit_breaker.extend."
_CIRCUIT_BREAKER_EXTEND_RE = re.compile("circuit_breaker\\.extend\\.(?P<symbol>[^.]+)")
_CIRCUIT_BREAKER_EXTEND_IMBALANCE_SIDE_VALUES = ("BUY", "SELL")
CircuitBreakerExtendImbalanceSide = Literal["BUY", "SELL"]


_CIRCUIT_BREAKER_EXTEND_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "indicative_price",
        "type": "float",
        "unit": "display_price",
        "required": True,
        "doc": "Where the symbol would have reopened, outside the corridor.",
        "constraints": {"gt": 0},
    },
    {
        "name": "indicative_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Quantity that would have executed. Always above zero: the producer only extends when the indicative uncross would have traded.",
        "constraints": {"gt": 0},
    },
    {
        "name": "imbalance_side",
        "type": "enum",
        "unit": None,
        "required": False,
        "doc": "Which side is unfilled at the indicative price. Absent when the book is balanced there.",
        "values": _CIRCUIT_BREAKER_EXTEND_IMBALANCE_SIDE_VALUES,
    },
    {
        "name": "resume_at_ns",
        "type": "int",
        "unit": "epoch_nanos",
        "required": True,
        "doc": "End of the new call phase. Always set; `extend()` computes it.",
    },
    {
        "name": "corridor_low",
        "type": "float",
        "unit": "display_price",
        "required": True,
        "doc": "Lower bound of the widened corridor.",
        "constraints": {"gt": 0},
    },
    {
        "name": "corridor_high",
        "type": "float",
        "unit": "display_price",
        "required": True,
        "doc": "Upper bound of the widened corridor.",
        "constraints": {"gt": 0},
    },
    {
        "name": "expansion",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "Rungs consumed after this widening -- at least 1, since the event is published by the widening itself.",
        "constraints": {"gt": 0},
    },
)


@dataclass(frozen=True, slots=True)
class CircuitBreakerExtend:
    """Engine to all: the call phase ended with the indicative price outside the
    corridor, so the symbol stays halted, the corridor widens by one rung and a
    fresh call phase begins.

    The symbol's state does not change here -- an extension is a continuation of the
    same halt -- so `md_gateway` deliberately does not re-emit a STATE event for it,
    only the moved corridor and resume time. The corridor fields are the corridor
    *after* widening, and unlike on `circuit_breaker.halt` they are always present: this
    event can only be produced on a path that has just asserted a corridor exists.
    `indicative_price` and `indicative_qty` are the imbalance indicator a real venue
    disseminates during a reopening. They are what lets a participant supply the
    offsetting interest that resolves the halt, which only works while there is still
    time to act.
    """

    symbol: str
    indicative_price: float  # unit: display_price
    indicative_qty: int  # unit: shares
    resume_at_ns: int  # unit: epoch_nanos
    corridor_low: float  # unit: display_price
    corridor_high: float  # unit: display_price
    expansion: int  # unit: dimensionless
    imbalance_side: CircuitBreakerExtendImbalanceSide | None = None

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
        if self.indicative_price <= 0:
            raise MessageValidationError(
                f"indicative_price: {self.indicative_price!r} must be > 0"
            )
        if self.indicative_qty <= 0:
            raise MessageValidationError(
                f"indicative_qty: {self.indicative_qty!r} must be > 0"
            )
        if self.imbalance_side is not None:
            if self.imbalance_side not in _CIRCUIT_BREAKER_EXTEND_IMBALANCE_SIDE_VALUES:
                raise MessageValidationError(
                    f"imbalance_side: {self.imbalance_side!r} is not one of {_CIRCUIT_BREAKER_EXTEND_IMBALANCE_SIDE_VALUES!r}"
                )
        if self.corridor_low <= 0:
            raise MessageValidationError(
                f"corridor_low: {self.corridor_low!r} must be > 0"
            )
        if self.corridor_high <= 0:
            raise MessageValidationError(
                f"corridor_high: {self.corridor_high!r} must be > 0"
            )
        if self.expansion <= 0:
            raise MessageValidationError(f"expansion: {self.expansion!r} must be > 0")

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "CircuitBreakerExtend":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            indicative_price=float(p["indicative_price"]),
            indicative_qty=int(p["indicative_qty"]),
            imbalance_side=(
                None
                if p.get("imbalance_side") is None
                else cast(CircuitBreakerExtendImbalanceSide, str(p["imbalance_side"]))
            ),
            resume_at_ns=int(p["resume_at_ns"]),
            corridor_low=float(p["corridor_low"]),
            corridor_high=float(p["corridor_high"]),
            expansion=int(p["expansion"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "indicative_price": self.indicative_price,
            "indicative_qty": self.indicative_qty,
            "resume_at_ns": self.resume_at_ns,
            "corridor_low": self.corridor_low,
            "corridor_high": self.corridor_high,
            "expansion": self.expansion,
        }
        if self.imbalance_side is not None:
            payload["imbalance_side"] = self.imbalance_side
        return payload


def topic_circuit_breaker_extend(symbol: str) -> str:
    """Build this message's topic without a string literal."""
    return f"circuit_breaker.extend.{symbol}"


def match_circuit_breaker_extend(topic: str) -> str | None:
    """Return ``symbol`` when ``topic`` matches, else None."""
    m = _CIRCUIT_BREAKER_EXTEND_RE.fullmatch(topic)
    return m.group("symbol") if m else None


def make_circuit_breaker_extend(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = CircuitBreakerExtend.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_circuit_breaker_extend(obj.symbol), obj.to_dict())


def make_circuit_breaker_extend_unchecked(
    *,
    symbol: str,
    indicative_price: float,
    indicative_qty: int,
    resume_at_ns: int,
    corridor_low: float,
    corridor_high: float,
    expansion: int,
    imbalance_side: CircuitBreakerExtendImbalanceSide | None = None,
) -> list[bytes]:
    """Identical frames to ``make_circuit_breaker_extend``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "symbol": str(symbol),
        "indicative_price": float(indicative_price),
        "indicative_qty": int(indicative_qty),
        "resume_at_ns": int(resume_at_ns),
        "corridor_low": float(corridor_low),
        "corridor_high": float(corridor_high),
        "expansion": int(expansion),
    }
    if imbalance_side is not None:
        payload["imbalance_side"] = str(imbalance_side)
    return [
        topic_circuit_breaker_extend(symbol).encode(),
        _msg.dumps(payload),
    ]


def parse_circuit_breaker_extend(frames: list[bytes]) -> "CircuitBreakerExtend":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_circuit_breaker_extend(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_CIRCUIT_BREAKER_EXTEND!r}"
        )
    payload = {**payload, "symbol": matched}
    obj = CircuitBreakerExtend.from_dict(payload)
    obj.validate()
    return obj


def describe_circuit_breaker_extend() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _CIRCUIT_BREAKER_EXTEND_FIELDS


TOPIC_CIRCUIT_BREAKER_RESUME = "circuit_breaker.resume.{symbol}"
PREFIX_CIRCUIT_BREAKER_RESUME = "circuit_breaker.resume."
_CIRCUIT_BREAKER_RESUME_RE = re.compile("circuit_breaker\\.resume\\.(?P<symbol>[^.]+)")
_CIRCUIT_BREAKER_RESUME_HALT_SOURCE_VALUES = ("CB", "ADMIN")
CircuitBreakerResumeHaltSource = Literal["CB", "ADMIN"]


_CIRCUIT_BREAKER_RESUME_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "halt_source",
        "type": "enum",
        "unit": None,
        "required": False,
        "doc": "What had put the symbol into the halt that just ended.",
        "values": _CIRCUIT_BREAKER_RESUME_HALT_SOURCE_VALUES,
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": 'Why the halt ended, when that is not simply "its call phase expired". Only the closing backstop sets it, to CLOSING_BACKSTOP.',
        "constraints": {"max_len": 64},
    },
    {
        "name": "clamped",
        "type": "bool",
        "unit": None,
        "required": False,
        "doc": "True when the print price was forced to the corridor boundary instead of the equilibrium. A client showing a clamped price as a discovered one would mislead. Absent on the three ordinary resumes, where no price is imposed at all -- which is a different statement from `false`, and worth keeping distinct.",
    },
    {
        "name": "print_price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "The price the backstop uncross printed at. Absent when there was no crossing interest to print, and on the three ordinary resumes.",
        "constraints": {"gt": 0},
    },
)


@dataclass(frozen=True, slots=True)
class CircuitBreakerResume:
    """Engine to all: the symbol is trading again. It rejoins whatever the exchange
    is currently doing rather than returning to continuous trading -- a halt that
    expires near the close resumes into CLOSING_AUCTION or CLOSED.

    Four producers, two shapes. Three of them -- ACE expiry, ADMIN resume-all and ADMIN
    per-symbol resume -- send `symbol` and `halt_source` alone. The closing backstop
    sends three fields more, because it is the one resume where the reopening price was
    imposed rather than discovered: it prints *at* the corridor boundary for a symbol
    that could not reopen inside it, which can leave the book crossed by design. The
    three extra fields are regime 3 and 4 rather than always-present nulls, so the three
    ordinary producers keep the two-key payload they have always sent.
    `normalise_cb_resume` reads each through a falsy guard, so an absent key and an
    empty one are the same event to it.
    """

    symbol: str
    halt_source: CircuitBreakerResumeHaltSource | None = None
    reason: str = ""
    clamped: bool | None = None
    print_price: float | None = None  # unit: display_price

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
        if self.halt_source is not None:
            if self.halt_source not in _CIRCUIT_BREAKER_RESUME_HALT_SOURCE_VALUES:
                raise MessageValidationError(
                    f"halt_source: {self.halt_source!r} is not one of {_CIRCUIT_BREAKER_RESUME_HALT_SOURCE_VALUES!r}"
                )
        if len(self.reason) > 64:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 64"
            )
        if self.print_price is not None:
            if self.print_price <= 0:
                raise MessageValidationError(
                    f"print_price: {self.print_price!r} must be > 0"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "CircuitBreakerResume":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            halt_source=(
                None
                if p.get("halt_source") is None
                else cast(CircuitBreakerResumeHaltSource, str(p["halt_source"]))
            ),
            reason=str(p.get("reason", "")),
            clamped=None if p.get("clamped") is None else bool(p["clamped"]),
            print_price=(
                None if p.get("print_price") is None else float(p["print_price"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
        }
        if self.halt_source is not None:
            payload["halt_source"] = self.halt_source
        if self.reason:
            payload["reason"] = self.reason
        if self.clamped is not None:
            payload["clamped"] = self.clamped
        if self.print_price is not None:
            payload["print_price"] = self.print_price
        return payload


def topic_circuit_breaker_resume(symbol: str) -> str:
    """Build this message's topic without a string literal."""
    return f"circuit_breaker.resume.{symbol}"


def match_circuit_breaker_resume(topic: str) -> str | None:
    """Return ``symbol`` when ``topic`` matches, else None."""
    m = _CIRCUIT_BREAKER_RESUME_RE.fullmatch(topic)
    return m.group("symbol") if m else None


def make_circuit_breaker_resume(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = CircuitBreakerResume.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_circuit_breaker_resume(obj.symbol), obj.to_dict())


def make_circuit_breaker_resume_unchecked(
    *,
    symbol: str,
    halt_source: CircuitBreakerResumeHaltSource | None = None,
    reason: str = "",
    clamped: bool | None = None,
    print_price: float | None = None,
) -> list[bytes]:
    """Identical frames to ``make_circuit_breaker_resume``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "symbol": str(symbol),
    }
    if halt_source is not None:
        payload["halt_source"] = str(halt_source)
    if reason:
        payload["reason"] = str(reason)
    if clamped is not None:
        payload["clamped"] = bool(clamped)
    if print_price is not None:
        payload["print_price"] = float(print_price)
    return [
        topic_circuit_breaker_resume(symbol).encode(),
        _msg.dumps(payload),
    ]


def parse_circuit_breaker_resume(frames: list[bytes]) -> "CircuitBreakerResume":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_circuit_breaker_resume(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_CIRCUIT_BREAKER_RESUME!r}"
        )
    payload = {**payload, "symbol": matched}
    obj = CircuitBreakerResume.from_dict(payload)
    obj.validate()
    return obj


def describe_circuit_breaker_resume() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _CIRCUIT_BREAKER_RESUME_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_CIRCUIT_BREAKER_HALT,
    TOPIC_CIRCUIT_BREAKER_EXTEND,
    TOPIC_CIRCUIT_BREAKER_RESUME,
)
