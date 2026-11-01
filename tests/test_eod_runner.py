"""run_day / pending_dates: gates, steps, idempotency, catch-up."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from edumatcher.clearing.store import (
    PositionRow,
    flush_batch,
    open_writer_connection,
    record_session_event,
    write_close_snapshot,
)
from edumatcher.eod import housekeeping
from edumatcher.eod.ledger import balances, open_ledger, runs, settled_dates
from edumatcher.eod.runner import (
    Options,
    Paths,
    RunLocked,
    exit_code,
    pending_dates,
    run_day,
    run_lock,
)

NOW = datetime(2026, 7, 5, 12, tzinfo=UTC)


def pos(gw: str, qty: int, unreal: float) -> PositionRow:
    return PositionRow(
        gateway_id=gw,
        symbol="AAPL",
        net_qty=qty,
        avg_cost=1000.0,
        realized_pnl=0.0,
        unrealized_pnl=unreal,
        mark_price=1050,
        buy_qty=0,
        sell_qty=0,
        buy_notional=0,
        sell_notional=0,
        last_trade_ts_ns=1,
        updated_ts_ns=1,
    )


def close_day(data: Path, day: str, unreal: float, *, phase: str = "CLOSED") -> None:
    """A trading day: the market was open (ts 0), then reached ``phase`` (ts 1)."""
    conn = open_writer_connection(data / "clearing.db")
    flush_batch(conn, [], [pos("A", 100, unreal), pos("B", -100, -unreal)], [])
    for ts, state in ((0, "CONTINUOUS"), (1, phase)):
        record_session_event(
            conn,
            event_type="PHASE",
            ts_ns=ts,
            trade_date=day,
            payload_json=json.dumps({"state": state}),
        )
    write_close_snapshot(conn, day)
    conn.close()


def boot(data: Path, day: str, unreal: float) -> None:
    """The engine starts before the open: it announces CLOSED, pm-clearing snapshots."""
    conn = open_writer_connection(data / "clearing.db")
    flush_batch(conn, [], [pos("A", 100, unreal), pos("B", -100, -unreal)], [])
    record_session_event(
        conn,
        event_type="PHASE",
        ts_ns=0,  # before the day's own phases (close_day uses 0 and 1)
        trade_date=day,
        payload_json=json.dumps({"state": "CLOSED"}),
    )
    write_close_snapshot(conn, day)
    conn.close()


@pytest.fixture()
def data(tmp_path: Path) -> Path:
    close_day(tmp_path, "2026-07-01", 5000.0)
    return tmp_path


def run(data: Path, day: str = "2026-07-01", **kw: object) -> list[str]:
    opts = Options(**kw)  # type: ignore[arg-type]
    outcome = run_day(Paths(data), day, opts, today="2026-07-05", now=NOW)
    return [f"{s.step}:{s.status}" for s in outcome.steps]


def test_a_full_run(data: Path) -> None:
    assert run(data) == [
        "gate:ok",
        "settle:ok",
        "report:ok",
        "audit:ok",
        "logs:ok",
        "backup:ok",
    ]
    out = data / "settlement" / "2026-07-01"
    assert (out / "statements" / "A.md").is_file() and (
        out / "instructions.csv"
    ).is_file()
    ledger = open_ledger(data / "eod.db")
    assert settled_dates(ledger) == ["2026-07-01"]
    assert balances(ledger) == {"A": 5000, "B": -5000}
    assert [r["status"] for r in runs(ledger)] == ["ok"]
    assert (data / "backup" / "2026-07-01" / "clearing.db.zst").is_file()
    ledger.close()


def test_the_engines_eod_directory_is_never_touched(data: Path) -> None:
    engine = data / "eod" / "2026-07-01"
    engine.mkdir(parents=True)
    (engine / "gtc_orders.json").write_text("[]")
    run(data)
    assert (engine / "gtc_orders.json").read_text() == "[]"


def test_a_second_run_is_a_no_op(data: Path) -> None:
    run(data)
    again = run(data)
    assert again[:2] == ["gate:ok", "settle:ok"]
    ledger = open_ledger(data / "eod.db")
    assert balances(ledger) == {"A": 5000, "B": -5000}
    ledger.close()


class TestGate:
    def test_no_closed_event_stops_everything(self, tmp_path: Path) -> None:
        close_day(tmp_path, "2026-07-01", 5000.0, phase="CONTINUOUS")
        assert run(tmp_path) == ["gate:fail"]
        assert not (tmp_path / "settlement").exists()
        ledger = open_ledger(tmp_path / "eod.db")
        assert settled_dates(ledger) == []
        assert [r["status"] for r in runs(ledger)] == ["failed"]
        ledger.close()

    def test_force_skips_only_the_closed_check(self, tmp_path: Path) -> None:
        close_day(tmp_path, "2026-07-01", 5000.0, phase="CONTINUOUS")
        assert run(tmp_path, force=True)[:3] == ["gate:ok", "settle:ok", "report:ok"]

    def test_the_latest_phase_must_be_closed(self, data: Path) -> None:
        # A mid-day restart re-announced CLOSED, then trading went on.
        conn = open_writer_connection(data / "clearing.db")
        record_session_event(
            conn,
            event_type="PHASE",
            ts_ns=2,
            trade_date="2026-07-01",
            payload_json=json.dumps({"state": "CONTINUOUS"}),
        )
        conn.close()
        assert run(data) == ["gate:fail"]

    def test_an_engine_boot_before_the_open_is_not_a_close(self, data: Path) -> None:
        boot(data, "2026-07-02", 5000.0)
        assert run(data, "2026-07-02") == ["gate:fail"]

    def test_no_snapshot_even_with_force(self, tmp_path: Path) -> None:
        open_writer_connection(tmp_path / "clearing.db").close()
        assert run(tmp_path, force=True) == ["gate:fail"]

    def test_missing_clearing_db(self, tmp_path: Path) -> None:
        assert run(tmp_path) == ["gate:fail"]

    def test_a_reconcile_discrepancy_fails_the_day(self, data: Path) -> None:
        conn = open_writer_connection(data / "clearing.db")
        conn.execute(
            "INSERT INTO trade_events (id, ts_ns, trade_date, symbol, quantity,"
            " price, buy_gateway_id, sell_gateway_id, ingest_ts_ns)"
            " VALUES ('T', 1, '2026-07-01', 'AAPL', 5, 100, 'A', 'B', 1)"
        )
        conn.commit()
        conn.close()
        assert run(data) == ["gate:fail"]


class TestSteps:
    def test_a_failed_report_keeps_the_settlement_and_heals_on_rerun(
        self, data: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_a: object, **_k: object) -> None:
            raise OSError("disk full")

        with monkeypatch.context() as m:
            m.setattr("edumatcher.eod.runner.write_day", boom)
            steps = run(data)
        assert steps[:3] == ["gate:ok", "settle:ok", "report:fail"]
        ledger = open_ledger(data / "eod.db")
        assert settled_dates(ledger) == ["2026-07-01"]
        assert [r["status"] for r in runs(ledger)] == ["report-failed"]
        ledger.close()
        assert run(data)[:3] == ["gate:ok", "settle:ok", "report:ok"]
        ledger = open_ledger(data / "eod.db")
        assert [r["status"] for r in runs(ledger)] == ["ok"]
        ledger.close()

    def test_housekeeping_trouble_never_fails_the_day(
        self, data: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "edumatcher.eod.runner.backup_databases",
            lambda *a, **k: housekeeping.StepResult("backup", "warn", "disk full"),
        )
        outcome = run_day(
            Paths(data), "2026-07-01", Options(), today="2026-07-05", now=NOW
        )
        assert exit_code(outcome) == 2
        assert (data / "settlement" / "2026-07-01").is_dir()
        ledger = open_ledger(data / "eod.db")
        assert [r["status"] for r in runs(ledger)] == ["ok"]
        ledger.close()

    def test_backup_skip_leaves_a_database_out_and_says_so(self, data: Path) -> None:
        conn = open_writer_connection(data / "clearing.db")
        conn.close()
        (data / "stats.db").write_bytes((data / "clearing.db").read_bytes())
        outcome = run_day(
            Paths(data),
            "2026-07-01",
            Options(backup_skip=("stats.db",)),
            today="2026-07-05",
            now=NOW,
        )
        backup = next(s for s in outcome.steps if s.step == "backup")
        assert (
            backup.status == "ok" and "skipped by request: stats.db" in backup.message
        )
        names = sorted(p.name for p in (data / "backup" / "2026-07-01").iterdir())
        assert names == ["clearing.db.zst", "eod.db.zst"]

    def test_without_skip_stats_is_backed_up(self, data: Path) -> None:
        (data / "stats.db").write_bytes((data / "clearing.db").read_bytes())
        run(data)
        assert (data / "backup" / "2026-07-01" / "stats.db.zst").is_file()

    def test_exit_codes(self, data: Path) -> None:
        ok = run_day(Paths(data), "2026-07-01", Options(), today="2026-07-05", now=NOW)
        assert exit_code(ok) == 0
        bad = run_day(Paths(data), "2026-07-09", Options(), today="2026-07-10", now=NOW)
        assert exit_code(bad) == 1

    def test_only_reruns_one_step_and_records_nothing(self, data: Path) -> None:
        run(data)
        ledger = open_ledger(data / "eod.db")
        before = runs(ledger)
        ledger.close()
        assert run(data, only="logs") == ["logs:ok"]
        ledger = open_ledger(data / "eod.db")
        assert runs(ledger) == before
        ledger.close()

    def test_only_report_needs_a_settled_day(self, data: Path) -> None:
        assert run(data, only="report") == ["report:fail"]

    def test_dry_run_writes_nothing(self, data: Path) -> None:
        steps = run(data, dry_run=True)
        assert steps == ["gate:ok", "settle:ok"]
        assert not (data / "settlement").exists() and not (data / "eod.db").exists()

    def test_redo_recomputes_and_drops_later_days(self, data: Path) -> None:
        close_day(data, "2026-07-02", 2000.0)
        run(data)
        run(data, "2026-07-02")
        ledger = open_ledger(data / "eod.db")
        assert settled_dates(ledger) == ["2026-07-01", "2026-07-02"]
        ledger.close()
        run(data, redo=True)
        ledger = open_ledger(data / "eod.db")
        assert settled_dates(ledger) == ["2026-07-01"]
        assert [r["trade_date"] for r in runs(ledger)] == ["2026-07-01"]
        ledger.close()

    def test_a_failed_redo_keeps_the_ledger(self, data: Path) -> None:
        close_day(data, "2026-07-02", 2000.0)
        run(data)
        run(data, "2026-07-02")
        conn = open_writer_connection(data / "clearing.db")
        conn.execute(
            "UPDATE position_close_snapshot SET realized_pnl = 999999"
            " WHERE trade_date = '2026-07-01' AND gateway_id = 'A'"
        )
        conn.commit()
        conn.close()
        assert run(data, redo=True)[:2] == ["gate:ok", "settle:fail"]
        ledger = open_ledger(data / "eod.db")
        assert settled_dates(ledger) == ["2026-07-01", "2026-07-02"]
        ledger.close()


class TestBaseline:
    def test_a_skipped_snapshot_day_is_not_lost(self, tmp_path: Path) -> None:
        # No scheduler: three days with snapshots, only the last one settled.
        for day, unreal in (("2026-07-01", 1000.0), ("2026-07-02", 3000.0)):
            close_day(tmp_path, day, unreal, phase="CONTINUOUS")
        close_day(tmp_path, "2026-07-03", 3500.0, phase="CONTINUOUS")
        run(tmp_path, "2026-07-03", force=True)
        ledger = open_ledger(tmp_path / "eod.db")
        assert balances(ledger) == {"A": 3500, "B": -3500}
        ledger.close()

    def test_the_next_day_starts_from_the_last_settled_one(
        self, tmp_path: Path
    ) -> None:
        for day, unreal in (
            ("2026-07-01", 1000.0),
            ("2026-07-02", 3000.0),
            ("2026-07-03", 3500.0),
        ):
            close_day(tmp_path, day, unreal, phase="CONTINUOUS")
        run(tmp_path, "2026-07-01", force=True)
        run(tmp_path, "2026-07-03", force=True)
        ledger = open_ledger(tmp_path / "eod.db")
        assert balances(ledger) == {"A": 3500, "B": -3500}
        ledger.close()

    def test_an_earlier_unsettled_close_blocks_a_later_date(self, data: Path) -> None:
        close_day(data, "2026-07-02", 2000.0)
        outcome = run_day(
            Paths(data), "2026-07-02", Options(), today="2026-07-05", now=NOW
        )
        settle = next(s for s in outcome.steps if s.step == "settle")
        assert settle.status == "fail" and "2026-07-01" in settle.message
        ledger = open_ledger(data / "eod.db")
        assert settled_dates(ledger) == []
        ledger.close()
        # In order, both settle.
        assert run(data)[:2] == ["gate:ok", "settle:ok"]
        assert run(data, "2026-07-02")[:2] == ["gate:ok", "settle:ok"]

    def test_a_report_failed_earlier_day_does_not_block(
        self, data: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        close_day(data, "2026-07-02", 2000.0)
        with monkeypatch.context() as m:
            m.setattr(
                "edumatcher.eod.runner.write_day",
                lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full")),
            )
            run(data)
        assert run(data, "2026-07-02")[:2] == ["gate:ok", "settle:ok"]


class TestPending:
    def test_oldest_first_and_only_dates_with_a_snapshot(self, data: Path) -> None:
        close_day(data, "2026-07-02", 2000.0)
        conn = open_writer_connection(data / "clearing.db")
        record_session_event(  # pre-snapshot history: CLOSED, no snapshot
            conn,
            event_type="PHASE",
            ts_ns=0,
            trade_date="2026-06-01",
            payload_json=json.dumps({"state": "CLOSED"}),
        )
        conn.close()
        assert pending_dates(Paths(data)) == ["2026-07-01", "2026-07-02"]

    def test_a_day_that_trading_went_on_after_is_not_pending(self, data: Path) -> None:
        # Engine restart mid-day: CLOSED re-announced, then CONTINUOUS.
        close_day(data, "2026-07-02", 2000.0, phase="CONTINUOUS")
        conn = open_writer_connection(data / "clearing.db")
        record_session_event(
            conn,
            event_type="PHASE",
            ts_ns=0,
            trade_date="2026-07-02",
            payload_json=json.dumps({"state": "CLOSED"}),
        )
        conn.close()
        # ts_ns=0 is older than the CONTINUOUS row (ts_ns=1)
        assert pending_dates(Paths(data)) == ["2026-07-01"]

    def test_a_day_with_only_an_engine_boot_is_not_pending(self, data: Path) -> None:
        boot(data, "2026-07-02", 5000.0)
        assert pending_dates(Paths(data)) == ["2026-07-01"]

    def test_a_start_up_run_before_the_open_leaves_the_day_to_its_close(
        self, data: Path
    ) -> None:
        # pm-scheduler runs `pm-eod run --pending` when it starts.  Started in
        # the morning, the only phase of the day is the engine's boot CLOSED;
        # settling then would book 0.00 and the day's trading never.
        run(data)
        boot(data, "2026-07-02", 5000.0)
        assert pending_dates(Paths(data)) == []
        close_day(data, "2026-07-02", 2000.0)  # the day trades and closes
        assert pending_dates(Paths(data)) == ["2026-07-02"]
        run(data, "2026-07-02")
        ledger = open_ledger(data / "eod.db")
        assert balances(ledger) == {"A": 2000, "B": -2000}
        ledger.close()

    def test_done_days_drop_out(self, data: Path) -> None:
        close_day(data, "2026-07-02", 2000.0)
        run(data)
        assert pending_dates(Paths(data)) == ["2026-07-02"]

    def test_nothing_without_a_clearing_db(self, tmp_path: Path) -> None:
        assert pending_dates(Paths(tmp_path)) == []


def test_the_lock_refuses_a_second_holder(tmp_path: Path) -> None:
    with run_lock(tmp_path):
        with pytest.raises(RunLocked):
            with run_lock(tmp_path):
                pass
    with run_lock(tmp_path):
        pass
