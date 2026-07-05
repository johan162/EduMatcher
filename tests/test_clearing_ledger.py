"""Tests for the clearing v2 ledger — P&L math and position state transitions."""

from __future__ import annotations

import pytest

from edumatcher.clearing.ledger import Ledger, _apply_fill_to_position, _Position

# ---------------------------------------------------------------------------
# Low-level fill helper tests
# ---------------------------------------------------------------------------


def _pos(gateway_id: str = "GW1", symbol: str = "AAPL") -> _Position:
    return _Position(gateway_id=gateway_id, symbol=symbol)


class TestApplyFillToPosition:
    def test_open_long(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=100, price=1000, is_buy=True, ts_ns=1)
        assert pos.net_qty == 100
        assert pos.avg_cost == pytest.approx(1000.0)
        assert pos.realized_pnl == pytest.approx(0.0)
        assert pos.mark_price == 1000

    def test_open_short(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=50, price=2000, is_buy=False, ts_ns=1)
        assert pos.net_qty == -50
        assert pos.avg_cost == pytest.approx(2000.0)
        assert pos.realized_pnl == pytest.approx(0.0)

    def test_add_to_long_updates_vwap(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=10, price=1000, is_buy=True, ts_ns=1)
        _apply_fill_to_position(pos, qty=10, price=1100, is_buy=True, ts_ns=2)
        # avg = (10*1000 + 10*1100) / 20 = 21000/20 = 1050
        assert pos.net_qty == 20
        assert pos.avg_cost == pytest.approx(1050.0)
        assert pos.realized_pnl == pytest.approx(0.0)

    def test_add_to_short_updates_vwap(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=10, price=1000, is_buy=False, ts_ns=1)
        _apply_fill_to_position(pos, qty=10, price=900, is_buy=False, ts_ns=2)
        assert pos.net_qty == -20
        assert pos.avg_cost == pytest.approx(950.0)
        assert pos.realized_pnl == pytest.approx(0.0)

    def test_partial_close_long(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=100, price=1000, is_buy=True, ts_ns=1)
        realized = _apply_fill_to_position(
            pos, qty=40, price=1100, is_buy=False, ts_ns=2
        )
        # realized = (1100 - 1000) * 40 = 4000
        assert realized == pytest.approx(4000.0)
        assert pos.realized_pnl == pytest.approx(4000.0)
        assert pos.net_qty == 60
        # avg_cost unchanged after partial close
        assert pos.avg_cost == pytest.approx(1000.0)

    def test_full_close_long(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=100, price=1000, is_buy=True, ts_ns=1)
        realized = _apply_fill_to_position(
            pos, qty=100, price=1100, is_buy=False, ts_ns=2
        )
        assert realized == pytest.approx(10000.0)
        assert pos.net_qty == 0
        assert pos.avg_cost == pytest.approx(0.0)
        assert pos.realized_pnl == pytest.approx(10000.0)

    def test_full_close_short(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=50, price=2000, is_buy=False, ts_ns=1)
        realized = _apply_fill_to_position(
            pos, qty=50, price=1800, is_buy=True, ts_ns=2
        )
        # realized = (2000 - 1800) * 50 = 10000
        assert realized == pytest.approx(10000.0)
        assert pos.net_qty == 0
        assert pos.avg_cost == pytest.approx(0.0)

    def test_partial_close_short(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=100, price=500, is_buy=False, ts_ns=1)
        realized = _apply_fill_to_position(pos, qty=30, price=480, is_buy=True, ts_ns=2)
        # realized = (500 - 480) * 30 = 600
        assert realized == pytest.approx(600.0)
        assert pos.net_qty == -70
        assert pos.avg_cost == pytest.approx(500.0)

    def test_cross_zero_long_to_short(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=100, price=1000, is_buy=True, ts_ns=1)
        # Sell 150 — closes 100 long, opens 50 short
        realized = _apply_fill_to_position(
            pos, qty=150, price=1200, is_buy=False, ts_ns=2
        )
        # realized on close: (1200 - 1000) * 100 = 20000
        assert realized == pytest.approx(20000.0)
        assert pos.net_qty == -50
        # New short avg_cost = fill price
        assert pos.avg_cost == pytest.approx(1200.0)
        assert pos.realized_pnl == pytest.approx(20000.0)

    def test_cross_zero_short_to_long(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=50, price=2000, is_buy=False, ts_ns=1)
        # Buy 80 — closes 50 short, opens 30 long
        realized = _apply_fill_to_position(
            pos, qty=80, price=1800, is_buy=True, ts_ns=2
        )
        # realized on close: (2000 - 1800) * 50 = 10000
        assert realized == pytest.approx(10000.0)
        assert pos.net_qty == 30
        assert pos.avg_cost == pytest.approx(1800.0)

    def test_realized_pnl_loss(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=100, price=1000, is_buy=True, ts_ns=1)
        realized = _apply_fill_to_position(
            pos, qty=100, price=900, is_buy=False, ts_ns=2
        )
        assert realized == pytest.approx(-10000.0)
        assert pos.realized_pnl == pytest.approx(-10000.0)

    def test_unrealized_pnl_long(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=10, price=1000, is_buy=True, ts_ns=1)
        # Another trade in same symbol updates mark_price
        _apply_fill_to_position(pos, qty=5, price=1100, is_buy=True, ts_ns=2)
        # net_qty=15, avg_cost=(10*1000+5*1100)/15=1033.33, mark=1100
        # unrealized = 15 * (1100 - 1033.33...) ≈ 1000
        assert pos.unrealized_pnl == pytest.approx(15 * (1100 - pos.avg_cost))

    def test_flat_then_reopen(self) -> None:
        """Full close followed by reopening on the same side works correctly."""
        pos = _pos()
        _apply_fill_to_position(pos, qty=100, price=1000, is_buy=True, ts_ns=1)
        _apply_fill_to_position(pos, qty=100, price=1050, is_buy=False, ts_ns=2)
        assert pos.net_qty == 0
        # Reopen
        _apply_fill_to_position(pos, qty=50, price=1100, is_buy=True, ts_ns=3)
        assert pos.net_qty == 50
        assert pos.avg_cost == pytest.approx(1100.0)

    def test_last_trade_ts_ns_updated(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=10, price=100, is_buy=True, ts_ns=42_000)
        assert pos.last_trade_ts_ns == 42_000

    def test_mark_price_updated_on_every_fill(self) -> None:
        pos = _pos()
        _apply_fill_to_position(pos, qty=10, price=100, is_buy=True, ts_ns=1)
        assert pos.mark_price == 100
        _apply_fill_to_position(pos, qty=5, price=110, is_buy=True, ts_ns=2)
        assert pos.mark_price == 110


