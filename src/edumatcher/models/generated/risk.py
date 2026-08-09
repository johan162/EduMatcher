# GENERATED FROM spec/messages/risk.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``risk`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/risk.yaml``; edit
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

FAMILY = "risk"
FAMILY_VERSION = 1


TOPIC_KILL_SWITCH = "risk.kill_switch"
_TOPIC_KILL_SWITCH_BYTES = "risk.kill_switch".encode()


_KILL_SWITCH_FIELDS: tuple[dict[str, Any], ...] = (
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
        "required": False,
        "doc": 'Scope to one instrument; "" cancels across all of them.',
        "constraints": {"max_len": 16},
    },
    {
        "name": "note",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Free-text reason, recorded on the admin monitor.",
        "constraints": {"max_len": 256},
    },
    {
        "name": "command_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Echoed on the ack. A kill-switch ack carries no natural identifier - unlike the symbol acks, which carry `symbol` - so without this two concurrent mass cancels for one gateway are indistinguishable once both acks are in flight.",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class KillSwitch:
    """Gateway or admin to engine: cancel a gateway's open risk-bearing exposure. The
    gateway is NOT halted - it may submit again as soon as the ack arrives.

    `symbol` scopes the cancel to one instrument. It is always emitted, as "" for the
    whole-gateway case, because the handler reads it as `if symbol_filter:` - empty and
    absent mean the same thing to it, and the hand-written builder always sent the key.
    `gateway_id` names whose exposure is cancelled, not who asked. This message only
    ever acts on the caller's own gateway; use risk.kill_switch_gateway for one
    participant acting on another.
    """

    gateway_id: str
    symbol: str = ""
    note: str = ""
    command_id: str = ""

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
        if len(self.note) > 256:
            raise MessageValidationError(
                f"note: length {len(self.note)} exceeds max_len 256"
            )
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "KillSwitch":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            symbol=str(p.get("symbol", "")),
            note=str(p.get("note", "")),
            command_id=str(p.get("command_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "gateway_id": self.gateway_id,
            "symbol": self.symbol,
        }
        if self.note:
            payload["note"] = self.note
        if self.command_id:
            payload["command_id"] = self.command_id
        return payload


def is_kill_switch(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_KILL_SWITCH


def make_kill_switch(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = KillSwitch.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_KILL_SWITCH, obj.to_dict())


def make_kill_switch_unchecked(
    *,
    gateway_id: str,
    symbol: str = "",
    note: str = "",
    command_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_kill_switch``, without ``validate()``.

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
    }
    if note:
        payload["note"] = str(note)
    if command_id:
        payload["command_id"] = str(command_id)
    return [
        _TOPIC_KILL_SWITCH_BYTES,
        _msg.dumps(payload),
    ]


def parse_kill_switch(frames: list[bytes]) -> "KillSwitch":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = KillSwitch.from_dict(payload)
    obj.validate()
    return obj


def describe_kill_switch() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _KILL_SWITCH_FIELDS


TOPIC_KILL_SWITCH_ACK = "risk.kill_switch_ack.{gateway_id}"
PREFIX_KILL_SWITCH_ACK = "risk.kill_switch_ack."
_KILL_SWITCH_ACK_RE = re.compile("risk\\.kill_switch_ack\\.(?P<gateway_id>[^.]+)")


_KILL_SWITCH_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
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
        "name": "cancelled_orders",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "cancelled_quotes",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "command_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class KillSwitchAck:
    """Engine to caller: what the kill switch cancelled.

    The counters are always emitted, as 0 on rejection: the hand-written builder put
    them in the base payload beside `accepted`, and a rejected kill switch cancelled
    nothing. `reason` is likewise always present, as "" on success.
    """

    gateway_id: str
    accepted: bool
    reason: str = ""
    cancelled_orders: int = 0  # unit: dimensionless
    cancelled_quotes: int = 0  # unit: dimensionless
    command_id: str = ""

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
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )
        if self.cancelled_orders < 0:
            raise MessageValidationError(
                f"cancelled_orders: {self.cancelled_orders!r} must be >= 0"
            )
        if self.cancelled_quotes < 0:
            raise MessageValidationError(
                f"cancelled_quotes: {self.cancelled_quotes!r} must be >= 0"
            )
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "KillSwitchAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
            cancelled_orders=int(p.get("cancelled_orders", 0)),
            cancelled_quotes=int(p.get("cancelled_quotes", 0)),
            command_id=str(p.get("command_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "accepted": self.accepted,
            "reason": self.reason,
            "cancelled_orders": self.cancelled_orders,
            "cancelled_quotes": self.cancelled_quotes,
        }
        if self.command_id:
            payload["command_id"] = self.command_id
        return payload


def topic_kill_switch_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"risk.kill_switch_ack.{gateway_id}"


def match_kill_switch_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _KILL_SWITCH_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_kill_switch_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = KillSwitchAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_kill_switch_ack(obj.gateway_id), obj.to_dict())


def make_kill_switch_ack_unchecked(
    *,
    gateway_id: str,
    accepted: bool,
    reason: str = "",
    cancelled_orders: int = 0,
    cancelled_quotes: int = 0,
    command_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_kill_switch_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "accepted": bool(accepted),
        "reason": str(reason),
        "cancelled_orders": int(cancelled_orders),
        "cancelled_quotes": int(cancelled_quotes),
    }
    if command_id:
        payload["command_id"] = str(command_id)
    return [
        topic_kill_switch_ack(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_kill_switch_ack(frames: list[bytes]) -> "KillSwitchAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_kill_switch_ack(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_KILL_SWITCH_ACK!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = KillSwitchAck.from_dict(payload)
    obj.validate()
    return obj


def describe_kill_switch_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _KILL_SWITCH_ACK_FIELDS


TOPIC_KILL_SWITCH_GATEWAY = "risk.kill_switch_gateway"
_TOPIC_KILL_SWITCH_GATEWAY_BYTES = "risk.kill_switch_gateway".encode()


_KILL_SWITCH_GATEWAY_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "The ADMIN caller; the ack is addressed to this id.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "target_gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Whose orders and quotes are cancelled.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "note",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 256},
    },
    {
        "name": "command_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class KillSwitchGateway:
    """ADMIN to engine: cancel every order and quote belonging to one named
    participant.

    The one message in this group where the caller and the affected gateway are allowed
    to differ. `gateway_id` is the ADMIN making the request - it is what the role and
    connection checks run against, and what addresses the ack - while
    `target_gateway_id` is whose exposure is cancelled. Two fields rather than one
    because they are two different participants, which is exactly what risk.kill_switch
    cannot express.
    """

    gateway_id: str
    target_gateway_id: str
    note: str = ""
    command_id: str = ""

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
        if len(self.target_gateway_id) > 32:
            raise MessageValidationError(
                f"target_gateway_id: length {len(self.target_gateway_id)} exceeds max_len 32"
            )
        if len(self.note) > 256:
            raise MessageValidationError(
                f"note: length {len(self.note)} exceeds max_len 256"
            )
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "KillSwitchGateway":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            target_gateway_id=str(p["target_gateway_id"]),
            note=str(p.get("note", "")),
            command_id=str(p.get("command_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "gateway_id": self.gateway_id,
            "target_gateway_id": self.target_gateway_id,
        }
        if self.note:
            payload["note"] = self.note
        if self.command_id:
            payload["command_id"] = self.command_id
        return payload


def is_kill_switch_gateway(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_KILL_SWITCH_GATEWAY


def make_kill_switch_gateway(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = KillSwitchGateway.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_KILL_SWITCH_GATEWAY, obj.to_dict())


def make_kill_switch_gateway_unchecked(
    *,
    gateway_id: str,
    target_gateway_id: str,
    note: str = "",
    command_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_kill_switch_gateway``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "gateway_id": str(gateway_id),
        "target_gateway_id": str(target_gateway_id),
    }
    if note:
        payload["note"] = str(note)
    if command_id:
        payload["command_id"] = str(command_id)
    return [
        _TOPIC_KILL_SWITCH_GATEWAY_BYTES,
        _msg.dumps(payload),
    ]


def parse_kill_switch_gateway(frames: list[bytes]) -> "KillSwitchGateway":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = KillSwitchGateway.from_dict(payload)
    obj.validate()
    return obj


def describe_kill_switch_gateway() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _KILL_SWITCH_GATEWAY_FIELDS


TOPIC_KILL_SWITCH_GATEWAY_ACK = "risk.kill_switch_gateway_ack.{gateway_id}"
PREFIX_KILL_SWITCH_GATEWAY_ACK = "risk.kill_switch_gateway_ack."
_KILL_SWITCH_GATEWAY_ACK_RE = re.compile(
    "risk\\.kill_switch_gateway_ack\\.(?P<gateway_id>[^.]+)"
)


_KILL_SWITCH_GATEWAY_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "target_gateway_id",
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
        "doc": "",
        "constraints": {"max_len": 512},
    },
    {
        "name": "cancelled_orders",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "cancelled_quotes",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "command_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class KillSwitchGatewayAck:
    """Engine to ADMIN: what the gateway-targeted kill switch cancelled.

    `target_gateway_id` is echoed in the body, unlike `gateway_id`, which the topic
    already carries. The two are different participants here, so an ack naming only the
    topic's id would not say who was actually acted on.
    """

    gateway_id: str
    accepted: bool
    target_gateway_id: str = ""
    reason: str = ""
    cancelled_orders: int = 0  # unit: dimensionless
    cancelled_quotes: int = 0  # unit: dimensionless
    command_id: str = ""

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
        if len(self.target_gateway_id) > 32:
            raise MessageValidationError(
                f"target_gateway_id: length {len(self.target_gateway_id)} exceeds max_len 32"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )
        if self.cancelled_orders < 0:
            raise MessageValidationError(
                f"cancelled_orders: {self.cancelled_orders!r} must be >= 0"
            )
        if self.cancelled_quotes < 0:
            raise MessageValidationError(
                f"cancelled_quotes: {self.cancelled_quotes!r} must be >= 0"
            )
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "KillSwitchGatewayAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            accepted=bool(p["accepted"]),
            target_gateway_id=str(p.get("target_gateway_id", "")),
            reason=str(p.get("reason", "")),
            cancelled_orders=int(p.get("cancelled_orders", 0)),
            cancelled_quotes=int(p.get("cancelled_quotes", 0)),
            command_id=str(p.get("command_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "accepted": self.accepted,
            "target_gateway_id": self.target_gateway_id,
            "reason": self.reason,
            "cancelled_orders": self.cancelled_orders,
            "cancelled_quotes": self.cancelled_quotes,
        }
        if self.command_id:
            payload["command_id"] = self.command_id
        return payload


def topic_kill_switch_gateway_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"risk.kill_switch_gateway_ack.{gateway_id}"


def match_kill_switch_gateway_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _KILL_SWITCH_GATEWAY_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_kill_switch_gateway_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = KillSwitchGatewayAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_kill_switch_gateway_ack(obj.gateway_id), obj.to_dict())


def make_kill_switch_gateway_ack_unchecked(
    *,
    gateway_id: str,
    accepted: bool,
    target_gateway_id: str = "",
    reason: str = "",
    cancelled_orders: int = 0,
    cancelled_quotes: int = 0,
    command_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_kill_switch_gateway_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "accepted": bool(accepted),
        "target_gateway_id": str(target_gateway_id),
        "reason": str(reason),
        "cancelled_orders": int(cancelled_orders),
        "cancelled_quotes": int(cancelled_quotes),
    }
    if command_id:
        payload["command_id"] = str(command_id)
    return [
        topic_kill_switch_gateway_ack(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_kill_switch_gateway_ack(frames: list[bytes]) -> "KillSwitchGatewayAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_kill_switch_gateway_ack(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_KILL_SWITCH_GATEWAY_ACK!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = KillSwitchGatewayAck.from_dict(payload)
    obj.validate()
    return obj


def describe_kill_switch_gateway_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _KILL_SWITCH_GATEWAY_ACK_FIELDS


TOPIC_KILL_SWITCH_GLOBAL = "risk.kill_switch_global"
_TOPIC_KILL_SWITCH_GLOBAL_BYTES = "risk.kill_switch_global".encode()


_KILL_SWITCH_GLOBAL_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "The ADMIN caller; the ack is addressed to this id.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "note",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 256},
    },
    {
        "name": "command_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class KillSwitchGlobal:
    """ADMIN to engine: cancel every resting order and quote, for every gateway. The
    full-market emergency stop.

    Distinct from risk.circuit_breaker_halt_all, which halts trading but leaves resting
    orders in place. This one cancels them outright, and does not halt anything - a
    gateway may submit again immediately.
    """

    gateway_id: str
    note: str = ""
    command_id: str = ""

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
        if len(self.note) > 256:
            raise MessageValidationError(
                f"note: length {len(self.note)} exceeds max_len 256"
            )
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "KillSwitchGlobal":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            note=str(p.get("note", "")),
            command_id=str(p.get("command_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "gateway_id": self.gateway_id,
        }
        if self.note:
            payload["note"] = self.note
        if self.command_id:
            payload["command_id"] = self.command_id
        return payload


def is_kill_switch_global(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_KILL_SWITCH_GLOBAL


def make_kill_switch_global(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = KillSwitchGlobal.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_KILL_SWITCH_GLOBAL, obj.to_dict())


def make_kill_switch_global_unchecked(
    *,
    gateway_id: str,
    note: str = "",
    command_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_kill_switch_global``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "gateway_id": str(gateway_id),
    }
    if note:
        payload["note"] = str(note)
    if command_id:
        payload["command_id"] = str(command_id)
    return [
        _TOPIC_KILL_SWITCH_GLOBAL_BYTES,
        _msg.dumps(payload),
    ]


def parse_kill_switch_global(frames: list[bytes]) -> "KillSwitchGlobal":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = KillSwitchGlobal.from_dict(payload)
    obj.validate()
    return obj


def describe_kill_switch_global() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _KILL_SWITCH_GLOBAL_FIELDS


TOPIC_KILL_SWITCH_GLOBAL_ACK = "risk.kill_switch_global_ack.{gateway_id}"
PREFIX_KILL_SWITCH_GLOBAL_ACK = "risk.kill_switch_global_ack."
_KILL_SWITCH_GLOBAL_ACK_RE = re.compile(
    "risk\\.kill_switch_global_ack\\.(?P<gateway_id>[^.]+)"
)


_KILL_SWITCH_GLOBAL_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
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
        "name": "cancelled_orders",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "cancelled_quotes",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "affected_gateways",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "command_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class KillSwitchGlobalAck:
    """Engine to ADMIN: what the market-wide kill switch cancelled.

    `affected_gateways` is what distinguishes this ack from the other two: the same two
    counters, plus how many participants they were spread across.
    """

    gateway_id: str
    accepted: bool
    reason: str = ""
    cancelled_orders: int = 0  # unit: dimensionless
    cancelled_quotes: int = 0  # unit: dimensionless
    affected_gateways: int = 0  # unit: dimensionless
    command_id: str = ""

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
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )
        if self.cancelled_orders < 0:
            raise MessageValidationError(
                f"cancelled_orders: {self.cancelled_orders!r} must be >= 0"
            )
        if self.cancelled_quotes < 0:
            raise MessageValidationError(
                f"cancelled_quotes: {self.cancelled_quotes!r} must be >= 0"
            )
        if self.affected_gateways < 0:
            raise MessageValidationError(
                f"affected_gateways: {self.affected_gateways!r} must be >= 0"
            )
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "KillSwitchGlobalAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
            cancelled_orders=int(p.get("cancelled_orders", 0)),
            cancelled_quotes=int(p.get("cancelled_quotes", 0)),
            affected_gateways=int(p.get("affected_gateways", 0)),
            command_id=str(p.get("command_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "accepted": self.accepted,
            "reason": self.reason,
            "cancelled_orders": self.cancelled_orders,
            "cancelled_quotes": self.cancelled_quotes,
            "affected_gateways": self.affected_gateways,
        }
        if self.command_id:
            payload["command_id"] = self.command_id
        return payload


def topic_kill_switch_global_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"risk.kill_switch_global_ack.{gateway_id}"


def match_kill_switch_global_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _KILL_SWITCH_GLOBAL_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_kill_switch_global_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = KillSwitchGlobalAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_kill_switch_global_ack(obj.gateway_id), obj.to_dict())


def make_kill_switch_global_ack_unchecked(
    *,
    gateway_id: str,
    accepted: bool,
    reason: str = "",
    cancelled_orders: int = 0,
    cancelled_quotes: int = 0,
    affected_gateways: int = 0,
    command_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_kill_switch_global_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "accepted": bool(accepted),
        "reason": str(reason),
        "cancelled_orders": int(cancelled_orders),
        "cancelled_quotes": int(cancelled_quotes),
        "affected_gateways": int(affected_gateways),
    }
    if command_id:
        payload["command_id"] = str(command_id)
    return [
        topic_kill_switch_global_ack(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_kill_switch_global_ack(frames: list[bytes]) -> "KillSwitchGlobalAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_kill_switch_global_ack(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_KILL_SWITCH_GLOBAL_ACK!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = KillSwitchGlobalAck.from_dict(payload)
    obj.validate()
    return obj


def describe_kill_switch_global_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _KILL_SWITCH_GLOBAL_ACK_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_KILL_SWITCH,
    TOPIC_KILL_SWITCH_ACK,
    TOPIC_KILL_SWITCH_GATEWAY,
    TOPIC_KILL_SWITCH_GATEWAY_ACK,
    TOPIC_KILL_SWITCH_GLOBAL,
    TOPIC_KILL_SWITCH_GLOBAL_ACK,
)
