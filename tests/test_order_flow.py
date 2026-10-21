from __future__ import annotations

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF

from tests.engine_invariants import assert_book_invariants


def make_order(
    *,
    symbol: str = "AAPL",
    side: Side,
    order_type: OrderType,
    qty: int,
    gateway_id: str,
    tif: TIF = TIF.DAY,
    price: int | None = None,
    stop_price: int | None = None,
    visible_qty: int | None = None,
) -> Order:
    return Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price_ticks=price,
        stop_price_ticks=stop_price,
        visible_qty=visible_qty,
    )


def test_limit_order_rests_when_not_crossing() -> None:
    book = OrderBook("AAPL")

    buy = make_order(
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=10,
        gateway_id="TRADER01",
        price=100,
    )
    trades, events = book.process(buy)

    assert trades == []
    assert buy.status == OrderStatus.NEW
    assert buy.remaining_qty == 10
    assert buy in book.resting_orders()
    assert events == []


def test_market_order_executes_and_discards_unfilled_remainder() -> None:
    book = OrderBook("AAPL")

    resting_ask = make_order(
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        qty=5,
        gateway_id="TRADER02",
        price=101,
    )
    book.process(resting_ask)

    market_buy = make_order(
        side=Side.BUY,
        order_type=OrderType.MARKET,
        qty=8,
        gateway_id="TRADER01",
    )
    trades, events = book.process(market_buy)

    assert len(trades) == 1
    assert trades[0].quantity == 5
    assert market_buy.status == OrderStatus.CANCELLED
    assert market_buy.remaining_qty == 3
    # Spec (review M1/C4): "discarding" the remainder is fine, doing it
    # SILENTLY is not — a DEDICATED cancellation event must be emitted so the
    # engine can notify the owner.  Because events currently hold mutable
    # Order references, checking "some event has status CANCELLED" would pass
    # by accident (the fill-time entry mutates underneath us — review C4), so
    # we require one more event occurrence than the single fill produced.
    occurrences = sum(1 for e in events if e.id == market_buy.id)
    assert occurrences >= 2, (
        f"M1: unfilled MARKET remainder was cancelled without emitting a "
        f"cancellation event (order appears {occurrences}x in events: "
        f"1 fill, no cancel)"
    )


def test_stop_order_triggers_into_market_after_trigger_trade() -> None:
    book = OrderBook("AAPL")

    ask = make_order(
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        qty=10,
        gateway_id="TRADER02",
        price=101,
    )
    book.process(ask)

    buy_stop = make_order(
        side=Side.BUY,
        order_type=OrderType.STOP,
        qty=3,
        gateway_id="TRADER01",
        stop_price=101,
    )
    stop_trades, _ = book.process(buy_stop)
    assert stop_trades == []

    trigger_buy = make_order(
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=1,
        gateway_id="TRADER03",
        price=101,
    )
    trades, _ = book.process(trigger_buy)

    # 1 trigger trade + 1 stop-triggered market trade.
    assert len(trades) == 2
    assert any(t.buy_gateway_id == "TRADER01" and t.quantity == 3 for t in trades)
    assert buy_stop.order_type == OrderType.MARKET
    assert buy_stop.status == OrderStatus.FILLED
    assert buy_stop.remaining_qty == 0


def test_stop_limit_triggers_and_rests_if_not_marketable() -> None:
    book = OrderBook("AAPL")

    ask = make_order(
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        qty=1,
        gateway_id="TRADER02",
        price=100,
    )
    book.process(ask)

    buy_stop_limit = make_order(
        side=Side.BUY,
        order_type=OrderType.STOP_LIMIT,
        qty=4,
        gateway_id="TRADER01",
        stop_price=100,
        price=99,
    )
    trades_before, _ = book.process(buy_stop_limit)
    assert trades_before == []

    trigger_buy = make_order(
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=1,
        gateway_id="TRADER03",
        price=100,
    )
    book.process(trigger_buy)

    assert buy_stop_limit.order_type == OrderType.LIMIT
    assert buy_stop_limit.status == OrderStatus.NEW
    assert buy_stop_limit.remaining_qty == 4
    assert any(o.id == buy_stop_limit.id for o in book.resting_orders())


