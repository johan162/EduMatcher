"""Batched, single-writer SQLite persistence for ``pm-log-srv``.

§7.4: every accepted ``LOG`` row is handed to one dedicated writer thread
via a thread-safe queue rather than written inline by whichever connection
happens to receive it — this keeps SQLite's single-writer model conflict-free
(no ``SQLITE_BUSY`` contention between concurrently-handled connections) and
lets the writer batch up to ``write_batch_size`` rows or
``write_batch_interval_ms`` milliseconds, whichever comes first, in one
transaction. This is the one piece of shared mutable state in the whole
process, deliberately kept as small as possible.
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass

from edumatcher.log_srv.schema import (
    INCREMENT_TOTAL_LOG_EVENTS,
    INCREMENT_TOTAL_TRUNCATED,
    INSERT_LOG_EVENT,
    UPDATE_PROCESS_LAST_SEEN_AND_COUNT_BY_N,
)

log = logging.getLogger(__name__)


@dataclass
class LogEventRow:
    """One row destined for ``log_events``, plus its owning session id."""

    client_ts: str
    server_ts: str
    process: str
    instance: str | None
    pid: int
    host: str
    session: str
    level: str
    logger: str
    module: str | None
    line: int | None
    has_exception: bool
    truncated: bool
    message: str


class WriterThread:
    """Owns the single writable SQLite connection and drains queued rows.

    Started once at server startup and stopped once at shutdown. Every
    per-connection handler enqueues rows via :meth:`enqueue`; this thread
    is the only code in the process that ever calls ``INSERT`` against
    ``log_events``, so callers never see ``SQLITE_BUSY`` regardless of how
    many LALF connections are concurrently sending ``LOG`` (§7.4).
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        batch_size: int = 50,
        batch_interval_ms: int = 100,
    ) -> None:
        self._conn = conn
        self._batch_size = batch_size
        self._batch_interval_sec = batch_interval_ms / 1000.0
        self._queue: "queue.Queue[LogEventRow]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        # Depth is read by the server's backpressure check (§5.8/§15.13) —
        # queue.Queue.qsize() is documented as approximate but "good enough
        # for backpressure" per the design; exposed as a property so callers
        # never reach into the private queue directly.
        self._lock = threading.Lock()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def enqueue(self, row: LogEventRow) -> None:
        self._queue.put(row)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name="log-srv-writer", daemon=True
        )
        self._thread.start()

    def stop(self, *, flush_timeout_sec: float = 2.0) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=flush_timeout_sec)
        # Final drain of anything left in the queue at shutdown, best-effort.
        self._drain_and_write(force=True)

    def _run(self) -> None:
        while self._running:
            wrote = self._drain_and_write(force=False)
            if not wrote:
                time.sleep(self._batch_interval_sec)

    def _drain_and_write(self, *, force: bool) -> int:
        rows: list[LogEventRow] = []
        deadline = time.monotonic() + self._batch_interval_sec
        while len(rows) < self._batch_size:
            try:
                if force:
                    row = self._queue.get_nowait()
                else:
                    timeout = max(0.0, deadline - time.monotonic())
                    if timeout <= 0 and rows:
                        break
                    row = self._queue.get(timeout=timeout if timeout > 0 else 0.01)
            except queue.Empty:
                break
            rows.append(row)
            if force:
                continue

        if not rows:
            return 0

        truncated_count = sum(1 for r in rows if r.truncated)
        try:
            with self._lock, self._conn:
                self._conn.executemany(
                    INSERT_LOG_EVENT,
                    [
                        (
                            r.client_ts,
                            r.server_ts,
                            r.process,
                            r.instance,
                            r.pid,
                            r.host,
                            r.session,
                            r.level,
                            r.logger,
                            r.module,
                            r.line,
                            int(r.has_exception),
                            int(r.truncated),
                            r.message,
                        )
                        for r in rows
                    ],
                )
                self._conn.execute(INCREMENT_TOTAL_LOG_EVENTS, (len(rows),))
                if truncated_count:
                    self._conn.execute(INCREMENT_TOTAL_TRUNCATED, (truncated_count,))
                # Update processes.last_seen_at/log_count for every distinct
                # session represented in this batch — one UPDATE per session
                # touched, not per row, since a session may contribute many
                # rows to a single batch.
                per_session_counts: dict[str, tuple[str, int]] = {}
                for r in rows:
                    prev_ts, prev_n = per_session_counts.get(
                        r.session, (r.server_ts, 0)
                    )
                    ts = r.server_ts if r.server_ts > prev_ts else prev_ts
                    per_session_counts[r.session] = (ts, prev_n + 1)
                for session_id, (ts, n) in per_session_counts.items():
                    self._conn.execute(
                        UPDATE_PROCESS_LAST_SEEN_AND_COUNT_BY_N,
                        (ts, n, session_id),
                    )
        except sqlite3.Error as exc:
            log.error(
                "writer thread: failed to persist batch of %d rows: %s", len(rows), exc
            )
            return 0

        return len(rows)
