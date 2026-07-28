"""SQLite schema for ``pm-log-srv``'s ``log.db``.

Mirrors ``edumatcher.stats.main``'s own ``SCHEMA`` constant conventions
(docs-design/EduMatcher-log-srv.md §6.1): append-only event tables with an
``INTEGER PRIMARY KEY AUTOINCREMENT`` surrogate key where insertion order
matters, composite indexes shaped ``(filter_column, ts)`` matching the
query patterns ``pm-log-cli`` actually needs (§9), and TEXT columns for
timestamps in the same UTC ISO-8601-with-milliseconds format every other
EduMatcher SQLite store already uses.

Three tables (§6.2-§6.4):

  log_events     One row per received LOG message — the append-only heart
                 of the database.
  processes      One row per LALF connection (session), a lightweight
                 connect/disconnect registry.
  server_stats   Single-row (id=1) table of pm-log-srv's own lifetime
                 operational counters.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS log_events (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    client_ts       TEXT NOT NULL,
    server_ts       TEXT NOT NULL,
    process         TEXT NOT NULL,
    instance        TEXT,
    pid             INTEGER NOT NULL,
    host            TEXT NOT NULL,
    session         TEXT NOT NULL,
    level           TEXT NOT NULL,
    logger          TEXT NOT NULL,
    module          TEXT,
    line            INTEGER,
    has_exception   INTEGER NOT NULL DEFAULT 0,
    truncated       INTEGER NOT NULL DEFAULT 0,
    message         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_le_process_ts ON log_events(process, client_ts);
CREATE INDEX IF NOT EXISTS idx_le_level_ts   ON log_events(level, client_ts);
CREATE INDEX IF NOT EXISTS idx_le_logger_ts  ON log_events(logger, client_ts);
CREATE INDEX IF NOT EXISTS idx_le_session    ON log_events(session);

CREATE TABLE IF NOT EXISTS processes (
    session         TEXT PRIMARY KEY,
    process         TEXT NOT NULL,
    instance        TEXT,
    pid             INTEGER NOT NULL,
    host            TEXT NOT NULL,
    connected_at    TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    disconnected_at TEXT,
    log_count       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_proc_process ON processes(process, connected_at);

CREATE TABLE IF NOT EXISTS server_stats (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    started_at          TEXT NOT NULL,
    total_log_events    INTEGER NOT NULL DEFAULT 0,
    total_connections   INTEGER NOT NULL DEFAULT 0,
    total_truncated     INTEGER NOT NULL DEFAULT 0,
    total_errors_sent   INTEGER NOT NULL DEFAULT 0
);
"""

INSERT_LOG_EVENT = """
INSERT INTO log_events
    (client_ts, server_ts, process, instance, pid, host, session,
     level, logger, module, line, has_exception, truncated, message)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""

UPSERT_PROCESS_CONNECT = """
INSERT INTO processes
    (session, process, instance, pid, host, connected_at, last_seen_at, disconnected_at, log_count)
VALUES (?,?,?,?,?,?,?,NULL,0)
ON CONFLICT(session) DO UPDATE SET
    last_seen_at = excluded.last_seen_at
"""

UPDATE_PROCESS_LAST_SEEN = """
UPDATE processes SET last_seen_at = ? WHERE session = ?
"""

UPDATE_PROCESS_LAST_SEEN_AND_COUNT = """
UPDATE processes SET last_seen_at = ?, log_count = log_count + 1 WHERE session = ?
"""

UPDATE_PROCESS_LAST_SEEN_AND_COUNT_BY_N = """
UPDATE processes SET last_seen_at = ?, log_count = log_count + ? WHERE session = ?
"""

UPDATE_PROCESS_DISCONNECTED = """
UPDATE processes SET disconnected_at = ? WHERE session = ?
"""

UPSERT_SERVER_STATS_INIT = """
INSERT INTO server_stats (id, started_at, total_log_events, total_connections, total_truncated, total_errors_sent)
VALUES (1, ?, 0, 0, 0, 0)
ON CONFLICT(id) DO UPDATE SET started_at = excluded.started_at
"""

INCREMENT_TOTAL_LOG_EVENTS = """
UPDATE server_stats SET total_log_events = total_log_events + ? WHERE id = 1
"""

INCREMENT_TOTAL_CONNECTIONS = """
UPDATE server_stats SET total_connections = total_connections + 1 WHERE id = 1
"""

INCREMENT_TOTAL_TRUNCATED = """
UPDATE server_stats SET total_truncated = total_truncated + ? WHERE id = 1
"""

INCREMENT_TOTAL_ERRORS_SENT = """
UPDATE server_stats SET total_errors_sent = total_errors_sent + 1 WHERE id = 1
"""

DELETE_OLD_LOG_EVENTS = """
DELETE FROM log_events WHERE client_ts < ?
"""


def open_db(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open (creating schema if absent) the log-server SQLite database.

    ``read_only`` opens the file via SQLite's URI ``mode=ro`` — used by
    ``pm-log-cli``, which never writes and must not block on or interfere
    with ``pm-log-srv``'s own writer connection (§4.1, §9). The schema is
    only created/verified on a writable open; a read-only open against a
    database that has never been created raises, which callers translate
    into ``pm-log-cli``'s documented exit code 1 (§9.8).
    """
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        return conn

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
