"""
Tests for order amendment (AMEND) feature.

Covers:
- Price-only amendment (priority lost)
- Quantity decrease (priority preserved)
- Quantity increase (priority lost)
- Price + quantity change (priority lost)
- Rejection cases (filled, cancelled, wrong type, bad values)
- Partial fill then amend
- Iceberg amendment
- Priority ordering verification after amend
"""

from __future__ import annotations

import time

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import (
    Order,
    OrderType,
    Side,
)


def _limit(
    side: Side,
    price: float,
    qty: int = 100,
    gateway_id: str = "GW1",
) -> Order:
    return Order.create(
        symbol="AAPL",
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        gateway_id=gateway_id,
        price=price,
    )


def _iceberg(
    side: Side,
    price: float,
    qty: int = 300,
    visible_qty: int = 100,
) -> Order:
    return Order.create(
        symbol="AAPL",
        side=side,
        order_type=OrderType.ICEBERG,
        quantity=qty,
        gateway_id="GW1",
        price=price,
        visible_qty=visible_qty,
    )


# ===========================================================================
# Basic amendment operations
# ===========================================================================


class TestAmendPrice:
    """Amending price loses priority."""

    def test_price_change_returns_order(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0)
        book.process(buy)

        amended, priority_reset, err = book.amend_order(buy.id, new_price=101.0)

        assert amended is buy
        assert amended.price == 101.0
        assert priority_reset is True
        assert err == ""

    def test_price_change_updates_timestamp(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0)
        book.process(buy)
        original_ts = buy.timestamp

        time.sleep(0.001)
        book.amend_order(buy.id, new_price=101.0)

        assert buy.timestamp > original_ts

    def test_price_decrease_also_loses_priority(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0)
        book.process(buy)

        _, priority_reset, _ = book.amend_order(buy.id, new_price=99.0)
        assert priority_reset is True

    def test_sell_price_change(self):
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0)
        book.process(sell)

        amended, priority_reset, _ = book.amend_order(sell.id, new_price=99.0)

        assert amended.price == 99.0
        assert priority_reset is True


class TestAmendQuantityDecrease:
    """Quantity decrease preserves priority."""

    def test_qty_decrease_preserves_priority(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, qty=100)
        book.process(buy)
        original_ts = buy.timestamp

        amended, priority_reset, _ = book.amend_order(buy.id, new_qty=80)

        assert amended.remaining_qty == 80
        assert amended.quantity == 80
        assert priority_reset is False
        assert amended.timestamp == original_ts

    def test_qty_decrease_updates_remaining(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, qty=200)
        book.process(buy)

        book.amend_order(buy.id, new_qty=150)

        assert buy.quantity == 150
        assert buy.remaining_qty == 150

    def test_qty_decrease_after_partial_fill(self):
        """After a partial fill of 40, reduce qty from 100 to 80 → remaining = 40."""
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, qty=100)
        book.process(buy)

        # Partial fill
        sell = _limit(Side.SELL, 100.0, qty=40)
        book.process(sell)
        assert buy.remaining_qty == 60

        amended, priority_reset, _ = book.amend_order(buy.id, new_qty=80)

        assert priority_reset is False
        assert amended.quantity == 80
        assert amended.remaining_qty == 40  # 80 - 40 filled


class TestAmendQuantityIncrease:
    """Quantity increase loses priority."""

    def test_qty_increase_loses_priority(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, qty=100)
        book.process(buy)
        original_ts = buy.timestamp

        time.sleep(0.001)
        amended, priority_reset, _ = book.amend_order(buy.id, new_qty=200)

        assert priority_reset is True
        assert amended.quantity == 200
        assert amended.remaining_qty == 200
        assert amended.timestamp > original_ts


class TestAmendPriceAndQty:
    """Changing both price and quantity."""

    def test_both_change_loses_priority(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, qty=100)
        book.process(buy)

        amended, priority_reset, _ = book.amend_order(
            buy.id, new_price=101.0, new_qty=150
        )

        assert priority_reset is True
        assert amended.price == 101.0
        assert amended.quantity == 150
        assert amended.remaining_qty == 150


