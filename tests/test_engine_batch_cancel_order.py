"""Batch cancels come out in the order the orders arrived.

Regression tests for X11 (docs-design/EduMatcher-Sim-Forensics-Workplan.md
§9): ``OrderBook._orders_by_gateway`` and ``QuoteIndex``'s per-gateway and
per-symbol keys were sets of strings, so quote replacement, disconnect and
kill-switch cancels were published in the per-process hash order and two
runs of the same input differed. With 40 ids a set's order matches arrival
order with negligible probability, so each test fails on the old code.
"""

from __future__ import annotations

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import TIF, Order, OrderType, Side
from edumatcher.models.quote import QuoteEntry, QuoteIndex
from tests.engine_harness import connect, make_engine, msgs, order_payload

N = 40


def test_x11_orders_for_gateway_follows_arrival_order() -> None:
    book = OrderBook("TEST")
    ids = []
    for i in range(N):
        stop = i % 2 == 1
        o = Order.create(
            symbol="TEST",
            side=Side.SELL,
            order_type=OrderType.STOP if stop else OrderType.LIMIT,
            quantity=1,
            gateway_id="GW01",
            tif=TIF.DAY,
            price_ticks=None if stop else 20000 + i,
            stop_price_ticks=5000 + i if stop else None,
        )
        book.process(o)
        ids.append(o.id)
    assert [o.id for o in book.orders_for_gateway("GW01")] == ids


def entry(gw: str, sym: str) -> QuoteEntry:
    return QuoteEntry(
        quote_id=f"{gw}-{sym}",
        gateway_id=gw,
        symbol=sym,
        bid_order_id=f"B-{gw}-{sym}",
        ask_order_id=f"S-{gw}-{sym}",
    )


def test_x11_quote_index_batch_cancels_follow_put_order() -> None:
    by_gateway, by_symbol = QuoteIndex(), QuoteIndex()
    syms = [f"S{i:02d}" for i in range(N)]
    gws = [f"MM{i:02d}" for i in range(N)]
    for sym in syms:
        by_gateway.put(entry("MM01", sym))
    for gw in gws:
        by_symbol.put(entry(gw, "AAPL"))
    assert [e.symbol for e in by_gateway.entries_for_gateway("MM01")] == syms
    assert [e.symbol for e in by_gateway.cancel_all_for_gateway("MM01")] == syms
    assert [e.gateway_id for e in by_symbol.cancel_all_for_symbol("AAPL")] == gws


def test_x11_kill_switch_cancels_in_arrival_order(monkeypatch, tmp_path) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    ids = []
    for i in range(N):
        payload = order_payload(
            Side.BUY, OrderType.LIMIT, 1, "GW01", price=50.0 + i / 100
        )
        engine._handle_new_order(payload)
        ids.append(payload["id"])
    engine._handle_kill_switch({"gateway_id": "GW01", "command_id": "c1"})
    assert [m["order_id"] for m in msgs(pub, "order.cancelled.GW01")] == ids
