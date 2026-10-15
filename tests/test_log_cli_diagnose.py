from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edumatcher.log_cli.diagnose import run_diagnostics
from edumatcher.log_srv.schema import open_db
from edumatcher.logclient.protocol import iso_utc


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = open_db(tmp_path / "log.db")
    try:
        yield connection
    finally:
        connection.close()


def _insert_event(
    conn: sqlite3.Connection,
    *,
    process: str,
    level: str,
    logger: str = "x.y",
    message: str = "msg",
    client_ts: str | None = None,
    server_ts: str | None = None,
    has_exception: bool = False,
    truncated: bool = False,
    session: str = "s1",
) -> None:
    now = iso_utc(time.time())
    conn.execute(
        "INSERT INTO log_events (client_ts, server_ts, process, instance, pid, host, "
        "session, level, logger, module, line, has_exception, truncated, message) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            client_ts or now,
            server_ts or now,
            process,
            None,
            1,
            "h",
            session,
            level,
            logger,
            None,
            None,
            int(has_exception),
            int(truncated),
            message,
        ),
    )
    conn.commit()


def _insert_process(
    conn: sqlite3.Connection,
    *,
    process: str,
    session: str = "s1",
    connected_at: str | None = None,
    last_seen_at: str | None = None,
    last_heartbeat_at: str | None = None,
    disconnected_at: str | None = None,
    disconnect_reason: str | None = "peer_closed",
) -> None:
    now = iso_utc(time.time())
    conn.execute(
        "INSERT INTO processes (session, process, instance, pid, host, connected_at, "
        "last_seen_at, last_heartbeat_at, disconnected_at, disconnect_reason, log_count) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            session,
            process,
            None,
            1,
            "h",
            connected_at or now,
            last_seen_at or now,
            last_heartbeat_at,
            disconnected_at,
            disconnect_reason if disconnected_at else None,
            1,
        ),
    )
    conn.commit()


def _iso_seconds_ago(seconds: float) -> str:
    dt = datetime.now(tz=timezone.utc) - timedelta(seconds=seconds)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# 1. error-rate spike
# ---------------------------------------------------------------------------


def test_error_spike_fires(conn: sqlite3.Connection) -> None:
    for _ in range(10):
        _insert_event(conn, process="pm-md-gwy", level="ERROR")
    findings = run_diagnostics(conn)
    assert any(f.heuristic == "error_rate_spike" for f in findings)


def test_error_spike_clean_case_does_not_fire(conn: sqlite3.Connection) -> None:
    _insert_event(conn, process="pm-md-gwy", level="INFO")
    findings = run_diagnostics(conn)
    assert not any(f.heuristic == "error_rate_spike" for f in findings)


# ---------------------------------------------------------------------------
# 2. repeated identical warning
# ---------------------------------------------------------------------------


def test_repeated_warning_fires(conn: sqlite3.Connection) -> None:
    for _ in range(25):
        _insert_event(
            conn, process="pm-api-gwy", level="WARNING", message="ENGINE_TIMEOUT"
        )
    findings = run_diagnostics(conn)
    assert any(f.heuristic == "repeated_warning" for f in findings)


def test_repeated_warning_clean_case_does_not_fire(conn: sqlite3.Connection) -> None:
    for i in range(5):
        _insert_event(
            conn, process="pm-api-gwy", level="WARNING", message=f"unique {i}"
        )
    findings = run_diagnostics(conn)
    assert not any(f.heuristic == "repeated_warning" for f in findings)


# ---------------------------------------------------------------------------
# 3. process silence (still connected, quiet)
# ---------------------------------------------------------------------------


def test_process_silence_fires(conn: sqlite3.Connection) -> None:
    _insert_process(
        conn,
        process="pm-stats",
        last_seen_at=_iso_seconds_ago(120),
        disconnected_at=None,
    )
    findings = run_diagnostics(conn)
    assert any(f.heuristic == "process_silence" for f in findings)


def test_process_silence_clean_case_does_not_fire(conn: sqlite3.Connection) -> None:
    _insert_process(conn, process="pm-stats", last_seen_at=_iso_seconds_ago(1))
    findings = run_diagnostics(conn)
    assert not any(f.heuristic == "process_silence" for f in findings)


