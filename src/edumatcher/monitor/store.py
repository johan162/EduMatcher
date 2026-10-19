"""``metrics.db``: pm-monitor's history for the operator dashboard (§9.5).

pm-monitor is the only writer; the dashboard bridge reads the file read-only.
WAL mode lets those reads run while pm-monitor writes. A second pm-monitor on
the same file is refused (an exclusive lock on ``metrics.db.lock``), since two
writers would each add their own increments to the same daily totals.

What is written, and when
-------------------------
* ``samples_raw`` -- every 10 s, the latest value of each series updated since
  the previous write (one row per series, not one per beacon).
* ``samples_1m`` -- one row per series per closed minute, from every sample
  pm-monitor received (2 s resolution), not from the 10 s raw rows: min, avg,
  max, last, the number of samples, and for a counter the reset-corrected
  increment (``delta``). A minute written partly before a restart is merged
  with the rest of it afterwards.
* ``daily_totals`` -- per trading date (session timezone) and series, the sum
  of the increments counted into "today" (§9.4). Kept for good.
* ``counter_last`` -- the last value and ``boot_id`` of every counter series.
* ``events`` -- every ``health.event``; its ``seq`` is the event's ``seq``.

``daily_totals`` and ``counter_last`` are written in the same transaction, so
after a restart pm-monitor resumes exactly where the file says it was: today's
totals come back, and the first beacon of a process that kept running counts
only what happened while pm-monitor was down (I69).

Retention runs hourly: raw rows older than ``raw_hours``, minute rows and
events older than ``minute_days``; then ``PRAGMA incremental_vacuum`` returns
the freed pages, so the file stops growing once it holds its window.

Timestamps are UTC ISO-8601 with milliseconds (``monitor.timefmt``); the
session timezone is pinned in ``metrics_meta`` on first open and a mismatch is
refused, as ``pm-stats`` does (F21).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from edumatcher.monitor.timefmt import iso_utc

try:  # POSIX; on Windows a second writer is documented as unsupported
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

RAW_EVERY_SEC = 10.0
RETENTION_EVERY_SEC = 3600.0
MINUTE = 60.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

-- One row per series; the sample tables refer to it by id, so a sample row
-- does not repeat its source, name and label (I70).
CREATE TABLE IF NOT EXISTS series (
    id      INTEGER PRIMARY KEY,
    source  TEXT NOT NULL,          -- "process/instance@host" or "host"
    name    TEXT NOT NULL,
    label   TEXT NOT NULL DEFAULT '',
    UNIQUE (name, label, source)
);

CREATE TABLE IF NOT EXISTS samples_raw (
    series  INTEGER NOT NULL,       -- series.id
    ts      TEXT NOT NULL,
    value   REAL NOT NULL,
    PRIMARY KEY (series, ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS samples_1m (
    series  INTEGER NOT NULL,       -- series.id
    ts      TEXT NOT NULL,          -- bucket start
    v_min   REAL, v_avg REAL, v_max REAL, v_last REAL,
    n       INTEGER NOT NULL,       -- samples in the bucket
    delta   REAL,                   -- counters: reset-corrected increment
    PRIMARY KEY (series, ts)
) WITHOUT ROWID;

-- The sample tables with their series spelled out, for people writing SQL.
CREATE VIEW IF NOT EXISTS v_samples_raw AS
    SELECT r.ts, s.source, s.name, s.label, r.value
    FROM samples_raw r JOIN series s ON s.id = r.series;
CREATE VIEW IF NOT EXISTS v_samples_1m AS
    SELECT m.ts, s.source, s.name, s.label,
           m.v_min, m.v_avg, m.v_max, m.v_last, m.n, m.delta
    FROM samples_1m m JOIN series s ON s.id = m.series;

CREATE TABLE IF NOT EXISTS daily_totals (
    date    TEXT NOT NULL,          -- trading date in the session timezone
    source  TEXT NOT NULL,
    name    TEXT NOT NULL,
    label   TEXT NOT NULL DEFAULT '',
    total   REAL NOT NULL,
    PRIMARY KEY (date, name, label, source)
);
-- avg_per_day looks up one name (and label) across dates; kept for good, so
-- without this every lookup would scan years of rows (review R6).
CREATE INDEX IF NOT EXISTS idx_daily_name ON daily_totals(name, label, date);

CREATE TABLE IF NOT EXISTS counter_last (
    source  TEXT NOT NULL,
    name    TEXT NOT NULL,
    label   TEXT NOT NULL DEFAULT '',
    boot_id TEXT NOT NULL,
    value   REAL NOT NULL,
    ts      TEXT NOT NULL,
    PRIMARY KEY (source, name, label)
);

CREATE TABLE IF NOT EXISTS events (
    seq      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    kind     TEXT NOT NULL,
    severity TEXT NOT NULL,
    subject  TEXT NOT NULL,         -- gateway id, process key, symbol, rule
    detail   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ev_ts ON events(ts);
"""

