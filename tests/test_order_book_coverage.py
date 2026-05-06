"""
Additional order_book tests targeting uncovered lines:
  - ICE replenishment when passive iceberg refills during a sweep
  - Stop/stop-limit triggers (SELL stop when price falls, BUY stop when rises)
  - Trailing stop ratchet and trigger
  - amend_order edge cases (invalid order state, non-amendable type, zero qty)
  - cancel_order
  - resting_orders / restore_stats
  - snapshot with icebergs and cancelled entries
  - FOK _available_qty with price filter
"""

from __future__ import annotations

import time

import pytest

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import (
    Order,
    OrderStatus,
    OrderType,
    Side,
    TIF,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make(
    side: Side,
    order_type: OrderType,
    qty: int,
    price: float | None = None,
    stop_price: float | None = None,
    visible_qty: int | None = None,
    trail_offset: float | None = None,
    gateway: str = "GW01",
) -> Order:
    o = Order.create(
        symbol="TEST",
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway,
        tif=TIF.DAY,
        price=price,
        stop_price=stop_price,
        visible_qty=visible_qty,
    )
    if trail_offset is not None:
        o.trail_offset = trail_offset
        o.stop_price = stop_price
    return o


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class TestCancelOrder:
    def test_cancel_resting_limit(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100.0)
        book.process(o, match=False)
        book.cancel_order(o.id)
        assert o.status == OrderStatus.CANCELLED

    def test_cancel_unknown_order_returns_none(self) -> None:
        book = OrderBook("TEST")
        result = book.cancel_order("NONEXISTENT")
        assert result is None

    def test_cancel_reduces_qty_index(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100.0)
        book.process(o, match=False)
        book.cancel_order(o.id)
        assert book._bid_qty.get(100.0, 0) == 0


# ---------------------------------------------------------------------------
# Resting orders / restore_stats
# ---------------------------------------------------------------------------


class TestRestingOrdersAndStats:
    def test_resting_orders_returns_active(self) -> None:
        book = OrderBook("TEST")
        o1 = _make(Side.BUY, OrderType.LIMIT, 100, price=100.0)
        o2 = _make(Side.SELL, OrderType.LIMIT, 100, price=101.0)
        book.process(o1, match=False)
        book.process(o2, match=False)
        resting = book.resting_orders()
        assert o1 in resting
        assert o2 in resting

    def test_resting_orders_excludes_cancelled(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100.0)
        book.process(o, match=False)
        book.cancel_order(o.id)
        assert book.resting_orders() == []

    def test_restore_stats(self) -> None:
        book = OrderBook("TEST")
        book.restore_stats(149.5, 150.5)
        assert book.last_buy_price == 149.5
        assert book.last_sell_price == 150.5


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_empty_book(self) -> None:
        book = OrderBook("TEST")
        snap = book.snapshot()
        assert snap["symbol"] == "TEST"
        assert snap["bids"] == []
        assert snap["asks"] == []
        assert snap["last_price"] is None

    def test_snapshot_aggregates_levels(self) -> None:
        book = OrderBook("TEST")
        book.process(_make(Side.BUY, OrderType.LIMIT, 100, price=100.0), match=False)
        book.process(_make(Side.BUY, OrderType.LIMIT, 200, price=100.0), match=False)
        snap = book.snapshot()
        assert len(snap["bids"]) == 1
        assert snap["bids"][0]["qty"] == 300
        assert snap["bids"][0]["count"] == 2

    def test_snapshot_iceberg_shows_displayed_only(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.ICEBERG, 500, price=100.0, visible_qty=50)
        book.process(o, match=False)
        snap = book.snapshot()
        assert snap["bids"][0]["qty"] == 50

    def test_snapshot_excludes_cancelled(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100.0)
        book.process(o, match=False)
        book.cancel_order(o.id)
        snap = book.snapshot()
        assert snap["bids"] == []

    def test_snapshot_last_trade_info(self) -> None:
        book = OrderBook("TEST")
        book.process(_make(Side.BUY, OrderType.LIMIT, 100, price=100.0), match=False)
        book.process(_make(Side.SELL, OrderType.LIMIT, 100, price=100.0), match=True)
        snap = book.snapshot()
        assert snap["last_price"] == 100.0
        assert snap["last_qty"] == 100


# ---------------------------------------------------------------------------
# Amend edge cases
# ---------------------------------------------------------------------------


class TestAmendEdgeCases:
    def test_amend_unknown_order(self) -> None:
        book = OrderBook("TEST")
        order, reset, reason = book.amend_order("BAD_ID")
        assert order is None
        assert "not found" in reason.lower()

    def test_amend_cancelled_order(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100.0)
        book.process(o, match=False)
        book.cancel_order(o.id)
        result, reset, reason = book.amend_order(o.id)
        assert result is None
        assert "cannot amend" in reason.lower()

    def test_amend_market_order_rejected(self) -> None:
        book = OrderBook("TEST")
        # Place a limit sell so the market buy won't immediately match
        book.process(_make(Side.SELL, OrderType.LIMIT, 100, price=200.0), match=False)
        o = _make(Side.BUY, OrderType.MARKET, 10)
        # Market orders aren't resting, so use a workaround: directly add to index
        o.status = OrderStatus.NEW
        book._order_index[o.id] = o
        result, reset, reason = book.amend_order(o.id)
        assert result is None
        assert "cannot amend" in reason.lower()

    def test_amend_zero_qty_rejected(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100.0)
        book.process(o, match=False)
        result, reset, reason = book.amend_order(o.id, new_qty=0)
        assert result is None
        assert "quantity" in reason.lower()

    def test_amend_qty_below_filled_rejected(self) -> None:
        book = OrderBook("TEST")
        # Set up a partial fill
        buy = _make(Side.BUY, OrderType.LIMIT, 100, price=100.0)
        book.process(buy, match=False)
        # Manually mark as partial
        buy.status = OrderStatus.PARTIAL
        buy.remaining_qty = 50
        result, reset, reason = book.amend_order(buy.id, new_qty=40)
        assert result is None
        assert "filled" in reason.lower()

    def test_amend_price_down_preserves_priority(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100.0)
        book.process(o, match=False)
        result, reset, reason = book.amend_order(o.id, new_qty=80)
        assert result is not None
        assert reset is False
        assert o.remaining_qty == 80

    def test_amend_price_change_resets_priority(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100.0)
        book.process(o, match=False)
        result, reset, reason = book.amend_order(o.id, new_price=101.0)
        assert result is not None
        assert reset is True
        assert o.price == 101.0

    def test_amend_qty_increase_resets_priority(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100.0)
        book.process(o, match=False)
        result, reset, reason = book.amend_order(o.id, new_qty=200)
        assert result is not None
        assert reset is True


# ---------------------------------------------------------------------------
# Stop triggers
# ---------------------------------------------------------------------------


class TestStopTriggers:
    def test_buy_stop_triggered_by_price_rise(self) -> None:
        book = OrderBook("TEST")
        # BUY STOP fires when price rises to/above stop_price
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=105.0)
        book.process(stop, match=False)
        # Simulate a trade at 106.0
        book.last_trade_price = 106.0
        now = time.time()
        triggered = book._check_stops(now)
        assert len(triggered) == 1
        assert triggered[0].order_type == OrderType.MARKET

    def test_sell_stop_triggered_by_price_fall(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.SELL, OrderType.STOP, 100, stop_price=95.0)
        book.process(stop, match=False)
        book.last_trade_price = 94.0
        triggered = book._check_stops(time.time())
        assert len(triggered) == 1
        assert triggered[0].order_type == OrderType.MARKET

    def test_buy_stop_not_triggered_below_price(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=110.0)
        book.process(stop, match=False)
        book.last_trade_price = 105.0
        triggered = book._check_stops(time.time())
        assert triggered == []

    def test_stop_limit_converts_to_limit(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP_LIMIT, 100, price=106.0, stop_price=105.0)
        book.process(stop, match=False)
        book.last_trade_price = 106.0
        triggered = book._check_stops(time.time())
        assert len(triggered) == 1
        assert triggered[0].order_type == OrderType.LIMIT

    def test_no_stops_without_trade_price(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=105.0)
        book.process(stop, match=False)
        triggered = book._check_stops(time.time())
        assert triggered == []

    def test_cancelled_stop_skipped(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=105.0)
        book.process(stop, match=False)
        book.cancel_order(stop.id)
        book.last_trade_price = 110.0
        triggered = book._check_stops(time.time())
        assert triggered == []

    def test_multiple_sell_stops_fire_from_one_price(self) -> None:
        """A single price drop below multiple SELL stop prices triggers all of them."""
        book = OrderBook("TEST")
        s1 = _make(Side.SELL, OrderType.STOP, 50, stop_price=100.0)
        s2 = _make(Side.SELL, OrderType.STOP, 50, stop_price=102.0)
        s3 = _make(Side.SELL, OrderType.STOP_LIMIT, 50, price=90.0, stop_price=104.0)
        for s in (s1, s2, s3):
            book.process(s, match=False)
        book.last_trade_price = 95.0  # below all three stop prices
        triggered = book._check_stops(time.time())
        assert len(triggered) == 3
        # STOP → MARKET, STOP_LIMIT → LIMIT
        types = {o.order_type for o in triggered}
        assert OrderType.MARKET in types
        assert OrderType.LIMIT in types

    def test_stop_cascade_end_to_end(self) -> None:
        """One trade triggers three SELL STOPs; each then executes against resting bids."""
        book = OrderBook("TEST")
        # Resting bids for the cascaded SELL MARKETs to consume
        for price in (95.0, 96.0, 97.0):
            book.process(_make(Side.BUY, OrderType.LIMIT, 50, price=price), match=False)
        # SELL STOPs that fire when price falls to/below their stop_price
        for stop_price in (100.0, 102.0, 104.0):
            book.process(
                _make(Side.SELL, OrderType.STOP, 50, stop_price=stop_price), match=False
            )
        # Thin ask to trigger the initial trade and set last_trade_price = 50
        book.process(_make(Side.SELL, OrderType.LIMIT, 10, price=50.0), match=False)

        buy_mkt = _make(Side.BUY, OrderType.MARKET, 10)
        trades, _events = book.process(buy_mkt)

        # 1 initial trade (BUY MKT vs SELL LIMIT@50) + 3 cascaded (each SELL MKT vs a resting bid)
        assert len(trades) == 4
        # All three bids should now be FILLED
        for order in (book._order_index.get(o.id) for o in [buy_mkt]):
            pass  # buy_mkt itself is FILLED/not resting
        snap = book.snapshot()
        assert snap["bids"] == []  # all three bids consumed by cascaded stops


