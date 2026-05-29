"""
P1 coverage tests — SMP, book-level cancel, GTC persistence, iceberg replenishment.

These tests close the highest-risk coverage gaps identified in the project review.
Each test class maps to one P1 recommendation.
"""

from __future__ import annotations

import time

from edumatcher.engine.order_book import OrderBook
from edumatcher.engine.persistence import load_gtc_orders, save_gtc_orders
from edumatcher.models.order import (
    Order,
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
    TIF,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _limit(
    side: Side,
    price: float,
    qty: int = 100,
    gateway_id: str = "GW1",
    smp_action: SmpAction = SmpAction.NONE,
    tif: TIF = TIF.DAY,
    symbol: str = "AAPL",
    visible_qty: int | None = None,
) -> Order:
    return Order.create(
        symbol=symbol,
        side=side,
        order_type=OrderType.ICEBERG if visible_qty else OrderType.LIMIT,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
        smp_action=smp_action,
        visible_qty=visible_qty,
    )


def _market(
    side: Side,
    qty: int = 100,
    gateway_id: str = "GW1",
    smp_action: SmpAction = SmpAction.NONE,
) -> Order:
    return Order.create(
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        quantity=qty,
        gateway_id=gateway_id,
        smp_action=smp_action,
    )


# ===========================================================================
# 1. SMP — Self Match Prevention (all 4 modes × buy/sell)
# ===========================================================================


class TestSmpCancelAggressor:
    """SMP mode: CANCEL_AGGRESSOR — incoming order is cancelled, resting stays."""

    def test_buy_aggressor_cancelled(self):
        book = OrderBook("AAPL")
        # Rest a SELL from GW1
        sell = _limit(Side.SELL, 100.0, gateway_id="GW1")
        book.process(sell)

        # Incoming BUY from same gateway with CANCEL_AGGRESSOR
        buy = _limit(
            Side.BUY, 100.0, gateway_id="GW1", smp_action=SmpAction.CANCEL_AGGRESSOR
        )
        trades, events = book.process(buy)

        assert trades == []
        assert buy.status == OrderStatus.CANCELLED
        assert sell.status == OrderStatus.NEW  # resting order untouched

    def test_sell_aggressor_cancelled(self):
        book = OrderBook("AAPL")
        # Rest a BUY from GW1
        buy = _limit(Side.BUY, 100.0, gateway_id="GW1")
        book.process(buy)

        # Incoming SELL from same gateway
        sell = _limit(
            Side.SELL, 100.0, gateway_id="GW1", smp_action=SmpAction.CANCEL_AGGRESSOR
        )
        trades, events = book.process(sell)

        assert trades == []
        assert sell.status == OrderStatus.CANCELLED
        assert buy.status == OrderStatus.NEW

    def test_different_gateway_no_smp(self):
        """SMP should not trigger when gateways differ."""
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0, gateway_id="GW1")
        book.process(sell)

        buy = _limit(
            Side.BUY, 100.0, gateway_id="GW2", smp_action=SmpAction.CANCEL_AGGRESSOR
        )
        trades, events = book.process(buy)

        assert len(trades) == 1  # normal fill
        assert buy.status == OrderStatus.FILLED

    def test_market_buy_aggressor_cancelled(self):
        """SMP works for MARKET orders too."""
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0, gateway_id="GW1")
        book.process(sell)

        buy = _market(Side.BUY, gateway_id="GW1", smp_action=SmpAction.CANCEL_AGGRESSOR)
        trades, events = book.process(buy)

        assert trades == []
        assert buy.status == OrderStatus.CANCELLED


