"""LALF-PS — the ZeroMQ log-distribution interface of ``pm-log-srv``.

Where :mod:`edumatcher.log_srv.server` speaks LALF over TCP to *producers*
(every ``pm-*`` process shipping its ``logging`` output in), this module
speaks ZeroMQ to *consumers* — log viewers, filters, search UIs and any
other tool that wants to see rows as they land rather than polling
``log.db`` on a timer.

Socket topology (deliberately identical in shape to ``pm-index``)
-----------------------------------------------------------------
``pm-log-srv`` binds two sockets:

``PUB``  (:data:`edumatcher.config.LOG_SRV_PUB_ADDR`, default ``:5601``)
    Every outbound message — live rows, notification ticks, backfill
    chunks, control acks and errors — leaves on this socket. Subscribers
    ``connect()`` a ``SUB`` socket and use ZeroMQ topic-prefix filtering,
    so a subscriber that only cares about its own traffic subscribes to
    the single prefix ``log.`` + its own ``sub_id``.

``PULL`` (:data:`edumatcher.config.LOG_SRV_PULL_ADDR`, default ``:5602``)
    Control requests — subscribe, renew, unsubscribe, backfill, status —
    arrive here from subscriber ``PUSH`` sockets.

Liveness: leases, not connections
---------------------------------
A ZeroMQ ``PUB`` socket is *blind*: it has no idea who is attached, and
publishing to nobody silently succeeds. That makes "stop sending to a
subscriber that died" impossible to solve on the publish path alone, so
LALF-PS makes every subscription an explicit **lease**. A subscription is
created with a TTL (``lease_sec``); the subscriber must send
``log.renew`` before that TTL elapses or the server reaps the
subscription: it drops the filter state, discards any buffered rows,
cancels any in-flight backfill job, and publishes a final
``log.lease_expired.{sub_id}``. A subscriber that crashes therefore costs
the server at most one lease period of buffering, with no dependence on
TCP-level disconnect detection (which ``PUB`` would not surface anyway).

As a second, purely defensive line, the ``PUB`` socket carries a bounded
``SNDHWM`` and each subscription's own row buffer is bounded — a
subscriber that is alive but too slow to keep up loses its oldest
buffered rows (reported back to it as ``dropped``) rather than growing
the server's memory without limit.

Threading
---------
``pm-log-srv``'s SQLite writer runs on its own thread (§7.4) and is the
component that knows when rows have actually been persisted and what
``seq`` they were assigned. ZeroMQ sockets are *not* thread-safe, so the
writer thread never touches them: it hands persisted batches to
:meth:`LogPubSubHub.on_batch_persisted`, which only appends to a
thread-safe queue. All socket IO happens in :meth:`LogPubSubHub.poll`,
called from the single-threaded main server loop.
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import zmq

from edumatcher.log_srv.schema import open_db
from edumatcher.log_srv.writer import LogEventRow
from edumatcher.logclient.protocol import iso_utc
from edumatcher.messaging.bus import get_context
from edumatcher.models.message import decode, encode

log = logging.getLogger(__name__)

PROTO_VERSION = "LALF-PS/1"
"""Wire-protocol version echoed in every ``log.subscribe_ack``.