def test_process_silence_is_informational_while_heartbeating(
    conn: sqlite3.Connection,
) -> None:
    _insert_process(
        conn,
        process="pm-dc-gwy",
        last_seen_at=_iso_seconds_ago(120),
        last_heartbeat_at=_iso_seconds_ago(2),
        disconnected_at=None,
    )
    findings = [f for f in run_diagnostics(conn) if f.heuristic == "process_silence"]
    assert [f.severity for f in findings] == ["info"]
    assert "heartbeating" in findings[0].message
    assert findings[0].details["processes"] == ["pm-dc-gwy"]


def test_process_silence_collapses_many_quiet_processes_into_one_finding(
    conn: sqlite3.Connection,
) -> None:
    for proc in ("pm-dc-gwy", "pm-md-gwy", "pm-alf-gwy"):
        _insert_process(
            conn,
            process=proc,
            session=proc,
            last_seen_at=_iso_seconds_ago(120),
            last_heartbeat_at=_iso_seconds_ago(2),
        )
    findings = [f for f in run_diagnostics(conn) if f.heuristic == "process_silence"]
    assert len(findings) == 1
    assert findings[0].details["count"] == 3


def test_process_silence_warns_when_heartbeat_is_also_stale(
    conn: sqlite3.Connection,
) -> None:
    _insert_process(
        conn,
        process="pm-dc-gwy",
        last_seen_at=_iso_seconds_ago(120),
        last_heartbeat_at=_iso_seconds_ago(120),
        disconnected_at=None,
    )
    findings = [f for f in run_diagnostics(conn) if f.heuristic == "process_silence"]
    assert [f.severity for f in findings] == ["warning"]


def test_process_silence_warns_when_heartbeat_column_is_unpopulated(
    conn: sqlite3.Connection,
) -> None:
    # Rows written before the column existed carry no heartbeat evidence.
    _insert_process(
        conn,
        process="pm-dc-gwy",
        last_seen_at=_iso_seconds_ago(120),
        last_heartbeat_at=None,
        disconnected_at=None,
    )
    findings = [f for f in run_diagnostics(conn) if f.heuristic == "process_silence"]
    assert [f.severity for f in findings] == ["warning"]


# ---------------------------------------------------------------------------
# 4. clock skew
# ---------------------------------------------------------------------------


def test_clock_skew_fires(conn: sqlite3.Connection) -> None:
    client_ts = _iso_seconds_ago(10)
    server_ts = _iso_seconds_ago(6.5)  # ~3.5s skew
    for _ in range(5):
        _insert_event(
            conn,
            process="pm-mm-bot",
            level="INFO",
            client_ts=client_ts,
            server_ts=server_ts,
        )
    findings = run_diagnostics(conn)
    assert any(f.heuristic == "clock_skew" for f in findings)


def test_clock_skew_clean_case_does_not_fire(conn: sqlite3.Connection) -> None:
    ts = iso_utc(time.time())
    _insert_event(conn, process="pm-mm-bot", level="INFO", client_ts=ts, server_ts=ts)
    findings = run_diagnostics(conn)
    assert not any(f.heuristic == "clock_skew" for f in findings)


# ---------------------------------------------------------------------------
# 5. truncated-message rate
# ---------------------------------------------------------------------------


def test_truncated_rate_fires(conn: sqlite3.Connection) -> None:
    _insert_event(conn, process="pm-ai-swarm", level="INFO", truncated=True)
    findings = run_diagnostics(conn)
    assert any(f.heuristic == "truncated_messages" for f in findings)


def test_truncated_rate_clean_case_does_not_fire(conn: sqlite3.Connection) -> None:
    _insert_event(conn, process="pm-ai-swarm", level="INFO", truncated=False)
    findings = run_diagnostics(conn)
    assert not any(f.heuristic == "truncated_messages" for f in findings)


# ---------------------------------------------------------------------------
# 6. exception clustering by logger
# ---------------------------------------------------------------------------


def test_exception_clustering_fires(conn: sqlite3.Connection) -> None:
    for _ in range(4):
        _insert_event(
            conn,
            process="pm-md-gwy",
            level="ERROR",
            logger="edumatcher.md_gateway.gateway",
            has_exception=True,
        )
    findings = run_diagnostics(conn)
    assert any(f.heuristic == "exception_clustering" for f in findings)


def test_exception_clustering_clean_case_does_not_fire(
    conn: sqlite3.Connection,
) -> None:
    _insert_event(conn, process="pm-md-gwy", level="ERROR", has_exception=False)
    findings = run_diagnostics(conn)
    assert not any(f.heuristic == "exception_clustering" for f in findings)


# ---------------------------------------------------------------------------
# 7. likely fallback-to-file event — must be distinguishable from #3 (silence)
# ---------------------------------------------------------------------------