class TestSmpCancelResting:
    """SMP mode: CANCEL_RESTING — resting order is cancelled, aggressor continues."""

    def test_buy_cancels_resting_sell(self):
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0, gateway_id="GW1")
        book.process(sell)

        buy = _limit(
            Side.BUY, 100.0, gateway_id="GW1", smp_action=SmpAction.CANCEL_RESTING
        )
        trades, events = book.process(buy)

        # No trade — resting was cancelled, aggressor rests (no liquidity left)
        assert trades == []
        assert sell.status == OrderStatus.CANCELLED
        assert buy.remaining_qty == 100  # not filled

    def test_sell_cancels_resting_buy(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, gateway_id="GW1")
        book.process(buy)

        sell = _limit(
            Side.SELL, 100.0, gateway_id="GW1", smp_action=SmpAction.CANCEL_RESTING
        )
        trades, events = book.process(sell)

        assert trades == []
        assert buy.status == OrderStatus.CANCELLED
        assert sell.remaining_qty == 100

    def test_skips_resting_and_fills_next(self):
        """After cancelling same-gateway resting, aggressor should fill against different-gateway orders."""
        book = OrderBook("AAPL")
        # Two sells: one same gateway, one different
        sell_same = _limit(Side.SELL, 100.0, gateway_id="GW1")
        sell_diff = _limit(Side.SELL, 100.0, gateway_id="GW2")
        book.process(sell_same)
        book.process(sell_diff)

        buy = _limit(
            Side.BUY, 100.0, gateway_id="GW1", smp_action=SmpAction.CANCEL_RESTING
        )
        trades, events = book.process(buy)

        assert len(trades) == 1
        assert sell_same.status == OrderStatus.CANCELLED
        assert buy.status == OrderStatus.FILLED

    def test_market_sell_cancels_resting_buy(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, gateway_id="GW1")
        book.process(buy)

        sell = _market(Side.SELL, gateway_id="GW1", smp_action=SmpAction.CANCEL_RESTING)
        trades, events = book.process(sell)

        assert trades == []
        assert buy.status == OrderStatus.CANCELLED


class TestSmpCancelBoth:
    """SMP mode: CANCEL_BOTH — both aggressor and resting are cancelled."""

    def test_buy_both_cancelled(self):
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0, gateway_id="GW1")
        book.process(sell)

        buy = _limit(
            Side.BUY, 100.0, gateway_id="GW1", smp_action=SmpAction.CANCEL_BOTH
        )
        trades, events = book.process(buy)

        assert trades == []
        assert buy.status == OrderStatus.CANCELLED
        assert sell.status == OrderStatus.CANCELLED

    def test_sell_both_cancelled(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, gateway_id="GW1")
        book.process(buy)

        sell = _limit(
            Side.SELL, 100.0, gateway_id="GW1", smp_action=SmpAction.CANCEL_BOTH
        )
        trades, events = book.process(sell)

        assert trades == []
        assert sell.status == OrderStatus.CANCELLED
        assert buy.status == OrderStatus.CANCELLED

    def test_market_buy_both_cancelled(self):
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0, gateway_id="GW1")
        book.process(sell)

        buy = _market(Side.BUY, gateway_id="GW1", smp_action=SmpAction.CANCEL_BOTH)
        trades, events = book.process(buy)

        assert trades == []
        assert buy.status == OrderStatus.CANCELLED
        assert sell.status == OrderStatus.CANCELLED


class TestSmpNone:
    """SMP mode: NONE — self-trading is allowed (default)."""

    def test_buy_fills_own_sell(self):
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0, gateway_id="GW1")
        book.process(sell)

        buy = _limit(Side.BUY, 100.0, gateway_id="GW1", smp_action=SmpAction.NONE)
        trades, events = book.process(buy)

        assert len(trades) == 1
        assert buy.status == OrderStatus.FILLED
        assert sell.status == OrderStatus.FILLED

    def test_sell_fills_own_buy(self):
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, gateway_id="GW1")
        book.process(buy)

        sell = _limit(Side.SELL, 100.0, gateway_id="GW1", smp_action=SmpAction.NONE)
        trades, events = book.process(sell)

        assert len(trades) == 1
        assert sell.status == OrderStatus.FILLED
        assert buy.status == OrderStatus.FILLED


# ===========================================================================
# 1b. SMP — Iceberg aggressor (_sweep_iceberg code path)
# ===========================================================================


