from __future__ import annotations

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.price import clear_tick_registry, register_tick_decimals


def setup_function() -> None:
    clear_tick_registry()
    register_tick_decimals("AAPL", 2)


def test_order_book_snapshot_converts_ticks_to_display_prices() -> None:
    book = OrderBook("AAPL")

    bid = Order.create(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        gateway_id="GW1",
        tif=TIF.DAY,
        price=10050,
    )
    ask = Order.create(
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        quantity=10,
        gateway_id="GW2",
        tif=TIF.DAY,
        price=10050,
    )

    # First order rests, second order crosses and creates a trade.
    book.process(bid)
    trades, _ = book.process(ask)
    assert trades

    snap = book.snapshot()
    assert snap["last_price"] == 100.50
    assert snap["last_qty"] == 10
    assert snap["recent_trades"]

    tr = snap["recent_trades"][-1]
    assert tr["price"] == 100.50
    assert isinstance(tr["ts_ns"], int)
    assert tr["ts_ns"] > 1_000_000_000_000_000_000


class TestAr04SnapshotClock:
    """AR-0.4: book.{symbol} and depth.{symbol} previously carried no time
    field at all, so nothing could establish whether a snapshot reflects a
    given trade. Both now carry ts_ns, produced by the same monotonic
    edumatcher.models.clock.now_ns() that stamps trade.executed, so a
    snapshot taken after a trade always orders at or after it.
    """

    def _book_with_one_trade(self) -> tuple[OrderBook, int]:
        book = OrderBook("AAPL")
        bid = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW1",
            tif=TIF.DAY,
            price=10050,
        )
        ask = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW2",
            tif=TIF.DAY,
            price=10050,
        )
        book.process(bid)
        trades, _ = book.process(ask)
        assert trades, "expected a match"
        return book, trades[0].ts_ns

    def test_book_snapshot_carries_ts_ns_at_or_after_the_trade(self) -> None:
        book, trade_ts_ns = self._book_with_one_trade()
        snap = book.snapshot()
        assert isinstance(snap["ts_ns"], int)
        assert snap["ts_ns"] >= trade_ts_ns

    def test_depth_snapshot_carries_ts_ns_at_or_after_the_trade(self) -> None:
        book, trade_ts_ns = self._book_with_one_trade()
        depth = book.depth_snapshot(tolerance_ticks=100)
        assert isinstance(depth["ts_ns"], int)
        assert depth["ts_ns"] >= trade_ts_ns

    def test_a_second_snapshot_never_orders_before_the_first(self) -> None:
        """now_ns()'s monotonicity guarantee, exercised at the snapshot
        call site rather than just the clock module itself."""
        book, _ = self._book_with_one_trade()
        snap1 = book.snapshot()
        snap2 = book.snapshot()
        assert snap2["ts_ns"] >= snap1["ts_ns"]