def test_fallback_to_file_fires_on_cleanly_disconnected_quiet_process(
    conn: sqlite3.Connection,
) -> None:
    _insert_process(
        conn,
        process="pm-md-gwy",
        disconnected_at=_iso_seconds_ago(120),
        disconnect_reason="peer_closed",
    )
    findings = run_diagnostics(conn)
    kinds = {f.heuristic for f in findings}
    assert "fallback_to_file" in kinds
    # Must NOT also fire the plain silence heuristic for the same row —
    # silence only considers disconnected_at IS NULL rows.
    assert "process_silence" not in kinds


def test_fallback_to_file_does_not_fire_when_process_reconnected(
    conn: sqlite3.Connection,
) -> None:
    """A later session row is proof the process came back."""
    _insert_process(
        conn,
        process="pm-md-gwy",
        session="s1",
        connected_at=_iso_seconds_ago(300),
        disconnected_at=_iso_seconds_ago(120),
        disconnect_reason="peer_closed",
    )
    _insert_process(
        conn,
        process="pm-md-gwy",
        session="s2",
        connected_at=_iso_seconds_ago(60),
        last_seen_at=_iso_seconds_ago(1),
    )
    findings = run_diagnostics(conn)
    assert not any(f.heuristic == "fallback_to_file" for f in findings)


def test_fallback_to_file_ignores_a_clean_exit(conn: sqlite3.Connection) -> None:
    """A client that sent EXIT shut down deliberately; that is not failover."""
    _insert_process(
        conn,
        process="pm-viewer",
        disconnected_at=_iso_seconds_ago(120),
        disconnect_reason="client_exit",
    )
    findings = run_diagnostics(conn)
    assert not any(f.heuristic == "fallback_to_file" for f in findings)


def test_fallback_to_file_reports_a_quiet_process_once_not_once_per_session(
    conn: sqlite3.Connection,
) -> None:
    """Regression: a process that connects repeatedly but never logs.

    Reconnection used to be inferred from ``log_events``, so a process
    with nothing to say could never clear the check and every one of its
    historical sessions was reported.
    """
    for i in range(20):
        _insert_process(
            conn,
            process="pm-viewer",
            session=f"s{i}",
            connected_at=_iso_seconds_ago(1000 - i * 10),
            disconnected_at=_iso_seconds_ago(995 - i * 10),
            disconnect_reason="peer_closed",
        )
    findings = [f for f in run_diagnostics(conn) if f.heuristic == "fallback_to_file"]
    assert len(findings) == 1
    assert findings[0].details["session"] == "s19"


def test_fallback_to_file_is_honest_when_the_reason_is_unrecorded(
    conn: sqlite3.Connection,
) -> None:
    """Rows predating the disconnect_reason column still fire, but say so."""
    _insert_process(
        conn,
        process="pm-md-gwy",
        disconnected_at=_iso_seconds_ago(120),
        disconnect_reason=None,
    )
    findings = [f for f in run_diagnostics(conn) if f.heuristic == "fallback_to_file"]
    assert len(findings) == 1
    assert "not recorded" in findings[0].message


def test_silence_and_fallback_are_mutually_exclusive_on_same_fixture_set(
    conn: sqlite3.Connection,
) -> None:
    """One clean-disconnect process (fallback) + one still-open-but-stalled
    process (silence) — each must fire exactly its own heuristic, not both."""
    _insert_process(
        conn,
        process="pm-md-gwy",
        session="s1",
        disconnected_at=_iso_seconds_ago(100),
        disconnect_reason="peer_closed",
    )
    _insert_process(
        conn, process="pm-stats", session="s2", last_seen_at=_iso_seconds_ago(100)
    )

    findings = run_diagnostics(conn)
    by_process: dict[str | None, set[str]] = {}
    for f in findings:
        if f.heuristic in ("fallback_to_file", "process_silence"):
            by_process.setdefault(f.details.get("process"), set()).add(f.heuristic)

    assert by_process.get("pm-md-gwy") == {"fallback_to_file"}
    assert by_process.get("pm-stats") == {"process_silence"}


def test_clean_session_reports_no_findings(conn: sqlite3.Connection) -> None:
    _insert_event(conn, process="pm-a", level="INFO", message="all quiet")
    _insert_process(conn, process="pm-a", last_seen_at=_iso_seconds_ago(1))
    findings = run_diagnostics(conn)
    assert findings == []
