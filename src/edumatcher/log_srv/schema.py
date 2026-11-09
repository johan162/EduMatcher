"""SQLite schema for ``pm-log-srv``'s ``log.db``.

Mirrors ``edumatcher.stats.main``'s own ``SCHEMA`` constant conventions
(docs-design/EduMatcher-log-srv.md §6.1): append-only event tables with an
``INTEGER PRIMARY KEY AUTOINCREMENT`` surrogate key where insertion order
matters, composite indexes shaped ``(filter_column, ts)`` matching the
query patterns ``pm-log-cli`` actually needs (§9), and TEXT columns for
timestamps in the same UTC ISO-8601-with-milliseconds format every other
EduMatcher SQLite store already uses.

Four tables (§6.2-§6.4):

  log_events     One row per received LOG message — the append-only heart
                 of the database.
  processes      One row per LALF connection (session), a lightweight
                 connect/disconnect registry.
  server_stats   Single-row (id=1) table of pm-log-srv's own lifetime
                 operational counters.
  schema_version Single-row (id=1) table holding :data:`SCHEMA_VERSION`.

An existing ``log.db`` written under another schema version is refused,
never migrated: the operator deletes it and the server starts a fresh one.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

#: Bumped whenever a table's shape changes. Version 1 was every ``log.db``
#: written before the ``schema_version`` table existed; version 2 added
#: ``log_events.tpl`` (the log-ledger template id).
SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);

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
    message         TEXT NOT NULL,
    tpl             TEXT
);

CREATE INDEX IF NOT EXISTS idx_le_process_ts ON log_events(process, client_ts);
CREATE INDEX IF NOT EXISTS idx_le_level_ts   ON log_events(level, client_ts);
CREATE INDEX IF NOT EXISTS idx_le_logger_ts  ON log_events(logger, client_ts);
CREATE INDEX IF NOT EXISTS idx_le_session    ON log_events(session);
-- Time-window lookups with no other filter: the LALF-PS backfill start
-- (first seq inside the window) and retention pruning.
CREATE INDEX IF NOT EXISTS idx_le_client_ts  ON log_events(client_ts);

CREATE TABLE IF NOT EXISTS processes (
    session         TEXT PRIMARY KEY,
    process         TEXT NOT NULL,
    instance        TEXT,
    pid             INTEGER NOT NULL,
    host            TEXT NOT NULL,
    connected_at    TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    last_heartbeat_at TEXT,
    disconnected_at TEXT,
    disconnect_reason TEXT,
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
     level, logger, module, line, has_exception, truncated, message, tpl)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""

UPSERT_PROCESS_CONNECT = """
INSERT INTO processes
    (session, process, instance, pid, host, connected_at, last_seen_at, last_heartbeat_at,
     disconnected_at, disconnect_reason, log_count)
VALUES (?,?,?,?,?,?,?,?,NULL,NULL,0)
ON CONFLICT(session) DO UPDATE SET
    last_seen_at = excluded.last_seen_at,
    last_heartbeat_at = excluded.last_heartbeat_at
"""

#: Records that a session is still in contact, whether or not it had
#: anything to log. ``last_seen_at`` deliberately keeps its narrower
#: meaning of "last LOG frame", so the two columns together separate a
#: process that is quiet from one that is gone.
UPDATE_PROCESS_HEARTBEAT = """
UPDATE processes SET last_heartbeat_at = ? WHERE session = ?
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

#: The reason is what separates a process that said goodbye from one that
#: vanished — ``pm-log-cli diagnose`` cannot tell a clean shutdown from a
#: crash or a file-failover without it.
UPDATE_PROCESS_DISCONNECTED = """
UPDATE processes SET disconnected_at = ?, disconnect_reason = ? WHERE session = ?
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

#: Deletes at most ``?`` rows per statement, oldest first, so an hourly prune
#: of a large backlog holds the write lock for one bounded chunk at a time
#: instead of one long transaction the writer thread would queue behind.
DELETE_OLD_LOG_EVENTS = """
DELETE FROM log_events WHERE seq IN (
    SELECT seq FROM log_events WHERE client_ts < ? ORDER BY seq LIMIT ?
)
"""

#: Rows removed per retention-prune statement.
PRUNE_CHUNK_ROWS = 5000

#: How long a connection waits on a locked database before SQLITE_BUSY.
BUSY_TIMEOUT_MS = 10_000


class LogDbSchemaError(RuntimeError):
    """An existing ``log.db`` was written under another :data:`SCHEMA_VERSION`."""


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create the current log-server schema on an open SQLite connection."""
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, ?)",
        (SCHEMA_VERSION,),
    )


def check_schema_version(conn: sqlite3.Connection, path: Path) -> None:
    """Raise :class:`LogDbSchemaError` unless ``conn`` is empty or current.

    A database with no tables at all is a brand-new file and passes. Any
    other database must carry ``schema_version`` = :data:`SCHEMA_VERSION`; a
    file older than the table itself counts as version 1.
    """
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if not tables:
        return
    version = 1
    if "schema_version" in tables:
        row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        version = row[0] if row is not None else 1
    if version != SCHEMA_VERSION:
        raise LogDbSchemaError(
            f"{path} has log.db schema version {version}, this build needs "
            f"{SCHEMA_VERSION}; old log databases are not migrated — delete "
            f"{path} (and its -wal/-shm files) and start pm-log-srv again"
        )


def open_db(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open (creating schema if absent) the log-server SQLite database.

    ``read_only`` opens the file via SQLite's URI ``mode=ro`` — used by
    ``pm-log-cli``, which never writes and must not block on or interfere
    with ``pm-log-srv``'s own writer connection (§4.1, §9). The schema is
    only created on a writable open, but both modes raise
    :class:`LogDbSchemaError` for an existing file of another
    :data:`SCHEMA_VERSION`; a read-only open against a
    database that has never been created raises, which callers translate
    into ``pm-log-cli``'s documented exit code 1 (§9.8).
    """
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        try:
            check_schema_version(conn, path)
        except LogDbSchemaError:
            conn.close()
            raise
        return conn

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    # WAL so readers (pm-log-cli, the LALF-PS backfill connection) never
    # block the writer's commits, as every other EduMatcher store does.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    try:
        check_schema_version(conn, path)
    except LogDbSchemaError:
        conn.close()
        raise
    initialize_schema(conn)
    conn.commit()
    return conn
