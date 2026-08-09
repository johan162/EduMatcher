# GENERATED FROM spec/messages/log.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``log`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/log.yaml``; edit the
spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
docs/developer/06-msgen.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, cast

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "log"
FAMILY_VERSION = 1


@dataclass(frozen=True, slots=True)
class LogFilter:
    """A row predicate, applied two ways by the server: evaluated in Python against a
    freshly persisted row on the live path, and compiled to a parameterised SQL
    WHERE clause for backfill. One definition with two evaluators is what
    guarantees a subscriber's backfill and its subsequent live stream contain the
    same kind of rows - a mismatch would show up as rows appearing or vanishing at
    the seam. Every field is optional; an empty filter matches everything.
    """

    min_level: str | None = None
    processes: list[str] = field(default_factory=list)
    loggers: list[str] = field(default_factory=list)
    sessions: list[str] = field(default_factory=list)
    contains: str | None = None
    exceptions_only: bool = False

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.min_level is not None:
            if len(self.min_level) > 16:
                raise MessageValidationError(
                    f"min_level: length {len(self.min_level)} exceeds max_len 16"
                )
        if self.contains is not None:
            if len(self.contains) > 256:
                raise MessageValidationError(
                    f"contains: length {len(self.contains)} exceeds max_len 256"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogFilter":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            min_level=None if p.get("min_level") is None else str(p["min_level"]),
            processes=[str(item) for item in p.get("processes", [])],
            loggers=[str(item) for item in p.get("loggers", [])],
            sessions=[str(item) for item in p.get("sessions", [])],
            contains=None if p.get("contains") is None else str(p["contains"]),
            exceptions_only=bool(p.get("exceptions_only", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "processes": self.processes,
            "loggers": self.loggers,
            "sessions": self.sessions,
            "exceptions_only": self.exceptions_only,
        }
        if self.min_level is not None:
            payload["min_level"] = self.min_level
        if self.contains is not None:
            payload["contains"] = self.contains
        return payload


TOPIC_LOG_SUBSCRIBE = "log.subscribe"
_TOPIC_LOG_SUBSCRIBE_BYTES = "log.subscribe".encode()
_LOG_SUBSCRIBE_MODE_VALUES = ("STREAM", "NOTIFY")
LogSubscribeMode = Literal["STREAM", "NOTIFY"]


_LOG_SUBSCRIBE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "mode",
        "type": "enum",
        "unit": None,
        "required": False,
        "doc": "STREAM pushes every row; NOTIFY pushes periodic counts.",
        "values": _LOG_SUBSCRIBE_MODE_VALUES,
    },
    {
        "name": "filter",
        "type": "nested",
        "unit": None,
        "required": False,
        "doc": "",
    },
    {
        "name": "backfill_minutes",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "Replay this many minutes before the live stream starts.",
    },
    {
        "name": "lease_sec",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "How long the subscription survives without a renew.",
    },
    {
        "name": "notify_interval_ms",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class LogSubscribe:
    """Subscriber to pm-log-srv: open or replace a leased stream.

    Everything past sub_id and mode is omitted when unset rather than sent as a default,
    which is what the hand-written builder did - the server applies its own defaults and
    cannot tell an omitted lease_sec from one that happens to equal the default.
    """

    sub_id: str
    mode: LogSubscribeMode = "STREAM"
    filter: LogFilter | None = None
    backfill_minutes: int | None = None  # unit: dimensionless
    lease_sec: int | None = None  # unit: dimensionless
    notify_interval_ms: int | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.sub_id) > 64:
            raise MessageValidationError(
                f"sub_id: length {len(self.sub_id)} exceeds max_len 64"
            )
        if self.mode not in _LOG_SUBSCRIBE_MODE_VALUES:
            raise MessageValidationError(
                f"mode: {self.mode!r} is not one of {_LOG_SUBSCRIBE_MODE_VALUES!r}"
            )
        if self.filter is not None:
            self.filter.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogSubscribe":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sub_id=str(p["sub_id"]),
            mode=cast(LogSubscribeMode, str(p.get("mode", "STREAM"))),
            filter=(
                None if p.get("filter") is None else LogFilter.from_dict(p["filter"])
            ),
            backfill_minutes=(
                None
                if p.get("backfill_minutes") is None
                else int(p["backfill_minutes"])
            ),
            lease_sec=None if p.get("lease_sec") is None else int(p["lease_sec"]),
            notify_interval_ms=(
                None
                if p.get("notify_interval_ms") is None
                else int(p["notify_interval_ms"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "sub_id": self.sub_id,
            "mode": self.mode,
        }
        if self.filter is not None:
            payload["filter"] = self.filter.to_dict()
        if self.backfill_minutes is not None:
            payload["backfill_minutes"] = self.backfill_minutes
        if self.lease_sec is not None:
            payload["lease_sec"] = self.lease_sec
        if self.notify_interval_ms is not None:
            payload["notify_interval_ms"] = self.notify_interval_ms
        return payload


def is_log_subscribe(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_LOG_SUBSCRIBE


def make_log_subscribe(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogSubscribe.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_LOG_SUBSCRIBE, obj.to_dict())


def parse_log_subscribe(frames: list[bytes]) -> "LogSubscribe":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = LogSubscribe.from_dict(payload)
    obj.validate()
    return obj


def describe_log_subscribe() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_SUBSCRIBE_FIELDS


TOPIC_LOG_RENEW = "log.renew"
_TOPIC_LOG_RENEW_BYTES = "log.renew".encode()


_LOG_RENEW_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "timestamp",
        "type": "float",
        "unit": "epoch_seconds",
        "required": True,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class LogRenew:
    """Lease keepalive. The liveness signal: a subscriber that stops renewing is
    dropped, which is how the server reclaims a viewer that went away without
    unsubscribing.
    """

    sub_id: str
    timestamp: float  # unit: epoch_seconds

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.sub_id) > 64:
            raise MessageValidationError(
                f"sub_id: length {len(self.sub_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogRenew":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sub_id=str(p["sub_id"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "sub_id": self.sub_id,
            "timestamp": self.timestamp,
        }


def is_log_renew(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_LOG_RENEW


def make_log_renew(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogRenew.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_LOG_RENEW, obj.to_dict())


def make_log_renew_unchecked(
    *,
    sub_id: str,
    timestamp: float,
) -> list[bytes]:
    """Identical frames to ``make_log_renew``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_LOG_RENEW_BYTES,
        _msg.dumps(
            {
                "sub_id": str(sub_id),
                "timestamp": float(timestamp),
            }
        ),
    ]


def parse_log_renew(frames: list[bytes]) -> "LogRenew":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = LogRenew.from_dict(payload)
    obj.validate()
    return obj


def describe_log_renew() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_RENEW_FIELDS


TOPIC_LOG_UNSUBSCRIBE = "log.unsubscribe"
_TOPIC_LOG_UNSUBSCRIBE_BYTES = "log.unsubscribe".encode()


_LOG_UNSUBSCRIBE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "timestamp",
        "type": "float",
        "unit": "epoch_seconds",
        "required": True,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class LogUnsubscribe:
    """Close a subscription immediately rather than letting it lapse."""

    sub_id: str
    timestamp: float  # unit: epoch_seconds

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.sub_id) > 64:
            raise MessageValidationError(
                f"sub_id: length {len(self.sub_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogUnsubscribe":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sub_id=str(p["sub_id"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "sub_id": self.sub_id,
            "timestamp": self.timestamp,
        }


def is_log_unsubscribe(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_LOG_UNSUBSCRIBE


def make_log_unsubscribe(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogUnsubscribe.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_LOG_UNSUBSCRIBE, obj.to_dict())


def make_log_unsubscribe_unchecked(
    *,
    sub_id: str,
    timestamp: float,
) -> list[bytes]:
    """Identical frames to ``make_log_unsubscribe``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_LOG_UNSUBSCRIBE_BYTES,
        _msg.dumps(
            {
                "sub_id": str(sub_id),
                "timestamp": float(timestamp),
            }
        ),
    ]


def parse_log_unsubscribe(frames: list[bytes]) -> "LogUnsubscribe":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = LogUnsubscribe.from_dict(payload)
    obj.validate()
    return obj


def describe_log_unsubscribe() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_UNSUBSCRIBE_FIELDS


TOPIC_LOG_BACKFILL_REQUEST = "log.backfill_request"
_TOPIC_LOG_BACKFILL_REQUEST_BYTES = "log.backfill_request".encode()


_LOG_BACKFILL_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "minutes",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
        "constraints": {"gt": 0},
    },
    {
        "name": "filter",
        "type": "nested",
        "unit": None,
        "required": False,
        "doc": "Defaults to the subscription's own filter when omitted.",
    },
    {
        "name": "max_rows",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class LogBackfillRequest:
    """Replay the last N minutes of history for one subscription."""

    sub_id: str
    minutes: int  # unit: dimensionless
    filter: LogFilter | None = None
    max_rows: int | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.sub_id) > 64:
            raise MessageValidationError(
                f"sub_id: length {len(self.sub_id)} exceeds max_len 64"
            )
        if self.minutes <= 0:
            raise MessageValidationError(f"minutes: {self.minutes!r} must be > 0")
        if self.filter is not None:
            self.filter.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogBackfillRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sub_id=str(p["sub_id"]),
            minutes=int(p["minutes"]),
            filter=(
                None if p.get("filter") is None else LogFilter.from_dict(p["filter"])
            ),
            max_rows=None if p.get("max_rows") is None else int(p["max_rows"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "sub_id": self.sub_id,
            "minutes": self.minutes,
        }
        if self.filter is not None:
            payload["filter"] = self.filter.to_dict()
        if self.max_rows is not None:
            payload["max_rows"] = self.max_rows
        return payload


def is_log_backfill_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_LOG_BACKFILL_REQUEST


def make_log_backfill_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogBackfillRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_LOG_BACKFILL_REQUEST, obj.to_dict())


def parse_log_backfill_request(frames: list[bytes]) -> "LogBackfillRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = LogBackfillRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_log_backfill_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_BACKFILL_REQUEST_FIELDS


TOPIC_LOG_STATUS_REQUEST = "log.status_request"
_TOPIC_LOG_STATUS_REQUEST_BYTES = "log.status_request".encode()


_LOG_STATUS_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "timestamp",
        "type": "float",
        "unit": "epoch_seconds",
        "required": True,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class LogStatusRequest:
    """Ask for subscription and server diagnostics."""

    sub_id: str
    timestamp: float  # unit: epoch_seconds

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.sub_id) > 64:
            raise MessageValidationError(
                f"sub_id: length {len(self.sub_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogStatusRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sub_id=str(p["sub_id"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "sub_id": self.sub_id,
            "timestamp": self.timestamp,
        }


def is_log_status_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_LOG_STATUS_REQUEST


def make_log_status_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogStatusRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_LOG_STATUS_REQUEST, obj.to_dict())


def make_log_status_request_unchecked(
    *,
    sub_id: str,
    timestamp: float,
) -> list[bytes]:
    """Identical frames to ``make_log_status_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_LOG_STATUS_REQUEST_BYTES,
        _msg.dumps(
            {
                "sub_id": str(sub_id),
                "timestamp": float(timestamp),
            }
        ),
    ]


def parse_log_status_request(frames: list[bytes]) -> "LogStatusRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = LogStatusRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_log_status_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_STATUS_REQUEST_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_LOG_SUBSCRIBE,
    TOPIC_LOG_RENEW,
    TOPIC_LOG_UNSUBSCRIBE,
    TOPIC_LOG_BACKFILL_REQUEST,
    TOPIC_LOG_STATUS_REQUEST,
)