def test_fok_rejects_when_liquidity_is_insufficient() -> None:
    book = OrderBook("AAPL")

    ask = make_order(
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        qty=5,
        gateway_id="TRADER02",
        price=100,
    )
    book.process(ask)

    fok_buy = make_order(
        side=Side.BUY,
        order_type=OrderType.FOK,
        qty=6,
        gateway_id="TRADER01",
        price=100,
    )
    trades, events = book.process(fok_buy)

    assert trades == []
    assert fok_buy.status == OrderStatus.REJECTED
    assert any(e.id == fok_buy.id and e.status == OrderStatus.REJECTED for e in events)


def test_fok_fills_completely_when_liquidity_is_sufficient() -> None:
    book = OrderBook("AAPL")

    ask = make_order(
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        qty=6,
        gateway_id="TRADER02",
        price=100,
    )
    book.process(ask)

    fok_buy = make_order(
        side=Side.BUY,
        order_type=OrderType.FOK,
        qty=6,
        gateway_id="TRADER01",
        price=100,
    )
    trades, _ = book.process(fok_buy)

    assert len(trades) == 1
    assert trades[0].quantity == 6
    assert fok_buy.status == OrderStatus.FILLED


def test_iceberg_exposes_only_visible_slice_in_book_snapshot() -> None:
    book = OrderBook("AAPL")

    iceberg_sell = make_order(
        side=Side.SELL,
        order_type=OrderType.ICEBERG,
        qty=10,
        gateway_id="TRADER02",
        price=100,
        visible_qty=3,
    )
    book.process(iceberg_sell)

    market_buy = make_order(
        side=Side.BUY,
        order_type=OrderType.MARKET,
        qty=4,
        gateway_id="TRADER01",
    )
    trades, _ = book.process(market_buy)

    # #17 semantics: a passive iceberg fills only its displayed slice per pass.
    # The 4-lot market order takes the 3-lot peak, the iceberg refreshes, and
    # 1 more lot fills against the new peak — two executions totalling 4.
    assert sum(t.quantity for t in trades) == 4
    assert [t.quantity for t in trades] == [3, 1]
    assert iceberg_sell.status == OrderStatus.PARTIAL
    assert iceberg_sell.remaining_qty == 6

    snapshot = book.snapshot()
    assert snapshot["asks"]
    # Only the current (partially consumed) displayed peak is visible — never
    # the hidden remaining quantity.  After selling 4 from a peak size of 3,
    # the refreshed peak has 2 lots left on show (hidden 6 stays hidden).
    assert snapshot["asks"][0]["qty"] == 2


def test_incoming_iceberg_trades_its_full_quantity_like_a_limit() -> None:
    """One execution per resting counterparty, not one per peak (participant
    guide, ICEBERG)."""
    book = OrderBook("AAPL")
    ask_1 = make_order(
        side=Side.SELL, order_type=OrderType.LIMIT, qty=30, gateway_id="R1", price=100
    )
    ask_2 = make_order(
        side=Side.SELL, order_type=OrderType.LIMIT, qty=25, gateway_id="R2", price=101
    )
    book.process(ask_1)
    book.process(ask_2)

    iceberg = make_order(
        side=Side.BUY,
        order_type=OrderType.ICEBERG,
        qty=100,
        gateway_id="I",
        price=101,
        visible_qty=10,
    )
    trades, _ = book.process(iceberg)

    assert [(t.sell_order_id, t.price, t.quantity) for t in trades] == [
        (ask_1.id, 100, 30),
        (ask_2.id, 101, 25),
    ]
    assert iceberg.remaining_qty == 45


def test_incoming_iceberg_rests_its_remainder_with_a_full_peak() -> None:
    book = OrderBook("AAPL")
    book.process(
        make_order(
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            qty=25,
            gateway_id="R",
            price=100,
        )
    )
    iceberg = make_order(
        side=Side.BUY,
        order_type=OrderType.ICEBERG,
        qty=100,
        gateway_id="I",
        price=100,
        visible_qty=10,
    )
    book.process(iceberg)

    assert iceberg.remaining_qty == 75
    assert iceberg.displayed_qty == 10
    assert book.snapshot()["bids"][0]["qty"] == 10
    assert_book_invariants(book, include_hygiene=True)