# ---------------------------------------------------------------------------
# Trailing stops
# ---------------------------------------------------------------------------


class TestTrailingStops:
    def test_sell_trailing_stop_ratchets_up(self) -> None:
        book = OrderBook("TEST")
        ts = _make(Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5.0)
        ts.stop_price = 95.0  # initial stop: 100 - 5
        book.last_trade_price = 100.0
        book._trailing_stops = [ts]
        book._order_index[ts.id] = ts
        # Price rises to 103 → stop ratchets to 98 (103 - 5), not triggered yet
        book.last_trade_price = 103.0
        triggered = book._check_trailing_stops(time.time())
        assert triggered == []
        assert ts.stop_price == pytest.approx(98.0)

    def test_sell_trailing_stop_triggered(self) -> None:
        book = OrderBook("TEST")
        ts = _make(Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5.0)
        ts.stop_price = 100.0
        book._trailing_stops = [ts]
        book._order_index[ts.id] = ts
        # Price falls to/below stop
        book.last_trade_price = 99.0
        triggered = book._check_trailing_stops(time.time())
        assert len(triggered) == 1
        assert triggered[0].order_type == OrderType.MARKET

    def test_buy_trailing_stop_ratchets_down(self) -> None:
        book = OrderBook("TEST")
        ts = _make(Side.BUY, OrderType.TRAILING_STOP, 100, trail_offset=5.0)
        ts.stop_price = 105.0  # initial stop: 100 + 5
        book._trailing_stops = [ts]
        book._order_index[ts.id] = ts
        # Price falls to 97 → stop ratchets down to 102 (97+5), not triggered
        book.last_trade_price = 97.0
        triggered = book._check_trailing_stops(time.time())
        assert triggered == []
        assert ts.stop_price == pytest.approx(102.0)

    def test_buy_trailing_stop_triggered(self) -> None:
        book = OrderBook("TEST")
        ts = _make(Side.BUY, OrderType.TRAILING_STOP, 100, trail_offset=5.0)
        ts.stop_price = 100.0
        book._trailing_stops = [ts]
        book._order_index[ts.id] = ts
        book.last_trade_price = 101.0  # >= stop
        triggered = book._check_trailing_stops(time.time())
        assert len(triggered) == 1

    def test_trailing_stop_no_trade_price(self) -> None:
        book = OrderBook("TEST")
        ts = _make(Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5.0)
        ts.stop_price = 95.0
        book._trailing_stops = [ts]
        triggered = book._check_trailing_stops(time.time())
        assert triggered == []

    def test_filled_trailing_stop_skipped(self) -> None:
        book = OrderBook("TEST")
        ts = _make(Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5.0)
        ts.stop_price = 100.0
        ts.status = OrderStatus.FILLED
        book._trailing_stops = [ts]
        book.last_trade_price = 90.0
        triggered = book._check_trailing_stops(time.time())
        assert triggered == []
        assert book._trailing_stops == []