Bumped only on a breaking change to the message set. A subscriber that
receives an unexpected value should refuse to proceed rather than guess.
"""

MODE_NOTIFY = "NOTIFY"
MODE_STREAM = "STREAM"
VALID_MODES = (MODE_NOTIFY, MODE_STREAM)

LEVEL_ORDER: dict[str, int] = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

# Error codes carried in log.error.{sub_id}. Kept as module constants (rather
# than inline string literals) for the same reason the LALF ERR codes are —
# they are part of the documented wire contract, not incidental text.
ERR_BAD_REQUEST = "BAD_REQUEST"
ERR_UNKNOWN_SUB = "UNKNOWN_SUB"
ERR_TOO_MANY_SUBS = "TOO_MANY_SUBS"
ERR_INVALID_FILTER = "INVALID_FILTER"
ERR_INVALID_MODE = "INVALID_MODE"
ERR_INVALID_WINDOW = "INVALID_WINDOW"
ERR_INTERNAL = "INTERNAL"

_ROW_COLUMNS = (
    "seq",
    "client_ts",
    "server_ts",
    "process",
    "instance",
    "pid",
    "host",
    "session",
    "level",
    "logger",
    "module",
    "line",
    "has_exception",
    "truncated",
    "message",
)

_SELECT_BACKFILL = f"SELECT {', '.join(_ROW_COLUMNS)} FROM log_events"


class LogFilterError(ValueError):
    """Raised when a subscriber sends a syntactically invalid filter."""


def _as_str_list(raw: object, field_name: str) -> tuple[str, ...]:
    """Coerce a JSON filter field to a tuple of non-empty strings."""
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise LogFilterError(f"filter.{field_name} must be a string or list of strings")
    out: list[str] = []
    for item in raw:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(item, str):
            raise LogFilterError(f"filter.{field_name} entries must be strings")
        if item:
            out.append(item)
    return tuple(out)


@dataclass(frozen=True)
class LogFilter:
    """Server-side row predicate shared by the live and backfill paths.

    The same filter object is applied two ways: :meth:`matches` evaluates
    it in Python against a freshly persisted row on the live path, and
    :meth:`sql_where` compiles it to a parameterised ``WHERE`` clause for
    the backfill path. Keeping one definition with two evaluators is what
    guarantees a subscriber's backfill and its subsequent live stream
    contain exactly the same kind of rows — a mismatch there would show up
    as rows mysteriously appearing or vanishing at the seam between the
    historical and live halves of a viewer's window.
    """

    min_level: str | None = None
    processes: tuple[str, ...] = ()
    loggers: tuple[str, ...] = ()
    sessions: tuple[str, ...] = ()
    contains: str | None = None
    exceptions_only: bool = False

    @classmethod
    def from_payload(cls, raw: object) -> "LogFilter":
        """Build a filter from the ``filter`` object of a control message."""
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise LogFilterError("filter must be an object")

        min_level_raw = raw.get("min_level")
        min_level: str | None = None
        if min_level_raw is not None:
            if not isinstance(min_level_raw, str):
                raise LogFilterError("filter.min_level must be a string")
            min_level = min_level_raw.upper()
            if min_level not in LEVEL_ORDER:
                raise LogFilterError(
                    f"filter.min_level must be one of {', '.join(LEVEL_ORDER)}"
                )

        contains_raw = raw.get("contains")
        if contains_raw is not None and not isinstance(contains_raw, str):
            raise LogFilterError("filter.contains must be a string")
        contains = contains_raw.lower() if contains_raw else None

        exc_raw = raw.get("exceptions_only", False)
        if not isinstance(exc_raw, bool):
            raise LogFilterError("filter.exceptions_only must be a boolean")

        return cls(
            min_level=min_level,
            processes=_as_str_list(raw.get("processes"), "processes"),
            loggers=_as_str_list(raw.get("loggers"), "loggers"),
            sessions=_as_str_list(raw.get("sessions"), "sessions"),
            contains=contains,
            exceptions_only=exc_raw,
        )

    def _allowed_levels(self) -> tuple[str, ...]:
        if self.min_level is None:
            return ()
        floor = LEVEL_ORDER[self.min_level]
        return tuple(name for name, rank in LEVEL_ORDER.items() if rank >= floor)

    def matches(self, row: LogEventRow) -> bool:
        """Evaluate the filter against one just-persisted row (live path)."""
        if self.min_level is not None:
            rank = LEVEL_ORDER.get(row.level.upper())
            if rank is None or rank < LEVEL_ORDER[self.min_level]:
                return False
        if self.processes and row.process not in self.processes:
            return False
        if self.sessions and row.session not in self.sessions:
            return False
        if self.loggers and not any(row.logger.startswith(p) for p in self.loggers):
            return False
        if self.exceptions_only and not row.has_exception:
            return False
        if self.contains and self.contains not in row.message.lower():
            return False
        return True

    def sql_where(self) -> tuple[list[str], list[Any]]:
        """Compile the filter to ``WHERE`` fragments + params (backfill path)."""
        clauses: list[str] = []
        params: list[Any] = []

        levels = self._allowed_levels()
        if levels:
            clauses.append(f"level IN ({','.join('?' * len(levels))})")
            params.extend(levels)
        if self.processes:
            clauses.append(f"process IN ({','.join('?' * len(self.processes))})")
            params.extend(self.processes)
        if self.sessions:
            clauses.append(f"session IN ({','.join('?' * len(self.sessions))})")
            params.extend(self.sessions)
        if self.loggers:
            clauses.append(
                "(" + " OR ".join(["logger LIKE ?"] * len(self.loggers)) + ")"
            )
            params.extend(f"{prefix}%" for prefix in self.loggers)
        if self.exceptions_only:
            clauses.append("has_exception = 1")
        if self.contains:
            clauses.append("LOWER(message) LIKE ?")
            params.append(f"%{self.contains}%")
        return clauses, params

    def to_dict(self) -> dict[str, Any]:
        """Echo form returned in ``log.subscribe_ack`` / ``log.status``."""
        return {
            "min_level": self.min_level,
            "processes": list(self.processes),
            "loggers": list(self.loggers),
            "sessions": list(self.sessions),
            "contains": self.contains,
            "exceptions_only": self.exceptions_only,
        }


@dataclass
class BackfillJob:
    """One in-flight ``log.backfill_request``, delivered chunk by chunk.

    A backfill is never sent as a single message: a busy hour can be
    hundreds of thousands of rows, and both a multi-megabyte ZeroMQ frame
    and the SQLite scan that produces it would stall the single-threaded
    main loop. Instead each job keeps a ``seq`` cursor and emits at most
    one bounded chunk per :meth:`LogPubSubHub.poll` call, so an arbitrarily
    large window costs a bounded amount of work per loop iteration.
    """

    sub_id: str
    request_id: str
    where_sql: str
    params: list[Any]
    cursor_seq: int = 0
    chunk_index: int = 0
    sent_rows: int = 0
    max_rows: int = 100_000
    chunk_rows: int = 500


@dataclass
class Subscription:
    """One leased subscription and everything the server buffers for it."""

    sub_id: str
    mode: str
    filt: LogFilter
    lease_sec: float
    notify_interval_sec: float
    max_pending_rows: int
    expires_at: float
    created_at: float = field(default_factory=time.monotonic)

    # NOTIFY-mode accumulator, coalesced and flushed on notify_interval_sec.
    pending_count: int = 0
    pending_levels: dict[str, int] = field(default_factory=dict)
    pending_last_seq: int = 0
    last_notify_at: float = field(default_factory=time.monotonic)

    # STREAM-mode buffer, drained (chunked) on every poll.
    pending_rows: list[dict[str, Any]] = field(default_factory=list)

    # Lifetime counters, reported by log.status.{sub_id}.
    sent_rows: int = 0
    sent_messages: int = 0
    dropped_rows: int = 0
    renewals: int = 0

    def renew(self, now: float) -> None:
        self.expires_at = now + self.lease_sec
        self.renewals += 1

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at

    def status(self, now: float) -> dict[str, Any]:
        return {
            "sub_id": self.sub_id,
            "mode": self.mode,
            "filter": self.filt.to_dict(),
            "lease_sec": self.lease_sec,
            "lease_remaining_sec": round(max(0.0, self.expires_at - now), 3),
            "age_sec": round(now - self.created_at, 3),
            "pending_rows": len(self.pending_rows),
            "pending_count": self.pending_count,
            "sent_rows": self.sent_rows,
            "sent_messages": self.sent_messages,
            "dropped_rows": self.dropped_rows,
            "renewals": self.renewals,
        }


def row_to_dict(seq: int, row: LogEventRow) -> dict[str, Any]:
    """Serialise a persisted row into its LALF-PS JSON representation."""
    return {
        "seq": seq,
        "client_ts": row.client_ts,
        "server_ts": row.server_ts,
        "process": row.process,
        "instance": row.instance,
        "pid": row.pid,
        "host": row.host,
        "session": row.session,
        "level": row.level,
        "logger": row.logger,
        "module": row.module,
        "line": row.line,
        "has_exception": bool(row.has_exception),
        "truncated": bool(row.truncated),
        "message": row.message,
    }


class LogPubSubHub:
    """Owns the LALF-PS sockets, the subscription registry and fan-out.

    Lifecycle mirrors :class:`~edumatcher.log_srv.writer.WriterThread`:
    :meth:`start` once at server startup, :meth:`poll` once per main-loop
    iteration, :meth:`stop` once at shutdown. The hub deliberately does no
    work of its own on a timer thread — everything is driven by the same
    loop that drives the TCP side, which is what keeps all ZeroMQ socket
    access confined to one thread without any locking.
    """

    def __init__(
        self,
        *,
        pub_addr: str,
        pull_addr: str,
        db_path: Path,
        server_name: str,
        lease_sec: float = 30.0,
        max_lease_sec: float = 300.0,
        max_subscribers: int = 32,
        notify_interval_ms: int = 250,
        backfill_chunk_rows: int = 500,
        max_backfill_minutes: int = 1440,
        max_backfill_rows: int = 100_000,
        max_pending_rows: int = 20_000,
        pub_sndhwm: int = 10_000,
        state_interval_sec: float = 5.0,
    ) -> None:
        self._pub_addr = pub_addr
        self._pull_addr = pull_addr
        self._db_path = db_path
        self._server_name = server_name
        self._lease_sec = lease_sec
        self._max_lease_sec = max_lease_sec
        self._max_subscribers = max_subscribers
        self._notify_interval_sec = notify_interval_ms / 1000.0
        self._backfill_chunk_rows = backfill_chunk_rows
        self._max_backfill_minutes = max_backfill_minutes
        self._max_backfill_rows = max_backfill_rows
        self._max_pending_rows = max_pending_rows
        self._pub_sndhwm = pub_sndhwm
        self._state_interval_sec = state_interval_sec

        self._pub: zmq.Socket[bytes] | None = None
        self._pull: zmq.Socket[bytes] | None = None
        self._read_conn: sqlite3.Connection | None = None

        self._subs: dict[str, Subscription] = {}
        self._backfills: dict[str, BackfillJob] = {}

        # Filled by the writer thread, drained by poll() on the main thread.
        # Bounded so that a pathological burst cannot grow without limit if
        # the main loop is somehow starved; overflow is counted and reported.
        self._inbox: "queue.Queue[list[dict[str, Any]]]" = queue.Queue(maxsize=1024)
        self._inbox_dropped = 0
        self._inbox_lock = threading.Lock()

        self._last_seq = 0
        self._last_state_at = 0.0
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Bind both sockets and open the read-only backfill connection."""
        ctx = get_context()
        pub: zmq.Socket[bytes] = ctx.socket(zmq.PUB)
        # A PUB socket with no send high-water mark queues without bound for
        # a subscriber that has stopped reading. Bounding it means the worst
        # case for a wedged-but-connected subscriber is dropped messages, not
        # unbounded growth in pm-log-srv's own resident set.
        pub.setsockopt(zmq.SNDHWM, self._pub_sndhwm)
        pub.setsockopt(zmq.LINGER, 0)
        pub.bind(self._pub_addr)
        self._pub = pub

        pull: zmq.Socket[bytes] = ctx.socket(zmq.PULL)
        pull.setsockopt(zmq.RCVHWM, 1000)
        pull.setsockopt(zmq.LINGER, 0)
        pull.bind(self._pull_addr)
        self._pull = pull

        self._read_conn = open_db(self._db_path, read_only=True)
        self._read_conn.row_factory = sqlite3.Row
        self._last_seq = self._current_max_seq()
        self._started = True

        log.info(
            "LALF-PS interface up: PUB=%s PULL=%s lease=%.0fs max_subscribers=%d",
            self._pub_addr,
            self._pull_addr,
            self._lease_sec,
            self._max_subscribers,
        )

    def stop(self) -> None:
        """Tell every subscriber the server is going away, then close."""
        if not self._started:
            return
        self._publish(
            "log.server_state",
            {
                "server": self._server_name,
                "state": "DOWN",
                "proto": PROTO_VERSION,
                "subscribers": len(self._subs),
                "last_seq": self._last_seq,
                "timestamp": time.time(),
            },
        )
        self._subs.clear()
        self._backfills.clear()
        for sock in (self._pub, self._pull):
            if sock is not None:
                try:
                    sock.close(linger=0)
                except zmq.ZMQError:  # pragma: no cover - defensive
                    pass
        self._pub = None
        self._pull = None
        if self._read_conn is not None:
            self._read_conn.close()
            self._read_conn = None
        self._started = False
        log.info("LALF-PS interface down")

    # ------------------------------------------------------------------
    # Writer-thread entry point
    # ------------------------------------------------------------------

    def on_batch_persisted(self, batch: list[tuple[int, LogEventRow]]) -> None:
        """Accept a committed batch from the writer thread.

        Called on :class:`WriterThread`'s thread — it must therefore do no
        socket IO and no subscription-registry mutation whatsoever. It only
        serialises the rows and hands them over a thread-safe queue; the
        actual matching and publishing happens later, on the main loop.
        """
        if not batch or not self._started:
            return
        rows = [row_to_dict(seq, row) for seq, row in batch]
        try:
            self._inbox.put_nowait(rows)
        except queue.Full:
            with self._inbox_lock:
                self._inbox_dropped += len(rows)

    # ------------------------------------------------------------------
    # Main-loop entry point
    # ------------------------------------------------------------------

    def poll(self) -> None:
        """One servicing pass — call once per main-loop iteration."""
        if not self._started:
            return
        now = time.monotonic()
        self._handle_control_requests(now)
        self._fan_out_new_rows()
        self._flush_notifies(now)
        self._flush_streams()
        self._pump_backfills()
        self._reap_expired(now)
        self._publish_server_state(now)

    # ------------------------------------------------------------------
    # Control channel (PULL)
    # ------------------------------------------------------------------

    def _handle_control_requests(self, now: float) -> None:
        if self._pull is None:
            return
        while True:
            try:
                frames = self._pull.recv_multipart(zmq.NOBLOCK)
            except zmq.Again:
                return
            except zmq.ZMQError as exc:  # pragma: no cover - defensive
                log.warning("LALF-PS control recv failed: %s", exc)
                return

            try:
                topic, payload = decode(frames)
            except Exception as exc:
                log.warning("LALF-PS: undecodable control frame dropped: %s", exc)
                continue

            sub_id = payload.get("sub_id")
            if not isinstance(sub_id, str) or not sub_id:
                # Without a sub_id there is no reply topic to answer on, so
                # the only possible action is to drop and log it.
                log.warning("LALF-PS: %s without usable sub_id dropped", topic)
                continue

            try:
                self._dispatch_control(topic, sub_id, payload, now)
            except LogFilterError as exc:
                self._error(sub_id, ERR_INVALID_FILTER, str(exc))
            except ValueError as exc:
                self._error(sub_id, ERR_BAD_REQUEST, str(exc))
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("LALF-PS: handler for %s failed", topic)
                self._error(sub_id, ERR_INTERNAL, str(exc))

    def _dispatch_control(
        self, topic: str, sub_id: str, payload: dict[str, Any], now: float
    ) -> None:
        if topic == "log.subscribe":
            self._handle_subscribe(sub_id, payload, now)
        elif topic == "log.renew":
            self._handle_renew(sub_id, now)
        elif topic == "log.unsubscribe":
            self._handle_unsubscribe(sub_id)
        elif topic == "log.backfill_request":
            self._handle_backfill_request(sub_id, payload, now)
        elif topic == "log.status_request":
            self._handle_status_request(sub_id, now)
        else:
            self._error(sub_id, ERR_BAD_REQUEST, f"unsupported topic: {topic}")

    def _handle_subscribe(
        self, sub_id: str, payload: dict[str, Any], now: float
    ) -> None:
        """Create or replace a subscription; idempotent by ``sub_id``.

        Re-sending ``log.subscribe`` for an existing ``sub_id`` is not an
        error — it replaces the mode/filter and re-emits the ack. That is
        deliberate: ZeroMQ's slow-joiner behaviour means a subscriber's
        very first ack can be published before its ``SUB`` connection has
        finished establishing, and a retry is the standard cure.
        """
        mode_raw = payload.get("mode", MODE_STREAM)
        if not isinstance(mode_raw, str):
            raise ValueError("mode must be a string")
        mode = mode_raw.upper()
        if mode not in VALID_MODES:
            self._error(
                sub_id,
                ERR_INVALID_MODE,
                f"mode must be one of {', '.join(VALID_MODES)}",
            )
            return

        existing = self._subs.get(sub_id)
        if existing is None and len(self._subs) >= self._max_subscribers:
            self._error(
                sub_id,
                ERR_TOO_MANY_SUBS,
                f"server is at its max_subscribers limit ({self._max_subscribers})",
            )
            return

        filt = LogFilter.from_payload(payload.get("filter"))
        lease_sec = self._clamp_lease(payload.get("lease_sec"))
        notify_interval = self._clamp_notify_interval(payload.get("notify_interval_ms"))

        sub = Subscription(
            sub_id=sub_id,
            mode=mode,
            filt=filt,
            lease_sec=lease_sec,
            notify_interval_sec=notify_interval,
            max_pending_rows=self._max_pending_rows,
            expires_at=now + lease_sec,
        )
        if existing is not None:
            # Preserve lifetime counters across a re-subscribe so a viewer
            # that re-issues its subscription does not appear to reset.
            sub.created_at = existing.created_at
            sub.sent_rows = existing.sent_rows
            sub.sent_messages = existing.sent_messages
            sub.dropped_rows = existing.dropped_rows
            sub.renewals = existing.renewals
        self._subs[sub_id] = sub

        self._publish(
            f"log.subscribe_ack.{sub_id}",
            {
                "accepted": True,
                "sub_id": sub_id,
                "proto": PROTO_VERSION,
                "server": self._server_name,
                "mode": mode,
                "filter": filt.to_dict(),
                "lease_sec": lease_sec,
                "renew_before_sec": round(lease_sec / 2.0, 3),
                "notify_interval_ms": int(notify_interval * 1000),
                "last_seq": self._last_seq,
                "backfill_request_id": "",
                "timestamp": time.time(),
            },
        )
        log.info(
            "LALF-PS subscribe sub_id=%s mode=%s lease=%.0fs filter=%s",
            sub_id,
            mode,
            lease_sec,
            filt.to_dict(),
        )

        minutes = payload.get("backfill_minutes")
        if minutes:
            self._start_backfill(sub_id, payload, filt, minutes)

    def _handle_renew(self, sub_id: str, now: float) -> None:
        sub = self._subs.get(sub_id)
        if sub is None:
            self._error(
                sub_id, ERR_UNKNOWN_SUB, "no such subscription; send log.subscribe"
            )
            return
        sub.renew(now)
        self._publish(
            f"log.renew_ack.{sub_id}",
            {
                "accepted": True,
                "sub_id": sub_id,
                "lease_sec": sub.lease_sec,
                "expires_in_sec": round(sub.expires_at - now, 3),
                "last_seq": self._last_seq,
                "timestamp": time.time(),
            },
        )

    def _handle_unsubscribe(self, sub_id: str) -> None:
        existed = self._subs.pop(sub_id, None) is not None
        self._backfills.pop(sub_id, None)
        self._publish(
            f"log.unsubscribe_ack.{sub_id}",
            {
                "accepted": existed,
                "sub_id": sub_id,
                "reason": "" if existed else "no such subscription",
                "timestamp": time.time(),
            },
        )
        if existed:
            log.info("LALF-PS unsubscribe sub_id=%s", sub_id)

    def _handle_status_request(self, sub_id: str, now: float) -> None:
        sub = self._subs.get(sub_id)
        payload: dict[str, Any] = {
            "sub_id": sub_id,
            "server": self._server_name,
            "proto": PROTO_VERSION,
            "subscribers": len(self._subs),
            "active_backfills": len(self._backfills),
            "last_seq": self._last_seq,
            "inbox_dropped": self._inbox_dropped,
            "subscription": sub.status(now) if sub is not None else None,
            "timestamp": time.time(),
        }
        self._publish(f"log.status.{sub_id}", payload)

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------

    def _handle_backfill_request(
        self, sub_id: str, payload: dict[str, Any], now: float
    ) -> None:
        """Serve an ad-hoc "last n minutes" request.

        A backfill does not require an active subscription for the *query*
        itself, but it does require one for delivery: without a lease the
        server has no way to learn that the requester died mid-transfer and
        would keep pushing chunks to nobody.
        """
        if sub_id not in self._subs:
            self._error(
                sub_id,
                ERR_UNKNOWN_SUB,
                "backfill requires an active subscription; send log.subscribe first",
            )
            return

        minutes = payload.get("minutes")
        filter_raw = payload.get("filter")
        filt = (
            self._subs[sub_id].filt
            if filter_raw is None
            else LogFilter.from_payload(filter_raw)
        )
        self._start_backfill(sub_id, payload, filt, minutes)
        # Requesting a backfill is itself proof of life; treat it as a renew
        # so a subscriber pulling a large window never expires mid-transfer.
        self._subs[sub_id].renew(now)

    def _start_backfill(
        self,
        sub_id: str,
        payload: dict[str, Any],
        filt: LogFilter,
        minutes_raw: object,
    ) -> None:
        try:
            minutes = int(minutes_raw)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            self._error(sub_id, ERR_INVALID_WINDOW, "minutes must be an integer")
            return
        if minutes <= 0:
            self._error(sub_id, ERR_INVALID_WINDOW, "minutes must be > 0")
            return
        if minutes > self._max_backfill_minutes:
            self._error(
                sub_id,
                ERR_INVALID_WINDOW,
                f"minutes exceeds server max_backfill_minutes"
                f"={self._max_backfill_minutes}",
            )
            return

        max_rows = self._max_backfill_rows
        req_max = payload.get("max_rows")
        if isinstance(req_max, int) and 0 < req_max < max_rows:
            max_rows = req_max

        request_id = f"{sub_id}-{int(time.time() * 1000):x}"
        cutoff = iso_utc(time.time() - minutes * 60)
        clauses, params = filt.sql_where()
        clauses.insert(0, "client_ts >= ?")
        params.insert(0, cutoff)

        self._backfills[sub_id] = BackfillJob(
            sub_id=sub_id,
            request_id=request_id,
            where_sql=" WHERE " + " AND ".join(clauses),
            params=params,
            max_rows=max_rows,
            chunk_rows=self._backfill_chunk_rows,
        )
        log.info(
            "LALF-PS backfill start sub_id=%s request_id=%s minutes=%d max_rows=%d",
            sub_id,
            request_id,
            minutes,
            max_rows,
        )

    def _pump_backfills(self) -> None:
        """Emit at most one chunk per active job, then stop."""
        if not self._backfills or self._read_conn is None:
            return
        for sub_id, job in list(self._backfills.items()):
            if sub_id not in self._subs:
                # Lease reaped underneath us — abandon the job silently.
                self._backfills.pop(sub_id, None)
                continue

            remaining = job.max_rows - job.sent_rows
            limit = min(job.chunk_rows, remaining)
            sql = (
                f"{_SELECT_BACKFILL}{job.where_sql} AND seq > ? "
                f"ORDER BY seq ASC LIMIT ?"
            )
            try:
                cursor = self._read_conn.execute(
                    sql, (*job.params, job.cursor_seq, limit)
                )
                fetched = cursor.fetchall()
            except sqlite3.Error as exc:
                log.error("LALF-PS backfill query failed for %s: %s", sub_id, exc)
                self._error(sub_id, ERR_INTERNAL, f"backfill query failed: {exc}")
                self._backfills.pop(sub_id, None)
                continue

            rows = [self._sqlite_row_to_dict(r) for r in fetched]
            if rows:
                job.cursor_seq = int(rows[-1]["seq"])
                job.sent_rows += len(rows)
            truncated = job.sent_rows >= job.max_rows and len(rows) == limit
            done = len(rows) < limit or truncated

            self._publish(
                f"log.backfill.{sub_id}",
                {
                    "sub_id": sub_id,
                    "request_id": job.request_id,
                    "chunk": job.chunk_index,
                    "rows": rows,
                    "row_count": len(rows),
                    "done": done,
                    "total_sent": job.sent_rows,
                    "truncated": truncated,
                    "last_seq": job.cursor_seq,
                    "timestamp": time.time(),
                },
            )
            job.chunk_index += 1
            sub = self._subs.get(sub_id)
            if sub is not None:
                sub.sent_messages += 1
                sub.sent_rows += len(rows)

            if done:
                self._backfills.pop(sub_id, None)
                log.info(
                    "LALF-PS backfill done sub_id=%s rows=%d chunks=%d truncated=%s",
                    sub_id,
                    job.sent_rows,
                    job.chunk_index,
                    truncated,
                )

    @staticmethod
    def _sqlite_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        out: dict[str, Any] = {key: row[key] for key in _ROW_COLUMNS}
        out["has_exception"] = bool(out["has_exception"])
        out["truncated"] = bool(out["truncated"])
        return out

    # ------------------------------------------------------------------
    # Live fan-out
    # ------------------------------------------------------------------

    def _fan_out_new_rows(self) -> None:
        """Drain the writer-thread inbox and route rows to subscriptions."""
        while True:
            try:
                rows = self._inbox.get_nowait()
            except queue.Empty:
                return
            for row in rows:
                seq = int(row["seq"])
                if seq > self._last_seq:
                    self._last_seq = seq
                for sub in self._subs.values():
                    if not self._row_matches(sub.filt, row):
                        continue
                    if sub.mode == MODE_NOTIFY:
                        sub.pending_count += 1
                        level = str(row["level"])
                        sub.pending_levels[level] = sub.pending_levels.get(level, 0) + 1
                        sub.pending_last_seq = max(sub.pending_last_seq, seq)
                    else:
                        sub.pending_rows.append(row)
                        overflow = len(sub.pending_rows) - sub.max_pending_rows
                        if overflow > 0:
                            # Alive but too slow: shed the oldest rows and tell
                            # the subscriber how many it missed, rather than
                            # letting one lagging viewer bloat the server.
                            del sub.pending_rows[:overflow]
                            sub.dropped_rows += overflow

    @staticmethod
    def _row_matches(filt: LogFilter, row: dict[str, Any]) -> bool:
        """Apply a filter to an already-serialised row dict."""
        if filt.min_level is not None:
            rank = LEVEL_ORDER.get(str(row["level"]).upper())
            if rank is None or rank < LEVEL_ORDER[filt.min_level]:
                return False
        if filt.processes and row["process"] not in filt.processes:
            return False
        if filt.sessions and row["session"] not in filt.sessions:
            return False
        if filt.loggers:
            logger_name = str(row["logger"] or "")
            if not any(logger_name.startswith(p) for p in filt.loggers):
                return False
        if filt.exceptions_only and not row["has_exception"]:
            return False
        if filt.contains and filt.contains not in str(row["message"]).lower():
            return False
        return True

    def _flush_notifies(self, now: float) -> None:
        for sub in self._subs.values():
            if sub.mode != MODE_NOTIFY or sub.pending_count == 0:
                continue
            if now - sub.last_notify_at < sub.notify_interval_sec:
                continue
            self._publish(
                f"log.notify.{sub.sub_id}",
                {
                    "sub_id": sub.sub_id,
                    "count": sub.pending_count,
                    "levels": dict(sub.pending_levels),
                    "last_seq": sub.pending_last_seq,
                    "server_last_seq": self._last_seq,
                    "timestamp": time.time(),
                },
            )
            sub.sent_messages += 1
            sub.pending_count = 0
            sub.pending_levels.clear()
            sub.last_notify_at = now

    def _flush_streams(self) -> None:
        for sub in self._subs.values():
            if sub.mode != MODE_STREAM or not sub.pending_rows:
                continue
            chunk = sub.pending_rows[: self._backfill_chunk_rows]
            del sub.pending_rows[: len(chunk)]
            dropped = sub.dropped_rows
            self._publish(
                f"log.event.{sub.sub_id}",
                {
                    "sub_id": sub.sub_id,
                    "rows": chunk,
                    "row_count": len(chunk),
                    "seq_from": int(chunk[0]["seq"]),
                    "seq_to": int(chunk[-1]["seq"]),
                    "server_last_seq": self._last_seq,
                    "dropped": dropped,
                    "timestamp": time.time(),
                },
            )
            sub.sent_rows += len(chunk)
            sub.sent_messages += 1

    # ------------------------------------------------------------------
    # Lease expiry / server state
    # ------------------------------------------------------------------

    def _reap_expired(self, now: float) -> None:
        """Drop every subscription whose lease has run out.

        This is the whole answer to "the subscriber died": nothing about a
        crashed process is visible on a ``PUB`` socket, so the server relies
        entirely on the absence of ``log.renew``. The final
        ``log.lease_expired`` is published on the off-chance the subscriber
        is in fact alive but merely wedged — it tells such a client
        unambiguously that it must re-subscribe rather than sit waiting for
        rows that will never come.
        """
        for sub_id, sub in list(self._subs.items()):
            if not sub.is_expired(now):
                continue
            self._subs.pop(sub_id, None)
            self._backfills.pop(sub_id, None)
            self._publish(
                f"log.lease_expired.{sub_id}",
                {
                    "sub_id": sub_id,
                    "reason": "lease expired; no log.renew received in time",
                    "lease_sec": sub.lease_sec,
                    "dropped_rows": sub.dropped_rows + len(sub.pending_rows),
                    "timestamp": time.time(),
                },
            )
            log.info(
                "LALF-PS lease expired sub_id=%s after %.1fs idle (buffered=%d)",
                sub_id,
                sub.lease_sec,
                len(sub.pending_rows),
            )

    def _publish_server_state(self, now: float) -> None:
        if now - self._last_state_at < self._state_interval_sec:
            return
        self._last_state_at = now
        self._publish(
            "log.server_state",
            {
                "server": self._server_name,
                "state": "UP",
                "proto": PROTO_VERSION,
                "pub_addr": self._pub_addr,
                "pull_addr": self._pull_addr,
                "subscribers": len(self._subs),
                "active_backfills": len(self._backfills),
                "last_seq": self._last_seq,
                "inbox_dropped": self._inbox_dropped,
                "default_lease_sec": self._lease_sec,
                "timestamp": time.time(),
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clamp_lease(self, raw: object) -> float:
        if raw is None:
            return self._lease_sec
        try:
            requested = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return self._lease_sec
        if requested <= 0:
            return self._lease_sec
        return min(requested, self._max_lease_sec)

    def _clamp_notify_interval(self, raw: object) -> float:
        if raw is None:
            return self._notify_interval_sec
        try:
            requested_ms = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return self._notify_interval_sec
        if requested_ms <= 0:
            return self._notify_interval_sec
        # Floor at the server default so a subscriber cannot ask to be woken
        # more often than the server is willing to publish.
        return max(requested_ms / 1000.0, self._notify_interval_sec)

    def _current_max_seq(self) -> int:
        if self._read_conn is None:
            return 0
        try:
            row = self._read_conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM log_events"
            ).fetchone()
        except sqlite3.Error:  # pragma: no cover - defensive
            return 0
        return int(row[0]) if row else 0

    def _error(self, sub_id: str, code: str, msg: str) -> None:
        log.debug("LALF-PS error to sub_id=%s code=%s msg=%s", sub_id, code, msg)
        self._publish(
            f"log.error.{sub_id}",
            {
                "accepted": False,
                "sub_id": sub_id,
                "code": code,
                "reason": msg,
                "timestamp": time.time(),
            },
        )

    def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self._pub is None:
            return
        try:
            self._pub.send_multipart(encode(topic, payload), zmq.NOBLOCK)
        except zmq.Again:
            # SNDHWM reached — by design we drop rather than block the loop.
            log.debug("LALF-PS: PUB high-water mark hit, dropped %s", topic)
        except zmq.ZMQError as exc:  # pragma: no cover - defensive
            log.warning("LALF-PS: publish of %s failed: %s", topic, exc)

    # ------------------------------------------------------------------
    # Introspection (used by tests and the server's debug summary)
    # ------------------------------------------------------------------

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    @property
    def active_backfill_count(self) -> int:
        return len(self._backfills)

    @property
    def last_seq(self) -> int:
        return self._last_seq
