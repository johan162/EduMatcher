from __future__ import annotations

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF


def make_order(
    *,
    symbol: str = "AAPL",
    side: Side,
    order_type: OrderType,
    qty: int,
    gateway_id: str,
    tif: TIF = TIF.DAY,
    price: float | None = None,
    stop_price: float | None = None,
    visible_qty: int | None = None,
) -> Order:
    return Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
        stop_price=stop_price,
        visible_qty=visible_qty,
    )


def test_limit_order_rests_when_not_crossing() -> None:
    book = OrderBook("AAPL")

    buy = make_order(
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=10,
        gateway_id="TRADER01",
        price=100.0,
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
        price=101.0,
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
        price=101.0,
    )
    book.process(ask)

    buy_stop = make_order(
        side=Side.BUY,
        order_type=OrderType.STOP,
        qty=3,
        gateway_id="TRADER01",
        stop_price=101.0,
    )
    stop_trades, _ = book.process(buy_stop)
    assert stop_trades == []

    trigger_buy = make_order(
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=1,
        gateway_id="TRADER03",
        price=101.0,
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
        price=100.0,
    )
    book.process(ask)

    buy_stop_limit = make_order(
        side=Side.BUY,
        order_type=OrderType.STOP_LIMIT,
        qty=4,
        gateway_id="TRADER01",
        stop_price=100.0,
        price=99.0,
    )
    trades_before, _ = book.process(buy_stop_limit)
    assert trades_before == []

    trigger_buy = make_order(
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=1,
        gateway_id="TRADER03",
        price=100.0,
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
        price=100.0,
    )
    book.process(ask)

    fok_buy = make_order(
        side=Side.BUY,
        order_type=OrderType.FOK,
        qty=6,
        gateway_id="TRADER01",
        price=100.0,
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
        price=100.0,
    )
    book.process(ask)

    fok_buy = make_order(
        side=Side.BUY,
        order_type=OrderType.FOK,
        qty=6,
        gateway_id="TRADER01",
        price=100.0,
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
        price=100.0,
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

    assert len(trades) == 1
    assert trades[0].quantity == 4
    assert iceberg_sell.status == OrderStatus.PARTIAL
    assert iceberg_sell.remaining_qty == 6

    snapshot = book.snapshot()
    assert snapshot["asks"]
    # Only displayed_qty should be visible, never hidden remaining quantity.
    assert snapshot["asks"][0]["qty"] == 3
