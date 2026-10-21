"""Icebergs in an auction uncross (workplan F1, bug A).

An iceberg's hidden quantity takes part in the uncross, ranked behind the
visible quantity at its price: each pass fills at most the shown slice, and a
used-up slice is replenished at the back of the queue, exactly as in
continuous matching. The equilibrium is computed from the same quantity the
uncross executes, so the published indicative is what prints.

Before the fix the equilibrium saw only the shown slice while the uncross
filled the hidden quantity in one go and deducted it from the price-level
index, wiping out other orders' quantity at that price.
See docs-design/EduMatcher-Matching-Test-Quality-Workplan.md §2.
"""

from __future__ import annotations

from typing import Any

from edumatcher.engine.auction import (
    compute_equilibrium,
    executable_at,
    execute_uncross,
)
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderStatus, OrderType, Side
from edumatcher.models.price import to_ticks
from edumatcher.models.session import SessionState
from edumatcher.models.trade import Trade

from tests.engine_harness import SYMBOL, make_engine, msgs
from tests.engine_invariants import assert_book_invariants, assert_qty_conservation


def _rest(
    book: OrderBook,
    side: Side,
    qty: int,
    price: int,
    gw: str,
    visible: int | None = None,
) -> Order:
    """Rest one LIMIT (or ICEBERG when *visible* is given) without matching."""
    order = Order.create(
        symbol=book.symbol,
        side=side,
        order_type=OrderType.LIMIT if visible is None else OrderType.ICEBERG,
        quantity=qty,
        gateway_id=gw,
        price_ticks=price,
        visible_qty=visible,
    )
    book.process(order, match=False)
    return order


def _fills(
    trades: list[Trade], names: dict[str, str]
) -> list[tuple[str, str, int, int]]:
    """Trades as (buyer, seller, price, qty) using readable order names."""
    return [
        (names[t.buy_order_id], names[t.sell_order_id], t.price, t.quantity)
        for t in trades
    ]


def test_shared_level_keeps_the_other_orders_quantity() -> None:
    book = OrderBook("X")
    ice = _rest(book, Side.SELL, 100, 100, "A", visible=10)
    lim = _rest(book, Side.SELL, 50, 100, "B")
    buy = _rest(book, Side.BUY, 60, 100, "C")

    result = compute_equilibrium(book)
    assert (result.eq_price, result.eq_qty) == (100, 60)
    trades, _ = execute_uncross(book, 100)

    names = {ice.id: "ICE", lim.id: "LIM", buy.id: "BUY"}
    # The iceberg's shown slice is first in time; its hidden quantity queues
    # behind the displayed LIMIT.
    assert _fills(trades, names) == [("BUY", "ICE", 100, 10), ("BUY", "LIM", 100, 50)]
    assert ice.remaining_qty == 90 and ice.displayed_qty == 10
    assert lim.status == OrderStatus.FILLED
    assert book._ask_qty == {100: 10}
    assert_book_invariants(book, include_hygiene=True)
    assert_qty_conservation([ice, lim, buy], trades)


def test_hidden_quantity_queues_behind_visible_peak_by_peak() -> None:
    book = OrderBook("X")
    ice = _rest(book, Side.SELL, 30, 100, "A", visible=10)
    lim = _rest(book, Side.SELL, 20, 100, "B")
    buy = _rest(book, Side.BUY, 50, 100, "C")

    trades, _ = execute_uncross(book, compute_equilibrium(book).eq_price or 0)

    names = {ice.id: "ICE", lim.id: "LIM", buy.id: "BUY"}
    assert _fills(trades, names) == [
        ("BUY", "ICE", 100, 10),
        ("BUY", "LIM", 100, 20),
        ("BUY", "ICE", 100, 10),
        ("BUY", "ICE", 100, 10),
    ]
    assert_book_invariants(book, include_hygiene=True)


def test_equilibrium_counts_hidden_quantity() -> None:
    book = OrderBook("X")
    ice = _rest(book, Side.SELL, 100, 100, "A", visible=10)
    b1 = _rest(book, Side.BUY, 60, 101, "C")
    b2 = _rest(book, Side.BUY, 5, 100, "D")

    # With the hidden 90 counted, 100 executes 65 and 101 only 60.
    result = compute_equilibrium(book)
    assert (result.eq_price, result.eq_qty) == (100, 65)
    assert (result.surplus, result.imbalance_side) == (35, "SELL")
    assert executable_at(book, 100).eq_qty == 65
    assert executable_at(book, 101).eq_qty == 60

    trades, _ = execute_uncross(book, 100)
    assert sum(t.quantity for t in trades) == result.eq_qty
    assert {t.price for t in trades} == {100}
    assert ice.remaining_qty == 35
    assert_book_invariants(book, include_hygiene=True)
    assert_qty_conservation([ice, b1, b2], trades)


def test_icebergs_on_both_sides() -> None:
    book = OrderBook("X")
    bid = _rest(book, Side.BUY, 50, 101, "A", visible=5)
    ask = _rest(book, Side.SELL, 40, 100, "B", visible=10)
    lim = _rest(book, Side.SELL, 5, 101, "C")

    result = compute_equilibrium(book)
    assert result.eq_qty == 45
    trades, _ = execute_uncross(book, result.eq_price or 0)

    assert sum(t.quantity for t in trades) == 45
    assert ask.status == OrderStatus.FILLED and lim.status == OrderStatus.FILLED
    assert bid.remaining_qty == 5 and bid.displayed_qty == 5
    assert book._bid_qty == {101: 5} and book._ask_qty == {}
    assert_book_invariants(book, include_hygiene=True)
    assert_qty_conservation([bid, ask, lim], trades)


def test_published_indicative_is_what_the_uncross_prints(monkeypatch, tmp_path) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    engine._session_state = SessionState.OPENING_AUCTION
    book = engine._book(SYMBOL)
    _rest(book, Side.SELL, 100, to_ticks(100.0, SYMBOL), "GW01", visible=10)
    _rest(book, Side.BUY, 60, to_ticks(101.0, SYMBOL), "GW02")
    _rest(book, Side.BUY, 5, to_ticks(100.0, SYMBOL), "GW03")

    engine._last_auction_indicative = 0.0
    engine._flush_auction_indicative()
    indicative: dict[str, Any] = msgs(pub, f"auction.indicative.{SYMBOL}")[-1]

    engine._run_uncross(reason="SCHEDULED")
    printed = msgs(pub, "trade.executed")
    result = msgs(pub, f"auction.result.{SYMBOL}")[-1]

    assert (indicative["eq_price"], indicative["eq_qty"]) == (100.0, 65)
    assert (result["eq_price"], result["eq_qty"]) == (100.0, 65)
    assert sum(t["quantity"] for t in printed) == 65
    assert {t["price"] for t in printed} == {100.0}
    assert_book_invariants(book, include_hygiene=True)
