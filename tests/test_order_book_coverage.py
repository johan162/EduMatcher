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
  - quote_orders_for_gateway / orders_for_gateway / _orders_by_gateway index
"""

from __future__ import annotations

import time

import pytest

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import (
    Order,
    OrderOrigin,
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
    TIF,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make(
    side: Side,
    order_type: OrderType,
    qty: int,
    price: int | None = None,
    stop_price: int | None = None,
    visible_qty: int | None = None,
    trail_offset: int | None = None,
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
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
        book.process(o, match=False)
        book.cancel_order(o.id)
        assert o.status == OrderStatus.CANCELLED

    def test_cancel_unknown_order_returns_none(self) -> None:
        book = OrderBook("TEST")
        result = book.cancel_order("NONEXISTENT")
        assert result is None

    def test_cancel_reduces_qty_index(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
        book.process(o, match=False)
        book.cancel_order(o.id)
        assert book._bid_qty.get(100.0, 0) == 0

    def test_cancel_stop_limit_does_not_corrupt_qty_index(self) -> None:
        # A resting STOP_LIMIT sits in the stop heap and contributes nothing to
        # the bid/ask qty index, even though it carries a limit price.
        # Cancelling it must NOT deduct from the genuine resting qty that shares
        # that limit price.
        book = OrderBook("TEST")
        resting = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
        book.process(resting, match=False)
        stop_limit = _make(
            Side.BUY, OrderType.STOP_LIMIT, 50, price=100, stop_price=105
        )
        book.process(stop_limit, match=False)
        assert book._bid_qty.get(100.0) == 100

        book.cancel_order(stop_limit.id)
        assert stop_limit.status == OrderStatus.CANCELLED
        # The genuine resting LIMIT qty at price 100 must be untouched.
        assert book._bid_qty.get(100.0) == 100

    def test_cancel_sell_stop_limit_does_not_corrupt_qty_index(self) -> None:
        book = OrderBook("TEST")
        resting = _make(Side.SELL, OrderType.LIMIT, 80, price=200)
        book.process(resting, match=False)
        stop_limit = _make(
            Side.SELL, OrderType.STOP_LIMIT, 40, price=200, stop_price=195
        )
        book.process(stop_limit, match=False)
        assert book._ask_qty.get(200.0) == 80

        book.cancel_order(stop_limit.id)
        assert stop_limit.status == OrderStatus.CANCELLED
        assert book._ask_qty.get(200.0) == 80


# ---------------------------------------------------------------------------
# Resting orders / restore_stats
# ---------------------------------------------------------------------------


class TestRestingOrdersAndStats:
    def test_resting_orders_returns_active(self) -> None:
        book = OrderBook("TEST")
        o1 = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
        o2 = _make(Side.SELL, OrderType.LIMIT, 100, price=101)
        book.process(o1, match=False)
        book.process(o2, match=False)
        resting = book.resting_orders()
        assert o1 in resting
        assert o2 in resting

    def test_resting_orders_excludes_cancelled(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
        book.process(o, match=False)
        book.cancel_order(o.id)
        assert book.resting_orders() == []

    def test_restore_stats(self) -> None:
        book = OrderBook("TEST")
        book.restore_stats(14950, 15050)
        assert book.last_buy_price == 14950
        assert book.last_sell_price == 15050


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
        book.process(_make(Side.BUY, OrderType.LIMIT, 100, price=100), match=False)
        book.process(_make(Side.BUY, OrderType.LIMIT, 200, price=100), match=False)
        snap = book.snapshot()
        assert len(snap["bids"]) == 1
        assert snap["bids"][0]["qty"] == 300
        assert snap["bids"][0]["count"] == 2

    def test_snapshot_iceberg_shows_displayed_only(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.ICEBERG, 500, price=100, visible_qty=50)
        book.process(o, match=False)
        snap = book.snapshot()
        assert snap["bids"][0]["qty"] == 50

    def test_snapshot_excludes_cancelled(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
        book.process(o, match=False)
        book.cancel_order(o.id)
        snap = book.snapshot()
        assert snap["bids"] == []

    def test_snapshot_last_trade_info(self) -> None:
        book = OrderBook("TEST")
        book.process(_make(Side.BUY, OrderType.LIMIT, 100, price=10000), match=False)
        book.process(_make(Side.SELL, OrderType.LIMIT, 100, price=10000), match=True)
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
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
        book.process(o, match=False)
        book.cancel_order(o.id)
        result, reset, reason = book.amend_order(o.id)
        assert result is None
        # H7: cancelled orders are purged from the indexes, so amend reports
        # "not found" rather than a dead-order "cannot amend" message.
        assert "not found" in reason.lower()

    def test_amend_market_order_rejected(self) -> None:
        book = OrderBook("TEST")
        # Place a limit sell so the market buy won't immediately match
        book.process(_make(Side.SELL, OrderType.LIMIT, 100, price=200), match=False)
        o = _make(Side.BUY, OrderType.MARKET, 10)
        # Market orders aren't resting, so use a workaround: directly add to index
        o.status = OrderStatus.NEW
        book._order_index[o.id] = o
        result, reset, reason = book.amend_order(o.id)
        assert result is None
        assert "cannot amend" in reason.lower()

    def test_amend_zero_qty_rejected(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
        book.process(o, match=False)
        result, reset, reason = book.amend_order(o.id, new_qty=0)
        assert result is None
        assert "quantity" in reason.lower()

    def test_amend_qty_below_filled_rejected(self) -> None:
        book = OrderBook("TEST")
        # Set up a partial fill
        buy = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
        book.process(buy, match=False)
        # Manually mark as partial
        buy.status = OrderStatus.PARTIAL
        buy.remaining_qty = 50
        result, reset, reason = book.amend_order(buy.id, new_qty=40)
        assert result is None
        assert "filled" in reason.lower()

    def test_amend_price_down_preserves_priority(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
        book.process(o, match=False)
        result, reset, reason = book.amend_order(o.id, new_qty=80)
        assert result is not None
        assert reset is False
        assert o.remaining_qty == 80

    def test_amend_price_change_resets_priority(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
        book.process(o, match=False)
        result, reset, reason = book.amend_order(o.id, new_price=101)
        assert result is not None
        assert reset is True
        assert o.price == 101.0

    def test_amend_qty_increase_resets_priority(self) -> None:
        book = OrderBook("TEST")
        o = _make(Side.BUY, OrderType.LIMIT, 100, price=100)
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
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=105)
        book.process(stop, match=False)
        # Simulate a trade at 106.0
        book.last_trade_price = 106.0
        now = time.time_ns()
        triggered = book._check_stops(now)
        assert len(triggered) == 1
        assert triggered[0].order_type == OrderType.MARKET

    def test_sell_stop_triggered_by_price_fall(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.SELL, OrderType.STOP, 100, stop_price=95)
        book.process(stop, match=False)
        book.last_trade_price = 94.0
        triggered = book._check_stops(time.time_ns())
        assert len(triggered) == 1
        assert triggered[0].order_type == OrderType.MARKET

    def test_buy_stop_not_triggered_below_price(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=110)
        book.process(stop, match=False)
        book.last_trade_price = 105.0
        triggered = book._check_stops(time.time_ns())
        assert triggered == []

    def test_stop_limit_converts_to_limit(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP_LIMIT, 100, price=106, stop_price=105)
        book.process(stop, match=False)
        book.last_trade_price = 106.0
        triggered = book._check_stops(time.time_ns())
        assert len(triggered) == 1
        assert triggered[0].order_type == OrderType.LIMIT

    def test_no_stops_without_trade_price(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=105)
        book.process(stop, match=False)
        triggered = book._check_stops(time.time_ns())
        assert triggered == []

    def test_cancelled_stop_skipped(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=105)
        book.process(stop, match=False)
        book.cancel_order(stop.id)
        book.last_trade_price = 110.0
        triggered = book._check_stops(time.time_ns())
        assert triggered == []

    def test_multiple_sell_stops_fire_from_one_price(self) -> None:
        """A single price drop below multiple SELL stop prices triggers all of them."""
        book = OrderBook("TEST")
        s1 = _make(Side.SELL, OrderType.STOP, 50, stop_price=100)
        s2 = _make(Side.SELL, OrderType.STOP, 50, stop_price=102)
        s3 = _make(Side.SELL, OrderType.STOP_LIMIT, 50, price=90, stop_price=104)
        for s in (s1, s2, s3):
            book.process(s, match=False)
        book.last_trade_price = 95.0  # below all three stop prices
        triggered = book._check_stops(time.time_ns())
        assert len(triggered) == 3
        # STOP → MARKET, STOP_LIMIT → LIMIT
        types = {o.order_type for o in triggered}
        assert OrderType.MARKET in types
        assert OrderType.LIMIT in types

    def test_stop_cascade_end_to_end(self) -> None:
        """One trade triggers three SELL STOPs; each then executes against resting bids."""
        book = OrderBook("TEST")
        # Resting bids for the cascaded SELL MARKETs to consume
        for price in (95, 96, 97):
            book.process(_make(Side.BUY, OrderType.LIMIT, 50, price=price), match=False)
        # SELL STOPs that fire when price falls to/below their stop_price
        for stop_price in (100, 102, 104):
            book.process(
                _make(Side.SELL, OrderType.STOP, 50, stop_price=stop_price), match=False
            )
        # Thin ask to trigger the initial trade and set last_trade_price = 50
        book.process(_make(Side.SELL, OrderType.LIMIT, 10, price=50), match=False)

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
        ts = _make(Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5)
        ts.stop_price = 95.0  # initial stop: 100 - 5
        book.last_trade_price = 100.0
        book._trailing_stops = [ts]
        book._order_index[ts.id] = ts
        # Price rises to 103 → stop ratchets to 98 (103 - 5), not triggered yet
        book.last_trade_price = 103.0
        triggered = book._check_trailing_stops(time.time_ns())
        assert triggered == []
        assert ts.stop_price == pytest.approx(98.0)

    def test_sell_trailing_stop_triggered(self) -> None:
        book = OrderBook("TEST")
        ts = _make(Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5)
        ts.stop_price = 100.0
        book._trailing_stops = [ts]
        book._order_index[ts.id] = ts
        # Price falls to/below stop
        book.last_trade_price = 99.0
        triggered = book._check_trailing_stops(time.time_ns())
        assert len(triggered) == 1
        assert triggered[0].order_type == OrderType.MARKET

    def test_buy_trailing_stop_ratchets_down(self) -> None:
        book = OrderBook("TEST")
        ts = _make(Side.BUY, OrderType.TRAILING_STOP, 100, trail_offset=5)
        ts.stop_price = 105.0  # initial stop: 100 + 5
        book._trailing_stops = [ts]
        book._order_index[ts.id] = ts
        # Price falls to 97 → stop ratchets down to 102 (97+5), not triggered
        book.last_trade_price = 97.0
        triggered = book._check_trailing_stops(time.time_ns())
        assert triggered == []
        assert ts.stop_price == pytest.approx(102.0)

    def test_buy_trailing_stop_triggered(self) -> None:
        book = OrderBook("TEST")
        ts = _make(Side.BUY, OrderType.TRAILING_STOP, 100, trail_offset=5)
        ts.stop_price = 100.0
        book._trailing_stops = [ts]
        book._order_index[ts.id] = ts
        book.last_trade_price = 101.0  # >= stop
        triggered = book._check_trailing_stops(time.time_ns())
        assert len(triggered) == 1

    def test_trailing_stop_no_trade_price(self) -> None:
        book = OrderBook("TEST")
        ts = _make(Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5)
        ts.stop_price = 95.0
        book._trailing_stops = [ts]
        triggered = book._check_trailing_stops(time.time_ns())
        assert triggered == []

    def test_filled_trailing_stop_skipped(self) -> None:
        book = OrderBook("TEST")
        ts = _make(Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5)
        ts.stop_price = 100.0
        ts.status = OrderStatus.FILLED
        book._trailing_stops = [ts]
        book.last_trade_price = 90.0
        triggered = book._check_trailing_stops(time.time_ns())
        assert triggered == []
        assert book._trailing_stops == []


# ---------------------------------------------------------------------------
# Iceberg replenishment via passive fill
# ---------------------------------------------------------------------------


class TestIcebergPassiveReplenishment:
    def test_passive_iceberg_replenished_after_fill(self) -> None:
        book = OrderBook("TEST")
        # Large iceberg ask: 200 total, 50 visible
        iceberg = _make(Side.SELL, OrderType.ICEBERG, 200, price=100, visible_qty=50)
        book.process(iceberg, match=False)
        # Aggressive buy takes all 50 displayed qty
        buyer = _make(Side.BUY, OrderType.LIMIT, 50, price=100)
        trades, events = book.process(buyer, match=True)
        assert len(trades) == 1
        assert trades[0].quantity == 50
        # Iceberg should be replenished to next peak
        assert iceberg.remaining_qty == 150
        assert iceberg.displayed_qty == 50

    def test_passive_iceberg_fully_consumed(self) -> None:
        book = OrderBook("TEST")
        iceberg = _make(Side.SELL, OrderType.ICEBERG, 50, price=100, visible_qty=50)
        book.process(iceberg, match=False)
        buyer = _make(Side.BUY, OrderType.LIMIT, 50, price=100)
        trades, events = book.process(buyer, match=True)
        assert iceberg.status == OrderStatus.FILLED


# ---------------------------------------------------------------------------
# quote_orders_for_gateway / _orders_by_gateway secondary index
# ---------------------------------------------------------------------------


def _make_quote_leg(
    side: Side,
    qty: int,
    price: int,
    gateway: str = "GW01",
    quote_id: str = "Q1",
) -> Order:
    """Build a resting LIMIT order tagged origin=QUOTE, the way
    Engine._handle_quote_new tags each of a quote's two legs (it sets
    .origin/.quote_id on the Order *after* Order.create(), since those are
    not create() parameters)."""
    o = Order.create(
        symbol="TEST",
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        gateway_id=gateway,
        tif=TIF.DAY,
        price=price,
    )
    o.origin = OrderOrigin.QUOTE
    o.quote_id = quote_id
    return o


class TestQuoteOrdersByGatewayIndex:
    def test_unknown_gateway_returns_empty_list(self) -> None:
        book = OrderBook("TEST")
        assert book.quote_orders_for_gateway("NOSUCHGW") == []

    def test_resting_quote_leg_is_indexed(self) -> None:
        book = OrderBook("TEST")
        bid = _make_quote_leg(Side.BUY, 500, price=100)
        book.process(bid, match=False)
        found = book.quote_orders_for_gateway("GW01")
        assert [o.id for o in found] == [bid.id]

    def test_both_legs_of_one_quote_are_indexed(self) -> None:
        book = OrderBook("TEST")
        bid = _make_quote_leg(Side.BUY, 500, price=100)
        ask = _make_quote_leg(Side.SELL, 500, price=101)
        book.process(bid, match=False)
        book.process(ask, match=False)
        found_ids = {o.id for o in book.quote_orders_for_gateway("GW01")}
        assert found_ids == {bid.id, ask.id}

    def test_ordinary_order_is_never_indexed(self) -> None:
        # origin defaults to OrderOrigin.ORDER — must not appear in the
        # quote-only index even though it rests in the same book/gateway.
        book = OrderBook("TEST")
        ordinary = _make(Side.BUY, OrderType.LIMIT, 100, price=100, gateway="GW01")
        assert ordinary.origin == OrderOrigin.ORDER
        book.process(ordinary, match=False)
        assert book.quote_orders_for_gateway("GW01") == []

    def test_mixed_quote_and_ordinary_orders_only_quote_returned(self) -> None:
        book = OrderBook("TEST")
        quote_leg = _make_quote_leg(Side.BUY, 500, price=100)
        ordinary = _make(Side.SELL, OrderType.LIMIT, 100, price=105, gateway="GW01")
        book.process(quote_leg, match=False)
        book.process(ordinary, match=False)
        found_ids = {o.id for o in book.quote_orders_for_gateway("GW01")}
        assert found_ids == {quote_leg.id}

    def test_different_gateways_do_not_cross_contaminate(self) -> None:
        book = OrderBook("TEST")
        leg_gw1 = _make_quote_leg(Side.BUY, 500, price=100, gateway="GW01")
        leg_gw2 = _make_quote_leg(Side.SELL, 500, price=101, gateway="GW02")
        book.process(leg_gw1, match=False)
        book.process(leg_gw2, match=False)
        assert [o.id for o in book.quote_orders_for_gateway("GW01")] == [leg_gw1.id]
        assert [o.id for o in book.quote_orders_for_gateway("GW02")] == [leg_gw2.id]

    def test_cancel_removes_leg_from_index(self) -> None:
        book = OrderBook("TEST")
        bid = _make_quote_leg(Side.BUY, 500, price=100)
        book.process(bid, match=False)
        assert book.quote_orders_for_gateway("GW01") != []
        book.cancel_order(bid.id)
        assert book.quote_orders_for_gateway("GW01") == []

    def test_cancel_one_leg_leaves_sibling_indexed(self) -> None:
        # Mirrors _on_quote_leg_filled cancelling only the sibling: the
        # index must reflect exactly one remaining leg, not zero and not
        # a stale reference to the cancelled one.
        book = OrderBook("TEST")
        bid = _make_quote_leg(Side.BUY, 500, price=100)
        ask = _make_quote_leg(Side.SELL, 500, price=101)
        book.process(bid, match=False)
        book.process(ask, match=False)
        book.cancel_order(ask.id)
        found = book.quote_orders_for_gateway("GW01")
        assert [o.id for o in found] == [bid.id]

    def test_full_fill_removes_leg_from_index(self) -> None:
        # A full fill purges via _apply_fill -> _purge_from_indexes, a
        # different code path from cancel_order but the same funnel this
        # index hooks — must be removed here too.
        book = OrderBook("TEST")
        bid = _make_quote_leg(Side.BUY, 500, price=100)
        book.process(bid, match=False)
        taker = _make(Side.SELL, OrderType.LIMIT, 500, price=100, gateway="GW02")
        trades, _events = book.process(taker, match=True)
        assert len(trades) == 1
        assert bid.status == OrderStatus.FILLED
        assert book.quote_orders_for_gateway("GW01") == []

    def test_partial_fill_leaves_leg_indexed_with_reduced_qty(self) -> None:
        # This is the exact scenario _cancel_orphaned_quote_legs exists for:
        # a partial fill must NOT remove the hit leg from the index — its
        # remainder keeps resting and must still be found (and eventually
        # cancelled) by a later replace.
        book = OrderBook("TEST")
        bid = _make_quote_leg(Side.BUY, 500, price=100)
        book.process(bid, match=False)
        taker = _make(Side.SELL, OrderType.LIMIT, 100, price=100, gateway="GW02")
        trades, _events = book.process(taker, match=True)
        assert len(trades) == 1
        assert bid.status == OrderStatus.PARTIAL
        assert bid.remaining_qty == 400
        found = book.quote_orders_for_gateway("GW01")
        assert [o.id for o in found] == [bid.id]
        assert found[0].remaining_qty == 400

    def test_gateway_entry_pruned_once_last_leg_removed(self) -> None:
        # Internal invariant: an empty per-gateway set must not linger in
        # _orders_by_gateway (mirrors the analogous cleanup QuoteIndex
        # does for _keys_by_gateway) — confirmed both externally (empty
        # list back) and internally (key actually gone, not just empty).
        book = OrderBook("TEST")
        bid = _make_quote_leg(Side.BUY, 500, price=100)
        book.process(bid, match=False)
        assert "GW01" in book._orders_by_gateway
        book.cancel_order(bid.id)
        assert book.quote_orders_for_gateway("GW01") == []
        assert "GW01" not in book._orders_by_gateway

    def test_reinsert_iceberg_path_never_touches_quote_index(self) -> None:
        # Icebergs are never quote legs in practice (_handle_quote_new only
        # creates LIMIT legs), but this pins that _reinsert_iceberg's
        # replenishment path — which does not call _rest — cannot
        # accidentally leave a quote-origin iceberg untracked or
        # double-tracked if that ever changed. Belt-and-braces: an iceberg
        # tagged origin=QUOTE by hand should still be tracked once (from its
        # initial _rest call) and remain tracked through replenishment.
        book = OrderBook("TEST")
        iceberg = _make(Side.SELL, OrderType.ICEBERG, 200, price=100, visible_qty=50)
        iceberg.origin = OrderOrigin.QUOTE
        iceberg.quote_id = "Q1"
        book.process(iceberg, match=False)
        assert [o.id for o in book.quote_orders_for_gateway("GW01")] == [iceberg.id]
        buyer = _make(Side.BUY, OrderType.LIMIT, 50, price=100, gateway="GW02")
        trades, _events = book.process(buyer, match=True)
        assert len(trades) == 1
        assert iceberg.remaining_qty == 150
        # Still indexed exactly once after replenishment — no duplicate
        # entry, no drop.
        found = book.quote_orders_for_gateway("GW01")
        assert [o.id for o in found] == [iceberg.id]

    def test_stop_order_tagged_quote_enters_both_broad_and_quote_view(self) -> None:
        # _orders_by_gateway is populated by _add_stop just like _rest (see
        # its definition) -- a stop order joins the broad index regardless
        # of origin, unlike before this index covered all origins, when
        # _add_stop was a separate funnel that never populated it at all.
        # quote_orders_for_gateway is a plain origin filter over that same
        # broad index (see its docstring) -- it does not also require
        # order_type == LIMIT, so a QUOTE-tagged stop, a case that can't
        # happen via Engine (quote legs are always plain LIMIT) but is
        # exercised here as a boundary case, now shows up in both views.
        # See TestOrdersByGatewayIndexStops for full stop-order coverage of
        # the broad index with realistic (origin=ORDER) stops.
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=105, gateway="GW01")
        stop.origin = OrderOrigin.QUOTE
        stop.quote_id = "Q1"
        book.process(stop, match=False)
        assert [o.id for o in book.orders_for_gateway("GW01")] == [stop.id]
        assert [o.id for o in book.quote_orders_for_gateway("GW01")] == [stop.id]

    def test_smp_cancel_resting_quote_leg_removes_it_from_index(self) -> None:
        """Regression test for a real bug found in review: _smp_cancel_resting
        is a *third* removal funnel (besides cancel_order and _apply_fill's
        full-fill purge) that used to bypass _purge_from_indexes entirely --
        it popped _order_index directly and never touched
        _orders_by_gateway. A same-gateway aggressor crossing its own
        resting QUOTE-origin leg under SmpAction.CANCEL_RESTING left a stale
        order_id in the index; the very next quote_orders_for_gateway call
        (exactly what Engine._cancel_orphaned_quote_legs does on every quote
        reissue) raised KeyError trying to resolve it back through
        _order_index. _smp_cancel_resting now funnels through
        _purge_from_indexes, which fixes this."""
        book = OrderBook("TEST")
        resting_quote_leg = Order.create(
            symbol="TEST",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100,
            smp_action=SmpAction.CANCEL_RESTING,
        )
        resting_quote_leg.origin = OrderOrigin.QUOTE
        resting_quote_leg.quote_id = "Q1"
        book.process(resting_quote_leg, match=False)
        assert [o.id for o in book.quote_orders_for_gateway("GW01")] == [
            resting_quote_leg.id
        ]

        # Same-gateway aggressor crosses it -- SMP fires CANCEL_RESTING.
        aggressor = Order.create(
            symbol="TEST",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100,
            smp_action=SmpAction.CANCEL_RESTING,
        )
        trades, events = book.process(aggressor, match=True)
        assert trades == []  # no fill -- SMP prevented it
        assert resting_quote_leg.status == OrderStatus.CANCELLED

        # Must not raise KeyError, and must correctly report no resting
        # quote legs left for this gateway.
        assert book.quote_orders_for_gateway("GW01") == []
        # The cancelled leg itself is gone from the broad index too -- but
        # GW01 still has one entry: the aggressor, an origin=ORDER LIMIT
        # that (nothing left to match after its counterparty was SMP-
        # cancelled) went on to rest via _rest(), same as any other order
        # with no resting counterpart. That's a legitimate, different
        # resting order for the same gateway, not a leak of the cancelled
        # leg -- confirmed explicitly below.
        assert [o.id for o in book.orders_for_gateway("GW01")] == [aggressor.id]
        assert resting_quote_leg.id not in book._orders_by_gateway.get("GW01", set())
        # Also fixes the pre-existing _entry_index leak in the same path.
        assert resting_quote_leg.id not in book._entry_index
        assert resting_quote_leg.id not in book._order_index

    def test_smp_cancel_both_resting_quote_leg_removes_it_from_index(self) -> None:
        """Same bug, via the CANCEL_BOTH branch (a separate call site from
        CANCEL_RESTING in _sweep, and a third in _match_fok's pre-check)."""
        book = OrderBook("TEST")
        resting_quote_leg = Order.create(
            symbol="TEST",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100,
            smp_action=SmpAction.CANCEL_BOTH,
        )
        resting_quote_leg.origin = OrderOrigin.QUOTE
        resting_quote_leg.quote_id = "Q1"
        book.process(resting_quote_leg, match=False)

        aggressor = Order.create(
            symbol="TEST",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100,
            smp_action=SmpAction.CANCEL_BOTH,
        )
        trades, events = book.process(aggressor, match=True)
        assert trades == []
        assert resting_quote_leg.status == OrderStatus.CANCELLED
        assert aggressor.status == OrderStatus.CANCELLED

        assert book.quote_orders_for_gateway("GW01") == []
        assert "GW01" not in book._orders_by_gateway


# ---------------------------------------------------------------------------
# orders_for_gateway / _orders_by_gateway — stop & trailing-stop coverage
# ---------------------------------------------------------------------------
#
# TestQuoteOrdersByGatewayIndex above covers the index's original scope
# (plain vs. quote-origin LIMIT orders). This class covers the part that's
# new now that _orders_by_gateway tracks every resting order: STOP,
# STOP_LIMIT and TRAILING_STOP orders, which enter and leave the book
# through their own funnels (_add_stop / _add_trailing_stop, and the direct
# _order_index pops in _check_stops / _check_trailing_stops) rather than
# _rest() / _purge_from_indexes().


class TestOrdersByGatewayIndexStops:
    def test_resting_stop_is_indexed(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=105, gateway="GW01")
        book.process(stop, match=False)
        assert [o.id for o in book.orders_for_gateway("GW01")] == [stop.id]

    def test_resting_stop_limit_is_indexed(self) -> None:
        book = OrderBook("TEST")
        stop = _make(
            Side.BUY,
            OrderType.STOP_LIMIT,
            100,
            price=106,
            stop_price=105,
            gateway="GW01",
        )
        book.process(stop, match=False)
        assert [o.id for o in book.orders_for_gateway("GW01")] == [stop.id]

    def test_resting_trailing_stop_is_indexed(self) -> None:
        book = OrderBook("TEST")
        ts = _make(
            Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5, gateway="GW01"
        )
        ts.stop_price = 95
        book.process(ts, match=False)
        assert [o.id for o in book.orders_for_gateway("GW01")] == [ts.id]

    def test_cancelled_stop_removed_from_index(self) -> None:
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=105, gateway="GW01")
        book.process(stop, match=False)
        assert book.orders_for_gateway("GW01") != []
        book.cancel_order(stop.id)
        assert book.orders_for_gateway("GW01") == []
        assert "GW01" not in book._orders_by_gateway

    def test_cancelled_trailing_stop_removed_from_index(self) -> None:
        # cancel_order looks the order up via _order_index (populated by
        # _add_trailing_stop, unlike _entry_index which trailing stops
        # never join) and purges it through the normal
        # _purge_from_indexes funnel -- confirms that path reaches
        # _orders_by_gateway for a trailing stop too.
        book = OrderBook("TEST")
        ts = _make(
            Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5, gateway="GW01"
        )
        ts.stop_price = 95
        book.process(ts, match=False)
        assert book.orders_for_gateway("GW01") != []
        book.cancel_order(ts.id)
        assert book.orders_for_gateway("GW01") == []
        assert "GW01" not in book._orders_by_gateway

    def test_triggered_stop_to_market_that_fills_is_removed_from_index(self) -> None:
        # A STOP that triggers converts to MARKET; if it fully matches it
        # never rests again, so _check_stops' direct _order_index pop must
        # also discard it from _orders_by_gateway or it would leak forever
        # (the order never revisits _rest()/_purge_from_indexes).
        book = OrderBook("TEST")
        book.process(_make(Side.SELL, OrderType.LIMIT, 100, price=100, gateway="GW02"))
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=105, gateway="GW01")
        book.process(stop, match=False)
        assert [o.id for o in book.orders_for_gateway("GW01")] == [stop.id]

        book.last_trade_price = 106
        triggered = book._check_stops(time.time_ns())
        assert len(triggered) == 1
        # Feed the converted MARKET order back through matching, as the
        # engine does with _check_stops' return value.
        trades, _events = book.process(triggered[0], match=True)
        assert len(trades) == 1
        assert stop.status == OrderStatus.FILLED
        assert book.orders_for_gateway("GW01") == []
        assert "GW01" not in book._orders_by_gateway

    def test_triggered_stop_limit_that_rests_again_is_indexed_exactly_once(
        self,
    ) -> None:
        # A STOP_LIMIT that triggers converts to LIMIT; if there's nothing
        # to match it rests again via _rest(), which must re-add it to
        # _orders_by_gateway -- exactly once, not zero (leaked) and not
        # twice (stale entry from before the trigger plus a fresh one).
        book = OrderBook("TEST")
        stop = _make(
            Side.BUY,
            OrderType.STOP_LIMIT,
            100,
            price=106,
            stop_price=105,
            gateway="GW01",
        )
        book.process(stop, match=False)
        assert [o.id for o in book.orders_for_gateway("GW01")] == [stop.id]

        book.last_trade_price = 106
        triggered = book._check_stops(time.time_ns())
        assert len(triggered) == 1
        assert triggered[0].order_type == OrderType.LIMIT
        # Nothing resting on the other side -- it rests as an ordinary LIMIT.
        trades, _events = book.process(triggered[0], match=True)
        assert trades == []
        assert stop.status == OrderStatus.NEW
        found = book.orders_for_gateway("GW01")
        assert [o.id for o in found] == [stop.id]
        assert len(book._orders_by_gateway["GW01"]) == 1

    def test_triggered_trailing_stop_that_fills_is_removed_from_index(self) -> None:
        book = OrderBook("TEST")
        book.process(_make(Side.BUY, OrderType.LIMIT, 100, price=100, gateway="GW02"))
        ts = _make(
            Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5, gateway="GW01"
        )
        ts.stop_price = 103
        book.process(ts, match=False)
        assert [o.id for o in book.orders_for_gateway("GW01")] == [ts.id]

        book.last_trade_price = 100  # <= stop_price(103) -- triggers
        triggered = book._check_trailing_stops(time.time_ns())
        assert len(triggered) == 1
        trades, _events = book.process(triggered[0], match=True)
        assert len(trades) == 1
        assert ts.status == OrderStatus.FILLED
        assert book.orders_for_gateway("GW01") == []
        assert "GW01" not in book._orders_by_gateway

    def test_buy_trailing_stop_trigger_path_also_clears_index(self) -> None:
        # Same as above via the BUY-side branch of _check_trailing_stops,
        # a separate code path from the SELL-side branch exercised above.
        book = OrderBook("TEST")
        book.process(_make(Side.SELL, OrderType.LIMIT, 100, price=100, gateway="GW02"))
        ts = _make(
            Side.BUY, OrderType.TRAILING_STOP, 100, trail_offset=5, gateway="GW01"
        )
        ts.stop_price = 97
        book.process(ts, match=False)
        assert [o.id for o in book.orders_for_gateway("GW01")] == [ts.id]

        book.last_trade_price = 100  # >= stop_price(97) -- triggers
        triggered = book._check_trailing_stops(time.time_ns())
        assert len(triggered) == 1
        trades, _events = book.process(triggered[0], match=True)
        assert len(trades) == 1
        assert book.orders_for_gateway("GW01") == []
        assert "GW01" not in book._orders_by_gateway

    def test_stop_triggered_before_last_trade_price_set_stays_indexed(self) -> None:
        # _check_stops is a no-op before any trade has happened in this
        # book -- confirms that a not-yet-triggerable stop just sits in
        # the index rather than being dropped or mis-handled.
        book = OrderBook("TEST")
        stop = _make(Side.BUY, OrderType.STOP, 100, stop_price=105, gateway="GW01")
        book.process(stop, match=False)
        triggered = book._check_stops(time.time_ns())
        assert triggered == []
        assert [o.id for o in book.orders_for_gateway("GW01")] == [stop.id]

    def test_mixed_origins_and_types_all_indexed_for_one_gateway(self) -> None:
        # A gateway with a plain LIMIT, a QUOTE leg, a STOP and a
        # TRAILING_STOP all resting at once -- orders_for_gateway (used by
        # Engine._handle_gateway_disconnect's CANCEL_ALL sweep and the
        # kill-switch handlers) must return all four; quote_orders_for_gateway
        # (used by _cancel_orphaned_quote_legs) must return only the leg.
        book = OrderBook("TEST")
        plain = _make(Side.BUY, OrderType.LIMIT, 100, price=90, gateway="GW01")
        quote_leg = _make_quote_leg(Side.BUY, 50, price=91, gateway="GW01")
        stop = _make(Side.SELL, OrderType.STOP, 100, stop_price=110, gateway="GW01")
        ts = _make(
            Side.SELL, OrderType.TRAILING_STOP, 100, trail_offset=5, gateway="GW01"
        )
        ts.stop_price = 115
        for o in (plain, quote_leg, stop, ts):
            book.process(o, match=False)

        all_ids = {o.id for o in book.orders_for_gateway("GW01")}
        assert all_ids == {plain.id, quote_leg.id, stop.id, ts.id}
        assert [o.id for o in book.quote_orders_for_gateway("GW01")] == [quote_leg.id]

    def test_different_gateways_stops_do_not_cross_contaminate(self) -> None:
        book = OrderBook("TEST")
        stop_gw1 = _make(Side.BUY, OrderType.STOP, 100, stop_price=105, gateway="GW01")
        stop_gw2 = _make(Side.SELL, OrderType.STOP, 100, stop_price=95, gateway="GW02")
        book.process(stop_gw1, match=False)
        book.process(stop_gw2, match=False)
        assert [o.id for o in book.orders_for_gateway("GW01")] == [stop_gw1.id]
        assert [o.id for o in book.orders_for_gateway("GW02")] == [stop_gw2.id]