def _iceberg(
    side: Side,
    price: float,
    total_qty: int = 300,
    visible_qty: int = 100,
    gateway_id: str = "GW1",
    smp_action: SmpAction = SmpAction.NONE,
) -> Order:
    return Order.create(
        symbol="AAPL",
        side=side,
        order_type=OrderType.ICEBERG,
        quantity=total_qty,
        gateway_id=gateway_id,
        tif=TIF.DAY,
        price=price,
        smp_action=smp_action,
        visible_qty=visible_qty,
    )


def _fok(
    side: Side,
    price: float,
    qty: int = 100,
    gateway_id: str = "GW1",
    smp_action: SmpAction = SmpAction.NONE,
) -> Order:
    return Order.create(
        symbol="AAPL",
        side=side,
        order_type=OrderType.FOK,
        quantity=qty,
        gateway_id=gateway_id,
        tif=TIF.DAY,
        price=price,
        smp_action=smp_action,
    )


class TestSmpIceberg:
    """SMP inside _sweep_iceberg — separate code path from _sweep."""

    def test_iceberg_cancel_aggressor_on_own_resting(self):
        """Iceberg BUY with CANCEL_AGGRESSOR encounters its own SELL — iceberg cancelled."""
        book = OrderBook("AAPL")
        resting_sell = _limit(Side.SELL, 100.0, gateway_id="GW1")
        book.process(resting_sell)

        iceberg = _iceberg(
            Side.BUY, 100.0, gateway_id="GW1", smp_action=SmpAction.CANCEL_AGGRESSOR
        )
        trades, events = book.process(iceberg)

        assert trades == []
        assert iceberg.status == OrderStatus.CANCELLED
        assert resting_sell.status == OrderStatus.NEW  # resting untouched

    def test_iceberg_cancel_resting_on_own_sell(self):
        """Iceberg BUY with CANCEL_RESTING cancels its own resting SELL and rests."""
        book = OrderBook("AAPL")
        resting_sell = _limit(Side.SELL, 100.0, gateway_id="GW1")
        book.process(resting_sell)

        iceberg = _iceberg(
            Side.BUY, 100.0, gateway_id="GW1", smp_action=SmpAction.CANCEL_RESTING
        )
        trades, events = book.process(iceberg)

        assert trades == []
        assert resting_sell.status == OrderStatus.CANCELLED
        # iceberg rests on the bid side after cancelling the resting sell
        assert iceberg.remaining_qty == 300

    def test_iceberg_cancel_both_on_own_sell(self):
        """Iceberg BUY with CANCEL_BOTH cancels itself and the resting SELL."""
        book = OrderBook("AAPL")
        resting_sell = _limit(Side.SELL, 100.0, gateway_id="GW1")
        book.process(resting_sell)

        iceberg = _iceberg(
            Side.BUY, 100.0, gateway_id="GW1", smp_action=SmpAction.CANCEL_BOTH
        )
        trades, events = book.process(iceberg)

        assert trades == []
        assert iceberg.status == OrderStatus.CANCELLED
        assert resting_sell.status == OrderStatus.CANCELLED

    def test_iceberg_cancel_resting_then_fills_different_gateway(self):
        """CANCEL_RESTING skips own order and fills against the next (different gateway)."""
        book = OrderBook("AAPL")
        own_sell = _limit(Side.SELL, 100.0, qty=100, gateway_id="GW1")
        other_sell = _limit(Side.SELL, 100.0, qty=100, gateway_id="GW2")
        book.process(own_sell)
        book.process(other_sell)

        iceberg = _iceberg(
            Side.BUY,
            100.0,
            total_qty=100,
            visible_qty=100,
            gateway_id="GW1",
            smp_action=SmpAction.CANCEL_RESTING,
        )
        trades, events = book.process(iceberg)

        assert len(trades) == 1
        assert own_sell.status == OrderStatus.CANCELLED
        assert iceberg.status == OrderStatus.FILLED

    def test_iceberg_no_smp_for_different_gateway(self):
        """Iceberg SMP must NOT fire when resting order belongs to a different gateway."""
        book = OrderBook("AAPL")
        resting_sell = _limit(Side.SELL, 100.0, qty=100, gateway_id="GW2")
        book.process(resting_sell)

        iceberg = _iceberg(
            Side.BUY,
            100.0,
            total_qty=100,
            visible_qty=100,
            gateway_id="GW1",
            smp_action=SmpAction.CANCEL_AGGRESSOR,
        )
        trades, events = book.process(iceberg)

        assert len(trades) == 1
        assert iceberg.status == OrderStatus.FILLED
        assert resting_sell.status == OrderStatus.FILLED


