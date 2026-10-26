"""SQLite storage and queries for published market news events, and the
value model's jumps (which no news announces)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
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
