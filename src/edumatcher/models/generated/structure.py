# GENERATED FROM spec/messages/structure.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``structure`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/structure.yaml``;
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

FAMILY = "structure"
FAMILY_VERSION = 1


TOPIC_COMBO_ACK = "combo.ack.{gateway_id}"
PREFIX_COMBO_ACK = "combo.ack."
_COMBO_ACK_RE = re.compile("combo\\.ack\\.(?P<gateway_id>[^.]+)")


_COMBO_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "combo_id",
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
        "doc": "",
        "constraints": {"max_len": 512},
    },
)


@dataclass(frozen=True, slots=True)
class ComboAck:
    """Engine to gateway: a combo submission was accepted or rejected.

    Three scalars. It carried a full ComboOrder.to_dict() state dump until the
    submission, event and persistence shapes were separated in 5.1c - and no consumer
    had ever read it: alf_console, alf_gwy, pm-stats and the api_gateway event stream
    all take only these three. Design section 15.4 records that removal.
    """

    gateway_id: str
    combo_id: str
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
        if len(self.combo_id) > 64:
            raise MessageValidationError(
                f"combo_id: length {len(self.combo_id)} exceeds max_len 64"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ComboAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            combo_id=str(p["combo_id"]),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "combo_id": self.combo_id,
            "accepted": self.accepted,
            "reason": self.reason,
        }


def topic_combo_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"combo.ack.{gateway_id}"


def match_combo_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _COMBO_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_combo_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = ComboAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_combo_ack(obj.gateway_id), obj.to_dict())


