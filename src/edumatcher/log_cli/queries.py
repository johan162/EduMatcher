"""SQL query functions backing every ``pm-log-cli`` subcommand.

Reads ``log.db`` directly, read-only, never over LALF (§4.1, §9, §15.2) —
mirrors ``pm-stats-cli``/``pm-audit-cli``'s own "query the store, not the
live process" posture so a busy or down ``pm-log-srv`` never blocks
troubleshooting.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from edumatcher.log_srv.schema import open_db
from edumatcher.logclient.protocol import iso_utc


def open_readonly(db_path: Path) -> sqlite3.Connection:
    conn = open_db(db_path, read_only=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# query / tail (§9.2, §9.3)
# ---------------------------------------------------------------------------

_QUERY_COLUMNS = [
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
]


def query_events(
    conn: sqlite3.Connection,
    *,
    process: str | None = None,
    levels: list[str] | None = None,
    logger_pattern: str | None = None,
    since: str | None = None,
    until: str | None = None,
    grep: str | None = None,
    has_exception: bool = False,
    min_seq: int | None = None,
    limit: int = 500,
    reverse: bool = False,
) -> list[dict[str, Any]]:
    """Backs both ``query`` (§9.3) and ``tail`` (§9.2, via ``min_seq``)."""
    clauses: list[str] = []
    params: list[Any] = []

    if process:
        clauses.append("process = ?")
        params.append(process)
    if levels:
        placeholders = ",".join("?" for _ in levels)
        clauses.append(f"level IN ({placeholders})")
        params.extend(levels)
    if logger_pattern:
        clauses.append("logger LIKE ?")
        params.append(logger_pattern)
    if since:
        clauses.append("client_ts >= ?")
        params.append(since)
    if until:
        clauses.append("client_ts <= ?")
        params.append(until)
    if grep:
        clauses.append("message LIKE ?")
        params.append(f"%{grep}%")
    if has_exception:
        clauses.append("has_exception = 1")
    if min_seq is not None:
        clauses.append("seq > ?")
        params.append(min_seq)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "ASC" if (reverse or min_seq is not None) else "DESC"
    sql = (
        f"SELECT {', '.join(_QUERY_COLUMNS)} FROM log_events {where} "
        f"ORDER BY seq {order} LIMIT ?"
    )
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    result = _rows_to_dicts(rows)
    # For the default newest-first display, re-sort ascending by seq so
    # output reads chronologically top-to-bottom even though the LIMIT was
    # applied against a DESC ordering (matches pm-audit-cli's own
    # "--limit caps from the newest end, but display stays chronological"
    # behavior for its non-reverse default).
    if not reverse and min_seq is None:
        result.sort(key=lambda r: r["seq"])
    return result


def max_seq(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(seq), 0) AS m FROM log_events").fetchone()
    return int(row["m"])


# ---------------------------------------------------------------------------
# processes (§9.4)
# ---------------------------------------------------------------------------

_PROCESS_COLUMNS = [
    "process",
    "instance",
    "pid",
    "host",
    "session",
    "connected_at",
    "last_seen_at",
    "disconnected_at",
    "log_count",
]


def query_processes(
    conn: sqlite3.Connection,
    *,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    where = "WHERE disconnected_at IS NULL" if active_only else ""
    sql = (
        f"SELECT {', '.join(_PROCESS_COLUMNS)} FROM processes {where} "
        "ORDER BY connected_at DESC"
    )
    rows = conn.execute(sql).fetchall()
    return _rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# stats (§9.5)
# ---------------------------------------------------------------------------


def query_stats(conn: sqlite3.Connection, db_path: Path) -> dict[str, Any]:
    server_row = conn.execute(
        "SELECT started_at, total_log_events, total_connections, "
        "total_truncated, total_errors_sent FROM server_stats WHERE id = 1"
    ).fetchone()
    server = dict(server_row) if server_row else {}

    total_rows = conn.execute("SELECT COUNT(*) AS n FROM log_events").fetchone()["n"]

    per_level = conn.execute(
        "SELECT level, COUNT(*) AS n FROM log_events GROUP BY level ORDER BY n DESC"
    ).fetchall()
    per_process = conn.execute(
        "SELECT process, COUNT(*) AS n FROM log_events GROUP BY process ORDER BY n DESC"
    ).fetchall()

    db_size = 0
    try:
        db_size = Path(db_path).stat().st_size
    except OSError:
        pass

    return {
        "server": server,
        "total_rows": total_rows,
        "per_level": _rows_to_dicts(per_level),
        "per_process": _rows_to_dicts(per_process),
        "db_size_bytes": db_size,
    }


# ---------------------------------------------------------------------------
# prune (§6.5, §9.1)
# ---------------------------------------------------------------------------


def prune_older_than(conn: sqlite3.Connection, days: int) -> int:
    cutoff = iso_utc(time.time() - days * 86400)
    with conn:
        cur = conn.execute("DELETE FROM log_events WHERE client_ts < ?", (cutoff,))
        return max(cur.rowcount, 0)
