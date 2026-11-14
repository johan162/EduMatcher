"""pm-eod: run / status / balances."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edumatcher.clearing.store import open_writer_connection
from edumatcher.eod import main as eod_main
from edumatcher.eod.ledger import open_ledger, runs
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


def test_dry_run_with_only_is_refused_and_writes_nothing(data: Path) -> None:
    # --only skips the gate and settle steps that --dry-run stops before, so
    # together they would really run the step.
    assert (
        cli(data, "run", "--date", "2026-07-01", "--only", "backup", "--dry-run") == 2
    )
    assert not (data / "backup").exists()


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


def test_a_catch_up_takes_one_backup_after_its_last_date(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Every date would back up the same current databases under an old label.
    close_day(data, "2026-07-02", 2000.0)
    close_day(data, "2026-07-03", 3000.0)
    assert cli(data, "run", "--pending") == 0
    out = capsys.readouterr().out
    assert sorted(p.name for p in (data / "backup").iterdir()) == ["2026-07-03"]
    assert out.count("backup: deferred") == 3
    lines = out.rstrip().splitlines()
    assert lines[-2] == "2026-07-03:"
    assert lines[-1].startswith("  [ok] backup: backed up")


def test_a_catch_up_that_stops_still_backs_up_what_it_did(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    close_day(data, "2026-07-02", 2000.0)
    conn = open_writer_connection(data / "clearing.db")
    conn.execute(  # a reconcile discrepancy fails 2026-07-02's gate
        "INSERT INTO trade_events (id, ts_ns, trade_date, symbol, quantity,"
        " price, buy_gateway_id, sell_gateway_id, ingest_ts_ns)"
        " VALUES ('T', 1, '2026-07-02', 'AAPL', 5, 100, 'A', 'B', 1)"
    )
    conn.commit()
    conn.close()
    assert cli(data, "run", "--pending") == 1
    assert sorted(p.name for p in (data / "backup").iterdir()) == ["2026-07-01"]
    assert "stopping" in capsys.readouterr().out


def test_one_date_backs_up_as_part_of_its_run(data: Path) -> None:
    assert cli(data, "run", "--date", "2026-07-01") == 0
    ledger = open_ledger(data / "eod.db")
    steps = json.loads(runs(ledger)[0]["steps_json"])
    ledger.close()
    backup = next(s for s in steps if s["step"] == "backup")
    assert backup["message"].startswith("backed up")


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


def test_show_lists_one_dates_rows_with_per_symbol_detail(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli(data, "run", "--date", "2026-07-01")
    capsys.readouterr()
    assert cli(data, "--format", "json", "show", "--date", "2026-07-01") == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["account"] for r in rows] == ["A", "B"]
    assert sum(float(r["amount"]) for r in rows) == 0
    assert all(isinstance(r["detail"], dict) for r in rows)
    assert cli(data, "show", "--date", "2026-07-01", "--gateway", "b") == 0
    out = capsys.readouterr().out
    assert "B" in out and "A " not in out.splitlines()[-1]


def test_show_steps_prints_full_messages(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli(data, "run", "--date", "2026-07-01")
    capsys.readouterr()
    assert cli(data, "--format", "json", "show", "--date", "2026-07-01", "--steps") == 0
    steps = json.loads(capsys.readouterr().out)
    assert [s["step"] for s in steps][:3] == ["gate", "settle", "report"]
    assert all(s["message"] for s in steps)


def test_show_an_unknown_date_has_no_rows(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli(data, "show", "--date", "2026-07-02") == 0
    assert capsys.readouterr().out.strip() == "No rows found."


def test_balances_with_a_broken_roster_is_a_clean_error(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (data / "ref_data" / "roster.yaml").write_text("traders: [\n")
    assert cli(data, "balances") == 1
    err = capsys.readouterr().err
    assert err.startswith("pm-eod: ") and "roster.yaml" in err
    assert "Traceback" not in err


def test_housekeeping_warnings_exit_three(
    data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edumatcher.eod import housekeeping

    monkeypatch.setattr(
        "edumatcher.eod.runner.backup_databases",
        lambda *a, **k: housekeeping.StepResult("backup", "warn", "disk full"),
    )
    assert cli(data, "run", "--date", "2026-07-01") == 3


@pytest.mark.parametrize("flag", ["--redo", "--force"])
def test_only_refuses_flags_it_would_ignore(
    data: Path, flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli(data, "run", "--date", "2026-07-01", "--only", "report", flag) == 2
    assert flag in capsys.readouterr().err


def test_a_database_error_outside_a_step_is_a_clean_error(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sqlite3

    def full(*_a: object, **_k: object) -> None:
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr("edumatcher.eod.runner.record_run", full)
    assert cli(data, "run", "--date", "2026-07-01") == 1
    assert capsys.readouterr().err == "pm-eod: database or disk is full\n"


class TestReadOnlyCommands:
    def test_status_quiet_without_clearing_db_is_unhealthy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = tmp_path / "typo" / "data"
        assert cli(data, "status", "-q") == 1
        assert "clearing.db" in capsys.readouterr().err
        assert not data.exists()

    @pytest.mark.parametrize(
        "args",
        [
            ("status",),
            ("balances",),
            ("balances", "--check"),
            ("show", "--date", "2026-07-01"),
        ],
    )
    def test_read_commands_create_no_ledger(
        self, data: Path, args: tuple[str, ...]
    ) -> None:
        assert cli(data, *args) == 0
        assert not (data / "eod.db").exists()

    def test_balances_without_a_ledger_are_the_openings(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli(data, "--format", "json", "balances") == 0
        assert json.loads(capsys.readouterr().out) == [
            {"account": "A", "balance": "10.00"}
        ]


class TestBounds:
    def test_an_impossible_date_is_a_usage_error(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli(data, "run", "--date", "2026-02-30") == 2
        assert "2026-02-30" in capsys.readouterr().err
        assert not (data / "eod.db").exists()

    @pytest.mark.parametrize("flag", ["--backup-keep-days", "--log-keep-days"])
    def test_negative_retention_is_a_usage_error(self, data: Path, flag: str) -> None:
        assert cli(data, "run", "--date", "2026-07-01", flag, "-1") == 2
        assert not (data / "eod.db").exists()


class TestDryRun:
    def test_a_settled_date_says_already_settled(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli(data, "run", "--date", "2026-07-01")
        capsys.readouterr()
        assert cli(data, "run", "--date", "2026-07-01", "--dry-run") == 0
        assert "[ok] settle: already settled" in capsys.readouterr().out

    def test_the_order_rule_fails_like_the_real_run(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        close_day(data, "2026-07-02", 2000.0)
        assert cli(data, "run", "--date", "2026-07-02", "--dry-run") == 1
        out = capsys.readouterr().out
        assert "[FAIL] settle: 2026-07-01 has closed but is not settled" in out
        assert not (data / "eod.db").exists()

    def test_a_pending_dry_run_chains_the_dates(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        close_day(data, "2026-07-02", 2000.0)
        assert cli(data, "run", "--pending", "--dry-run") == 0
        out = capsys.readouterr().out
        assert "would settle: A +50.00, B -50.00" in out
        assert "would settle: A -30.00, B +30.00" in out  # from 07-01, not zero
        assert not (data / "eod.db").exists()

    def test_redo_dry_run_names_what_it_would_drop(
        self, data: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        close_day(data, "2026-07-02", 2000.0)
        cli(data, "run", "--pending")
        capsys.readouterr()
        assert cli(data, "run", "--date", "2026-07-01", "--redo", "--dry-run") == 0
        out = capsys.readouterr().out
        assert (
            "would settle: A +50.00, B -50.00; would drop 2026-07-01, 2026-07-02" in out
        )
        ledger = open_ledger(data / "eod.db")
        assert [r["trade_date"] for r in runs(ledger)] == ["2026-07-02", "2026-07-01"]
        ledger.close()