# ---------------------------------------------------------------------------
# Worked example from design doc (table in section 7.2)
# ---------------------------------------------------------------------------


class TestWorkedExample:
    """Reproduce the five-step example from the design document."""

    def test_full_sequence(self) -> None:
        pos = _pos()

        # Step 1: BUY 10 @ 100
        _apply_fill_to_position(pos, qty=10, price=100, is_buy=True, ts_ns=1)
        assert pos.net_qty == 10
        assert pos.avg_cost == pytest.approx(100.0)
        assert pos.realized_pnl == pytest.approx(0.0)

        # Step 2: BUY 10 @ 110  (avg = (10*100 + 10*110) / 20 = 105)
        _apply_fill_to_position(pos, qty=10, price=110, is_buy=True, ts_ns=2)
        assert pos.net_qty == 20
        assert pos.avg_cost == pytest.approx(105.0)

        # Step 3: SELL 20 @ 115  (realized = (115-105)*20 = 200, flat)
        _apply_fill_to_position(pos, qty=20, price=115, is_buy=False, ts_ns=3)
        assert pos.net_qty == 0
        assert pos.realized_pnl == pytest.approx(200.0)

        # Step 4: SELL 15 @ 108  (cross-zero from flat — open short)
        _apply_fill_to_position(pos, qty=15, price=108, is_buy=False, ts_ns=4)
        assert pos.net_qty == -15
        assert pos.avg_cost == pytest.approx(108.0)
        assert pos.realized_pnl == pytest.approx(200.0)

        # Step 5: BUY 20 @ 105  (close 15 short + open 5 long)
        # realized from short: (108 - 105) * 15 = 45
        _apply_fill_to_position(pos, qty=20, price=105, is_buy=True, ts_ns=5)
        assert pos.net_qty == 5
        assert pos.avg_cost == pytest.approx(105.0)
        assert pos.realized_pnl == pytest.approx(245.0)


