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


def test_rewrite_before_shorthand_converts_dash_nnn_after_tail() -> None:
    argv = ["--db", "x.db", "tail", "-50", "--process", "pm-a"]
    assert log_cli_main._rewrite_before_shorthand(argv) == [
        "--db",
        "x.db",
        "tail",
        "--before",
        "50",
        "--process",
        "pm-a",
    ]


def test_rewrite_before_shorthand_ignores_tokens_before_tail_subcommand() -> None:
    # A "-50"-shaped token before the "tail" subcommand token must not be
    # touched (e.g. it could be part of --db's value in a pathological case,
    # or simply not related to tail at all).
    argv = ["-50", "tail"]
    assert log_cli_main._rewrite_before_shorthand(argv) == argv


def test_rewrite_before_shorthand_rejects_zero_and_leading_zero() -> None:
    argv = ["tail", "-0"]
    assert log_cli_main._rewrite_before_shorthand(argv) == ["tail", "-0"]
    argv2 = ["tail", "-007"]
    assert log_cli_main._rewrite_before_shorthand(argv2) == ["tail", "-007"]


def test_rewrite_before_shorthand_rejects_out_of_range_four_digits() -> None:
    argv = ["tail", "-1000"]
    assert log_cli_main._rewrite_before_shorthand(argv) == ["tail", "-1000"]


def test_tail_before_shorthand_prints_backfill_then_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "log.db"
    conn = _make_db(db)
    try:
        for i in range(5):
            _seed_event(conn, process="pm-a", level="INFO", message=f"m{i}")
    finally:
        conn.close()

    def _stop_after_first_sleep(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", _stop_after_first_sleep)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-log-cli", "--db", str(db), "tail", "-3"],
    )

    log_cli_main.main()
    out = capsys.readouterr().out
    # Only the last 3 of the 5 seeded rows should appear in the backfill.
    assert "m0" not in out
    assert "m1" not in out
    assert "m2" in out
    assert "m3" in out
    assert "m4" in out


def test_tail_before_flag_long_form_also_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "log.db"
    conn = _make_db(db)
    try:
        for i in range(3):
            _seed_event(conn, process="pm-a", level="INFO", message=f"m{i}")
    finally:
        conn.close()

    def _stop(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", _stop)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-log-cli", "--db", str(db), "tail", "--before", "2"],
    )

    log_cli_main.main()
    out = capsys.readouterr().out
    assert "m0" not in out
    assert "m1" in out
    assert "m2" in out


def test_tail_before_out_of_range_via_long_flag_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "log.db"
    conn = _make_db(db)
    conn.close()

    monkeypatch.setattr(
        sys,
        "argv",
        ["pm-log-cli", "--db", str(db), "tail", "--before", "1000"],
    )

    with pytest.raises(SystemExit) as excinfo:
        log_cli_main.main()
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "--before/-NNN must be between 1 and 999" in err


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
