"""build_day: databases -> DayReport."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import closing
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from edumatcher.clearing.store import (
    PositionRow,
    TradeEventRow,
    flush_batch,
    open_writer_connection,
    write_close_snapshot,
)
from edumatcher.eod.assemble import build_day
from edumatcher.eod.ledger import LedgerError, open_ledger, record_day
from edumatcher.eod.roster import Trader
from edumatcher.eod.settle import settle_date
from edumatcher.stats.main import initialize_schema as initialize_stats


def pos(gw: str, qty: int, unreal: float, mark: int = 1050) -> PositionRow:
    return PositionRow(
        gateway_id=gw,
        symbol="AAPL",
        net_qty=qty,
        avg_cost=1000.0,
        realized_pnl=0.0,
        unrealized_pnl=unreal,
        mark_price=mark,
        buy_qty=0,
        sell_qty=0,
        buy_notional=0,
        sell_notional=0,
        last_trade_ts_ns=1,
        updated_ts_ns=1,
    )


def trade(
    trade_id: str, buy: str, sell: str, ts_ns: int, date: str = "2026-07-01"
) -> TradeEventRow:
    return TradeEventRow(
        id=trade_id,
        ts_ns=ts_ns,
        trade_date=date,
        symbol="AAPL",
        quantity=100,
        price=1000,
        buy_order_id="B",
        sell_order_id="S",
        buy_gateway_id=buy,
        sell_gateway_id=sell,
        aggressor_side="BUY",
        ingest_ts_ns=ts_ns,
    )


@pytest.fixture()
def dbs(
    tmp_path: Path,
) -> Generator[tuple[sqlite3.Connection, sqlite3.Connection], None, None]:
    clearing = open_writer_connection(tmp_path / "clearing.db")
    flush_batch(
        clearing,
        [
            trade("T2", "A", "B", 2_000_000_000_000),
            trade("T1", "A", "B", 1_000_000_000_000),
        ],
        [pos("A", 100, 5000.0), pos("B", -100, -5000.0), pos("Z", 0, 0.0)],
        [],
    )
    write_close_snapshot(clearing, "2026-07-01")
    ledger = open_ledger(tmp_path / "eod.db")
    record_day(ledger, "2026-07-01", settle_date(clearing, "2026-07-01", None))
    yield clearing, ledger
    clearing.close()
    ledger.close()


ROSTER = {
    "A": Trader("A", "Alice", "alice@example.org", 10_000),
    "Q": Trader("Q", "Quiet", None, 500),
}


def test_statements_for_active_listed_and_idle_traders(
    dbs: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    clearing, ledger = dbs
    rep = build_day(clearing, ledger, "2026-07-01", ROSTER)
    by = {s.gateway: s for s in rep.statements}
    assert sorted(by) == ["A", "B", "Q", "Z"]
    a = by["A"]
    assert (a.name, a.listed, a.amount_minor) == ("Alice", True, 5000)
    assert a.balance_minor == 15_000  # opening 100.00 + 50.00
    assert a.symbol_pnl == {"AAPL": Decimal("50")}
    assert [(p.symbol, p.net_qty, p.mark) for p in a.positions] == [
        ("AAPL", 100, Decimal("10.50"))
    ]
    assert [t.time_utc for t in a.trades] == ["00:16:40", "00:33:20"]
    assert (a.trades[0].side, a.trades[0].price) == ("BUY", Decimal("10.00"))
    assert str(a.positions[0].mark) == "10.50" and str(a.trades[0].price) == "10.00"
    assert by["B"].trades[0].side == "SELL" and by["B"].listed is False
    q = by["Q"]
    assert (q.amount_minor, q.balance_minor, q.trades, q.positions) == (0, 500, (), ())
    assert by["Z"].positions == ()  # flat


def test_a_self_trade_is_one_line_and_other_days_are_left_out(
    dbs: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    clearing, ledger = dbs
    flush_batch(
        clearing,
        [
            trade("T3", "B", "B", 3_000_000_000_000),
            trade("T0", "A", "B", 1, date="2026-06-30"),
        ],
        [],
        [],
    )
    by = {
        s.gateway: s for s in build_day(clearing, ledger, "2026-07-01", {}).statements
    }
    assert [t.side for t in by["A"].trades] == ["BUY", "BUY"]
    assert [t.side for t in by["B"].trades] == ["SELL", "SELL", "SELF"]


def test_result_by_symbol_leaves_out_what_is_neither_held_traded_nor_moved(
    tmp_path: Path,
) -> None:
    # A symbol closed out long ago stays in the snapshot at 0.00 forever.
    clearing = open_writer_connection(tmp_path / "clearing.db")
    old = lambda sym, qty: replace(pos("A", qty, 0.0), symbol=sym)  # noqa: E731
    flush_batch(
        clearing,
        [trade("T1", "A", "B", 1_000_000_000_000)],  # AAPL, flat afterwards
        [old("AAPL", 0), old("HELD", 10), old("GONE", 0), pos("B", 0, 0.0)],
        [],
    )
    write_close_snapshot(clearing, "2026-07-01")
    ledger = open_ledger(tmp_path / "eod.db")
    record_day(ledger, "2026-07-01", settle_date(clearing, "2026-07-01", None))
    by = {
        s.gateway: s for s in build_day(clearing, ledger, "2026-07-01", {}).statements
    }
    clearing.close()
    ledger.close()
    assert sorted(by["A"].symbol_pnl) == ["AAPL", "HELD"]  # traded; held
    assert sorted(by["B"].symbol_pnl) == ["AAPL"]  # traded


def test_warnings_name_unlisted_gateways(
    dbs: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    clearing, ledger = dbs
    rep = build_day(clearing, ledger, "2026-07-01", ROSTER)
    assert rep.warnings == (
        "gateway B is not in the roster",
        "gateway Z is not in the roster",
    )


def test_empty_roster_warns_once(
    dbs: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    clearing, ledger = dbs
    rep = build_day(clearing, ledger, "2026-07-01", {})
    assert rep.warnings == ("no roster: statements are keyed by gateway id",)


def test_summary_proves_the_day_nets_out(
    dbs: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    clearing, ledger = dbs
    rep = build_day(clearing, ledger, "2026-07-01", ROSTER)
    assert (rep.summary.total_minor, rep.summary.rounding_minor) == (0, 0)
    assert rep.summary.symbols is None


def test_market_stats_are_used_when_given(
    dbs: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    clearing, ledger = dbs
    with closing(sqlite3.connect(":memory:")) as stats:
        stats.row_factory = sqlite3.Row
        initialize_stats(stats)
        stats.execute(
            "INSERT INTO daily_stats (date, symbol, close_price, volume, trade_count, turnover)"
            " VALUES ('2026-07-01', 'AAPL', 1050, 200, 2, 210000)"
        )
        rep = build_day(clearing, ledger, "2026-07-01", ROSTER, stats)
    assert rep.summary.symbols is not None
    assert [
        (x.symbol, x.volume, x.trade_count, x.close) for x in rep.summary.symbols
    ] == [("AAPL", 200, 2, Decimal("10.50"))]


def test_an_unsettled_date_is_an_error(
    dbs: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    clearing, ledger = dbs
    with pytest.raises(LedgerError, match="not settled"):
        build_day(clearing, ledger, "2026-07-02", ROSTER)


def test_a_broken_stats_db_is_a_warning_not_a_failure(
    dbs: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    clearing, ledger = dbs
    with closing(sqlite3.connect(":memory:")) as stats:  # no daily_stats table
        rep = build_day(clearing, ledger, "2026-07-01", ROSTER, stats)
    assert rep.summary.symbols is None
    assert any(
        w.startswith("market statistics unavailable: ") and "daily_stats" in w
        for w in rep.warnings
    )


def test_an_interval_over_a_skipped_close_names_its_start(
    dbs: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    clearing, ledger = dbs
    flush_batch(clearing, [], [pos("A", 100, 6000.0), pos("B", -100, -6000.0)], [])
    write_close_snapshot(clearing, "2026-07-02")  # closed, never settled
    flush_batch(clearing, [], [pos("A", 100, 7000.0), pos("B", -100, -7000.0)], [])
    write_close_snapshot(clearing, "2026-07-03")
    record_day(
        ledger,
        "2026-07-03",
        settle_date(clearing, "2026-07-03", "2026-07-01"),
    )
    by = {
        s.gateway: s
        for s in build_day(clearing, ledger, "2026-07-03", ROSTER).statements
    }
    assert by["A"].since == "2026-07-01" and by["A"].amount_minor == 2000
    by = {
        s.gateway: s
        for s in build_day(clearing, ledger, "2026-07-01", ROSTER).statements
    }
    assert by["A"].since is None
