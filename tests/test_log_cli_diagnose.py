from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edumatcher.log_cli.diagnose import run_diagnostics
from edumatcher.log_srv.schema import open_db
from edumatcher.logclient.protocol import iso_utc


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return open_db(tmp_path / "log.db")


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
    last_seen_at: str | None = None,
    disconnected_at: str | None = None,
) -> None:
    now = iso_utc(time.time())
    conn.execute(
        "INSERT INTO processes (session, process, instance, pid, host, connected_at, "
        "last_seen_at, disconnected_at, log_count) VALUES (?,?,?,?,?,?,?,?,?)",
        (session, process, None, 1, "h", now, last_seen_at or now, disconnected_at, 1),
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
    )
    findings = run_diagnostics(conn)
    kinds = {f.heuristic for f in findings}
    assert "fallback_to_file" in kinds
    # Must NOT also fire the plain silence heuristic for the same row —
    # silence only considers disconnected_at IS NULL rows.
    assert "process_silence" not in kinds


def test_fallback_to_file_does_not_fire_when_process_resumed_logging(
    conn: sqlite3.Connection,
) -> None:
    disc_ts = _iso_seconds_ago(120)
    _insert_process(conn, process="pm-md-gwy", session="s1", disconnected_at=disc_ts)
    # Simulate a fresh reconnect (new session) that has since logged again —
    # should NOT be flagged as "gone silent after fallback".
    _insert_event(conn, process="pm-md-gwy", level="INFO", session="s2")
    findings = run_diagnostics(conn)
    assert not any(f.heuristic == "fallback_to_file" for f in findings)


def test_silence_and_fallback_are_mutually_exclusive_on_same_fixture_set(
    conn: sqlite3.Connection,
) -> None:
    """One clean-disconnect process (fallback) + one still-open-but-stalled
    process (silence) — each must fire exactly its own heuristic, not both."""
    _insert_process(
        conn, process="pm-md-gwy", session="s1", disconnected_at=_iso_seconds_ago(100)
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