SeriesKey = tuple[str, str, str]  # (source, name, label)


class StoreLockedError(RuntimeError):
    """Another pm-monitor already writes this metrics.db."""


class IncompatibleStoreError(RuntimeError):
    """The file was recorded under a different session timezone."""


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create the current schema (idempotent)."""
    conn.executescript(SCHEMA)


@dataclass
class _Minute:
    """One series' samples within one minute."""

    start: float
    v_min: float
    v_max: float
    total: float
    n: int
    last: float
    delta: float | None  # None for a gauge

    def add(self, value: float) -> None:
        self.v_min = min(self.v_min, value)
        self.v_max = max(self.v_max, value)
        self.total += value
        self.n += 1
        self.last = value


class MetricsStore:
    """The single writer of ``metrics.db``."""

    def __init__(
        self,
        path: Path,
        session_tz_name: str,
        *,
        raw_hours: int,
        minute_days: int,
    ) -> None:
        self.path = path
        self.raw_hours = raw_hours
        self.minute_days = minute_days
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = self._acquire_lock(path)
        try:
            self.conn = sqlite3.connect(str(path), isolation_level=None)
            # Only takes effect on a new file, and only before anything is
            # written to it -- switching to WAL writes the header, so first.
            self.conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")
            initialize_schema(self.conn)
            self._pin_timezone(session_tz_name)
        except Exception:
            self._release_lock()
            raise
        self._raw: dict[SeriesKey, tuple[float, float]] = {}  # -> (wall, value)
        self._minutes: dict[SeriesKey, _Minute] = {}
        self._closed: list[tuple[SeriesKey, _Minute]] = []
        self._daily: dict[tuple[str, str, str, str], float] = {}
        self._next_raw = 0.0
        self._next_retention = 0.0
        self._new_series: list[SeriesKey] = []
        self._series: dict[SeriesKey, int] = {
            (src, name, label): sid
            for sid, src, name, label in self.conn.execute(
                "SELECT id, source, name, label FROM series"
            )
        }

    # ------------------------------------------------------------------
    # open / close
    # ------------------------------------------------------------------

    @staticmethod
    def _acquire_lock(path: Path) -> IO[str] | None:
        if fcntl is None:  # pragma: no cover
            return None
        handle = open(f"{path}.lock", "w", encoding="ascii")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise StoreLockedError(
                f"{path} is already written by another pm-monitor; run one "
                f"pm-monitor per data directory"
            ) from None
        return handle

    def _release_lock(self) -> None:
        if self._lock is not None:
            self._lock.close()  # closing the descriptor releases the flock
            self._lock = None

    def _pin_timezone(self, name: str) -> None:
        row = self.conn.execute(
            "SELECT value FROM metrics_meta WHERE key = 'session_timezone'"
        ).fetchone()
        if row is not None and row[0] != name:
            raise IncompatibleStoreError(
                f"{self.path} was recorded with session timezone {row[0]!r}, but "
                f"engine config now says {name!r}. Its daily totals would then "
                f"mean two different things. Fix engine config's "
                f"locale.session_timezone back to {row[0]!r}, or move "
                f"{self.path.name} aside to start a new history."
            )
        self.conn.execute(
            "INSERT OR REPLACE INTO metrics_meta(key, value) VALUES ('session_timezone', ?)",
            (name,),
        )

    def close(
        self,
        now_wall: float,
        counters: dict[SeriesKey, tuple[str, float]] | None = None,
    ) -> None:
        """Write everything pending (the current minute too) and close.

        Pass the tracker's ``counters`` whenever increments may be pending:
        the daily totals and the counter state must be written together.
        """
        try:
            self.flush_raw(now_wall, counters)
            self.flush_minutes(now_wall, force=True)
        finally:
            self.conn.close()
            self._release_lock()

    # ------------------------------------------------------------------
    # input
    # ------------------------------------------------------------------

    def record(
        self, key: SeriesKey, value: float, now_wall: float, *, counter: bool
    ) -> None:
        """One sample of one series, as received."""
        self._raw[key] = (now_wall, value)
        start = now_wall - now_wall % MINUTE
        minute = self._minutes.get(key)
        if minute is not None and minute.start != start:
            self._closed.append((key, minute))
            minute = None
        if minute is None:
            self._minutes[key] = _Minute(
                start, value, value, value, 1, value, 0.0 if counter else None
            )
        else:
            minute.add(value)

    def record_increment(
        self, date: str, key: SeriesKey, delta: float, now_wall: float
    ) -> None:
        """An increment counted into ``date``'s total (after :meth:`record`)."""
        day_key = (date, *key)
        self._daily[day_key] = self._daily.get(day_key, 0.0) + delta
        minute = self._minutes.get(key)
        if minute is not None and minute.start == now_wall - now_wall % MINUTE:
            minute.delta = (minute.delta or 0.0) + delta

    # ------------------------------------------------------------------
    # output
    # ------------------------------------------------------------------

    def due_raw(self, now_wall: float) -> bool:
        return now_wall >= self._next_raw

    def flush_raw(
        self,
        now_wall: float,
        counters: dict[SeriesKey, tuple[str, float]] | None = None,
    ) -> int:
        """Raw rows, daily totals and counter state in one transaction.

        ``counters`` is the tracker's ``(boot_id, value)`` per counter series,
        so the file's totals and its counter state always agree. Returns the
        raw rows written.
        """
        self._next_raw = now_wall + RAW_EVERY_SEC
        daily = [(*k, total) for k, total in self._daily.items() if total]
        ts = iso_utc(now_wall)
        last = [(*k, boot, v, ts) for k, (boot, v) in (counters or {}).items()]
        conn = self.conn
        with self._transaction():
            raw = [
                (self._series_id(key), iso_utc(w), v)
                for key, (w, v) in self._raw.items()
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO samples_raw(series, ts, value) VALUES (?, ?, ?)",
                raw,
            )
            conn.executemany(
                "INSERT INTO daily_totals(date, source, name, label, total) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(date, name, label, source) "
                "DO UPDATE SET total = total + excluded.total",
                daily,
            )
            conn.executemany(
                "INSERT OR REPLACE INTO counter_last"
                "(source, name, label, boot_id, value, ts) VALUES (?, ?, ?, ?, ?, ?)",
                last,
            )
        self._raw.clear()
        self._daily.clear()
        return len(raw)

    def flush_minutes(self, now_wall: float, *, force: bool = False) -> int:
        """Write every closed minute (and the open ones with ``force``).

        A bucket already in the file (written at a shutdown part-way through
        the minute) is merged, not replaced.
        """
        start = now_wall - now_wall % MINUTE
        for key, minute in list(self._minutes.items()):
            if force or minute.start < start:
                self._closed.append((key, minute))
                del self._minutes[key]
        if not self._closed:
            return 0
        with self._transaction():
            self._write_minutes()
        n = len(self._closed)
        self._closed.clear()
        return n

    def _write_minutes(self) -> None:
        rows = [
            (
                self._series_id(key),
                iso_utc(m.start),
                m.v_min,
                m.total / m.n,
                m.v_max,
                m.last,
                m.n,
                m.delta,
            )
            for key, m in self._closed
        ]
        self.conn.executemany(
            "INSERT INTO samples_1m"
            "(series, ts, v_min, v_avg, v_max, v_last, n, delta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(series, ts) DO UPDATE SET "
            "v_min = min(v_min, excluded.v_min), "
            "v_max = max(v_max, excluded.v_max), "
            "v_avg = (v_avg * n + excluded.v_avg * excluded.n) / (n + excluded.n), "
            "v_last = excluded.v_last, "
            "n = n + excluded.n, "
            "delta = CASE WHEN delta IS NULL AND excluded.delta IS NULL THEN NULL "
            "ELSE coalesce(delta, 0) + coalesce(excluded.delta, 0) END",
            rows,
        )

    def apply_retention(self, now_wall: float) -> bool:
        """Delete rows outside the windows, hourly; True when it ran."""
        if now_wall < self._next_retention:
            return False
        self._next_retention = now_wall + RETENTION_EVERY_SEC
        raw_cut = iso_utc(now_wall - self.raw_hours * 3600)
        minute_cut = iso_utc(now_wall - self.minute_days * 86400)
        with self._transaction():
            self._delete_old(raw_cut, minute_cut)
        self.conn.execute("PRAGMA incremental_vacuum")
        return True

    def _delete_old(self, raw_cut: str, minute_cut: str) -> None:
        conn = self.conn
        # Per series, so each delete is a range of the primary key rather
        # than a scan of the table.
        ids = [(sid,) for sid in self._series.values()]
        conn.executemany(
            "DELETE FROM samples_raw WHERE series = ? AND ts < ?",
            [(sid, raw_cut) for (sid,) in ids],
        )
        conn.executemany(
            "DELETE FROM samples_1m WHERE series = ? AND ts < ?",
            [(sid, minute_cut) for (sid,) in ids],
        )
        conn.execute("DELETE FROM events WHERE ts < ?", (minute_cut,))
        conn.execute("DELETE FROM counter_last WHERE ts < ?", (minute_cut,))

    def add_event(
        self, ts: str, kind: str, severity: str, subject: str, detail: str
    ) -> int:
        """Store one event; its ``seq`` is the event's ``seq`` on the wire."""
        cur = self.conn.execute(
            "INSERT INTO events(ts, kind, severity, subject, detail) VALUES (?, ?, ?, ?, ?)",
            (ts, kind, severity, subject, detail),
        )
        return int(cur.lastrowid or 0)

    @contextmanager
    def _transaction(self) -> Generator[None, None, None]:
        """One transaction; on failure roll back, including new series ids."""
        self.conn.execute("BEGIN")
        try:
            yield
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            self._forget_new_series()
            raise
        self._new_series.clear()

    def _series_id(self, key: SeriesKey) -> int:
        """The id of a series, created on first use (inside a transaction)."""
        sid = self._series.get(key)
        if sid is None:
            source, name, label = key
            self.conn.execute(
                "INSERT OR IGNORE INTO series(source, name, label) VALUES (?, ?, ?)",
                key,
            )
            row = self.conn.execute(
                "SELECT id FROM series WHERE name = ? AND label = ? AND source = ?",
                (name, label, source),
            ).fetchone()
            sid = self._series[key] = int(row[0])
            self._new_series.append(key)
        return sid

    def _forget_new_series(self) -> None:
        """A rolled-back transaction took the series rows it created along."""
        for key in self._new_series:
            self._series.pop(key, None)
        self._new_series.clear()

    # ------------------------------------------------------------------
    # restart
    # ------------------------------------------------------------------

    def counter_state(self) -> dict[SeriesKey, tuple[str, float]]:
        """The ``(boot_id, value)`` of every counter series last written."""
        rows = self.conn.execute(
            "SELECT source, name, label, boot_id, value FROM counter_last"
        )
        return {(s, n, lb): (boot, v) for s, n, lb, boot, v in rows}

    def totals_for(self, date: str) -> list[tuple[str, str, str, float]]:
        """``(source, name, label, total)`` of one trading date."""
        rows = self.conn.execute(
            "SELECT source, name, label, total FROM daily_totals WHERE date = ?",
            (date,),
        )
        return [(s, n, lb, float(t)) for s, n, lb, t in rows]

    def avg_per_day(
        self, name: str, label: str | None, before: str, days: int = 7
    ) -> float | None:
        """Mean daily total of ``name`` (one label, or all summed) over the
        last ``days`` trading dates with data before ``before``; ``None``
        without any."""
        where = "name = ? AND date < ?"
        args: list[Any] = [name, before]
        if label is not None:
            where += " AND label = ?"
            args.append(label)
        rows = self.conn.execute(
            f"SELECT SUM(total) FROM daily_totals WHERE {where} "
            f"GROUP BY date ORDER BY date DESC LIMIT ?",
            (*args, days),
        ).fetchall()
        if not rows:
            return None
        return sum(float(r[0]) for r in rows) / len(rows)
