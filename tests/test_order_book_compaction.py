"""Cancelled orders deep in the book must not pile up in the heaps.

A cancel only marks the heap entry invalid; the entry leaves the heap when it
reaches the top. Orders cancelled away from the touch never do, so before
OrderBook._compact_heaps the heaps (each entry holding its Order alive, and
walked by every snapshot) grew with every cancel. An AI swarm cancelling
stale orders made that visible as steady engine memory growth.
"""

from __future__ import annotations

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import TIF, Order, OrderType, Side


def _order(side: Side, price: int, otype: OrderType = OrderType.LIMIT) -> Order:
    return Order.create(
        symbol="TEST",
        side=side,
        order_type=otype,
        quantity=10,
        gateway_id="GW01",
        tif=TIF.DAY,
        price_ticks=price if otype == OrderType.LIMIT else None,
        stop_price_ticks=price if otype == OrderType.STOP else None,
    )


def _heap_sizes(book: OrderBook) -> int:
    return sum(
        len(h)
        for h in (
            book._bids,
            book._asks,
            book._buy_stops,
            book._sell_stops,
        )  # pyright: ignore[reportPrivateUsage]
    )


def test_cancels_behind_the_touch_do_not_grow_the_heaps() -> None:
    book = OrderBook("TEST")
    # A live touch on both sides that never moves.
    book.process(_order(Side.BUY, 1000), match=False)
    book.process(_order(Side.SELL, 1100), match=False)
    for i in range(5000):
        bid = _order(Side.BUY, 900 - i % 50)
        ask = _order(Side.SELL, 1200 + i % 50)
        stop = _order(Side.BUY, 1500 + i % 50, OrderType.STOP)
        for o in (bid, ask, stop):
            book.process(o, match=False)
            book.cancel_order(o.id)
    assert _heap_sizes(book) <= 2 * 2 + 64 + 3
    snap = book.snapshot()
    assert [lvl["price"] for lvl in snap["bids"]] == [10.0]
    assert [lvl["price"] for lvl in snap["asks"]] == [11.0]


def test_matching_still_follows_priority_after_compaction() -> None:
    book = OrderBook("TEST")
    first = _order(Side.SELL, 1100)
    second = _order(Side.SELL, 1100)
    book.process(first, match=False)
    book.process(second, match=False)
    for i in range(500):  # force several compactions
        o = _order(Side.SELL, 1300 + i)
        book.process(o, match=False)
        book.cancel_order(o.id)
    buy = _order(Side.BUY, 1100)
    trades = book.process(buy)[0]
    assert len(trades) == 1 and trades[0].sell_order_id == first.id
