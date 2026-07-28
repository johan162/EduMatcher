from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from edumatcher.log_cli import queries
from edumatcher.log_srv.schema import open_db
from edumatcher.logclient.protocol import iso_utc


def _seed(conn: sqlite3.Connection, rows: list[dict]) -> None:
    for r in rows:
        conn.execute(
            "INSERT INTO log_events (client_ts, server_ts, process, instance, pid, "
            "host, session, level, logger, module, line, has_exception, truncated, message) "
            "VALUES (:client_ts, :server_ts, :process, :instance, :pid, :host, :session, "
            ":level, :logger, :module, :line, :has_exception, :truncated, :message)",
            {
                "client_ts": r.get("client_ts", iso_utc(time.time())),
                "server_ts": r.get("server_ts", iso_utc(time.time())),
                "process": r["process"],
                "instance": r.get("instance"),
                "pid": r.get("pid", 1),
                "host": r.get("host", "h"),
                "session": r.get("session", "s1"),
                "level": r["level"],
                "logger": r.get("logger", "x.y"),
                "module": r.get("module"),
                "line": r.get("line"),
                "has_exception": int(r.get("has_exception", False)),
                "truncated": int(r.get("truncated", False)),
                "message": r["message"],
            },
        )
    conn.commit()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "log.db"


@pytest.fixture
def conn(db_path: Path) -> sqlite3.Connection:
    connection = open_db(db_path)
    # Match how pm-log-cli actually opens the database (queries.open_readonly
    # sets row_factory = sqlite3.Row) — the query functions index rows by
    # column name, so a plain tuple-factory connection would not exercise
    # the real code path pm-log-cli uses.
    connection.row_factory = sqlite3.Row
    return connection


def test_query_events_filters_by_process(conn: sqlite3.Connection) -> None:
    _seed(
        conn,
        [
            {"process": "pm-a", "level": "INFO", "message": "hello a"},
            {"process": "pm-b", "level": "INFO", "message": "hello b"},
        ],
    )
    rows = queries.query_events(conn, process="pm-a")
    assert len(rows) == 1
    assert rows[0]["process"] == "pm-a"


def test_query_events_filters_by_level(conn: sqlite3.Connection) -> None:
    _seed(
        conn,
        [
            {"process": "pm-a", "level": "INFO", "message": "info msg"},
            {"process": "pm-a", "level": "ERROR", "message": "error msg"},
        ],
    )
    rows = queries.query_events(conn, levels=["ERROR"])
    assert len(rows) == 1
    assert rows[0]["level"] == "ERROR"


def test_query_events_grep(conn: sqlite3.Connection) -> None:
    _seed(
        conn,
        [
            {"process": "pm-a", "level": "INFO", "message": "needle in haystack"},
            {"process": "pm-a", "level": "INFO", "message": "nothing here"},
        ],
    )
    rows = queries.query_events(conn, grep="needle")
    assert len(rows) == 1
    assert "needle" in rows[0]["message"]


def test_query_events_has_exception(conn: sqlite3.Connection) -> None:
    _seed(
        conn,
        [
            {
                "process": "pm-a",
                "level": "ERROR",
                "message": "a",
                "has_exception": True,
            },
            {
                "process": "pm-a",
                "level": "ERROR",
                "message": "b",
                "has_exception": False,
            },
        ],
    )
    rows = queries.query_events(conn, has_exception=True)
    assert len(rows) == 1
    assert rows[0]["message"] == "a"


def test_query_events_limit_and_order(conn: sqlite3.Connection) -> None:
    _seed(
        conn,
        [{"process": "pm-a", "level": "INFO", "message": f"m{i}"} for i in range(10)],
    )
    rows = queries.query_events(conn, limit=3)
    assert len(rows) == 3
    # default is newest-first-selected but chronological display
    assert rows[0]["seq"] < rows[-1]["seq"]


def test_query_events_reverse(conn: sqlite3.Connection) -> None:
    _seed(
        conn,
        [{"process": "pm-a", "level": "INFO", "message": f"m{i}"} for i in range(5)],
    )
    rows = queries.query_events(conn, reverse=True, limit=3)
    assert len(rows) == 3
    assert rows[0]["seq"] < rows[1]["seq"] < rows[2]["seq"]


def test_query_events_min_seq_for_tail(conn: sqlite3.Connection) -> None:
    _seed(
        conn,
        [{"process": "pm-a", "level": "INFO", "message": f"m{i}"} for i in range(5)],
    )
    top = queries.max_seq(conn)
    _seed(conn, [{"process": "pm-a", "level": "INFO", "message": "new one"}])
    rows = queries.query_events(conn, min_seq=top)
    assert len(rows) == 1
    assert rows[0]["message"] == "new one"


def test_query_processes_active_only(conn: sqlite3.Connection) -> None:
    now = iso_utc(time.time())
    conn.execute(
        "INSERT INTO processes (session, process, instance, pid, host, connected_at, "
        "last_seen_at, disconnected_at, log_count) VALUES (?,?,?,?,?,?,?,?,?)",
        ("s1", "pm-a", None, 1, "h", now, now, None, 0),
    )
    conn.execute(
        "INSERT INTO processes (session, process, instance, pid, host, connected_at, "
        "last_seen_at, disconnected_at, log_count) VALUES (?,?,?,?,?,?,?,?,?)",
        ("s2", "pm-b", None, 2, "h", now, now, now, 0),
    )
    conn.commit()
    active = queries.query_processes(conn, active_only=True)
    assert len(active) == 1
    assert active[0]["process"] == "pm-a"

    all_rows = queries.query_processes(conn, active_only=False)
    assert len(all_rows) == 2


def test_prune_older_than(conn: sqlite3.Connection) -> None:
    old_ts = iso_utc(time.time() - 40 * 86400)
    new_ts = iso_utc(time.time())
    _seed(
        conn,
        [{"process": "pm-a", "level": "INFO", "message": "old", "client_ts": old_ts}],
    )
    _seed(
        conn,
        [{"process": "pm-a", "level": "INFO", "message": "new", "client_ts": new_ts}],
    )
    deleted = queries.prune_older_than(conn, 30)
    assert deleted == 1
    remaining = conn.execute("SELECT message FROM log_events").fetchall()
    assert [tuple(row) for row in remaining] == [("new",)]


def test_query_stats_basic(conn: sqlite3.Connection, db_path: Path) -> None:
    conn.execute(
        "INSERT INTO server_stats (id, started_at, total_log_events, total_connections, "
        "total_truncated, total_errors_sent) VALUES (1, ?, 5, 2, 0, 1)",
        (iso_utc(time.time()),),
    )
    conn.commit()
    _seed(
        conn,
        [
            {"process": "pm-a", "level": "INFO", "message": "a"},
            {"process": "pm-a", "level": "ERROR", "message": "b"},
        ],
    )
    stats = queries.query_stats(conn, db_path)
    assert stats["total_rows"] == 2
    assert stats["server"]["total_log_events"] == 5
    levels = {row["level"] for row in stats["per_level"]}
    assert levels == {"INFO", "ERROR"}
