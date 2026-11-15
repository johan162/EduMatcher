"""WP-CLR05 (clearing review C2-C8, C11): pm-clearing-cli says what is true.

See docs-design/reviews/EduMatcher-Clearing-Review-2026-11.md.
"""

from __future__ import annotations

import json
import shutil
import stat
import time
from pathlib import Path
from typing import Any

import pytest

from edumatcher.clearing.cli import build_parser
from edumatcher.clearing.cli import main as cli_main
from edumatcher.clearing.main import ClearingProcess
from edumatcher.clearing.store import (
    PositionRow,
    flush_batch,
    open_writer_connection,
    prune_old_events,
)
from edumatcher.models.message import make_trade_msg

_DAY_NS = 86_400 * 10**9


def _trade(seq: int, ts_ns: int, *, price: float = 100.0) -> list[bytes]:
    return make_trade_msg(
        {
            "id": f"000001-{seq:09d}",
            "run_seq": 1,
            "symbol": "AAPL",
            "buy_order_id": "b",
            "sell_order_id": "s",
            "buy_gateway_id": "GW01",
            "sell_gateway_id": "GW02",
            "price": price,
            "quantity": 10,
            "aggressor_side": "BUY",
            "ts_ns": ts_ns,
            "tick_decimals": 2,
            "price_ticks": round(price * 100),
            "match_type": "CONTINUOUS",
        }
    )


def _ledger(db: Path, ages_days: tuple[int, ...], retention_days: int = 7) -> None:
    """Trades `ages_days` old, written by pm-clearing, pruned as at a close."""
    proc = ClearingProcess(pub_addr="inproc://unused", db_path=db, print_every=0)
    now = time.time_ns()
    for seq, age in enumerate(ages_days, start=1):
        proc._handle_message(_trade(seq, now - age * _DAY_NS))
    proc.flush_now()
    prune_old_events(proc._conn, retention_days=retention_days)
    proc._conn.close()


def _cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db: Path,
    *args: str,
) -> tuple[int, str, str]:
    monkeypatch.setattr("sys.argv", ["pm-clearing-cli", "--datapath", str(db), *args])
    code = 0
    try:
        cli_main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    out = capsys.readouterr()
    return code, out.out, out.err


# --- C2: reconcile and pruned days ------------------------------------------


def test_reconcile_skips_pruned_days_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db = tmp_path / "clearing.db"
    _ledger(db, (10, 9, 0))

    code, out, _ = _cli(monkeypatch, capsys, db, "reconcile")

    assert code == 0
    assert "OK" in out
    assert "2 day(s) before" in out and "not reconciled (raw trades pruned)" in out
    assert "| BUY" not in out


def test_reconcile_inside_the_pruned_range_says_so(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db = tmp_path / "clearing.db"
    _ledger(db, (10, 9, 0))
    old = time.strftime("%Y-%m-%d", time.localtime(time.time() - 10 * 86_400))

    code, out, _ = _cli(
        monkeypatch, capsys, db, "reconcile", "--from", old, "--to", old
    )

    assert code == 0
    assert "not reconciled (raw trades pruned)" in out


def test_reconcile_json_is_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db = tmp_path / "clearing.db"
    _ledger(db, (10, 0))

    _, out, _ = _cli(monkeypatch, capsys, db, "--format", "json", "reconcile")

    assert json.loads(out) == []


# --- C3: reconcile money in currency -----------------------------------------


def _discrepancy(db: Path) -> None:
    """A daily row whose raw trades disagree with it (10 x 100.00 vs 10 x 99.00)."""
    _ledger(db, (0,))
    conn = open_writer_connection(db)
    conn.execute("UPDATE trade_events SET price = 9900")
    conn.commit()
    conn.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [((), [990.0, 1000.0, -10.0]), (("--raw-output",), [99000, 100000, -1000])],
    ids=["currency", "raw"],
)
def test_reconcile_money_is_in_currency_unless_raw(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    raw: tuple[str, ...],
    expected: list[float],
) -> None:
    db = tmp_path / "clearing.db"
    _discrepancy(db)

    _, out, _ = _cli(monkeypatch, capsys, db, *raw, "--format", "json", "reconcile")

    rows = json.loads(out)
    assert rows
    row = rows[0]
    assert [row["raw_notional"], row["summary_notional"], row["notional_diff"]] == (
        expected
    )
    assert row["tick_decimals"] == 2


