"""SQLite storage and queries for published market news events, and the
value model's jumps (which no news announces)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from edumatcher.config import DATA_DIR

NEWS_HISTORY_DB = DATA_DIR / "market_sim_news.db"


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create the current news-history schema on an open SQLite connection."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS news_events (
            event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT NOT NULL,
            ts_ns INTEGER NOT NULL,
            scope TEXT NOT NULL,
            targets TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            headline TEXT NOT NULL,
            sentiment REAL NOT NULL,
            credibility REAL,
            related_id TEXT NOT NULL
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS news_events_ts ON news_events(ts_ns DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS news_events_status ON news_events(status)")
    # One row per jump of a symbol's true value: log_jump is the jump's log
    # size, value the symbol's value after the step that carried it.
    conn.execute("""CREATE TABLE IF NOT EXISTS value_jumps (
            ts_ns INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            log_jump REAL NOT NULL,
            value REAL NOT NULL
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS value_jumps_ts ON value_jumps(ts_ns)")


def _insert_event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    timestamp = event.get("ts_ns")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise ValueError("news event has an invalid ts_ns")
    news_id = event.get("id")
    if not isinstance(news_id, str) or not news_id:
        raise ValueError("news event has an invalid id")
    targets = event.get("targets")
    if not isinstance(targets, list):
        raise ValueError("news event has invalid targets")

    conn.execute(
        """INSERT INTO news_events
              (id, ts_ns, scope, targets, kind, status, headline, sentiment,
            credibility, related_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            news_id,
            int(timestamp),
            str(event["scope"]),
            json.dumps(targets, separators=(",", ":")),
            str(event["kind"]),
            str(event["status"]),
            str(event["headline"]),
            float(event["sentiment"]),
            event.get("credibility"),
            str(event.get("related_id", "")),
        ),
    )


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    conn = sqlite3.connect(path, timeout=5.0)
    try:
        initialize_schema(conn)
        if is_new:
            _import_legacy(conn, path.with_suffix(".jsonl"))
        conn.commit()
        return conn
    except Exception:
        conn.close()
        raise


def _import_legacy(conn: sqlite3.Connection, path: Path) -> None:
    try:
        legacy = path.open(encoding="utf-8")
    except FileNotFoundError:
        return
    with legacy:
        for line in legacy:
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    _insert_event(conn, event)
            except json.JSONDecodeError, KeyError, TypeError, ValueError:
                continue


def append_news_event(path: Path, event: dict[str, Any]) -> None:
    with closing(_connect(path)) as conn:
        with conn:
            _insert_event(conn, event)


def prune_news_events(path: Path, before_ns: int) -> int:
    """Delete the headlines published before ``before_ns``; how many went."""
    with closing(_connect(path)) as conn:
        with conn:
            return conn.execute(
                "DELETE FROM news_events WHERE ts_ns < ?", (before_ns,)
            ).rowcount


def append_value_jumps(
    path: Path, ts_ns: int, jumps: dict[str, float], values: dict[str, float]
) -> None:
    """Record one model step's jumps (symbol -> log size) at ``ts_ns``."""
    with closing(_connect(path)) as conn:
        with conn:
            conn.executemany(
                "INSERT INTO value_jumps (ts_ns, symbol, log_jump, value) "
                "VALUES (?, ?, ?, ?)",
                [(ts_ns, s, j, values[s]) for s, j in sorted(jumps.items())],
            )


def _epoch_ns(value: datetime) -> int:
    delta = value.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (
        delta.days * 86400 + delta.seconds
    ) * 1_000_000_000 + delta.microseconds * 1000


def read_news_events(
    path: Path,
    *,
    limit: int,
    date_filter: date | None = None,
    timezone_name: str = "Europe/Stockholm",
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    parameters: list[int] = []
    where = ""
    if date_filter is not None:
        zone = ZoneInfo(timezone_name)
        start = datetime.combine(date_filter, time.min, tzinfo=zone)
        end = datetime.combine(date_filter + timedelta(days=1), time.min, tzinfo=zone)
        where = "WHERE ts_ns >= ? AND ts_ns < ?"
        parameters.extend((_epoch_ns(start), _epoch_ns(end)))
    parameters.append(limit)

    with closing(_connect(path)) as conn:
        rows = conn.execute(
            f"""SELECT id, ts_ns, scope, targets, kind, status, headline,
                       sentiment, credibility, related_id
                FROM news_events {where}
                ORDER BY ts_ns DESC, rowid DESC LIMIT ?""",
            parameters,
        ).fetchall()

    return [
        {
            "id": row[0],
            "ts_ns": row[1],
            "scope": row[2],
            "targets": json.loads(row[3]),
            "kind": row[4],
            "status": row[5],
            "headline": row[6],
            "sentiment": row[7],
            "credibility": row[8],
            "related_id": row[9],
        }
        for row in rows
    ]


def open_news_readonly(path: Path) -> sqlite3.Connection:
    """Open the news history read-only, for a reader in another process;
    FileNotFoundError when pm-market-sim has never written one."""
    if not path.exists():
        raise FileNotFoundError(f"news history not found: {path}")
    conn = sqlite3.connect(f"file:{quote(str(path.resolve()))}?mode=ro", uri=True)
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def query_news(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int = 0,
    from_ns: int | None = None,
    to_ns: int | None = None,
    targets: frozenset[str] | None = None,
    status: str | None = None,
    sentiment: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """One page of headlines, newest first, and how many match in all.

    ``from_ns``/``to_ns`` bound ``ts_ns`` inclusively. ``targets`` keeps the
    MARKET headlines and those naming any of its symbols or sectors.
    ``sentiment`` is ``positive`` (> 0) or ``negative`` (< 0). Each row's
    ``resolution`` is what became of a rumour (CONFIRMED or RETRACTED, None
    while open, and None for every other headline), from the whole table, so
    a page never hides it.
    """
    where: list[str] = []
    params: list[Any] = []
    if from_ns is not None:
        where.append("n.ts_ns >= ?")
        params.append(from_ns)
    if to_ns is not None:
        where.append("n.ts_ns <= ?")
        params.append(to_ns)
    if targets is not None:
        marks = ",".join("?" * len(targets))
        where.append(
            "(n.scope = 'MARKET' OR EXISTS (SELECT 1 FROM json_each(n.targets)"
            f" WHERE value IN ({marks})))"
        )
        params.extend(sorted(targets))
    if status is not None:
        where.append("n.status = ?")
        params.append(status)
    if sentiment == "positive":
        where.append("n.sentiment > 0")
    elif sentiment == "negative":
        where.append("n.sentiment < 0")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    (total,) = conn.execute(
        f"SELECT COUNT(*) FROM news_events n {clause}", params
    ).fetchone()
    # A resolution follows its rumour in the table: event_seq, not the id
    # alone, ties the two, as ids may repeat across a restart.
    rows = conn.execute(
        f"""SELECT n.id, n.ts_ns, n.scope, n.targets, n.kind, n.status,
                   n.headline, n.sentiment, n.credibility, n.related_id,
                   CASE WHEN n.status = 'RUMOUR' THEN (
                       SELECT r.status FROM news_events r
                       WHERE r.related_id = n.id AND r.status != 'RUMOUR'
                         AND r.event_seq > n.event_seq
                       ORDER BY r.event_seq LIMIT 1) END
            FROM news_events n {clause}
            ORDER BY n.ts_ns DESC, n.event_seq DESC LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        event: dict[str, Any] = {
            "id": row[0],
            "ts_ns": row[1],
            "scope": row[2],
            "targets": json.loads(row[3]),
            "kind": row[4],
            "status": row[5],
            "headline": row[6],
            "sentiment": row[7],
            "related_id": row[9],
            "resolution": row[10],
        }
        if row[8] is not None:  # absent on the wire, so absent here
            event["credibility"] = row[8]
        events.append(event)
    return events, int(total)