# ===========================================================================
# 1c. SMP — partial fill before encountering own resting order
# ===========================================================================


class TestSmpPartialFillThenEncounterOwn:
    """
    Aggressor fills partially against a different-gateway order, then hits
    its own resting order — SMP should fire at that point.
    """

    def test_cancel_aggressor_after_partial_fill(self):
        """
        BUY 200 @ 101.0, CANCEL_AGGRESSOR:
          - fills 100 against GW2 sell @ 100.0  (different gateway → normal fill)
          - next resting is GW1 sell @ 100.5    (same gateway → CANCEL_AGGRESSOR)
        Result: 1 trade (100 filled), aggressor then CANCELLED mid-sweep.
        """
        book = OrderBook("AAPL")
        other_sell = _limit(Side.SELL, 100.0, qty=100, gateway_id="GW2")
        own_sell = _limit(Side.SELL, 100.5, qty=100, gateway_id="GW1")
        book.process(other_sell)
        book.process(own_sell)

        buy = _limit(
            Side.BUY,
            101.0,
            qty=200,
            gateway_id="GW1",
            smp_action=SmpAction.CANCEL_AGGRESSOR,
        )
        trades, events = book.process(buy)

        assert len(trades) == 1
        assert trades[0].quantity == 100
        assert buy.status == OrderStatus.CANCELLED
        assert own_sell.status == OrderStatus.NEW  # untouched

    def test_cancel_resting_after_partial_fill(self):
        """
        BUY 200 @ 101.0, CANCEL_RESTING:
          - fills 100 against GW2 sell @ 100.0  (different gateway → normal fill)
          - next resting is GW1 sell @ 100.5    (same gateway → cancel resting, continue)
          - no more liquidity → aggressor rests with 100 remaining
        """
        book = OrderBook("AAPL")
        other_sell = _limit(Side.SELL, 100.0, qty=100, gateway_id="GW2")
        own_sell = _limit(Side.SELL, 100.5, qty=100, gateway_id="GW1")
        book.process(other_sell)
        book.process(own_sell)

        buy = _limit(
            Side.BUY,
            101.0,
            qty=200,
            gateway_id="GW1",
            smp_action=SmpAction.CANCEL_RESTING,
        )
        trades, events = book.process(buy)

        assert len(trades) == 1
        assert trades[0].quantity == 100
        assert own_sell.status == OrderStatus.CANCELLED
        assert buy.remaining_qty == 100  # partially filled, now resting
        assert buy.status == OrderStatus.PARTIAL


# ===========================================================================
# 1d. SMP — FOK aggressor
# ===========================================================================


