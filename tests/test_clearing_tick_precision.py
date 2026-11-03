"""K6 (C4, C5): a symbol whose tick precision changes, and queries across symbols
of different precision.

Rule (K6): the ledger stores every money value of a position in ticks of the
precision of the *latest* trade for its symbol. When a trade arrives with a
different ``tick_decimals``, the position's stored values -- ``avg_cost``,
``mark_price``, both P&Ls and the buy/sell notionals -- are converted to the new
scale first (exact when precision grows, rounded to the nearest tick when it
shrinks), and so are the pending daily deltas and the daily row already
stored. Queries rank and sum in currency, never in raw ticks.
See docs-design/EduMatcher-Key-Component-Fixes-Workplan.md K6.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from edumatcher.clearing.ledger import Ledger
from edumatcher.clearing.store import (
    apply_schema,
    flush_batch,
    query_exposure,
    query_symbols,
)

_TS = 1_700_000_000_000_000_000


def _trade(
    ledger: Ledger,
    *,
    buyer: str,
    seller: str,
    price: int,
    qty: int,
    decimals: int,
    symbol: str = "AAPL",
    ts_ns: int = _TS,
) -> None:
    ledger.apply_trade(
        symbol=symbol,
        buy_gateway_id=buyer,
        sell_gateway_id=seller,
        price=price,
        tick_decimals=decimals,
        quantity=qty,
        ts_ns=ts_ns,
        ingest_ts_ns=ts_ns,
    )


def test_precision_increase_converts_the_stored_position() -> None:
    ledger = Ledger()
    _trade(ledger, buyer="A", seller="B", price=1000, qty=10, decimals=2)  # $10.00
    # A sells all ten at $11.00, quoted at 4 decimals.
    _trade(ledger, buyer="B", seller="A", price=110_000, qty=10, decimals=4)

    pos = ledger.position("A", "AAPL")
    assert pos is not None
    assert pos.tick_decimals == 4
    assert pos.net_qty == 0
    assert pos.realized_pnl == pytest.approx(100_000)  # $10.00 in 4-decimal ticks
    assert pos.buy_notional == 10 * 1000 * 100
    assert pos.sell_notional == 10 * 110_000


def test_precision_decrease_converts_the_stored_position() -> None:
    ledger = Ledger()
    _trade(ledger, buyer="A", seller="B", price=100_000, qty=10, decimals=4)  # $10.00
    _trade(ledger, buyer="B", seller="A", price=1100, qty=10, decimals=2)  # $11.00

    pos = ledger.position("A", "AAPL")
    assert pos is not None
    assert (pos.tick_decimals, pos.net_qty) == (2, 0)
    assert pos.realized_pnl == pytest.approx(1000)  # $10.00 in 2-decimal ticks


def test_holders_not_in_the_trade_are_converted_when_remarked() -> None:
    ledger = Ledger()
    _trade(ledger, buyer="A", seller="B", price=1000, qty=10, decimals=2)
    _trade(ledger, buyer="C", seller="D", price=110_000, qty=1, decimals=4)

    pos = ledger.position("A", "AAPL")
    assert pos is not None
    assert pos.tick_decimals == 4
    assert pos.avg_cost == pytest.approx(100_000)
    assert pos.mark_price == 110_000
    assert pos.unrealized_pnl == pytest.approx(10 * 10_000)


def test_daily_row_accumulates_in_one_scale_across_a_precision_change() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_schema(conn)
    ledger = Ledger()

    _trade(ledger, buyer="A", seller="B", price=1000, qty=10, decimals=2)
    pos_rows, daily_rows = ledger.get_flush_rows(updated_ts_ns=1)
    flush_batch(conn, [], pos_rows, daily_rows)
    ledger.clear_batch()

    _trade(ledger, buyer="B", seller="A", price=110_000, qty=10, decimals=4)
    pos_rows, daily_rows = ledger.get_flush_rows(updated_ts_ns=2)
    flush_batch(conn, [], pos_rows, daily_rows)

    row = conn.execute(
        "SELECT traded_notional, realized_pnl, tick_decimals"
        " FROM gateway_daily_summary WHERE gateway_id = 'A'"
    ).fetchone()
    assert row["tick_decimals"] == 4
    assert row["traded_notional"] == 10 * 1000 * 100 + 10 * 110_000
    assert row["realized_pnl"] == pytest.approx(100_000)


def test_pending_daily_delta_is_converted_within_one_batch() -> None:
    ledger = Ledger()
    _trade(ledger, buyer="A", seller="B", price=1000, qty=10, decimals=2)
    _trade(ledger, buyer="B", seller="A", price=110_000, qty=10, decimals=4)

    _pos, daily = ledger.get_flush_rows(updated_ts_ns=1)
    a = next(d for d in daily if d.gateway_id == "A")
    assert a.tick_decimals == 4
    assert a.delta_traded_notional == 10 * 1000 * 100 + 10 * 110_000


# --- C5 ---------------------------------------------------------------------


def _position(
    conn: sqlite3.Connection,
    gateway: str,
    symbol: str,
    *,
    net_qty: int,
    mark: int,
    decimals: int,
    unrealized: float = 0.0,
) -> None:
    conn.execute(
        "INSERT INTO gateway_symbol_positions (gateway_id, symbol, net_qty,"
        " avg_cost, realized_pnl, unrealized_pnl, mark_price, tick_decimals,"
        " buy_qty, sell_qty, buy_notional, sell_notional, updated_ts_ns)"
        " VALUES (?, ?, ?, 0.0, 0.0, ?, ?, ?, 0, 0, 0, 0, 1)",
        (gateway, symbol, net_qty, unrealized, mark, decimals),
    )


def _daily(
    conn: sqlite3.Connection,
    date: str,
    symbol: str,
    *,
    notional: int,
    decimals: int,
    realized: float = 0.0,
) -> None:
    conn.execute(
        "INSERT INTO gateway_daily_summary (trade_date, gateway_id, symbol,"
        " traded_qty, traded_notional, buy_qty, sell_qty, buy_notional,"
        " sell_notional, net_amount, realized_pnl, end_net_qty, end_avg_cost,"
        " end_unrealized_pnl, tick_decimals, last_trade_ts_ns, updated_ts_ns)"
        " VALUES (?, 'A', ?, 1, ?, 0, 0, 0, 0, 0, ?, 0, 0.0, 0.0, ?, 1, 1)",
        (date, symbol, notional, realized, decimals),
    )


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(tmp_path / "q.db")
    c.row_factory = sqlite3.Row
    apply_schema(c)
    return c


def test_exposure_ranks_by_currency_not_raw_ticks(conn: sqlite3.Connection) -> None:
    # CHEAP: 10 x $0.50 = $5 (raw 50_000); DEAR: 10 x $10.00 = $100 (raw 10_000).
    _position(conn, "A", "CHEAP", net_qty=10, mark=5000, decimals=4)
    _position(conn, "A", "DEAR", net_qty=10, mark=1000, decimals=2)

    for sort in ("gross_notional", "net_notional"):
        rows = query_exposure(conn, sort=sort)
        assert [r["symbol"] for r in rows] == ["DEAR", "CHEAP"], sort


def test_exposure_pnl_sorts_rank_by_currency(conn: sqlite3.Connection) -> None:
    _position(conn, "A", "FINE", net_qty=1, mark=1, decimals=4, unrealized=50_000)  # $5
    _position(
        conn, "A", "COARSE", net_qty=1, mark=1, decimals=2, unrealized=1_000
    )  # $10

    rows = query_exposure(conn, sort="unrealized_pnl")
    assert [r["symbol"] for r in rows] == ["COARSE", "FINE"]


def test_symbols_sums_a_symbol_traded_at_two_precisions_in_one_scale(
    conn: sqlite3.Connection,
) -> None:
    _daily(
        conn, "2026-11-02", "AAPL", notional=1_000, decimals=2, realized=500.0
    )  # $10, $5
    _daily(
        conn, "2026-11-03", "AAPL", notional=110_000, decimals=4, realized=20_000.0
    )  # $11, $2

    (row,) = query_symbols(conn, from_date="2026-11-02", to_date="2026-11-03")

    assert row["tick_decimals"] == 4
    assert row["traded_notional"] == pytest.approx(100_000 + 110_000)
    assert row["realized_pnl"] == pytest.approx(50_000 + 20_000)


def test_symbols_ranks_by_currency_across_symbols(conn: sqlite3.Connection) -> None:
    _daily(conn, "2026-11-03", "CHEAP", notional=50_000, decimals=4)  # $5
    _daily(conn, "2026-11-03", "DEAR", notional=1_000, decimals=2)  # $10

    rows = query_symbols(conn, sort="traded_notional")

    assert [r["symbol"] for r in rows] == ["DEAR", "CHEAP"]


def test_symbols_open_unrealized_is_in_the_row_scale(conn: sqlite3.Connection) -> None:
    _daily(conn, "2026-11-03", "AAPL", notional=110_000, decimals=4)
    _position(conn, "A", "AAPL", net_qty=1, mark=1, decimals=2, unrealized=300.0)  # $3
    _position(
        conn, "B", "AAPL", net_qty=1, mark=1, decimals=4, unrealized=20_000.0
    )  # $2

    (row,) = query_symbols(conn)

    assert row["open_unrealized_pnl"] == pytest.approx(30_000 + 20_000)


# --- K1-K10 review follow-ups -------------------------------------------------


def test_bystanders_daily_row_is_converted_within_one_batch() -> None:
    """A trades at 2 decimals; C and D then trade at 4 in the same batch. A's
    position is converted by the re-mark, and A's pending daily delta must be
    too: its row's money and its end_* snapshot share one tick_decimals
    (review #7)."""
    ledger = Ledger()
    _trade(ledger, buyer="A", seller="B", price=1000, qty=10, decimals=2)
    _trade(ledger, buyer="C", seller="D", price=110_000, qty=1, decimals=4)

    _pos, daily = ledger.get_flush_rows(updated_ts_ns=1)
    a = next(d for d in daily if d.gateway_id == "A")
    assert a.tick_decimals == 4
    assert a.delta_traded_notional == 10 * 1000 * 100
    assert a.delta_buy_notional == 10 * 1000 * 100
    assert a.end_avg_cost == pytest.approx(100_000)
    assert a.end_unrealized_pnl == pytest.approx(10 * 10_000)


def test_flat_holder_is_converted_with_its_symbol() -> None:
    """A flat position carries realized P&L in the old scale too; it is
    converted with the rest of the symbol, not left behind (review #7)."""
    ledger = Ledger()
    _trade(ledger, buyer="A", seller="B", price=1000, qty=10, decimals=2)
    _trade(ledger, buyer="B", seller="A", price=1100, qty=10, decimals=2)
    _trade(ledger, buyer="C", seller="D", price=110_000, qty=1, decimals=4)

    pos = ledger.position("A", "AAPL")
    assert pos is not None and pos.net_qty == 0
    assert pos.tick_decimals == 4
    assert pos.realized_pnl == pytest.approx(100_000)


def test_no_sqlite_math_functions_are_needed(conn: sqlite3.Connection) -> None:
    """POWER() exists only in SQLite builds compiled with math functions.
    Without it every daily upsert -- every clearing flush -- would fail, so
    neither the writes nor the queries may use it (review #6)."""

    def missing(*_args: object) -> float:
        raise sqlite3.OperationalError("no such function: POWER")

    conn.create_function("POWER", 2, missing)
    ledger = Ledger()
    _trade(ledger, buyer="A", seller="B", price=1000, qty=10, decimals=2)
    pos_rows, daily_rows = ledger.get_flush_rows(updated_ts_ns=1)
    flush_batch(conn, [], pos_rows, daily_rows)
    ledger.clear_batch()
    _trade(ledger, buyer="B", seller="A", price=110_000, qty=10, decimals=4)
    pos_rows, daily_rows = ledger.get_flush_rows(updated_ts_ns=2)
    flush_batch(conn, [], pos_rows, daily_rows)

    for sort in (
        "gross_notional",
        "net_notional",
        "realized_pnl",
        "unrealized_pnl",
        "total_pnl",
    ):
        query_exposure(conn, sort=sort)
    for sort in ("symbol", "traded_qty", "traded_notional", "realized_pnl"):
        query_symbols(conn, sort=sort)
    row = conn.execute(
        "SELECT traded_notional, tick_decimals FROM gateway_daily_summary"
        " WHERE gateway_id = 'A'"
    ).fetchone()
    assert (row["traded_notional"], row["tick_decimals"]) == (
        10 * 1000 * 100 + 10 * 110_000,
        4,
    )