def make_combo_ack_unchecked(
    *,
    gateway_id: str,
    combo_id: str,
    accepted: bool,
    reason: str = "",
) -> list[bytes]:
    """Identical frames to ``make_combo_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_combo_ack(gateway_id).encode(),
        _msg.dumps(
            {
                "combo_id": str(combo_id),
                "accepted": bool(accepted),
                "reason": str(reason),
            }
        ),
    ]


def parse_combo_ack(frames: list[bytes]) -> "ComboAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_combo_ack(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_COMBO_ACK!r}")
    payload = {**payload, "gateway_id": matched}
    obj = ComboAck.from_dict(payload)
    obj.validate()
    return obj


def describe_combo_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _COMBO_ACK_FIELDS


TOPIC_COMBO_STATUS = "combo.status.{gateway_id}"
PREFIX_COMBO_STATUS = "combo.status."
_COMBO_STATUS_RE = re.compile("combo\\.status\\.(?P<gateway_id>[^.]+)")
_COMBO_STATUS_STATUS_VALUES = (
    "PENDING",
    "PARTIALLY_MATCHED",
    "MATCHED",
    "FAILED",
    "CANCELLED",
    "REJECTED",
)
ComboStatusStatus = Literal[
    "PENDING",
    "PARTIALLY_MATCHED",
    "MATCHED",
    "FAILED",
    "CANCELLED",
    "REJECTED",
]


_COMBO_STATUS_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "combo_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "status",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "Mirrors models/combo.py::ComboStatus.",
        "values": _COMBO_STATUS_STATUS_VALUES,
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Why a terminal status was reached; absent on the happy path.",
        "constraints": {"max_len": 512},
    },
)


@dataclass(frozen=True, slots=True)
class ComboStatus:
    """Engine to gateway: a combo moved to a new lifecycle state.

    PENDING is never published - it is the state a combo is created in, so the first
    event a client sees is always a transition out of it. `reason` replaced a `details`
    map carrying exactly one key, always "reason", which both consumers unwrapped on
    arrival. It is omitted when empty, which is what the map's `if reason else None`
    guard did.
    """

    gateway_id: str
    combo_id: str
    status: ComboStatusStatus
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
        if len(self.combo_id) > 64:
            raise MessageValidationError(
                f"combo_id: length {len(self.combo_id)} exceeds max_len 64"
            )
        if self.status not in _COMBO_STATUS_STATUS_VALUES:
            raise MessageValidationError(
                f"status: {self.status!r} is not one of {_COMBO_STATUS_STATUS_VALUES!r}"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ComboStatus":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            combo_id=str(p["combo_id"]),
            status=cast(ComboStatusStatus, str(p["status"])),
            reason=str(p.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "combo_id": self.combo_id,
            "status": self.status,
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


def topic_combo_status(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"combo.status.{gateway_id}"


def match_combo_status(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _COMBO_STATUS_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_combo_status(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = ComboStatus.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_combo_status(obj.gateway_id), obj.to_dict())


def make_combo_status_unchecked(
    *,
    gateway_id: str,
    combo_id: str,
    status: ComboStatusStatus,
    reason: str = "",
) -> list[bytes]:
    """Identical frames to ``make_combo_status``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "combo_id": str(combo_id),
        "status": str(status),
    }
    if reason:
        payload["reason"] = str(reason)
    return [
        topic_combo_status(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_combo_status(frames: list[bytes]) -> "ComboStatus":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_combo_status(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_COMBO_STATUS!r}")
    payload = {**payload, "gateway_id": matched}
    obj = ComboStatus.from_dict(payload)
    obj.validate()
    return obj


def describe_combo_status() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _COMBO_STATUS_FIELDS


TOPIC_OCO_ACK = "oco.ack.{gateway_id}"
PREFIX_OCO_ACK = "oco.ack."
_OCO_ACK_RE = re.compile("oco\\.ack\\.(?P<gateway_id>[^.]+)")


_OCO_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "oco_id",
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
        "doc": "",
        "constraints": {"max_len": 512},
    },
    {
        "name": "order_id_1",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "The first leg's engine order id.",
        "constraints": {"max_len": 64},
    },
    {
        "name": "order_id_2",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "The second leg's engine order id.",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class OcoAck:
    """Engine to gateway: an OCO pair was accepted or rejected.

    The two order ids are always emitted, as "" on rejection: the hand-written builder
    put them in the base payload rather than under a guard, and a rejected pair has no
    orders to name. They are what lets a client tie the pair to the two single-order
    acks that follow.
    """

    gateway_id: str
    oco_id: str
    accepted: bool
    reason: str = ""
    order_id_1: str = ""
    order_id_2: str = ""

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
        if len(self.oco_id) > 64:
            raise MessageValidationError(
                f"oco_id: length {len(self.oco_id)} exceeds max_len 64"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )
        if len(self.order_id_1) > 64:
            raise MessageValidationError(
                f"order_id_1: length {len(self.order_id_1)} exceeds max_len 64"
            )
        if len(self.order_id_2) > 64:
            raise MessageValidationError(
                f"order_id_2: length {len(self.order_id_2)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OcoAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            oco_id=str(p["oco_id"]),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
            order_id_1=str(p.get("order_id_1", "")),
            order_id_2=str(p.get("order_id_2", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "oco_id": self.oco_id,
            "accepted": self.accepted,
            "reason": self.reason,
            "order_id_1": self.order_id_1,
            "order_id_2": self.order_id_2,
        }


def topic_oco_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"oco.ack.{gateway_id}"


def match_oco_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _OCO_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_oco_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OcoAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_oco_ack(obj.gateway_id), obj.to_dict())


def make_oco_ack_unchecked(
    *,
    gateway_id: str,
    oco_id: str,
    accepted: bool,
    reason: str = "",
    order_id_1: str = "",
    order_id_2: str = "",
) -> list[bytes]:
    """Identical frames to ``make_oco_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_oco_ack(gateway_id).encode(),
        _msg.dumps(
            {
                "oco_id": str(oco_id),
                "accepted": bool(accepted),
                "reason": str(reason),
                "order_id_1": str(order_id_1),
                "order_id_2": str(order_id_2),
            }
        ),
    ]


def parse_oco_ack(frames: list[bytes]) -> "OcoAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_oco_ack(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_OCO_ACK!r}")
    payload = {**payload, "gateway_id": matched}
    obj = OcoAck.from_dict(payload)
    obj.validate()
    return obj


def describe_oco_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _OCO_ACK_FIELDS


TOPIC_OCO_CANCELLED = "oco.cancelled.{gateway_id}"
PREFIX_OCO_CANCELLED = "oco.cancelled."
_OCO_CANCELLED_RE = re.compile("oco\\.cancelled\\.(?P<gateway_id>[^.]+)")


_OCO_CANCELLED_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "oco_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "cancelled_order_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
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
class OcoCancelled:
    """Engine to gateway: one leg of an OCO pair was cancelled because the other was
    actioned.

    Distinct from order.cancelled, which says an order is gone. This says *why* - the
    sibling filled or was cancelled - and names the pair, which an order-level event
    cannot.
    """

    gateway_id: str
    oco_id: str
    cancelled_order_id: str
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
        if len(self.oco_id) > 64:
            raise MessageValidationError(
                f"oco_id: length {len(self.oco_id)} exceeds max_len 64"
            )
        if len(self.cancelled_order_id) > 64:
            raise MessageValidationError(
                f"cancelled_order_id: length {len(self.cancelled_order_id)} exceeds max_len 64"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OcoCancelled":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            oco_id=str(p["oco_id"]),
            cancelled_order_id=str(p["cancelled_order_id"]),
            reason=str(p.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "oco_id": self.oco_id,
            "cancelled_order_id": self.cancelled_order_id,
            "reason": self.reason,
        }


def topic_oco_cancelled(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"oco.cancelled.{gateway_id}"


def match_oco_cancelled(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _OCO_CANCELLED_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_oco_cancelled(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = OcoCancelled.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_oco_cancelled(obj.gateway_id), obj.to_dict())


def make_oco_cancelled_unchecked(
    *,
    gateway_id: str,
    oco_id: str,
    cancelled_order_id: str,
    reason: str = "",
) -> list[bytes]:
    """Identical frames to ``make_oco_cancelled``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_oco_cancelled(gateway_id).encode(),
        _msg.dumps(
            {
                "oco_id": str(oco_id),
                "cancelled_order_id": str(cancelled_order_id),
                "reason": str(reason),
            }
        ),
    ]


def parse_oco_cancelled(frames: list[bytes]) -> "OcoCancelled":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_oco_cancelled(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_OCO_CANCELLED!r}")
    payload = {**payload, "gateway_id": matched}
    obj = OcoCancelled.from_dict(payload)
    obj.validate()
    return obj


def describe_oco_cancelled() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _OCO_CANCELLED_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_COMBO_ACK,
    TOPIC_COMBO_STATUS,
    TOPIC_OCO_ACK,
    TOPIC_OCO_CANCELLED,
)