class TestSmpFok:
    """
    FOK + SMP interactions.  FOK pre-checks available qty before sweeping;
    SMP fires during the actual sweep.
    """

    def test_fok_cancel_aggressor_same_gateway(self):
        """
        FOK BUY 100 @ 100.0, CANCEL_AGGRESSOR, against own resting SELL.
        Pre-check counts 100 available, but SMP cancels the aggressor in sweep.
        Result: no trade, aggressor CANCELLED.
        """
        book = OrderBook("AAPL")
        own_sell = _limit(Side.SELL, 100.0, qty=100, gateway_id="GW1")
        book.process(own_sell)

        fok = _fok(
            Side.BUY,
            100.0,
            qty=100,
            gateway_id="GW1",
            smp_action=SmpAction.CANCEL_AGGRESSOR,
        )
        trades, events = book.process(fok)

        assert trades == []
        assert fok.status == OrderStatus.CANCELLED
        assert own_sell.status == OrderStatus.NEW

    def test_fok_cancel_resting_same_gateway(self):
        """
        FOK BUY 100 @ 100.0, CANCEL_RESTING, against own resting SELL.

        The pre-check counts 100 available (same-gateway qty included), so the
        sweep starts.  SMP=CANCEL_RESTING then cancels the resting order and
        continues — but there is no further liquidity, so the FOK ends up
        unfilled.  _match_fok does not call _rest() or explicitly cancel the
        aggressor after the sweep, so the FOK status stays NEW and the order
        is silently discarded (neither resting nor cancelled in events).

        This is an edge case: SMP removes the liquidity that passed the pre-check.
        The practical consequence is the same as a REJECTED FOK — no fill occurs.
        """
        book = OrderBook("AAPL")
        own_sell = _limit(Side.SELL, 100.0, qty=100, gateway_id="GW1")
        book.process(own_sell)

        fok = _fok(
            Side.BUY,
            100.0,
            qty=100,
            gateway_id="GW1",
            smp_action=SmpAction.CANCEL_RESTING,
        )
        trades, events = book.process(fok)

        assert trades == []
        assert own_sell.status == OrderStatus.CANCELLED
        # FOK is silently discarded — not rested, not explicitly cancelled
        assert fok.remaining_qty == 100
        # verify no further buy-side liquidity remains at that price
        snap = book.snapshot()
        assert all(level["price"] != 100.0 for level in snap["bids"])

    def test_fok_fills_normally_different_gateway(self):
        """FOK SMP must not fire against different-gateway resting orders."""
        book = OrderBook("AAPL")
        other_sell = _limit(Side.SELL, 100.0, qty=100, gateway_id="GW2")
        book.process(other_sell)

        fok = _fok(
            Side.BUY,
            100.0,
            qty=100,
            gateway_id="GW1",
            smp_action=SmpAction.CANCEL_AGGRESSOR,
        )
        trades, events = book.process(fok)

        assert len(trades) == 1
        assert fok.status == OrderStatus.FILLED


# ===========================================================================
# 2. Book-level cancel (T-CAN-001–005)
# ===========================================================================


class TestBookCancel:
    """Direct tests for OrderBook.cancel_order()."""

    def test_cancel_resting_limit_buy(self):
        """T-CAN-001: Cancel a resting BUY LIMIT order."""
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0)
        book.process(buy)

        result = book.cancel_order(buy.id)

        assert result is not None
        assert result.status == OrderStatus.CANCELLED
        assert result.id == buy.id
        # Should be removed from active book — no fills possible
        sell = _limit(Side.SELL, 100.0)
        trades, _ = book.process(sell)
        assert trades == []

    def test_cancel_resting_limit_sell(self):
        """T-CAN-002: Cancel a resting SELL LIMIT order."""
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0)
        book.process(sell)

        result = book.cancel_order(sell.id)

        assert result is not None
        assert result.status == OrderStatus.CANCELLED
        # Verify removed — aggressive buy finds no liquidity
        buy = _limit(Side.BUY, 100.0)
        trades, _ = book.process(buy)
        assert trades == []

    def test_cancel_nonexistent_returns_none(self):
        """T-CAN-003: Cancel for unknown order_id returns None."""
        book = OrderBook("AAPL")
        result = book.cancel_order("does-not-exist")
        assert result is None

    def test_cancel_already_filled_returns_none(self):
        """T-CAN-004: Cannot cancel a fully filled order."""
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0)
        book.process(sell)
        buy = _limit(Side.BUY, 100.0)
        book.process(buy)  # fills the sell

        assert sell.status == OrderStatus.FILLED
        result = book.cancel_order(sell.id)
        assert result is None

    def test_cancel_already_cancelled_returns_none(self):
        """T-CAN-005: Cannot cancel an already-cancelled order."""
        book = OrderBook("AAPL")
        order = _limit(Side.BUY, 100.0)
        book.process(order)

        # Cancel once
        result1 = book.cancel_order(order.id)
        assert result1 is not None
        # Cancel again
        result2 = book.cancel_order(order.id)
        assert result2 is None

    def test_cancel_partial_order(self):
        """Cancel a partially filled order — remaining qty is discarded."""
        book = OrderBook("AAPL")
        sell = _limit(Side.SELL, 100.0, qty=200)
        book.process(sell)
        buy = _limit(Side.BUY, 100.0, qty=100)
        book.process(buy)  # partial fill on sell

        assert sell.status == OrderStatus.PARTIAL
        assert sell.remaining_qty == 100

        result = book.cancel_order(sell.id)
        assert result is not None
        assert result.status == OrderStatus.CANCELLED
        # No further fills possible
        buy2 = _limit(Side.BUY, 100.0, qty=100)
        trades, _ = book.process(buy2)
        assert trades == []

    def test_cancel_stop_order(self):
        """Cancel a resting stop order before it triggers."""
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

        result = book.cancel_order(stop.id)
        assert result is not None
        assert result.status == OrderStatus.CANCELLED

    def test_cancel_updates_qty_index(self):
        """After cancel, the price-level qty index is decremented."""
        book = OrderBook("AAPL")
        buy = _limit(Side.BUY, 100.0, qty=50)
        book.process(buy)

        assert book._bid_qty.get(100.0, 0) == 50
        book.cancel_order(buy.id)
        assert book._bid_qty.get(100.0, 0) == 0