# ===========================================================================
# Rejection cases
# ===========================================================================


class TestAmendRejections:
    """Cases where amend should fail."""

    def test_order_not_found(self):
        book = OrderBook("AAPL")

        amended, _, reason = book.amend_order("nonexistent", new_price=100.0)

        assert amended is None
        assert "not found" in reason.lower()

    def test_filled_order(self):
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0)
        book.process(sell)
        buy = _limit(Side.BUY, 100.0)
        book.process(buy)  # fills the sell

        amended, _, reason = book.amend_order(sell.id, new_price=99.0)

        assert amended is None
        # H7: a fully filled order is purged from the book indexes, so amending
        # it reports "not found" rather than lingering as a dead FILLED record.
        assert "not found" in reason.lower()

    def test_cancelled_order(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0)
        book.process(buy)
        book.cancel_order(buy.id)

        amended, _, reason = book.amend_order(buy.id, new_price=101.0)

        assert amended is None
        # H7: a cancelled order is purged from the book indexes, so amending it
        # reports "not found" rather than lingering as a dead CANCELLED record.
        assert "not found" in reason.lower()

    def test_market_order_not_amendable(self):
        book = OrderBook("AAPL")
        mkt = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            gateway_id="GW1",
        )
        # Market orders don't rest, but even if somehow in the index:
        book._order_index[mkt.id] = mkt

        amended, _, reason = book.amend_order(mkt.id, new_price=100.0)

        assert amended is None
        assert "MARKET" in reason

    def test_stop_order_not_amendable(self):
        book = OrderBook("AAPL")
        stop = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.STOP,
            quantity=100,
            gateway_id="GW1",
            stop_price=105.0,
        )
        book.process(stop)

        amended, _, reason = book.amend_order(stop.id, new_price=106.0)

        assert amended is None
        assert "STOP" in reason

    def test_qty_below_filled(self):
        """New qty must exceed already-filled amount."""
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, qty=100)
        book.process(buy)
        # Partial fill of 60
        sell = _limit(Side.SELL, 100.0, qty=60)
        book.process(sell)

        amended, _, reason = book.amend_order(buy.id, new_qty=50)

        assert amended is None
        assert "already-filled" in reason.lower()

    def test_qty_zero(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0)
        book.process(buy)

        amended, _, reason = book.amend_order(buy.id, new_qty=0)

        assert amended is None
        assert "positive" in reason.lower()

    def test_negative_price(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0)
        book.process(buy)

        amended, _, reason = book.amend_order(buy.id, new_price=-1.0)

        assert amended is None
        assert "positive" in reason.lower()


# ===========================================================================
# Priority ordering verification
# ===========================================================================


class TestAmendPriority:
    """Verify that priority changes affect actual matching order."""

    def test_qty_decrease_keeps_position_ahead(self):
        """Order A placed first, then B. A decreases qty → A still fills first."""
        book = OrderBook("AAPL")
        a = _limit(Side.BUY, 100.0, qty=100, gateway_id="A")
        book.process(a)
        b = _limit(Side.BUY, 100.0, qty=100, gateway_id="B")
        book.process(b)

        # A decreases qty — keeps priority
        book.amend_order(a.id, new_qty=50)

        # Incoming sell should fill A first
        sell = _limit(Side.SELL, 100.0, qty=50, gateway_id="MM")
        trades, _ = book.process(sell)

        assert len(trades) == 1
        assert trades[0].buy_order_id == a.id

    def test_price_change_moves_to_back(self):
        """Order A placed first at 100. B placed at 100. A amends to 100 (same price but
        priority_reset=True because it's technically a price 'change' from 100→100 triggers
        only when new_price != old_price). Here we amend A to 101 then back to 100."""
        book = OrderBook("AAPL")
        a = _limit(Side.BUY, 100.0, qty=50, gateway_id="A")
        book.process(a)
        b = _limit(Side.BUY, 100.0, qty=50, gateway_id="B")
        book.process(b)

        # A changes price to 101 then back to 100 — loses priority both times
        book.amend_order(a.id, new_price=101.0)
        book.amend_order(a.id, new_price=100.0)

        # Now B should fill first at 100
        sell = _limit(Side.SELL, 100.0, qty=50, gateway_id="MM")
        trades, _ = book.process(sell)

        assert len(trades) == 1
        assert trades[0].buy_order_id == b.id

    def test_qty_increase_moves_to_back(self):
        """A increases qty → goes behind B."""
        book = OrderBook("AAPL")
        a = _limit(Side.BUY, 100.0, qty=50, gateway_id="A")
        book.process(a)
        b = _limit(Side.BUY, 100.0, qty=50, gateway_id="B")
        book.process(b)

        book.amend_order(a.id, new_qty=100)

        sell = _limit(Side.SELL, 100.0, qty=50, gateway_id="MM")
        trades, _ = book.process(sell)

        assert len(trades) == 1
        assert trades[0].buy_order_id == b.id