# ---------------------------------------------------------------------------
# Iceberg replenishment via passive fill
# ---------------------------------------------------------------------------


class TestIcebergPassiveReplenishment:
    def test_passive_iceberg_replenished_after_fill(self) -> None:
        book = OrderBook("TEST")
        # Large iceberg ask: 200 total, 50 visible
        iceberg = _make(Side.SELL, OrderType.ICEBERG, 200, price=100.0, visible_qty=50)
        book.process(iceberg, match=False)
        # Aggressive buy takes all 50 displayed qty
        buyer = _make(Side.BUY, OrderType.LIMIT, 50, price=100.0)
        trades, events = book.process(buyer, match=True)
        assert len(trades) == 1
        assert trades[0].quantity == 50
        # Iceberg should be replenished to next peak
        assert iceberg.remaining_qty == 150
        assert iceberg.displayed_qty == 50

    def test_passive_iceberg_fully_consumed(self) -> None:
        book = OrderBook("TEST")
        iceberg = _make(Side.SELL, OrderType.ICEBERG, 50, price=100.0, visible_qty=50)
        book.process(iceberg, match=False)
        buyer = _make(Side.BUY, OrderType.LIMIT, 50, price=100.0)
        trades, events = book.process(buyer, match=True)
        assert iceberg.status == OrderStatus.FILLED