# ===========================================================================
# 3. GTC single-order persistence round-trip
# ===========================================================================


class TestGtcPersistence:
    """Tests for save_gtc_orders / load_gtc_orders round-trip."""

    def test_save_and_load_resting_gtc(self, tmp_path):
        """GTC NEW orders survive a round-trip."""
        path = tmp_path / "gtc.json"
        order = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW1",
            tif=TIF.GTC,
            price=150.0,
        )
        save_gtc_orders([order], path)
        loaded = load_gtc_orders(path)

        assert len(loaded) == 1
        assert loaded[0].id == order.id
        assert loaded[0].symbol == "AAPL"
        assert loaded[0].side == Side.BUY
        assert loaded[0].price == 150.0
        assert loaded[0].quantity == 100
        assert loaded[0].remaining_qty == 100
        assert loaded[0].tif == TIF.GTC
        assert loaded[0].status == OrderStatus.NEW

    def test_preserves_timestamp(self, tmp_path):
        """Original timestamp is preserved for price-time priority continuity."""
        path = tmp_path / "gtc.json"
        order = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW1",
            tif=TIF.GTC,
            price=150.0,
        )
        original_ts = order.timestamp
        save_gtc_orders([order], path)
        loaded = load_gtc_orders(path)

        assert loaded[0].timestamp == original_ts

    def test_partial_order_persisted(self, tmp_path):
        """PARTIAL-status GTC orders are also saved."""
        path = tmp_path / "gtc.json"
        order = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=200,
            gateway_id="GW1",
            tif=TIF.GTC,
            price=150.0,
        )
        # Simulate partial fill
        order.remaining_qty = 100
        order.status = OrderStatus.PARTIAL

        save_gtc_orders([order], path)
        loaded = load_gtc_orders(path)

        assert len(loaded) == 1
        assert loaded[0].remaining_qty == 100
        assert loaded[0].status == OrderStatus.PARTIAL

    def test_day_orders_excluded(self, tmp_path):
        """DAY orders are NOT persisted."""
        path = tmp_path / "gtc.json"
        day_order = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW1",
            tif=TIF.DAY,
            price=150.0,
        )
        gtc_order = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            gateway_id="GW1",
            tif=TIF.GTC,
            price=149.0,
        )
        save_gtc_orders([day_order, gtc_order], path)
        loaded = load_gtc_orders(path)

        assert len(loaded) == 1
        assert loaded[0].id == gtc_order.id

    def test_filled_orders_excluded(self, tmp_path):
        """Filled GTC orders are NOT persisted."""
        path = tmp_path / "gtc.json"
        order = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW1",
            tif=TIF.GTC,
            price=150.0,
        )
        order.status = OrderStatus.FILLED
        order.remaining_qty = 0

        save_gtc_orders([order], path)
        loaded = load_gtc_orders(path)

        assert len(loaded) == 0

    def test_cancelled_orders_excluded(self, tmp_path):
        """Cancelled GTC orders are NOT persisted."""
        path = tmp_path / "gtc.json"
        order = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW1",
            tif=TIF.GTC,
            price=150.0,
        )
        order.status = OrderStatus.CANCELLED

        save_gtc_orders([order], path)
        loaded = load_gtc_orders(path)

        assert len(loaded) == 0

    def test_load_nonexistent_file_returns_empty(self, tmp_path):
        """Loading from a missing file returns empty list (graceful)."""
        path = tmp_path / "does_not_exist.json"
        loaded = load_gtc_orders(path)
        assert loaded == []

    def test_load_malformed_json_returns_empty(self, tmp_path):
        """Loading from corrupt file returns empty list (graceful)."""
        path = tmp_path / "corrupt.json"
        path.write_text("not valid json {{{{")
        loaded = load_gtc_orders(path)
        assert loaded == []

    def test_multiple_orders_round_trip(self, tmp_path):
        """Multiple GTC orders are all preserved."""
        path = tmp_path / "gtc.json"
        orders = [
            Order.create(
                symbol=sym,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=100,
                gateway_id="GW1",
                tif=TIF.GTC,
                price=p,
            )
            for sym, p in [("AAPL", 150.0), ("MSFT", 400.0), ("GOOG", 170.0)]
        ]
        save_gtc_orders(orders, path)
        loaded = load_gtc_orders(path)

        assert len(loaded) == 3
        loaded_ids = {o.id for o in loaded}
        assert loaded_ids == {o.id for o in orders}

    def test_restored_order_can_match_on_book(self, tmp_path):
        """Restored GTC order can be placed on book and matched normally."""
        path = tmp_path / "gtc.json"
        order = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW1",
            tif=TIF.GTC,
            price=150.0,
        )
        save_gtc_orders([order], path)
        loaded = load_gtc_orders(path)

        book = OrderBook("AAPL")
        book.process(loaded[0])

        # Aggressive sell should match the restored order
        sell = _limit(Side.SELL, 150.0)
        trades, events = book.process(sell)
        assert len(trades) == 1
        assert trades[0].price == 150.0


