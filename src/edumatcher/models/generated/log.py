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

import re
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


@dataclass(frozen=True, slots=True)
class LevelCount:
    """How many rows of one level a NOTIFY subscription has buffered. This was a map
    on the wire - {"INFO": 3, "ERROR": 1} - which the IDL excludes deliberately
    (design section 15.4). The key was a value, and a list of records says so: the
    level is a field, not a key.
    """

    level: str
    count: int  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.level) > 16:
            raise MessageValidationError(
                f"level: length {len(self.level)} exceeds max_len 16"
            )
        if self.count < 0:
            raise MessageValidationError(f"count: {self.count!r} must be >= 0")

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LevelCount":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            level=str(p["level"]),
            count=int(p["count"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "level": self.level,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class LogRow:
    """One persisted log line, exactly the columns log_events stores. Carried by both
    log.event (live) and log.backfill (history) so a viewer sees one row shape at
    the seam between them.
    """

    seq: int  # unit: dimensionless
    client_ts: str
    server_ts: str
    process: str
    instance: str
    pid: int  # unit: dimensionless
    host: str
    session: str
    level: str
    logger: str
    module: str
    line: int  # unit: dimensionless
    has_exception: bool
    truncated: bool
    message: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.process) > 64:
            raise MessageValidationError(
                f"process: length {len(self.process)} exceeds max_len 64"
            )
        if len(self.instance) > 64:
            raise MessageValidationError(
                f"instance: length {len(self.instance)} exceeds max_len 64"
            )
        if len(self.host) > 128:
            raise MessageValidationError(
                f"host: length {len(self.host)} exceeds max_len 128"
            )
        if len(self.session) > 64:
            raise MessageValidationError(
                f"session: length {len(self.session)} exceeds max_len 64"
            )
        if len(self.level) > 16:
            raise MessageValidationError(
                f"level: length {len(self.level)} exceeds max_len 16"
            )
        if len(self.logger) > 128:
            raise MessageValidationError(
                f"logger: length {len(self.logger)} exceeds max_len 128"
            )
        if len(self.module) > 128:
            raise MessageValidationError(
                f"module: length {len(self.module)} exceeds max_len 128"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogRow":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            seq=int(p["seq"]),
            client_ts=str(p["client_ts"]),
            server_ts=str(p["server_ts"]),
            process=str(p["process"]),
            instance=str(p["instance"]),
            pid=int(p["pid"]),
            host=str(p["host"]),
            session=str(p["session"]),
            level=str(p["level"]),
            logger=str(p["logger"]),
            module=str(p["module"]),
            line=int(p["line"]),
            has_exception=bool(p["has_exception"]),
            truncated=bool(p["truncated"]),
            message=str(p["message"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "seq": self.seq,
            "client_ts": self.client_ts,
            "server_ts": self.server_ts,
            "process": self.process,
            "instance": self.instance,
            "pid": self.pid,
            "host": self.host,
            "session": self.session,
            "level": self.level,
            "logger": self.logger,
            "module": self.module,
            "line": self.line,
            "has_exception": self.has_exception,
            "truncated": self.truncated,
            "message": self.message,
        }


_SUBSCRIPTION_STATUS_MODE_VALUES = ("STREAM", "NOTIFY")
SubscriptionStatusMode = Literal["STREAM", "NOTIFY"]


@dataclass(frozen=True, slots=True)
class SubscriptionStatus:
    """One subscription's live counters, reported by log.status. This is the record
    that motivated allowing a record inside a record: it carries the
    subscription's own LogFilter. Flattening that into filter_min_level and
    friends is the `a_b` flattening section 16.2 argued against, and forbidding
    depth was a rule broader than its reason - what the generators cannot survive
    is a cycle, not a level.
    """

    sub_id: str
    mode: SubscriptionStatusMode
    filter: LogFilter
    lease_sec: float  # unit: dimensionless
    lease_remaining_sec: float  # unit: dimensionless
    age_sec: float  # unit: dimensionless
    pending_rows: int  # unit: dimensionless
    pending_count: int  # unit: dimensionless
    sent_rows: int  # unit: dimensionless
    sent_messages: int  # unit: dimensionless
    dropped_rows: int  # unit: dimensionless
    renewals: int  # unit: dimensionless

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
        if self.mode not in _SUBSCRIPTION_STATUS_MODE_VALUES:
            raise MessageValidationError(
                f"mode: {self.mode!r} is not one of {_SUBSCRIPTION_STATUS_MODE_VALUES!r}"
            )
        self.filter.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SubscriptionStatus":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sub_id=str(p["sub_id"]),
            mode=cast(SubscriptionStatusMode, str(p["mode"])),
            filter=LogFilter.from_dict(p["filter"]),
            lease_sec=float(p["lease_sec"]),
            lease_remaining_sec=float(p["lease_remaining_sec"]),
            age_sec=float(p["age_sec"]),
            pending_rows=int(p["pending_rows"]),
            pending_count=int(p["pending_count"]),
            sent_rows=int(p["sent_rows"]),
            sent_messages=int(p["sent_messages"]),
            dropped_rows=int(p["dropped_rows"]),
            renewals=int(p["renewals"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "sub_id": self.sub_id,
            "mode": self.mode,
            "filter": self.filter.to_dict(),
            "lease_sec": self.lease_sec,
            "lease_remaining_sec": self.lease_remaining_sec,
            "age_sec": self.age_sec,
            "pending_rows": self.pending_rows,
            "pending_count": self.pending_count,
            "sent_rows": self.sent_rows,
            "sent_messages": self.sent_messages,
            "dropped_rows": self.dropped_rows,
            "renewals": self.renewals,
        }


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


TOPIC_LOG_SUBSCRIBE_ACK = "log.subscribe_ack.{sub_id}"
PREFIX_LOG_SUBSCRIBE_ACK = "log.subscribe_ack."
_LOG_SUBSCRIBE_ACK_RE = re.compile("log\\.subscribe_ack\\.(?P<sub_id>[^.]+)")
_LOG_SUBSCRIBE_ACK_MODE_VALUES = ("STREAM", "NOTIFY")
LogSubscribeAckMode = Literal["STREAM", "NOTIFY"]


_LOG_SUBSCRIBE_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "proto",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "server",
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
        "required": True,
        "doc": "",
        "values": _LOG_SUBSCRIBE_ACK_MODE_VALUES,
    },
    {
        "name": "filter",
        "type": "nested",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "lease_sec",
        "type": "float",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "renew_before_sec",
        "type": "float",
        "unit": "dimensionless",
        "required": True,
        "doc": "Renew sooner than this; half the lease.",
    },
    {
        "name": "notify_interval_ms",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "last_seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "backfill_request_id",
        "type": "string",
        "unit": None,
        "required": False,
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
class LogSubscribeAck:
    """Confirm a subscription and echo the terms the server chose.

    The filter comes back parsed rather than as sent, so a subscriber can see what the
    server actually understood - which is where a lenient filter parse would otherwise
    hide a typo.
    """

    accepted: bool
    sub_id: str
    proto: str
    server: str
    mode: LogSubscribeAckMode
    filter: LogFilter
    lease_sec: float  # unit: dimensionless
    renew_before_sec: float  # unit: dimensionless
    notify_interval_ms: int  # unit: dimensionless
    last_seq: int  # unit: dimensionless
    timestamp: float  # unit: epoch_seconds
    backfill_request_id: str = ""

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
        if len(self.proto) > 16:
            raise MessageValidationError(
                f"proto: length {len(self.proto)} exceeds max_len 16"
            )
        if len(self.server) > 64:
            raise MessageValidationError(
                f"server: length {len(self.server)} exceeds max_len 64"
            )
        if self.mode not in _LOG_SUBSCRIBE_ACK_MODE_VALUES:
            raise MessageValidationError(
                f"mode: {self.mode!r} is not one of {_LOG_SUBSCRIBE_ACK_MODE_VALUES!r}"
            )
        self.filter.validate()
        if len(self.backfill_request_id) > 64:
            raise MessageValidationError(
                f"backfill_request_id: length {len(self.backfill_request_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogSubscribeAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            accepted=bool(p["accepted"]),
            sub_id=str(p["sub_id"]),
            proto=str(p["proto"]),
            server=str(p["server"]),
            mode=cast(LogSubscribeAckMode, str(p["mode"])),
            filter=LogFilter.from_dict(p["filter"]),
            lease_sec=float(p["lease_sec"]),
            renew_before_sec=float(p["renew_before_sec"]),
            notify_interval_ms=int(p["notify_interval_ms"]),
            last_seq=int(p["last_seq"]),
            backfill_request_id=str(p.get("backfill_request_id", "")),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "accepted": self.accepted,
            "sub_id": self.sub_id,
            "proto": self.proto,
            "server": self.server,
            "mode": self.mode,
            "filter": self.filter.to_dict(),
            "lease_sec": self.lease_sec,
            "renew_before_sec": self.renew_before_sec,
            "notify_interval_ms": self.notify_interval_ms,
            "last_seq": self.last_seq,
            "timestamp": self.timestamp,
        }
        if self.backfill_request_id:
            payload["backfill_request_id"] = self.backfill_request_id
        return payload


def topic_log_subscribe_ack(sub_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"log.subscribe_ack.{sub_id}"


def match_log_subscribe_ack(topic: str) -> str | None:
    """Return ``sub_id`` when ``topic`` matches, else None."""
    m = _LOG_SUBSCRIBE_ACK_RE.fullmatch(topic)
    return m.group("sub_id") if m else None


def make_log_subscribe_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogSubscribeAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_log_subscribe_ack(obj.sub_id), obj.to_dict())


def parse_log_subscribe_ack(frames: list[bytes]) -> "LogSubscribeAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_log_subscribe_ack(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_LOG_SUBSCRIBE_ACK!r}"
        )
    payload = {**payload, "sub_id": matched}
    obj = LogSubscribeAck.from_dict(payload)
    obj.validate()
    return obj


def describe_log_subscribe_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_SUBSCRIBE_ACK_FIELDS


TOPIC_LOG_RENEW_ACK = "log.renew_ack.{sub_id}"
PREFIX_LOG_RENEW_ACK = "log.renew_ack."
_LOG_RENEW_ACK_RE = re.compile("log\\.renew_ack\\.(?P<sub_id>[^.]+)")


_LOG_RENEW_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "lease_sec",
        "type": "float",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "expires_in_sec",
        "type": "float",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "last_seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
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
class LogRenewAck:
    """Confirm a keepalive and say how long the lease now has."""

    accepted: bool
    sub_id: str
    lease_sec: float  # unit: dimensionless
    expires_in_sec: float  # unit: dimensionless
    last_seq: int  # unit: dimensionless
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
    def from_dict(cls, p: Mapping[str, Any]) -> "LogRenewAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            accepted=bool(p["accepted"]),
            sub_id=str(p["sub_id"]),
            lease_sec=float(p["lease_sec"]),
            expires_in_sec=float(p["expires_in_sec"]),
            last_seq=int(p["last_seq"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "accepted": self.accepted,
            "sub_id": self.sub_id,
            "lease_sec": self.lease_sec,
            "expires_in_sec": self.expires_in_sec,
            "last_seq": self.last_seq,
            "timestamp": self.timestamp,
        }


def topic_log_renew_ack(sub_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"log.renew_ack.{sub_id}"


def match_log_renew_ack(topic: str) -> str | None:
    """Return ``sub_id`` when ``topic`` matches, else None."""
    m = _LOG_RENEW_ACK_RE.fullmatch(topic)
    return m.group("sub_id") if m else None


def make_log_renew_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogRenewAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_log_renew_ack(obj.sub_id), obj.to_dict())


def make_log_renew_ack_unchecked(
    *,
    accepted: bool,
    sub_id: str,
    lease_sec: float,
    expires_in_sec: float,
    last_seq: int,
    timestamp: float,
) -> list[bytes]:
    """Identical frames to ``make_log_renew_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_log_renew_ack(sub_id).encode(),
        _msg.dumps(
            {
                "accepted": bool(accepted),
                "sub_id": str(sub_id),
                "lease_sec": float(lease_sec),
                "expires_in_sec": float(expires_in_sec),
                "last_seq": int(last_seq),
                "timestamp": float(timestamp),
            }
        ),
    ]


def parse_log_renew_ack(frames: list[bytes]) -> "LogRenewAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_log_renew_ack(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_LOG_RENEW_ACK!r}")
    payload = {**payload, "sub_id": matched}
    obj = LogRenewAck.from_dict(payload)
    obj.validate()
    return obj


def describe_log_renew_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_RENEW_ACK_FIELDS


TOPIC_LOG_UNSUBSCRIBE_ACK = "log.unsubscribe_ack.{sub_id}"
PREFIX_LOG_UNSUBSCRIBE_ACK = "log.unsubscribe_ack."
_LOG_UNSUBSCRIBE_ACK_RE = re.compile("log\\.unsubscribe_ack\\.(?P<sub_id>[^.]+)")


_LOG_UNSUBSCRIBE_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "sub_id",
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
        "constraints": {"max_len": 256},
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
class LogUnsubscribeAck:
    """Confirm a close, or say there was nothing to close."""

    accepted: bool
    sub_id: str
    timestamp: float  # unit: epoch_seconds
    reason: str = ""

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
        if len(self.reason) > 256:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 256"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogUnsubscribeAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            accepted=bool(p["accepted"]),
            sub_id=str(p["sub_id"]),
            reason=str(p.get("reason", "")),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "accepted": self.accepted,
            "sub_id": self.sub_id,
            "timestamp": self.timestamp,
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


def topic_log_unsubscribe_ack(sub_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"log.unsubscribe_ack.{sub_id}"


def match_log_unsubscribe_ack(topic: str) -> str | None:
    """Return ``sub_id`` when ``topic`` matches, else None."""
    m = _LOG_UNSUBSCRIBE_ACK_RE.fullmatch(topic)
    return m.group("sub_id") if m else None


def make_log_unsubscribe_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogUnsubscribeAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_log_unsubscribe_ack(obj.sub_id), obj.to_dict())


def make_log_unsubscribe_ack_unchecked(
    *,
    accepted: bool,
    sub_id: str,
    timestamp: float,
    reason: str = "",
) -> list[bytes]:
    """Identical frames to ``make_log_unsubscribe_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "accepted": bool(accepted),
        "sub_id": str(sub_id),
        "timestamp": float(timestamp),
    }
    if reason:
        payload["reason"] = str(reason)
    return [
        topic_log_unsubscribe_ack(sub_id).encode(),
        _msg.dumps(payload),
    ]


def parse_log_unsubscribe_ack(frames: list[bytes]) -> "LogUnsubscribeAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_log_unsubscribe_ack(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_LOG_UNSUBSCRIBE_ACK!r}"
        )
    payload = {**payload, "sub_id": matched}
    obj = LogUnsubscribeAck.from_dict(payload)
    obj.validate()
    return obj


def describe_log_unsubscribe_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_UNSUBSCRIBE_ACK_FIELDS


TOPIC_LOG_STATUS = "log.status.{sub_id}"
PREFIX_LOG_STATUS = "log.status."
_LOG_STATUS_RE = re.compile("log\\.status\\.(?P<sub_id>[^.]+)")


_LOG_STATUS_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "server",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "proto",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "subscribers",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "active_backfills",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "last_seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "inbox_dropped",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "subscription",
        "type": "nested",
        "unit": None,
        "required": False,
        "doc": "",
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
class LogStatus:
    """Server and subscription diagnostics, on request.

    subscription is null when the requester has no live subscription - asking for status
    is legal without one, and null says "you have none" where an absent key would say
    "the server declined to tell you".
    """

    sub_id: str
    server: str
    proto: str
    subscribers: int  # unit: dimensionless
    active_backfills: int  # unit: dimensionless
    last_seq: int  # unit: dimensionless
    inbox_dropped: int  # unit: dimensionless
    timestamp: float  # unit: epoch_seconds
    subscription: SubscriptionStatus | None = None

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
        if len(self.server) > 64:
            raise MessageValidationError(
                f"server: length {len(self.server)} exceeds max_len 64"
            )
        if len(self.proto) > 16:
            raise MessageValidationError(
                f"proto: length {len(self.proto)} exceeds max_len 16"
            )
        if self.subscription is not None:
            self.subscription.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogStatus":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sub_id=str(p["sub_id"]),
            server=str(p["server"]),
            proto=str(p["proto"]),
            subscribers=int(p["subscribers"]),
            active_backfills=int(p["active_backfills"]),
            last_seq=int(p["last_seq"]),
            inbox_dropped=int(p["inbox_dropped"]),
            subscription=(
                None
                if p.get("subscription") is None
                else SubscriptionStatus.from_dict(p["subscription"])
            ),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "sub_id": self.sub_id,
            "server": self.server,
            "proto": self.proto,
            "subscribers": self.subscribers,
            "active_backfills": self.active_backfills,
            "last_seq": self.last_seq,
            "inbox_dropped": self.inbox_dropped,
            "subscription": (
                None if self.subscription is None else self.subscription.to_dict()
            ),
            "timestamp": self.timestamp,
        }


def topic_log_status(sub_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"log.status.{sub_id}"


def match_log_status(topic: str) -> str | None:
    """Return ``sub_id`` when ``topic`` matches, else None."""
    m = _LOG_STATUS_RE.fullmatch(topic)
    return m.group("sub_id") if m else None


def make_log_status(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogStatus.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_log_status(obj.sub_id), obj.to_dict())


def parse_log_status(frames: list[bytes]) -> "LogStatus":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_log_status(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_LOG_STATUS!r}")
    payload = {**payload, "sub_id": matched}
    obj = LogStatus.from_dict(payload)
    obj.validate()
    return obj


def describe_log_status() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_STATUS_FIELDS


TOPIC_LOG_BACKFILL = "log.backfill.{sub_id}"
PREFIX_LOG_BACKFILL = "log.backfill."
_LOG_BACKFILL_RE = re.compile("log\\.backfill\\.(?P<sub_id>[^.]+)")


_LOG_BACKFILL_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "request_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "chunk",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "rows",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "row_count",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "done",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "total_sent",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "truncated",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "last_seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
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
class LogBackfill:
    """One chunk of replayed history for a subscription.

    Chunked because a backfill can be far larger than one message: done marks the last
    chunk, and truncated says the server stopped at max_rows rather than at the end of
    history. The two are different answers to "why did it stop".
    """

    sub_id: str
    request_id: str
    chunk: int  # unit: dimensionless
    rows: list[LogRow]
    row_count: int  # unit: dimensionless
    done: bool
    total_sent: int  # unit: dimensionless
    truncated: bool
    last_seq: int  # unit: dimensionless
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
        if len(self.request_id) > 64:
            raise MessageValidationError(
                f"request_id: length {len(self.request_id)} exceeds max_len 64"
            )
        for rows_item in self.rows:
            rows_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogBackfill":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sub_id=str(p["sub_id"]),
            request_id=str(p["request_id"]),
            chunk=int(p["chunk"]),
            rows=[LogRow.from_dict(item) for item in p["rows"]],
            row_count=int(p["row_count"]),
            done=bool(p["done"]),
            total_sent=int(p["total_sent"]),
            truncated=bool(p["truncated"]),
            last_seq=int(p["last_seq"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "sub_id": self.sub_id,
            "request_id": self.request_id,
            "chunk": self.chunk,
            "rows": [item.to_dict() for item in self.rows],
            "row_count": self.row_count,
            "done": self.done,
            "total_sent": self.total_sent,
            "truncated": self.truncated,
            "last_seq": self.last_seq,
            "timestamp": self.timestamp,
        }


def topic_log_backfill(sub_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"log.backfill.{sub_id}"


def match_log_backfill(topic: str) -> str | None:
    """Return ``sub_id`` when ``topic`` matches, else None."""
    m = _LOG_BACKFILL_RE.fullmatch(topic)
    return m.group("sub_id") if m else None


def make_log_backfill(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogBackfill.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_log_backfill(obj.sub_id), obj.to_dict())


def parse_log_backfill(frames: list[bytes]) -> "LogBackfill":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_log_backfill(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_LOG_BACKFILL!r}")
    payload = {**payload, "sub_id": matched}
    obj = LogBackfill.from_dict(payload)
    obj.validate()
    return obj


def describe_log_backfill() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_BACKFILL_FIELDS


TOPIC_LOG_EVENT = "log.event.{sub_id}"
PREFIX_LOG_EVENT = "log.event."
_LOG_EVENT_RE = re.compile("log\\.event\\.(?P<sub_id>[^.]+)")


_LOG_EVENT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "rows",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Never empty; the server skips a flush with nothing to send.",
    },
    {
        "name": "row_count",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "seq_from",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "seq_to",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "server_last_seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "dropped",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "Lifetime rows dropped for this subscription, not this batch.",
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
class LogEvent:
    """A batch of live rows for a STREAM subscription."""

    sub_id: str
    rows: list[LogRow]
    row_count: int  # unit: dimensionless
    seq_from: int  # unit: dimensionless
    seq_to: int  # unit: dimensionless
    server_last_seq: int  # unit: dimensionless
    dropped: int  # unit: dimensionless
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
        if len(self.rows) < 1:
            raise MessageValidationError("rows: fewer than 1 item(s)")
        for rows_item in self.rows:
            rows_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogEvent":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sub_id=str(p["sub_id"]),
            rows=[LogRow.from_dict(item) for item in p["rows"]],
            row_count=int(p["row_count"]),
            seq_from=int(p["seq_from"]),
            seq_to=int(p["seq_to"]),
            server_last_seq=int(p["server_last_seq"]),
            dropped=int(p["dropped"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "sub_id": self.sub_id,
            "rows": [item.to_dict() for item in self.rows],
            "row_count": self.row_count,
            "seq_from": self.seq_from,
            "seq_to": self.seq_to,
            "server_last_seq": self.server_last_seq,
            "dropped": self.dropped,
            "timestamp": self.timestamp,
        }


def topic_log_event(sub_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"log.event.{sub_id}"


def match_log_event(topic: str) -> str | None:
    """Return ``sub_id`` when ``topic`` matches, else None."""
    m = _LOG_EVENT_RE.fullmatch(topic)
    return m.group("sub_id") if m else None


def make_log_event(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogEvent.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_log_event(obj.sub_id), obj.to_dict())


def parse_log_event(frames: list[bytes]) -> "LogEvent":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_log_event(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_LOG_EVENT!r}")
    payload = {**payload, "sub_id": matched}
    obj = LogEvent.from_dict(payload)
    obj.validate()
    return obj


def describe_log_event() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_EVENT_FIELDS


TOPIC_LOG_NOTIFY = "log.notify.{sub_id}"
PREFIX_LOG_NOTIFY = "log.notify."
_LOG_NOTIFY_RE = re.compile("log\\.notify\\.(?P<sub_id>[^.]+)")


_LOG_NOTIFY_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "count",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "levels",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "last_seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "server_last_seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
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
class LogNotify:
    """Periodic counts for a NOTIFY subscription: how much happened, without the
    rows.

    levels was a map keyed by level name. It is a list of records now - the key was a
    value, and design section 15.4 says a spec that appears to need a map is describing
    a message that should have been this.
    """

    sub_id: str
    count: int  # unit: dimensionless
    levels: list[LevelCount]
    last_seq: int  # unit: dimensionless
    server_last_seq: int  # unit: dimensionless
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
        for levels_item in self.levels:
            levels_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogNotify":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sub_id=str(p["sub_id"]),
            count=int(p["count"]),
            levels=[LevelCount.from_dict(item) for item in p["levels"]],
            last_seq=int(p["last_seq"]),
            server_last_seq=int(p["server_last_seq"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "sub_id": self.sub_id,
            "count": self.count,
            "levels": [item.to_dict() for item in self.levels],
            "last_seq": self.last_seq,
            "server_last_seq": self.server_last_seq,
            "timestamp": self.timestamp,
        }


def topic_log_notify(sub_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"log.notify.{sub_id}"


def match_log_notify(topic: str) -> str | None:
    """Return ``sub_id`` when ``topic`` matches, else None."""
    m = _LOG_NOTIFY_RE.fullmatch(topic)
    return m.group("sub_id") if m else None


def make_log_notify(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogNotify.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_log_notify(obj.sub_id), obj.to_dict())


def parse_log_notify(frames: list[bytes]) -> "LogNotify":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_log_notify(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_LOG_NOTIFY!r}")
    payload = {**payload, "sub_id": matched}
    obj = LogNotify.from_dict(payload)
    obj.validate()
    return obj


def describe_log_notify() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_NOTIFY_FIELDS


TOPIC_LOG_LEASE_EXPIRED = "log.lease_expired.{sub_id}"
PREFIX_LOG_LEASE_EXPIRED = "log.lease_expired."
_LOG_LEASE_EXPIRED_RE = re.compile("log\\.lease_expired\\.(?P<sub_id>[^.]+)")


_LOG_LEASE_EXPIRED_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "sub_id",
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
        "required": True,
        "doc": "",
        "constraints": {"max_len": 256},
    },
    {
        "name": "lease_sec",
        "type": "float",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "dropped_rows",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
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
class LogLeaseExpired:
    """The subscription was reaped for want of a renew.

    Published on the off-chance the subscriber is alive but wedged: nothing about a
    crashed process is visible on a PUB socket, so this tells a client that is in fact
    listening that it must re-subscribe rather than wait for rows that will never come.
    """

    sub_id: str
    reason: str
    lease_sec: float  # unit: dimensionless
    dropped_rows: int  # unit: dimensionless
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
        if len(self.reason) > 256:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 256"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogLeaseExpired":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sub_id=str(p["sub_id"]),
            reason=str(p["reason"]),
            lease_sec=float(p["lease_sec"]),
            dropped_rows=int(p["dropped_rows"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "sub_id": self.sub_id,
            "reason": self.reason,
            "lease_sec": self.lease_sec,
            "dropped_rows": self.dropped_rows,
            "timestamp": self.timestamp,
        }


def topic_log_lease_expired(sub_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"log.lease_expired.{sub_id}"


def match_log_lease_expired(topic: str) -> str | None:
    """Return ``sub_id`` when ``topic`` matches, else None."""
    m = _LOG_LEASE_EXPIRED_RE.fullmatch(topic)
    return m.group("sub_id") if m else None


def make_log_lease_expired(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogLeaseExpired.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_log_lease_expired(obj.sub_id), obj.to_dict())


def make_log_lease_expired_unchecked(
    *,
    sub_id: str,
    reason: str,
    lease_sec: float,
    dropped_rows: int,
    timestamp: float,
) -> list[bytes]:
    """Identical frames to ``make_log_lease_expired``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_log_lease_expired(sub_id).encode(),
        _msg.dumps(
            {
                "sub_id": str(sub_id),
                "reason": str(reason),
                "lease_sec": float(lease_sec),
                "dropped_rows": int(dropped_rows),
                "timestamp": float(timestamp),
            }
        ),
    ]


def parse_log_lease_expired(frames: list[bytes]) -> "LogLeaseExpired":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_log_lease_expired(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_LOG_LEASE_EXPIRED!r}"
        )
    payload = {**payload, "sub_id": matched}
    obj = LogLeaseExpired.from_dict(payload)
    obj.validate()
    return obj


def describe_log_lease_expired() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_LEASE_EXPIRED_FIELDS


TOPIC_LOG_ERROR = "log.error.{sub_id}"
PREFIX_LOG_ERROR = "log.error."
_LOG_ERROR_RE = re.compile("log\\.error\\.(?P<sub_id>[^.]+)")


_LOG_ERROR_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "Always false; present so every reply has the same first key.",
    },
    {
        "name": "sub_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "code",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 512},
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
class LogError:
    """A control request was rejected, with a machine-readable code."""

    accepted: bool
    sub_id: str
    code: str
    reason: str
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
        if len(self.code) > 32:
            raise MessageValidationError(
                f"code: length {len(self.code)} exceeds max_len 32"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogError":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            accepted=bool(p["accepted"]),
            sub_id=str(p["sub_id"]),
            code=str(p["code"]),
            reason=str(p["reason"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "accepted": self.accepted,
            "sub_id": self.sub_id,
            "code": self.code,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


def topic_log_error(sub_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"log.error.{sub_id}"


def match_log_error(topic: str) -> str | None:
    """Return ``sub_id`` when ``topic`` matches, else None."""
    m = _LOG_ERROR_RE.fullmatch(topic)
    return m.group("sub_id") if m else None


def make_log_error(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogError.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_log_error(obj.sub_id), obj.to_dict())


def make_log_error_unchecked(
    *,
    accepted: bool,
    sub_id: str,
    code: str,
    reason: str,
    timestamp: float,
) -> list[bytes]:
    """Identical frames to ``make_log_error``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_log_error(sub_id).encode(),
        _msg.dumps(
            {
                "accepted": bool(accepted),
                "sub_id": str(sub_id),
                "code": str(code),
                "reason": str(reason),
                "timestamp": float(timestamp),
            }
        ),
    ]


def parse_log_error(frames: list[bytes]) -> "LogError":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_log_error(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_LOG_ERROR!r}")
    payload = {**payload, "sub_id": matched}
    obj = LogError.from_dict(payload)
    obj.validate()
    return obj


def describe_log_error() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_ERROR_FIELDS


TOPIC_LOG_SERVER_STATE = "log.server_state"
_TOPIC_LOG_SERVER_STATE_BYTES = "log.server_state".encode()
_LOG_SERVER_STATE_STATE_VALUES = ("UP", "DOWN")
LogServerStateState = Literal["UP", "DOWN"]


_LOG_SERVER_STATE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "server",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "state",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _LOG_SERVER_STATE_STATE_VALUES,
    },
    {
        "name": "proto",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "pub_addr",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 128},
    },
    {
        "name": "pull_addr",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 128},
    },
    {
        "name": "subscribers",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "active_backfills",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "last_seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "inbox_dropped",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "default_lease_sec",
        "type": "float",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
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
class LogServerState:
    """Periodic server heartbeat and configuration, broadcast to everyone rather than
    addressed - it is how a viewer finds the server at all.
    """

    server: str
    state: LogServerStateState
    proto: str
    pub_addr: str
    pull_addr: str
    subscribers: int  # unit: dimensionless
    active_backfills: int  # unit: dimensionless
    last_seq: int  # unit: dimensionless
    inbox_dropped: int  # unit: dimensionless
    default_lease_sec: float  # unit: dimensionless
    timestamp: float  # unit: epoch_seconds

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.server) > 64:
            raise MessageValidationError(
                f"server: length {len(self.server)} exceeds max_len 64"
            )
        if self.state not in _LOG_SERVER_STATE_STATE_VALUES:
            raise MessageValidationError(
                f"state: {self.state!r} is not one of {_LOG_SERVER_STATE_STATE_VALUES!r}"
            )
        if len(self.proto) > 16:
            raise MessageValidationError(
                f"proto: length {len(self.proto)} exceeds max_len 16"
            )
        if len(self.pub_addr) > 128:
            raise MessageValidationError(
                f"pub_addr: length {len(self.pub_addr)} exceeds max_len 128"
            )
        if len(self.pull_addr) > 128:
            raise MessageValidationError(
                f"pull_addr: length {len(self.pull_addr)} exceeds max_len 128"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LogServerState":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            server=str(p["server"]),
            state=cast(LogServerStateState, str(p["state"])),
            proto=str(p["proto"]),
            pub_addr=str(p["pub_addr"]),
            pull_addr=str(p["pull_addr"]),
            subscribers=int(p["subscribers"]),
            active_backfills=int(p["active_backfills"]),
            last_seq=int(p["last_seq"]),
            inbox_dropped=int(p["inbox_dropped"]),
            default_lease_sec=float(p["default_lease_sec"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "server": self.server,
            "state": self.state,
            "proto": self.proto,
            "pub_addr": self.pub_addr,
            "pull_addr": self.pull_addr,
            "subscribers": self.subscribers,
            "active_backfills": self.active_backfills,
            "last_seq": self.last_seq,
            "inbox_dropped": self.inbox_dropped,
            "default_lease_sec": self.default_lease_sec,
            "timestamp": self.timestamp,
        }


def is_log_server_state(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_LOG_SERVER_STATE


def make_log_server_state(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = LogServerState.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_LOG_SERVER_STATE, obj.to_dict())


def make_log_server_state_unchecked(
    *,
    server: str,
    state: LogServerStateState,
    proto: str,
    pub_addr: str,
    pull_addr: str,
    subscribers: int,
    active_backfills: int,
    last_seq: int,
    inbox_dropped: int,
    default_lease_sec: float,
    timestamp: float,
) -> list[bytes]:
    """Identical frames to ``make_log_server_state``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_LOG_SERVER_STATE_BYTES,
        _msg.dumps(
            {
                "server": str(server),
                "state": str(state),
                "proto": str(proto),
                "pub_addr": str(pub_addr),
                "pull_addr": str(pull_addr),
                "subscribers": int(subscribers),
                "active_backfills": int(active_backfills),
                "last_seq": int(last_seq),
                "inbox_dropped": int(inbox_dropped),
                "default_lease_sec": float(default_lease_sec),
                "timestamp": float(timestamp),
            }
        ),
    ]


def parse_log_server_state(frames: list[bytes]) -> "LogServerState":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = LogServerState.from_dict(payload)
    obj.validate()
    return obj


def describe_log_server_state() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _LOG_SERVER_STATE_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_LOG_SUBSCRIBE,
    TOPIC_LOG_RENEW,
    TOPIC_LOG_UNSUBSCRIBE,
    TOPIC_LOG_BACKFILL_REQUEST,
    TOPIC_LOG_STATUS_REQUEST,
    TOPIC_LOG_SUBSCRIBE_ACK,
    TOPIC_LOG_RENEW_ACK,
    TOPIC_LOG_UNSUBSCRIBE_ACK,
    TOPIC_LOG_STATUS,
    TOPIC_LOG_BACKFILL,
    TOPIC_LOG_EVENT,
    TOPIC_LOG_NOTIFY,
    TOPIC_LOG_LEASE_EXPIRED,
    TOPIC_LOG_ERROR,
    TOPIC_LOG_SERVER_STATE,
)
