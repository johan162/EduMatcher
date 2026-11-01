"""pm-eod: run / status / balances."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edumatcher.eod import main as eod_main
from tests.test_eod_runner import close_day  # noqa: F401  (reuse the seeding helper)


@pytest.fixture(autouse=True)
def _today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eod_main, "_today", lambda: "2026-07-05")


@pytest.fixture()
def data(tmp_path: Path) -> Path:
    close_day(tmp_path, "2026-07-01", 5000.0)
    (tmp_path / "ref_data").mkdir()
    (tmp_path / "ref_data" / "roster.yaml").write_text(
        "traders:\n  - gateway: A\n    name: Alice\n    opening_balance: 10\n"
    )
    return tmp_path


def cli(data: Path, *args: str) -> int:
    try:
        eod_main.main(["--datapath", str(data), *args])
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_run_prints_each_step_and_exits_zero(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli(data, "run", "--date", "2026-07-01") == 0
    out = capsys.readouterr().out
    for step in ("gate", "settle", "report", "audit", "logs", "backup"):
        assert f"[ok] {step}" in out


def test_backup_skip_is_repeatable_and_validated(data: Path) -> None:
    assert (
        cli(
            data,
            "run",
            "--date",
            "2026-07-01",
            "--backup-skip",
            "stats.db",
            "--backup-skip",
            "clearing.db",
        )
        == 0
    )
    assert not (data / "backup" / "2026-07-01" / "clearing.db.zst").exists()
    assert cli(data, "run", "--date", "2026-07-01", "--backup-skip", "audit.log") == 2


def test_run_failure_exits_one(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(data, "run", "--date", "2026-07-02") == 1
    assert "[FAIL] gate" in capsys.readouterr().out


def test_run_needs_a_date_or_pending(data: Path) -> None:
    assert cli(data, "run") == 2


def test_bad_date_is_rejected(data: Path) -> None:
    assert cli(data, "run", "--date", "tomorrow") != 0


def test_pending_runs_oldest_first_and_stops_at_a_failure(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    close_day(data, "2026-07-02", 2000.0)
    assert cli(data, "run", "--pending") == 0
    out = capsys.readouterr().out
    assert out.index("2026-07-01") < out.index("2026-07-02")
    assert cli(data, "run", "--pending") == 0
    assert "nothing pending" in capsys.readouterr().out


def test_status_lists_runs_and_quiet_reports_health(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli(data, "status", "-q") == 1  # a closed day is waiting
    assert capsys.readouterr().out == ""
    cli(data, "run", "--date", "2026-07-01")
    capsys.readouterr()
    assert cli(data, "status", "-q") == 0
    assert cli(data, "--format", "json", "status") == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["trade_date"] == "2026-07-01" and rows[0]["status"] == "ok"


def test_a_failed_run_for_a_date_that_never_closed_is_not_unhealthy(
    data: Path,
) -> None:
    cli(data, "run", "--date", "2026-07-01")
    assert cli(data, "run", "--date", "2026-07-09") == 1  # a typo
    assert cli(data, "status", "-q") == 0


def test_a_closed_day_that_is_waiting_keeps_status_unhealthy(data: Path) -> None:
    cli(data, "run", "--date", "2026-07-01")
    close_day(data, "2026-07-02", 2000.0)
    assert cli(data, "status", "-q") == 1


def test_balances_include_roster_openings(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli(data, "run", "--date", "2026-07-01")
    capsys.readouterr()
    assert cli(data, "--format", "json", "balances") == 0
    rows = {r["account"]: r["balance"] for r in json.loads(capsys.readouterr().out)}
    assert rows == {"A": "60.00", "B": "-50.00"}
    assert cli(data, "--format", "json", "balances", "--gateway", "b") == 0
    assert [r["account"] for r in json.loads(capsys.readouterr().out)] == ["B"]


def test_balances_check(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli(data, "run", "--date", "2026-07-01")
    capsys.readouterr()
    assert cli(data, "balances", "--check") == 0
    assert "OK" in capsys.readouterr().out
    import sqlite3

    conn = sqlite3.connect(data / "eod.db")
    conn.execute("UPDATE eod_settlement SET amount_minor = 1 WHERE account = 'A'")
    conn.commit()
    conn.close()
    assert cli(data, "balances", "--check") == 1
    assert "2026-07-01" in capsys.readouterr().out


def test_a_second_pm_eod_is_refused(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from edumatcher.eod.runner import run_lock

    with run_lock(data):
        assert cli(data, "run", "--date", "2026-07-01") == 1
    assert "another pm-eod" in capsys.readouterr().err