# --- C4: full precision ------------------------------------------------------


def test_positions_print_every_digit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db = tmp_path / "clearing.db"
    conn = open_writer_connection(db)
    flush_batch(
        conn,
        [],
        [
            PositionRow(
                gateway_id="GW01",
                symbol="AAPL",
                net_qty=1,
                avg_cost=1234567.0,
                realized_pnl=1234567.0,
                unrealized_pnl=123456789.0,
                mark_price=1234567,
                buy_qty=1,
                sell_qty=0,
                buy_notional=123456789,
                sell_notional=0,
                last_trade_ts_ns=1,
                updated_ts_ns=1,
                tick_decimals=2,
            )
        ],
        [],
    )
    conn.close()

    _, out, _ = _cli(monkeypatch, capsys, db, "positions")

    assert "12345.67" in out
    assert "1234567.89" in out
    assert "e+" not in out


# --- C5: dates ---------------------------------------------------------------


def test_an_impossible_date_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db = tmp_path / "clearing.db"
    _ledger(db, (0,))

    code, _, err = _cli(monkeypatch, capsys, db, "daily", "--date", "2026-02-30")

    assert code == 2
    assert "2026-02-30" in err


# --- C6: prune ---------------------------------------------------------------


def test_prune_refuses_a_missing_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db = tmp_path / "typo" / "clearing.db"

    code, _, err = _cli(monkeypatch, capsys, db, "prune", "--days", "30")

    assert code == 1
    assert "not found" in err
    assert not db.exists()
    assert not db.parent.exists()


def test_prune_help_promises_no_vacuum() -> None:
    """The top-level help lists every subcommand's help line."""
    assert "VACUUM" not in build_parser().format_help()


# --- C7: one safe read-only opener -------------------------------------------


def test_a_data_path_with_a_question_mark_opens_the_right_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    where = tmp_path / "odd?dir"
    where.mkdir()
    db = where / "clearing.db"
    _ledger(db, (0,))

    code, out, err = _cli(monkeypatch, capsys, db, "--format", "json", "trades")

    assert code == 0, err
    assert len(json.loads(out)) == 1


# --- C8: health writes the real file -----------------------------------------


def test_health_reports_a_read_only_database(tmp_path: Path) -> None:
    from edumatcher.clearing.cli import _check_database_health

    db = tmp_path / "clearing.db"
    _ledger(db, (0,))
    copy = tmp_path / "ro" / "clearing.db"
    copy.parent.mkdir()
    shutil.copy(db, copy)
    copy.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    try:
        ok, detail, _ = _check_database_health(copy)
    finally:
        copy.chmod(stat.S_IRUSR | stat.S_IWUSR)

    assert ok is False
    assert "read" in detail.lower()


def test_health_passes_a_writable_database(tmp_path: Path) -> None:
    from edumatcher.clearing.cli import _check_database_health

    db = tmp_path / "clearing.db"
    _ledger(db, (0,))

    ok, detail, _ = _check_database_health(db)

    assert ok is True, detail


# --- C11: trades show where they came from -----------------------------------


def test_trades_show_match_type_and_msg_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db = tmp_path / "clearing.db"
    _ledger(db, (0,))

    _, out, _ = _cli(monkeypatch, capsys, db, "--format", "json", "trades")

    row: dict[str, Any] = json.loads(out)[0]
    assert row["match_type"] == "CONTINUOUS"
    assert "msg_id" in row
