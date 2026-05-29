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
    assert isinstance(tr["timestamp"], float)
    assert tr["timestamp"] > 1_000_000_000.0
