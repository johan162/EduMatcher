"""Optional SQLite index builder and query helper for pm-audit-cli.

The index provides faster multi-dimensional queries when the audit log grows
large.  It is entirely optional: all ``pm-audit-cli`` queries work without it.

Schema
------
A single ``audit_events`` table holds one row per parsed log line with the
most-queried fields promoted to dedicated indexed columns.  The full JSON
payload is kept in the ``payload`` column so no information is lost.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edumatcher.audit.query import (
    AuditEntry,
    date_to_range,
    discover_log_files,
    iter_entries,
    parse_ts,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    topic       TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    gateway_id  TEXT,
    symbol      TEXT,
    order_id    TEXT,
    trade_id    TEXT,
    event_type  TEXT
);

CREATE INDEX IF NOT EXISTS idx_timestamp  ON audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_topic      ON audit_events(topic);
CREATE INDEX IF NOT EXISTS idx_gateway    ON audit_events(gateway_id);
CREATE INDEX IF NOT EXISTS idx_symbol     ON audit_events(symbol);
CREATE INDEX IF NOT EXISTS idx_order      ON audit_events(order_id);
CREATE INDEX IF NOT EXISTS idx_trade      ON audit_events(trade_id);
CREATE INDEX IF NOT EXISTS idx_event_type ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_topic_ts   ON audit_events(topic, timestamp);
CREATE INDEX IF NOT EXISTS idx_gw_ts      ON audit_events(gateway_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_sym_ts     ON audit_events(symbol, timestamp);

CREATE TABLE IF NOT EXISTS index_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_LAST_TS_KEY = "last_indexed_timestamp"
_LOG_FILE_KEY = "log_file"
_BUILT_AT_KEY = "built_at"


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def open_index(db_path: Path) -> sqlite3.Connection:
    """Open (and create if needed) the SQLite index at *db_path*."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def open_readonly_index(db_path: Path) -> sqlite3.Connection:
    """Open an existing index for read-only queries."""
    if not db_path.exists():
        raise FileNotFoundError(f"Audit index not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------


def _entry_to_row(entry: AuditEntry) -> tuple[Any, ...]:
    parts = entry.topic.split(".")
    event_type = parts[-1] if len(parts) > 1 else entry.topic
    return (
        entry.timestamp,
        entry.topic,
        json.dumps(entry.payload),
        entry.gateway_id,
        entry.symbol,
        entry.order_id,
        entry.trade_id,
        event_type,
    )


def _get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM index_meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
        (key, value),
    )


def build_index(
    db_path: Path,
    log_file: Path,
    log_dir: Path | None = None,
    *,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    days: int | None = None,
    rebuild: bool = False,
    incremental: bool = False,
    batch_size: int = 500,
) -> int:
    """Populate or update the SQLite index from JSONL log files.

    Parameters
    ----------
    db_path:
        Destination SQLite file.
    log_file:
        Primary ``audit.log`` path.
    log_dir:
        Directory for rotated backups (defaults to ``log_file.parent``).
    from_dt / to_dt:
        Restrict indexing to a time window.
    days:
        Shorthand: index the last *N* days.
    rebuild:
        Drop and recreate the entire table before indexing.
    incremental:
        Only add entries newer than the last indexed timestamp.
    batch_size:
        Insert rows in batches of this size.

    Returns
    -------
    int
        Number of rows inserted.
    """
    if days is not None:
        from datetime import timedelta

        to_dt = datetime.now(timezone.utc)
        from_dt = to_dt - timedelta(days=days)

    log_files = discover_log_files(log_file, log_dir)

    conn = open_index(db_path)
    try:
        if rebuild:
            conn.execute("DELETE FROM audit_events")
            conn.execute("DELETE FROM index_meta")
            conn.commit()

        last_ts_str: str | None = None
        if incremental and not rebuild:
            last_ts_str = _get_meta(conn, _LAST_TS_KEY)
            if last_ts_str:
                try:
                    from_dt = parse_ts(last_ts_str)
                    # Exclude the last-indexed timestamp itself (already in DB)
                    from datetime import timedelta

                    from_dt = from_dt + timedelta(microseconds=1)
                except ValueError:
                    last_ts_str = None

        inserted = 0
        batch: list[tuple[Any, ...]] = []
        newest_ts: str | None = None

        _insert_sql = (
            "INSERT INTO audit_events "
            "(timestamp, topic, payload, gateway_id, symbol, order_id, trade_id, event_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )

        for entry in iter_entries(
            log_files,
            from_dt=from_dt,
            to_dt=to_dt,
            limit=None,
        ):
            batch.append(_entry_to_row(entry))
            newest_ts = entry.timestamp
            if len(batch) >= batch_size:
                conn.executemany(_insert_sql, batch)
                inserted += len(batch)
                batch.clear()

        if batch:
            conn.executemany(_insert_sql, batch)
            inserted += len(batch)

        if newest_ts:
            _set_meta(conn, _LAST_TS_KEY, newest_ts)
        _set_meta(conn, _LOG_FILE_KEY, str(log_file))
        _set_meta(
            conn,
            _BUILT_AT_KEY,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        conn.commit()
        return inserted
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Index queries
# ---------------------------------------------------------------------------


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _where_clauses(
    topic_prefix: str | None,
    gateway: str | None,
    symbol: str | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
    date_str: str | None,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if date_str:
        s, e = date_to_range(date_str)
        from_dt, to_dt = s, e

    if topic_prefix:
        clauses.append("topic LIKE ?")
        params.append(topic_prefix + "%")
    if gateway:
        clauses.append("gateway_id = ?")
        params.append(gateway)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    if from_dt:
        clauses.append("timestamp >= ?")
        params.append(from_dt.isoformat(timespec="milliseconds"))
    if to_dt:
        clauses.append("timestamp <= ?")
        params.append(to_dt.isoformat(timespec="milliseconds"))
    return clauses, params


def query_index_events(
    conn: sqlite3.Connection,
    *,
    topic_prefix: str | None = None,
    gateway: str | None = None,
    symbol: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    date_str: str | None = None,
    limit: int = 100,
    reverse: bool = False,
) -> list[dict[str, Any]]:
    clauses, params = _where_clauses(
        topic_prefix, gateway, symbol, from_dt, to_dt, date_str
    )
    order = "DESC" if reverse else "ASC"
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    sql = f"SELECT timestamp, topic, gateway_id, symbol, order_id, payload FROM audit_events {where} ORDER BY timestamp {order} LIMIT ?"  # noqa: E501
    rows = conn.execute(sql, params).fetchall()
    return _rows_to_dicts(rows)


def index_is_available(db_path: Path) -> bool:
    """Return True if a usable index file exists at *db_path*."""
    if not db_path.exists():
        return False
    try:
        conn = open_readonly_index(db_path)
        conn.execute("SELECT 1 FROM audit_events LIMIT 1")
        conn.close()
        return True
    except (sqlite3.Error, FileNotFoundError):
        return False
