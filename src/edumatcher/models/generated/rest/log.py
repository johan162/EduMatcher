# GENERATED FROM spec/messages/log.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``log`` message family.

Family version 1. Derived from ``spec/messages/log.yaml`` by the rest emitter; edit the
spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SubscriptionStatusMode = Literal["STREAM", "NOTIFY"]
LogSubscribeMode = Literal["STREAM", "NOTIFY"]
LogSubscribeAckMode = Literal["STREAM", "NOTIFY"]
LogServerStateState = Literal["UP", "DOWN"]


class LogFilter(BaseModel):
    """A row predicate, applied two ways by the server: evaluated in Python against a
    freshly persisted row on the live path, and compiled to a parameterised SQL
    WHERE clause for backfill. One definition with two evaluators is what
    guarantees a subscriber's backfill and its subsequent live stream contain the
    same kind of rows - a mismatch would show up as rows appearing or vanishing at
    the seam. Every field is optional; an empty filter matches everything.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    min_level: str | None = Field(default=None, max_length=16)
    """Lowest level to include, e.g. WARNING."""
    processes: list[str]
    """Process names to include; empty means all."""
    loggers: list[str]
    """Logger names to include; empty means all."""
    sessions: list[str]
    """Session ids to include; empty means all."""
    contains: str | None = Field(default=None, max_length=256)
    """Substring the message must contain."""
    exceptions_only: bool


class LevelCount(BaseModel):
    """How many rows of one level a NOTIFY subscription has buffered. This was a map
    on the wire - {"INFO": 3, "ERROR": 1} - which the IDL excludes deliberately
    (design section 15.4). The key was a value, and a list of records says so: the
    level is a field, not a key.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    level: str = Field(max_length=16)
    count: int = Field(ge=0)


class LogRow(BaseModel):
    """One persisted log line, exactly the columns log_events stores. Carried by both
    log.event (live) and log.backfill (history) so a viewer sees one row shape at
    the seam between them.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    seq: int
    """Monotonic server sequence; the cursor for backfill."""
    client_ts: str
    """Producer wall-clock, ISO-8601 (e.g. 2026-07-29T10:00:00.000Z)."""
    server_ts: str
    """Server receive time, ISO-8601; the log_events columns are TEXT."""
    process: str = Field(max_length=64)
    instance: str = Field(max_length=64)
    pid: int
    host: str = Field(max_length=128)
    session: str = Field(max_length=64)
    level: str = Field(max_length=16)
    logger: str = Field(max_length=128)
    module: str = Field(max_length=128)
    line: int
    has_exception: bool
    truncated: bool
    message: str


class SubscriptionStatus(BaseModel):
    """One subscription's live counters, reported by log.status. This is the record
    that motivated allowing a record inside a record: it carries the
    subscription's own LogFilter. Flattening that into filter_min_level and
    friends is the `a_b` flattening section 16.2 argued against, and forbidding
    depth was a rule broader than its reason - what the generators cannot survive
    is a cycle, not a level.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    sub_id: str = Field(max_length=64)
    mode: SubscriptionStatusMode
    filter: LogFilter
    lease_sec: float
    lease_remaining_sec: float
    age_sec: float
    pending_rows: int
    pending_count: int
    sent_rows: int
    sent_messages: int
    dropped_rows: int
    renewals: int


class LogSubscribe(BaseModel):
    """Subscriber to pm-log-srv: open or replace a leased stream."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    sub_id: str = Field(max_length=64)
    mode: LogSubscribeMode
    """STREAM pushes every row; NOTIFY pushes periodic counts."""
    filter: LogFilter | None = Field(default=None)
    backfill_minutes: int | None = Field(default=None)
    """Replay this many minutes before the live stream starts."""
    lease_sec: int | None = Field(default=None)
    """How long the subscription survives without a renew."""
    notify_interval_ms: int | None = Field(default=None)


class LogRenew(BaseModel):
    """Lease keepalive. The liveness signal: a subscriber that stops renewing is
    dropped, which is how the server reclaims a viewer that went away without
    unsubscribing.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    sub_id: str = Field(max_length=64)
    timestamp: float
    """Unit: epoch_seconds."""


