"""Close snapshots are pruned, the latest never (For-Later L019, WP-FL14).

``write_close_snapshot`` copies every position, flat ones included, under
each closed date, and nothing deleted old dates: one full position table per
day in ``clearing.db`` and in every nightly backup. They now follow the
``trade_events`` retention (``--retention-days``), and are pruned where those
rows are; the newest snapshot date is always kept, because pm-eod settles the
next day from it.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edumatcher.clearing import cli
from edumatcher.clearing.main import ClearingProcess
from edumatcher.clearing.store import (
    PositionRow,
    clearing_instance,
    flush_batch,
    open_writer_connection,
    prune_close_snapshots,
    write_close_snapshot,
)
from edumatcher.eod.settle import Baseline, settle_date
from tests.conftest import opened


def _day(days_ago: int) -> str:
    # UTC, as SQLite's date('now') in the prune.
    return (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()


def _position(gw: str, unrealized: float) -> PositionRow:
    return PositionRow(
        gateway_id=gw,
        symbol="AAPL",
        net_qty=100,
        avg_cost=1000.0,
        realized_pnl=0.0,
        unrealized_pnl=unrealized,
        mark_price=1050,
        buy_qty=100,
        sell_qty=0,
        buy_notional=100000,
        sell_notional=0,
        last_trade_ts_ns=1,
        updated_ts_ns=1,
    )


def _snapshots(conn: sqlite3.Connection, ages: range) -> None:
    flush_batch(conn, [], [_position("A", 10.0), _position("B", -10.0)], [])
    for age in ages:
        write_close_snapshot(conn, _day(age))


def _dates(conn: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT trade_date FROM position_close_snapshot ORDER BY 1"
        )
    ]


def test_dates_older_than_the_retention_are_deleted(tmp_path: Path) -> None:
    conn = open_writer_connection(tmp_path / "clearing.db")
    try:
        _snapshots(conn, range(40))
        deleted = prune_close_snapshots(conn, retention_days=30)
        kept = _dates(conn)
    finally:
        conn.close()
    # As for trade_events, a date exactly 30 days old is kept.
    assert kept == [_day(age) for age in range(30, -1, -1)]
    assert deleted == 9 * 2  # nine dates, two positions each


def test_the_newest_snapshot_is_kept_even_past_the_retention(tmp_path: Path) -> None:
    """A market that has not traded for longer than the retention: pm-eod's
    next settlement still needs the last close."""
    conn = open_writer_connection(tmp_path / "clearing.db")
    try:
        _snapshots(conn, range(40, 80))
        prune_close_snapshots(conn, retention_days=30)
        kept = _dates(conn)
    finally:
        conn.close()
    assert kept == [_day(40)]


def test_an_empty_table_prunes_nothing(tmp_path: Path) -> None:
    conn = open_writer_connection(tmp_path / "clearing.db")
    try:
        assert prune_close_snapshots(conn, retention_days=30) == 0
    finally:
        conn.close()


# CLOSED prunes (dates 31-40 days old go; 1-30 stay), CONTINUOUS does not.
@pytest.mark.parametrize(("state", "left"), [("CLOSED", 30), ("CONTINUOUS", 40)])
def test_the_close_prunes_snapshots_with_the_trade_retention(
    tmp_path: Path, state: str, left: int
) -> None:
    proc = ClearingProcess(
        pub_addr="inproc://unused",
        db_path=tmp_path / "clearing.db",
        print_every=0,
        retention_days=30,
    )
    opened(proc._conn)
    try:
        _snapshots(proc._conn, range(1, 41))
        proc._handle_session_state({"state": state, "prev_state": "X"})
        dates = [d for d in _dates(proc._conn) if d != _day(0)]
    finally:
        proc._conn.close()
    assert len(dates) == left


def test_the_cli_prune_prunes_snapshots_too(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = tmp_path / "clearing.db"
    conn = open_writer_connection(db)
    _snapshots(conn, range(40))
    conn.close()
    monkeypatch.setattr(sys, "argv", ["pm-clearing-cli", "--datapath", str(db), "prune", "--days", "30"])  # fmt: skip
    cli.main()
    out = capsys.readouterr().out
    conn = sqlite3.connect(db)
    try:
        assert len(_dates(conn)) == 31
    finally:
        conn.close()
    assert "Pruned 18 close-snapshot rows" in out


def test_pm_eod_settles_from_its_recorded_baseline_after_a_prune(
    tmp_path: Path,
) -> None:
    """The previous settled date's snapshot was pruned (pm-eod had not run
    for longer than the retention): its equity recorded in eod.db is the
    baseline, not zero; a missing snapshot is no longer read as a reset."""
    conn = open_writer_connection(tmp_path / "clearing.db")
    try:
        # P&L in ticks: equity A +20.00, B -20.00 at today's close.
        flush_batch(conn, [], [_position("A", 2000.0), _position("B", -2000.0)], [])
        write_close_snapshot(conn, _day(0))
        settled = Baseline(
            {("A", "AAPL"): Decimal("10"), ("B", "AAPL"): Decimal("-10")},
            clearing_instance(conn),
        )
        got = settle_date(conn, _day(0), _day(45), settled)
    finally:
        conn.close()
    assert got.amounts_minor == {"A": 1000, "B": -1000}
    assert not got.baseline_reset and not got.baseline_changed