# ---------------------------------------------------------------------------
# Ledger integration tests
# ---------------------------------------------------------------------------


class TestLedger:
    def _make_ts(self, day: int) -> int:
        """Build a nanosecond timestamp for 2026-07-0{day} 12:00:00 UTC."""
        from datetime import datetime, timezone

        dt = datetime(2026, 7, day, 12, 0, 0, tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)

    def test_apply_trade_updates_both_legs(self) -> None:
        ledger = Ledger()
        ts = self._make_ts(1)
        ledger.apply_trade(
            symbol="AAPL",
            buy_gateway_id="GW_BUY",
            sell_gateway_id="GW_SELL",
            price=1000,
            quantity=100,
            ts_ns=ts,
            ingest_ts_ns=ts + 1000,
        )

        buy_pos = ledger.position("GW_BUY", "AAPL")
        sell_pos = ledger.position("GW_SELL", "AAPL")
        assert buy_pos is not None
        assert sell_pos is not None
        assert buy_pos.net_qty == 100
        assert sell_pos.net_qty == -100

    def test_get_flush_rows_returns_position_and_daily(self) -> None:
        ledger = Ledger()
        ts = self._make_ts(1)
        ledger.apply_trade(
            symbol="AAPL",
            buy_gateway_id="GW_A",
            sell_gateway_id="GW_B",
            price=500,
            quantity=10,
            ts_ns=ts,
            ingest_ts_ns=ts,
        )

        pos_rows, daily_rows = ledger.get_flush_rows(updated_ts_ns=ts + 100)

        # Two gateways → two position rows, two daily rows
        assert len(pos_rows) == 2
        assert len(daily_rows) == 2

        gws = {r.gateway_id for r in pos_rows}
        assert gws == {"GW_A", "GW_B"}

    def test_clear_batch_resets_daily_deltas(self) -> None:
        ledger = Ledger()
        ts = self._make_ts(1)
        ledger.apply_trade(
            symbol="MSFT",
            buy_gateway_id="GW_X",
            sell_gateway_id="GW_Y",
            price=200,
            quantity=5,
            ts_ns=ts,
            ingest_ts_ns=ts,
        )
        ledger.clear_batch()

        # After clearing batch, no daily rows should be pending.
        _, daily_rows = ledger.get_flush_rows(updated_ts_ns=ts)
        assert daily_rows == []

        # Positions should still be in memory.
        assert ledger.position("GW_X", "MSFT") is not None

    def test_positions_survive_across_batches(self) -> None:
        """Realized P&L accumulates across multiple flush cycles."""
        ledger = Ledger()
        ts1 = self._make_ts(1)
        ts2 = self._make_ts(2)

        # First batch: buy 100
        ledger.apply_trade(
            symbol="AAPL",
            buy_gateway_id="GW_A",
            sell_gateway_id="GW_B",
            price=1000,
            quantity=100,
            ts_ns=ts1,
            ingest_ts_ns=ts1,
        )
        ledger.clear_batch()

        # Second batch: sell 100 at profit
        ledger.apply_trade(
            symbol="AAPL",
            buy_gateway_id="GW_B",
            sell_gateway_id="GW_A",
            price=1100,
            quantity=100,
            ts_ns=ts2,
            ingest_ts_ns=ts2,
        )

        buy_pos = ledger.position("GW_A", "AAPL")
        assert buy_pos is not None
        assert buy_pos.net_qty == 0
        assert buy_pos.realized_pnl == pytest.approx(10000.0)

    def test_daily_delta_accumulates_notional(self) -> None:
        ledger = Ledger()
        ts = self._make_ts(1)

        ledger.apply_trade(
            symbol="AAPL",
            buy_gateway_id="GW1",
            sell_gateway_id="GW2",
            price=100,
            quantity=10,
            ts_ns=ts,
            ingest_ts_ns=ts,
        )
        _, daily_rows = ledger.get_flush_rows(updated_ts_ns=ts)

        buy_daily = next(r for r in daily_rows if r.gateway_id == "GW1")
        sell_daily = next(r for r in daily_rows if r.gateway_id == "GW2")

        assert buy_daily.delta_buy_qty == 10
        assert buy_daily.delta_buy_notional == 1000
        assert buy_daily.delta_sell_qty == 0
        assert sell_daily.delta_sell_qty == 10
        assert sell_daily.delta_sell_notional == 1000
        assert sell_daily.delta_buy_qty == 0

    def test_daily_row_net_amount(self) -> None:
        ledger = Ledger()
        ts = self._make_ts(1)
        ledger.apply_trade(
            symbol="AAPL",
            buy_gateway_id="GW1",
            sell_gateway_id="GW1",
            price=100,
            quantity=5,
            ts_ns=ts,
            ingest_ts_ns=ts,
        )
        _, daily_rows = ledger.get_flush_rows(updated_ts_ns=ts)
        # GW1 buys 5 and sells 5 in same batch — net_amount = 500 - 500 = 0
        row = daily_rows[0]
        assert row.delta_net_amount == row.delta_buy_notional - row.delta_sell_notional

    def test_all_positions(self) -> None:
        ledger = Ledger()
        ts = self._make_ts(1)
        ledger.apply_trade(
            symbol="AAPL",
            buy_gateway_id="GW_A",
            sell_gateway_id="GW_B",
            price=100,
            quantity=1,
            ts_ns=ts,
            ingest_ts_ns=ts,
        )
        ledger.apply_trade(
            symbol="MSFT",
            buy_gateway_id="GW_A",
            sell_gateway_id="GW_C",
            price=200,
            quantity=1,
            ts_ns=ts,
            ingest_ts_ns=ts,
        )
        positions = ledger.all_positions()
        # GW_A: AAPL and MSFT; GW_B: AAPL; GW_C: MSFT
        assert len(positions) == 4

    def test_duplicate_trade_date_in_same_batch(self) -> None:
        """Two trades on the same day accumulate into one DailySummaryRow per key."""
        ledger = Ledger()
        ts = self._make_ts(1)

        ledger.apply_trade(
            symbol="AAPL",
            buy_gateway_id="GW1",
            sell_gateway_id="GW2",
            price=100,
            quantity=10,
            ts_ns=ts,
            ingest_ts_ns=ts,
        )
        ledger.apply_trade(
            symbol="AAPL",
            buy_gateway_id="GW1",
            sell_gateway_id="GW2",
            price=110,
            quantity=5,
            ts_ns=ts + 1_000_000,
            ingest_ts_ns=ts + 1_000_000,
        )

        _, daily_rows = ledger.get_flush_rows(updated_ts_ns=ts + 2_000_000)

        # Still two keys: (GW1, AAPL) and (GW2, AAPL)
        gw1_row = next(r for r in daily_rows if r.gateway_id == "GW1")
        assert gw1_row.delta_buy_qty == 15
        assert gw1_row.delta_buy_notional == 100 * 10 + 110 * 5
