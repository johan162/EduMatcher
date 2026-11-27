"""The Audit GUI's job store (workplan AG9, design §7.3).

An application-owned SQLite file in the derivative store (``jobs.db``): one
row per job, the only channel between the API process and the worker. The
API submits, reads and cancels; the worker claims, reports progress and a
heartbeat, and finishes. Every connection is short-lived and closed.

States: ``queued``, ``running``, ``succeeded``, ``failed``, ``cancelled``,
``unavailable`` (the request cannot be served by this evidence, e.g. too
little disk). ``progress`` is ``(done, total)`` only once the total is
known; before that it is None, never a made-up percentage.

Identical *active* requests (same kind, snapshot and options) share one job.
A job whose worker died, or stopped beating, is ``failed`` with reason
``WORKER_LOST`` when the API next reconciles (on every job read and at
start-up).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from collections.abc import Callable, Generator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"
UNAVAILABLE = "unavailable"
ACTIVE = frozenset({QUEUED, RUNNING})

#: Job kinds of R1 (design §8 ``POST /jobs``).
PREPARE = "prepare"
VERIFY = "verify"
FORENSICS_IMPORT = "forensics_import"
KINDS = frozenset({PREPARE, VERIFY, FORENSICS_IMPORT})

#: Reasons a job ended other than by succeeding (stable codes).
WORKER_LOST = "WORKER_LOST"
TIMEOUT = "TIMEOUT"
CANCELLED_BY_USER = "CANCELLED"
JOB_ERROR = "JOB_ERROR"
DISK_LOW = "DISK_LOW"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    options TEXT NOT NULL,
    dedup_key TEXT NOT NULL,
    state TEXT NOT NULL,
    stage TEXT,
    done INTEGER,
    total INTEGER,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    worker_pid INTEGER,
    heartbeat_at REAL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    reason TEXT,
    detail TEXT,
    result TEXT
);
CREATE INDEX IF NOT EXISTS jobs_active ON jobs (dedup_key, state);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs (state, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


@dataclass(frozen=True)
class Job:
    job_id: str
    kind: str
    snapshot_id: str
    options: dict[str, Any]
    state: str
    stage: str | None
    done: int | None
    total: int | None
    cancel_requested: bool
    worker_pid: int | None
    #: Epoch seconds of the worker's last beat.
    heartbeat_at: float | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    reason: str | None
    detail: str | None
    result: dict[str, Any] | None

    @property
    def progress(self) -> tuple[int, int] | None:
        if self.total is None or self.done is None:
            return None
        return self.done, self.total


def dedup_key(kind: str, snapshot_id: str, options: dict[str, Any]) -> str:
    raw = json.dumps([kind, snapshot_id, options], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


class JobStore:
    """The job table; safe to use from several threads and processes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        # executescript commits on its own: not inside _tx's transaction.
        with closing(sqlite3.connect(path, timeout=30)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    @contextmanager
    def _tx(self) -> Generator[sqlite3.Connection]:
        """One short transaction (``BEGIN IMMEDIATE``: writers serialise)."""
        with closing(
            sqlite3.connect(self.path, timeout=30, isolation_level=None)
        ) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    # -- the API side ---------------------------------------------------

    def submit(
        self, kind: str, snapshot_id: str, options: dict[str, Any]
    ) -> tuple[Job, bool]:
        """The active job for this request, or a new queued one; and
        whether it was created."""
        if kind not in KINDS:
            raise ValueError(f"unknown job kind {kind!r}")
        key = dedup_key(kind, snapshot_id, options)
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE dedup_key = ? AND state IN (?, ?) "
                "ORDER BY created_at LIMIT 1",
                (key, QUEUED, RUNNING),
            ).fetchone()
            if row is not None:
                return _job(row), False
            job_id = "j-" + secrets.token_hex(8)
            conn.execute(
                "INSERT INTO jobs (job_id, kind, snapshot_id, options, dedup_key, "
                "state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_id, kind, snapshot_id, json.dumps(options), key, QUEUED, _now()),
            )
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return _job(row), True

    def get(self, job_id: str) -> Job | None:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return _job(row) if row is not None else None

    def latest(
        self, kind: str, snapshot_id: str, state: str | None = None
    ) -> Job | None:
        """The most recent job of `kind` for the snapshot (in `state`)."""
        query = "SELECT * FROM jobs WHERE kind = ? AND snapshot_id = ?"
        args: list[Any] = [kind, snapshot_id]
        if state is not None:
            query += " AND state = ?"
            args.append(state)
        with self._tx() as conn:
            row = conn.execute(query + " ORDER BY rowid DESC LIMIT 1", args).fetchone()
        return _job(row) if row is not None else None

    def cancel(self, job_id: str) -> Job | None:
        """A queued job ends now; a running one is asked to stop."""
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            if row["state"] == QUEUED:
                conn.execute(
                    "UPDATE jobs SET state = ?, reason = ?, finished_at = ? WHERE job_id = ?",
                    (CANCELLED, CANCELLED_BY_USER, _now(), job_id),
                )
            elif row["state"] == RUNNING:
                conn.execute(
                    "UPDATE jobs SET cancel_requested = 1 WHERE job_id = ?", (job_id,)
                )
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return _job(row)

    def reconcile(self, alive: Callable[[int], bool], stale_after: float) -> list[Job]:
        """Fail every running job whose worker is gone or silent for more
        than `stale_after` seconds; the jobs so ended."""
        lost: list[Job] = []
        with self._tx() as conn:
            now = _epoch()
            for row in conn.execute(
                "SELECT * FROM jobs WHERE state = ?", (RUNNING,)
            ).fetchall():
                pid, beat = row["worker_pid"], row["heartbeat_at"]
                dead = pid is None or not alive(int(pid))
                silent = beat is None or now - float(beat) > stale_after
                if dead or silent:
                    conn.execute(
                        "UPDATE jobs SET state = ?, reason = ?, detail = ?, finished_at = ? "
                        "WHERE job_id = ?",
                        (
                            FAILED,
                            WORKER_LOST,
                            "the worker process ended or stopped reporting while running this job",
                            _now(),
                            row["job_id"],
                        ),
                    )
                    lost.append(_job(conn.execute("SELECT * FROM jobs WHERE job_id = ?", (row["job_id"],)).fetchone()))  # fmt: skip
        return lost

    # -- the worker side ------------------------------------------------

    def claim(self, worker_pid: int) -> Job | None:
        """The oldest queued job, now running for `worker_pid`."""
        with self._tx() as conn:
            row = conn.execute(
                "SELECT job_id FROM jobs WHERE state = ? ORDER BY created_at, rowid LIMIT 1",
                (QUEUED,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET state = ?, worker_pid = ?, started_at = ?, heartbeat_at = ? "
                "WHERE job_id = ?",
                (RUNNING, worker_pid, _now(), _epoch(), row["job_id"]),
            )
            claimed = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (row["job_id"],)
            ).fetchone()
        return _job(claimed)

    def heartbeat(self, job_id: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE jobs SET heartbeat_at = ? WHERE job_id = ?", (_epoch(), job_id)
            )

    def progress(
        self, job_id: str, stage: str, done: int | None, total: int | None
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE jobs SET stage = ?, done = ?, total = ?, heartbeat_at = ? WHERE job_id = ?",
                (stage, done, total, _epoch(), job_id),
            )

    def cancel_requested(self, job_id: str) -> bool:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

    def finish(
        self,
        job_id: str,
        state: str,
        *,
        reason: str | None = None,
        detail: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE jobs SET state = ?, reason = ?, detail = ?, result = ?, finished_at = ? "
                "WHERE job_id = ?",
                (
                    state,
                    reason,
                    detail,
                    json.dumps(result) if result is not None else None,
                    _now(),
                    job_id,
                ),
            )


def _job(row: sqlite3.Row) -> Job:
    return Job(
        job_id=row["job_id"],
        kind=row["kind"],
        snapshot_id=row["snapshot_id"],
        options=json.loads(row["options"]),
        state=row["state"],
        stage=row["stage"],
        done=row["done"],
        total=row["total"],
        cancel_requested=bool(row["cancel_requested"]),
        worker_pid=row["worker_pid"],
        heartbeat_at=row["heartbeat_at"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        reason=row["reason"],
        detail=row["detail"],
        result=json.loads(row["result"]) if row["result"] else None,
    )


__all__ = [
    "ACTIVE",
    "CANCELLED",
    "FAILED",
    "FORENSICS_IMPORT",
    "KINDS",
    "PREPARE",
    "QUEUED",
    "RUNNING",
    "SUCCEEDED",
    "UNAVAILABLE",
    "VERIFY",
    "WORKER_LOST",
    "Job",
    "JobStore",
]