# ===========================================================================
# Iceberg amendment
# ===========================================================================


class TestAmendIceberg:
    """Amendment of iceberg orders."""

    def test_iceberg_price_change(self):
        book = OrderBook("AAPL")
        ice = _iceberg(Side.BUY, 100.0, qty=300, visible_qty=100)
        book.process(ice)

        amended, priority_reset, _ = book.amend_order(ice.id, new_price=101.0)

        assert amended.price == 101.0
        assert priority_reset is True
        assert amended.displayed_qty == 100  # still limited to visible_qty

    def test_iceberg_qty_decrease(self):
        book = OrderBook("AAPL")
        ice = _iceberg(Side.BUY, 100.0, qty=300, visible_qty=100)
        book.process(ice)

        amended, priority_reset, _ = book.amend_order(ice.id, new_qty=200)

        assert priority_reset is False
        assert amended.remaining_qty == 200
        assert amended.displayed_qty == 100  # visible peak unchanged

    def test_iceberg_qty_decrease_below_visible(self):
        """If new remaining < visible_qty, displayed_qty = remaining."""
        book = OrderBook("AAPL")
        ice = _iceberg(Side.BUY, 100.0, qty=300, visible_qty=100)
        book.process(ice)

        amended, _, _ = book.amend_order(ice.id, new_qty=50)

        assert amended.remaining_qty == 50
        assert amended.displayed_qty == 50  # capped at remaining

    def test_amended_iceberg_still_matchable(self):
        book = OrderBook("AAPL")
        ice = _iceberg(Side.BUY, 100.0, qty=300, visible_qty=100)
        book.process(ice)

        book.amend_order(ice.id, new_price=101.0)

        sell = _limit(Side.SELL, 101.0, qty=50)
        trades, _ = book.process(sell)

        assert len(trades) == 1
        assert trades[0].price == 101.0


# ===========================================================================
# Qty index correctness
# ===========================================================================


class TestAmendQtyIndex:
    """Verify the price-level qty index stays consistent after amend."""

    def test_qty_decrease_updates_index(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, qty=100)
        book.process(buy)

        assert book._bid_qty.get(100.0) == 100

        book.amend_order(buy.id, new_qty=60)

        assert book._bid_qty.get(100.0) == 60

    def test_price_change_moves_qty_between_levels(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, qty=100)
        book.process(buy)

        assert book._bid_qty.get(100.0) == 100

        book.amend_order(buy.id, new_price=101.0)

        assert book._bid_qty.get(100.0, 0) == 0
        assert book._bid_qty.get(101.0) == 100

    def test_sell_side_qty_index(self):
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0, qty=100)
        book.process(sell)

        assert book._ask_qty.get(100.0) == 100

        book.amend_order(sell.id, new_price=99.0)

        assert book._ask_qty.get(100.0, 0) == 0
        assert book._ask_qty.get(99.0) == 100
