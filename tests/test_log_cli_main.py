from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

from edumatcher.log_cli import main as log_cli_main
from edumatcher.log_srv.schema import open_db
from edumatcher.logclient.protocol import iso_utc


def _seed_event(
    conn: sqlite3.Connection,
    *,
    process: str,
    level: str,
    message: str,
    client_ts: str | None = None,
) -> None:
    now = iso_utc(time.time())
    conn.execute(
        "INSERT INTO log_events (client_ts, server_ts, process, instance, pid, host, "
        "session, level, logger, module, line, has_exception, truncated, message) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            client_ts or now,
            now,
            process,
            None,
            1,
            "h",
            "s1",
            level,
            "edumatcher.test",
            None,
            None,
            0,
            0,
            message,
        ),
    )
    conn.commit()


def _make_db(path: Path) -> sqlite3.Connection:
    return open_db(path)


def test_query_filters_by_process_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "log.db"
    conn = _make_db(db)
    try:
        _seed_event(conn, process="pm-api-gwy", level="INFO", message="api ok")
        _seed_event(conn, process="pm-engine", level="INFO", message="engine ok")
    finally:
        conn.close()

    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-log-cli", "--db", str(db), "query", "--process", "pm-api-gwy"],
    )

    log_cli_main.main()
    out = capsys.readouterr().out
    assert "pm-api-gwy" in out
    assert "pm-engine" not in out


def test_subcommand_format_overrides_global_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "log.db"
    conn = _make_db(db)
    try:
        _seed_event(conn, process="pm-api-gwy", level="WARNING", message="warn")
    finally:
        conn.close()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pm-log-cli",
            "--db",
            str(db),
            "--format",
            "human",
            "query",
            "--format",
            "json",
            "--process",
            "pm-api-gwy",
        ],
    )

    log_cli_main.main()
    out = capsys.readouterr().out.strip().splitlines()
    assert out
    first = json.loads(out[0])
    assert first["process"] == "pm-api-gwy"
    assert first["level"] == "WARNING"


def test_diagnose_exits_non_zero_when_findings_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "log.db"
    conn = _make_db(db)
    try:
        # Intent test: repeated operational errors should fail diagnostics so
        # operators can gate deployments on signal, not manually inspect logs.
        for _ in range(10):
            _seed_event(conn, process="pm-md-gwy", level="ERROR", message="boom")
    finally:
        conn.close()

    monkeypatch.setattr(sys, "argv", ["pm-log-cli", "--db", str(db), "diagnose"])

    with pytest.raises(SystemExit) as excinfo:
        log_cli_main.main()
    assert excinfo.value.code == 3
    out = capsys.readouterr().out
    assert "Recommendation:" in out


def test_prune_removes_rows_older_than_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "log.db"
    conn = _make_db(db)
    try:
        old_ts = (
            (datetime.now(tz=timezone.utc) - timedelta(days=40))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        _seed_event(
            conn, process="pm-api-gwy", level="INFO", message="old", client_ts=old_ts
        )
        _seed_event(conn, process="pm-api-gwy", level="INFO", message="new")
    finally:
        conn.close()

    monkeypatch.setattr(
        sys, "argv", ["pm-log-cli", "--db", str(db), "prune", "--days", "30"]
    )

    log_cli_main.main()
    out = capsys.readouterr().out
    assert "Pruned 1 row(s) older than 30 days." in out

    check = sqlite3.connect(db)
    try:
        rows = check.execute("SELECT message FROM log_events ORDER BY seq").fetchall()
        assert rows == [("new",)]
    finally:
        check.close()


def test_query_missing_database_fails_with_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(
        sys, "argv", ["pm-log-cli", "--db", str(missing), "query", "--limit", "1"]
    )

    with pytest.raises(SystemExit) as excinfo:
        log_cli_main.main()
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "Log database not found" in err
    assert "pm-log-srv" in err
