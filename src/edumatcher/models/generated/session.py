# GENERATED FROM spec/messages/session.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``session`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/session.yaml``; edit
the spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
docs/developer/06-msgen.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "session"
FAMILY_VERSION = 1


@dataclass(frozen=True, slots=True)
class NextTransition:
    """The transition after this one: what the session moves to, and when. Present
    only when the scheduler drove the transition, since it alone knows the day's
    timetable. A manual or admin-driven transition carries no next - deliberately,
    because the schedule says what *should* happen while the engine decides what
    *does*, and a countdown derived from the timetable alone would tick toward a
    transition nobody will perform. The two fields are one record rather than two
    optional keys because neither is meaningful alone: a phase without a time
    cannot be counted down to, and a time without a phase does not say what
    happens.
    """

    state: str
    at: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.state) > 32:
            raise MessageValidationError(
                f"state: length {len(self.state)} exceeds max_len 32"
            )
        if len(self.at) > 32:
            raise MessageValidationError(
                f"at: length {len(self.at)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "NextTransition":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            state=str(p["state"]),
            at=str(p["at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "state": self.state,
            "at": self.at,
        }


@dataclass(frozen=True, slots=True)
class ReplyTo:
    """Where to send the outcome of a command, and under what correlation id.
    Supplied by an *interactive* requester that wants to know what happened. pm-
    scheduler omits it: it drives the timetable, has nobody to report back to, and
    the public session.state broadcast already says what occurred. A record rather
    than two optional keys for the same reason as NextTransition - a command_id
    with no gateway to answer on is undeliverable, and a gateway with no
    command_id cannot be correlated.
    """

    command_id: str
    gateway_id: str

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

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ReplyTo":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            command_id=str(p["command_id"]),
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "command_id": self.command_id,
            "gateway_id": self.gateway_id,
        }


TOPIC_SESSION_STATE = "session.state"
_TOPIC_SESSION_STATE_BYTES = "session.state".encode()


_SESSION_STATE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "state",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "The session state now in effect.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "prev_state",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "The state departed from; absent on the first broadcast.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "next",
        "type": "nested",
        "unit": None,
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class SessionState:
    """Broadcast the engine's current session state to every subscriber. The most
    widely consumed topic in the system.

    prev_state is omitted when empty rather than emitted as "", which is what the hand-
    written payload did. next is present only on a scheduler-driven transition.
    """

    state: str
    prev_state: str = ""
    next: NextTransition | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.state) > 32:
            raise MessageValidationError(
                f"state: length {len(self.state)} exceeds max_len 32"
            )
        if len(self.prev_state) > 32:
            raise MessageValidationError(
                f"prev_state: length {len(self.prev_state)} exceeds max_len 32"
            )
        if self.next is not None:
            self.next.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SessionState":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            state=str(p["state"]),
            prev_state=str(p.get("prev_state", "")),
            next=None if p.get("next") is None else NextTransition.from_dict(p["next"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "state": self.state,
        }
        if self.prev_state:
            payload["prev_state"] = self.prev_state
        if self.next is not None:
            payload["next"] = self.next.to_dict()
        return payload


def is_session_state(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_SESSION_STATE


def make_session_state(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SessionState.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_SESSION_STATE, obj.to_dict())


def parse_session_state(frames: list[bytes]) -> "SessionState":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = SessionState.from_dict(payload)
    obj.validate()
    return obj


def describe_session_state() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SESSION_STATE_FIELDS


TOPIC_SESSION_TRANSITION = "session.transition"
_TOPIC_SESSION_TRANSITION_BYTES = "session.transition".encode()


_SESSION_TRANSITION_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "to_state",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "next",
        "type": "nested",
        "unit": None,
        "required": False,
        "doc": "Describes the transition *after* this one, so the engine can publish a countdown target. A manual transition omits it, which clears any stale target the engine was holding.",
    },
    {
        "name": "reply_to",
        "type": "nested",
        "unit": None,
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class SessionTransition:
    """Scheduler or operator to engine: request a state change."""

    to_state: str
    next: NextTransition | None = None
    reply_to: ReplyTo | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.to_state) > 32:
            raise MessageValidationError(
                f"to_state: length {len(self.to_state)} exceeds max_len 32"
            )
        if self.next is not None:
            self.next.validate()
        if self.reply_to is not None:
            self.reply_to.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SessionTransition":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            to_state=str(p["to_state"]),
            next=None if p.get("next") is None else NextTransition.from_dict(p["next"]),
            reply_to=(
                None if p.get("reply_to") is None else ReplyTo.from_dict(p["reply_to"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "to_state": self.to_state,
        }
        if self.next is not None:
            payload["next"] = self.next.to_dict()
        if self.reply_to is not None:
            payload["reply_to"] = self.reply_to.to_dict()
        return payload


def is_session_transition(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_SESSION_TRANSITION


def make_session_transition(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SessionTransition.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_SESSION_TRANSITION, obj.to_dict())


def parse_session_transition(frames: list[bytes]) -> "SessionTransition":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = SessionTransition.from_dict(payload)
    obj.validate()
    return obj


def describe_session_transition() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SESSION_TRANSITION_FIELDS


TOPIC_SESSION_TRANSITION_ACK = "session.transition_ack.{gateway_id}"
PREFIX_SESSION_TRANSITION_ACK = "session.transition_ack."
_SESSION_TRANSITION_ACK_RE = re.compile(
    "session\\.transition_ack\\.(?P<gateway_id>[^.]+)"
)


_SESSION_TRANSITION_ACK_FIELDS: tuple[dict[str, Any], ...] = (
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
        "name": "to_state",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Rejection detail; empty when accepted.",
        "constraints": {"max_len": 256},
    },
)


@dataclass(frozen=True, slots=True)
class SessionTransitionAck:
    """Engine to the requesting gateway: the outcome of a transition request.

    Addressed rather than broadcast, because a command_id belongs to whoever issued it -
    putting it on the public session.state topic would hand every subscriber another
    operator's correlation id. It also closes a silent failure: a request the engine
    discarded previously produced no reply at all, so a caller could not tell a
    rejection from a timeout.
    """

    gateway_id: str
    command_id: str
    accepted: bool
    to_state: str = ""
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
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )
        if len(self.to_state) > 32:
            raise MessageValidationError(
                f"to_state: length {len(self.to_state)} exceeds max_len 32"
            )
        if len(self.reason) > 256:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 256"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SessionTransitionAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            command_id=str(p["command_id"]),
            accepted=bool(p["accepted"]),
            to_state=str(p.get("to_state", "")),
            reason=str(p.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "command_id": self.command_id,
            "accepted": self.accepted,
            "to_state": self.to_state,
            "reason": self.reason,
        }


def topic_session_transition_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"session.transition_ack.{gateway_id}"


def match_session_transition_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _SESSION_TRANSITION_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_session_transition_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SessionTransitionAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_session_transition_ack(obj.gateway_id), obj.to_dict())


def make_session_transition_ack_unchecked(
    *,
    gateway_id: str,
    command_id: str,
    accepted: bool,
    to_state: str = "",
    reason: str = "",
) -> list[bytes]:
    """Identical frames to ``make_session_transition_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_session_transition_ack(gateway_id).encode(),
        _msg.dumps(
            {
                "command_id": str(command_id),
                "accepted": bool(accepted),
                "to_state": str(to_state),
                "reason": str(reason),
            }
        ),
    ]


def parse_session_transition_ack(frames: list[bytes]) -> "SessionTransitionAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_session_transition_ack(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_SESSION_TRANSITION_ACK!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = SessionTransitionAck.from_dict(payload)
    obj.validate()
    return obj


def describe_session_transition_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SESSION_TRANSITION_ACK_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_SESSION_STATE,
    TOPIC_SESSION_TRANSITION,
    TOPIC_SESSION_TRANSITION_ACK,
)
