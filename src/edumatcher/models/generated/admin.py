# GENERATED FROM spec/messages/admin.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``admin`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/admin.yaml``; edit
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

FAMILY = "admin"
FAMILY_VERSION = 1


@dataclass(frozen=True, slots=True)
class AdminActionScope:
    """What one admin command acted on, and what it did. Every field is optional
    because every action uses a different subset -- see the family header on why
    that is a stated limitation rather than a variant type. The name is inherited
    from the wire key rather than chosen: three of the seven fields are outcome
    counts rather than scope, which makes "AdminActionScope" a slightly generous
    reading of its own contents. It was kept because renaming the key is a wire
    change for every `/admin/monitor` client and buys nothing a reader can use.
    """

    symbol: str | None = None
    target_gateway_id: str | None = None
    level: str | None = None
    note: str = ""
    cancelled_orders: int | None = None  # unit: dimensionless
    cancelled_quotes: int | None = None  # unit: dimensionless
    affected_gateways: int | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.symbol is not None:
            if len(self.symbol) > 16:
                raise MessageValidationError(
                    f"symbol: length {len(self.symbol)} exceeds max_len 16"
                )
        if self.target_gateway_id is not None:
            if len(self.target_gateway_id) > 32:
                raise MessageValidationError(
                    f"target_gateway_id: length {len(self.target_gateway_id)} exceeds max_len 32"
                )
        if self.level is not None:
            if len(self.level) > 32:
                raise MessageValidationError(
                    f"level: length {len(self.level)} exceeds max_len 32"
                )
        if len(self.note) > 256:
            raise MessageValidationError(
                f"note: length {len(self.note)} exceeds max_len 256"
            )
        if self.cancelled_orders is not None:
            if self.cancelled_orders < 0:
                raise MessageValidationError(
                    f"cancelled_orders: {self.cancelled_orders!r} must be >= 0"
                )
        if self.cancelled_quotes is not None:
            if self.cancelled_quotes < 0:
                raise MessageValidationError(
                    f"cancelled_quotes: {self.cancelled_quotes!r} must be >= 0"
                )
        if self.affected_gateways is not None:
            if self.affected_gateways < 0:
                raise MessageValidationError(
                    f"affected_gateways: {self.affected_gateways!r} must be >= 0"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "AdminActionScope":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=None if p.get("symbol") is None else str(p["symbol"]),
            target_gateway_id=(
                None
                if p.get("target_gateway_id") is None
                else str(p["target_gateway_id"])
            ),
            level=None if p.get("level") is None else str(p["level"]),
            note=str(p.get("note", "")),
            cancelled_orders=(
                None
                if p.get("cancelled_orders") is None
                else int(p["cancelled_orders"])
            ),
            cancelled_quotes=(
                None
                if p.get("cancelled_quotes") is None
                else int(p["cancelled_quotes"])
            ),
            affected_gateways=(
                None
                if p.get("affected_gateways") is None
                else int(p["affected_gateways"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {}
        if self.symbol is not None:
            payload["symbol"] = self.symbol
        if self.target_gateway_id is not None:
            payload["target_gateway_id"] = self.target_gateway_id
        if self.level is not None:
            payload["level"] = self.level
        if self.note:
            payload["note"] = self.note
        if self.cancelled_orders is not None:
            payload["cancelled_orders"] = self.cancelled_orders
        if self.cancelled_quotes is not None:
            payload["cancelled_quotes"] = self.cancelled_quotes
        if self.affected_gateways is not None:
            payload["affected_gateways"] = self.affected_gateways
        return payload


TOPIC_ADMIN_ACTION = "admin.action.{gateway_id}"
PREFIX_ADMIN_ACTION = "admin.action."
_ADMIN_ACTION_RE = re.compile("admin\\.action\\.(?P<gateway_id>[^.]+)")
_ADMIN_ACTION_ACTION_VALUES = (
    "kill_switch.self",
    "kill_switch.gateway",
    "kill_switch.global",
    "kill_switch.symbol",
    "circuit_breaker.trigger",
    "circuit_breaker.resume",
)
AdminActionAction = Literal[
    "kill_switch.self",
    "kill_switch.gateway",
    "kill_switch.global",
    "kill_switch.symbol",
    "circuit_breaker.trigger",
    "circuit_breaker.resume",
]


_ADMIN_ACTION_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "The ADMIN caller. Topic-only; the body says the same thing as `initiator_gateway_id`.",
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
        "name": "initiator_gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "action",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "Which command ran. The six the engine publishes, enumerated rather than left a free string: a seventh admin command that forgets to declare itself here fails loudly at its first invocation, which is better than appearing in the monitor as a value no client renders. The values look like topics and are not: `circuit_breaker.trigger` is the action behind `risk.symbol_halt`, and there is no `circuit_breaker.trigger` topic anywhere.",
        "values": _ADMIN_ACTION_ACTION_VALUES,
    },
    {
        "name": "scope",
        "type": "nested",
        "unit": None,
        "required": True,
        "doc": "",
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
        "doc": 'Why it was rejected; "" on an accepted action.',
        "constraints": {"max_len": 512},
    },
)


@dataclass(frozen=True, slots=True)
class AdminAction:
    """Engine to the admin monitor: one admin-gated command ran, who ran it, what it
    acted on, and whether it was accepted.

    This is the one topic in the system addressed to a gateway that is **not** for that
    gateway. The suffix names the ADMIN caller so a monitor can filter by operator, but
    the event must never reach that caller's own private trading stream --
    `EngineClient._handle_event` checks the prefix before the private/market-data split
    for exactly that reason, and `ADMIN_ACTION_PREFIX` is deliberately absent from
    `PRIVATE_PREFIXES`. `initiator_gateway_id` repeats the topic suffix in the body.
    That is redundant on the live wire and load-bearing off it: an event stored,
    forwarded or rendered without its topic still says who ran the command. Publishing
    is a no-op without a `command_id` — with nothing to correlate against, a monitor
    record is an entry no client can tie to a request.
    """

    gateway_id: str
    command_id: str
    initiator_gateway_id: str
    action: AdminActionAction
    scope: AdminActionScope
    accepted: bool
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
        if len(self.initiator_gateway_id) > 32:
            raise MessageValidationError(
                f"initiator_gateway_id: length {len(self.initiator_gateway_id)} exceeds max_len 32"
            )
        if self.action not in _ADMIN_ACTION_ACTION_VALUES:
            raise MessageValidationError(
                f"action: {self.action!r} is not one of {_ADMIN_ACTION_ACTION_VALUES!r}"
            )
        self.scope.validate()
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "AdminAction":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            command_id=str(p["command_id"]),
            initiator_gateway_id=str(p["initiator_gateway_id"]),
            action=cast(AdminActionAction, str(p["action"])),
            scope=AdminActionScope.from_dict(p["scope"]),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "command_id": self.command_id,
            "initiator_gateway_id": self.initiator_gateway_id,
            "action": self.action,
            "scope": self.scope.to_dict(),
            "accepted": self.accepted,
            "reason": self.reason,
        }


def topic_admin_action(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"admin.action.{gateway_id}"


def match_admin_action(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _ADMIN_ACTION_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_admin_action(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = AdminAction.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_admin_action(obj.gateway_id), obj.to_dict())


def parse_admin_action(frames: list[bytes]) -> "AdminAction":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_admin_action(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_ADMIN_ACTION!r}")
    payload = {**payload, "gateway_id": matched}
    obj = AdminAction.from_dict(payload)
    obj.validate()
    return obj


def describe_admin_action() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _ADMIN_ACTION_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (TOPIC_ADMIN_ACTION,)