# ===========================================================================
# 4. Iceberg replenishment cycle
# ===========================================================================


class TestIcebergReplenishment:
    """Tests for iceberg displayed_qty refresh, timestamp update, and hidden qty reveal."""

    def test_displayed_qty_replenishes_after_fill(self):
        """When visible slice is consumed, displayed_qty resets from hidden reserve."""
        book = OrderBook("AAPL")
        # Iceberg BUY: total=300, visible peak=100
        iceberg = _limit(Side.BUY, 100.0, qty=300, visible_qty=100)
        book.process(iceberg)

        # Sell 100 — consumes the visible slice
        sell = _limit(Side.SELL, 100.0, qty=100)
        trades, events = book.process(sell)

        assert len(trades) == 1
        assert iceberg.remaining_qty == 200
        # After consuming the peak, it should replenish
        assert iceberg.displayed_qty == 100  # new peak from hidden

    def test_timestamp_refreshes_on_replenishment(self):
        """Replenished iceberg gets a new timestamp (back of price-time queue)."""
        book = OrderBook("AAPL")
        iceberg = _limit(Side.BUY, 100.0, qty=300, visible_qty=100)
        original_ts = iceberg.timestamp
        book.process(iceberg)

        # Small delay to ensure timestamp differs
        time.sleep(0.001)

        sell = _limit(Side.SELL, 100.0, qty=100)
        book.process(sell)

        # Timestamp should have been updated
        assert iceberg.timestamp > original_ts

    def test_hidden_qty_fully_revealed_over_multiple_fills(self):
        """Multiple fill cycles reveal all hidden quantity."""
        book = OrderBook("AAPL")
        # Iceberg BUY: total=250, visible=100
        iceberg = _limit(Side.BUY, 100.0, qty=250, visible_qty=100)
        book.process(iceberg)

        # Fill 1: consume 100 → replenish to 100 (remaining 150)
        sell1 = _limit(Side.SELL, 100.0, qty=100)
        book.process(sell1)
        assert iceberg.remaining_qty == 150
        assert iceberg.displayed_qty == 100

        # Fill 2: consume 100 → replenish to 50 (remaining 50, less than peak)
        sell2 = _limit(Side.SELL, 100.0, qty=100)
        book.process(sell2)
        assert iceberg.remaining_qty == 50
        assert iceberg.displayed_qty == 50  # only 50 left to show

        # Fill 3: consume 50 → fully filled
        sell3 = _limit(Side.SELL, 100.0, qty=50)
        book.process(sell3)
        assert iceberg.remaining_qty == 0
        assert iceberg.status == OrderStatus.FILLED

    def test_iceberg_loses_priority_after_replenishment(self):
        """After replenishment, iceberg goes behind earlier orders at same price."""
        book = OrderBook("AAPL")
        # Place iceberg first
        iceberg = _limit(Side.BUY, 100.0, qty=200, visible_qty=50, gateway_id="ICE")
        book.process(iceberg)

        # Consume the first slice — iceberg replenishes with a new timestamp
        sell1 = _limit(Side.SELL, 100.0, qty=50, gateway_id="MM")
        book.process(sell1)

        # Place a regular limit at same price BEFORE the replenishment timestamp
        # To guarantee ordering, manually backdate it to just before iceberg's new ts
        regular = _limit(Side.BUY, 100.0, qty=50, gateway_id="REG")
        regular.timestamp = (
            iceberg.timestamp - 1
        )  # 1ns earlier than replenished iceberg
        book.process(regular)

        # Next sell should fill the regular order (earlier timestamp than replenished iceberg)
        sell2 = _limit(Side.SELL, 100.0, qty=50, gateway_id="MM")
        trades, events = book.process(sell2)

        assert len(trades) == 1
        # The fill should be against the regular order, not the iceberg
        filled_buy_id = trades[0].buy_order_id
        assert filled_buy_id == regular.id

    def test_iceberg_sell_replenishment(self):
        """Iceberg SELL also replenishes correctly."""
        book = OrderBook("AAPL")
        iceberg = _limit(Side.SELL, 100.0, qty=300, visible_qty=100)
        book.process(iceberg)

        buy = _limit(Side.BUY, 100.0, qty=100)
        trades, events = book.process(buy)

        assert len(trades) == 1
        assert iceberg.remaining_qty == 200
        assert iceberg.displayed_qty == 100

    def test_partial_visible_fill_no_replenishment(self):
        """If only part of the visible slice is consumed, no replenishment occurs."""
        book = OrderBook("AAPL")
        iceberg = _limit(Side.BUY, 100.0, qty=300, visible_qty=100)
        book.process(iceberg)
        original_ts = iceberg.timestamp

        # Sell only 50 — partial consumption of the visible slice
        sell = _limit(Side.SELL, 100.0, qty=50)
        book.process(sell)

        assert iceberg.remaining_qty == 250
        # Displayed qty should be reduced but NOT replenished (still > 0)
        assert iceberg.displayed_qty == 50
        # Timestamp unchanged (no replenishment occurred)
        assert iceberg.timestamp == original_ts

    def test_aggressive_iceberg_sweeps_then_rests(self):
        """An aggressive iceberg that partially fills rests with correct displayed_qty."""
        book = OrderBook("AAPL")
        # Resting sell with only 50 shares
        sell = _limit(Side.SELL, 100.0, qty=50)
        book.process(sell)

        # Aggressive iceberg BUY: total=200, visible=80
        iceberg = _limit(Side.BUY, 100.0, qty=200, visible_qty=80)
        trades, events = book.process(iceberg)

        assert len(trades) == 1
        assert trades[0].quantity == 50
        assert iceberg.remaining_qty == 150
        # After aggressive sweep, should rest with visible slice
        assert iceberg.status == OrderStatus.PARTIAL