class LogUnsubscribe(BaseModel):
    """Close a subscription immediately rather than letting it lapse."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    sub_id: str = Field(max_length=64)
    timestamp: float
    """Unit: epoch_seconds."""


class LogBackfillRequest(BaseModel):
    """Replay the last N minutes of history for one subscription."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    sub_id: str = Field(max_length=64)
    minutes: int = Field(gt=0)
    filter: LogFilter | None = Field(default=None)
    """Defaults to the subscription's own filter when omitted."""
    max_rows: int | None = Field(default=None)


class LogStatusRequest(BaseModel):
    """Ask for subscription and server diagnostics."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    sub_id: str = Field(max_length=64)
    timestamp: float
    """Unit: epoch_seconds."""


class LogSubscribeAck(BaseModel):
    """Confirm a subscription and echo the terms the server chose."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    sub_id: str = Field(max_length=64)
    proto: str = Field(max_length=16)
    server: str = Field(max_length=64)
    mode: LogSubscribeAckMode
    filter: LogFilter
    lease_sec: float
    renew_before_sec: float
    """Renew sooner than this; half the lease."""
    notify_interval_ms: int
    last_seq: int
    backfill_request_id: str | None = Field(default=None, max_length=64)
    timestamp: float
    """Unit: epoch_seconds."""


class LogRenewAck(BaseModel):
    """Confirm a keepalive and say how long the lease now has."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    sub_id: str = Field(max_length=64)
    lease_sec: float
    expires_in_sec: float
    last_seq: int
    timestamp: float
    """Unit: epoch_seconds."""


class LogUnsubscribeAck(BaseModel):
    """Confirm a close, or say there was nothing to close."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    sub_id: str = Field(max_length=64)
    reason: str | None = Field(default=None, max_length=256)
    timestamp: float
    """Unit: epoch_seconds."""


class LogStatus(BaseModel):
    """Server and subscription diagnostics, on request."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    sub_id: str = Field(max_length=64)
    server: str = Field(max_length=64)
    proto: str = Field(max_length=16)
    subscribers: int
    active_backfills: int
    last_seq: int
    inbox_dropped: int
    subscription: SubscriptionStatus | None
    timestamp: float
    """Unit: epoch_seconds."""


class LogBackfill(BaseModel):
    """One chunk of replayed history for a subscription."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    sub_id: str = Field(max_length=64)
    request_id: str = Field(max_length=64)
    chunk: int
    rows: list[LogRow]
    row_count: int
    done: bool
    total_sent: int
    truncated: bool
    last_seq: int
    timestamp: float
    """Unit: epoch_seconds."""


class LogEvent(BaseModel):
    """A batch of live rows for a STREAM subscription."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    sub_id: str = Field(max_length=64)
    rows: list[LogRow] = Field(min_length=1)
    """Never empty; the server skips a flush with nothing to send."""
    row_count: int
    seq_from: int
    seq_to: int
    server_last_seq: int
    dropped: int
    """Lifetime rows dropped for this subscription, not this batch."""
    timestamp: float
    """Unit: epoch_seconds."""


class LogNotify(BaseModel):
    """Periodic counts for a NOTIFY subscription: how much happened, without the
    rows.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    sub_id: str = Field(max_length=64)
    count: int
    levels: list[LevelCount]
    last_seq: int
    server_last_seq: int
    timestamp: float
    """Unit: epoch_seconds."""


class LogLeaseExpired(BaseModel):
    """The subscription was reaped for want of a renew."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    sub_id: str = Field(max_length=64)
    reason: str = Field(max_length=256)
    lease_sec: float
    dropped_rows: int
    timestamp: float
    """Unit: epoch_seconds."""


class LogError(BaseModel):
    """A control request was rejected, with a machine-readable code."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    """Always false; present so every reply has the same first key."""
    sub_id: str = Field(max_length=64)
    code: str = Field(max_length=32)
    reason: str = Field(max_length=512)
    timestamp: float
    """Unit: epoch_seconds."""


class LogServerState(BaseModel):
    """Periodic server heartbeat and configuration, broadcast to everyone rather than
    addressed - it is how a viewer finds the server at all.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    server: str = Field(max_length=64)
    state: LogServerStateState
    proto: str = Field(max_length=16)
    pub_addr: str = Field(max_length=128)
    pull_addr: str = Field(max_length=128)
    subscribers: int
    active_backfills: int
    last_seq: int
    inbox_dropped: int
    default_lease_sec: float
    timestamp: float
    """Unit: epoch_seconds."""
