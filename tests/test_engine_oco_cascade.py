"""An OCO leg that ends inside a stop cascade ends its sibling at once.

Regression tests for finding X15 of the simulation forensics
(docs-design/EduMatcher-Sim-Forensics-Workplan.md §9): the engine pulled an
OCO sibling only from the publication loops, after ``book.process()`` had
returned. A stop cascade runs inside ``process()``, so a stop triggered later
in the same dispatch could still trade with the sibling (C5, 2026-10-25:
"fill after sibling FILLED"). The quote-submit loop did not pull it at all,
so a stop leg the cascade cancelled left its sibling live for good. The same
shape as X3 for quote legs, fixed the same way: the book reports the leg's
end while the dispatch is still running.

X17 (seen while fixing X15): a leg 1 that ended on entry still let leg 2
reach the book, where a stop already breached traded at once.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.order import OrderType, Side
from tests.engine_harness import (
    SYMBOL,
    all_msgs,
    connect,
    make_engine,
    msgs,
    order_payload,
    resting_ids,
    submit_quote,
)


def new_order(engine: Any, **kw: Any) -> str:
    payload = order_payload(**kw)
    engine._handle_new_order(payload)
    return str(payload["id"])


def oco(engine: Any, gw: str, qty: int, leg1: dict[str, Any], leg2: dict[str, Any]) -> tuple[str, str]:  # fmt: skip
    engine._handle_oco_order(
        {
            "oco_id": "OCO1",
            "gateway_id": gw,
            "symbol": SYMBOL,
            "quantity": qty,
            "tif": "DAY",
            "tick_decimals": 2,
            "leg1": leg1,
            "leg2": leg2,
        }
    )
    (ack,) = msgs(engine.pub_sock, f"oco.ack.{gw}")
    assert ack["accepted"], ack
    return ack["order_id_1"], ack["order_id_2"]


def traded(pub: Any, order_id: str) -> list[dict[str, Any]]:
    return [
        t
        for t in msgs(pub, "trade.executed")
        if order_id in (t["buy_order_id"], t["sell_order_id"])
    ]


def oco_cancelled(pub: Any, gw: str) -> list[str]:
    return [p["cancelled_order_id"] for p in msgs(pub, f"oco.cancelled.{gw}")]


def test_a_stop_triggered_after_a_leg_filled_cannot_trade_with_its_sibling(
    monkeypatch, tmp_path
) -> None:
    """The sim's case (AI037-2B1F): MM01's ask trades at 101 and triggers
    GW01's buy stop leg, which fills from the ask at 100. That print triggers
    GW03's sell stop, which must not sell into GW01's limit leg: it was
    pulled when the stop leg filled."""
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        gateways=("GW01", "GW02", "GW03", "MM01"),
        mm_gateways=("MM01",),
    )
    connect(engine, "GW01", "GW02", "GW03", "MM01")
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=5, gateway_id="GW02", price=101.0)  # fmt: skip
    limit_leg, stop_leg = oco(
        engine,
        "GW01",
        10,
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 9000},
        {"side": "BUY", "order_type": "STOP", "stop_price_ticks": 10100},
    )
    sell_stop = new_order(engine, side=Side.SELL, order_type=OrderType.STOP, qty=10, gateway_id="GW03", stop_price=100.5)  # fmt: skip

    submit_quote(engine, "MM01", bid_price=95.0, ask_price=100.0, ask_qty=20)

    assert [t["price"] for t in traded(pub, stop_leg)] == [100.0]
    assert traded(pub, limit_leg) == []
    assert oco_cancelled(pub, "GW01") == [limit_leg]
    assert limit_leg not in resting_ids(engine.books[SYMBOL])
    # The sell stop found no bid left, rather than the pulled leg.
    assert traded(pub, sell_stop) == []
    (cancel,) = [
        p for p in msgs(pub, "order.cancelled.GW03") if p["order_id"] == sell_stop
    ]
    assert cancel["cancel_reason"] == "INSUFFICIENT_LIQUIDITY"


def test_a_stop_leg_the_cascade_cancels_ends_its_sibling(monkeypatch, tmp_path) -> None:
    """The second shape in the sim (AI055-AEC): a quote's print triggers a
    stop leg that finds no liquidity and is cancelled. The quote-submit
    loop never ran the OCO follow-up, so the limit leg stayed live and
    filled seconds later."""
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        gateways=("GW01", "GW02", "MM01"),
        mm_gateways=("MM01",),
    )
    connect(engine, "GW01", "GW02", "MM01")
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=5, gateway_id="GW02", price=100.0)  # fmt: skip
    limit_leg, stop_leg = oco(
        engine,
        "GW01",
        10,
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 9000},
        {"side": "BUY", "order_type": "STOP", "stop_price_ticks": 10000},
    )

    submit_quote(engine, "MM01", bid_price=95.0, ask_price=100.0, ask_qty=5)

    (cancel,) = [
        p for p in msgs(pub, "order.cancelled.GW01") if p["order_id"] == stop_leg
    ]
    assert cancel["cancel_reason"] == "INSUFFICIENT_LIQUIDITY"
    assert oco_cancelled(pub, "GW01") == [limit_leg]
    assert limit_leg not in resting_ids(engine.books[SYMBOL])


def test_a_triggered_sibling_still_queued_in_the_cascade_is_cancelled(
    monkeypatch, tmp_path
) -> None:
    """One print at 98 triggers GW03's sell stop (99) and GW01's sell stop
    leg (98), in that order. GW03's stop fills GW01's limit leg at 95, so the
    stop leg, triggered but still queued, must not sell after all."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=5, gateway_id="GW02", price=98.0)  # fmt: skip
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=10, gateway_id="GW02", price=90.0)  # fmt: skip
    limit_leg, stop_leg = oco(
        engine,
        "GW01",
        10,
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 9500},
        {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9800},
    )
    sell_stop = new_order(engine, side=Side.SELL, order_type=OrderType.STOP, qty=10, gateway_id="GW03", stop_price=99.0)  # fmt: skip

    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=5, gateway_id="GW03", price=98.0)  # fmt: skip

    (fill,) = traded(pub, sell_stop)
    assert (fill["buy_order_id"], fill["price"]) == (limit_leg, 95.0)
    assert traded(pub, stop_leg) == []
    assert oco_cancelled(pub, "GW01") == [stop_leg]
    # Nothing at all reported the stop leg as traded or cancelled otherwise
    # (it did fire before it was pulled: order.triggered says so).
    assert [
        topic
        for topic, p in all_msgs(pub)
        if p.get("order_id") == stop_leg
        and topic.startswith(("order.fill.", "order.cancelled.", "order.expired."))
    ] == []


def test_a_fok_counts_only_one_leg_of_an_oco_pair(monkeypatch, tmp_path) -> None:
    """Once the first leg fills, its sibling leaves the book mid-sweep, so a
    FOK that needs both legs' quantity must be rejected up front, not filled
    in part (or, before X15, filled against both legs)."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    oco(
        engine,
        "GW01",
        10,
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 10000},
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 9900},
    )

    fok = new_order(engine, side=Side.SELL, order_type=OrderType.FOK, qty=15, gateway_id="GW02", price=99.0)  # fmt: skip

    assert msgs(pub, "trade.executed") == []
    (reject,) = [p for p in msgs(pub, "order.ack.GW02") if p["order_id"] == fok]
    assert reject["accepted"] is False
    assert reject["reject_code"] == "INSUFFICIENT_LIQUIDITY"
    assert len(resting_ids(engine.books[SYMBOL])) == 2


def test_a_leg_that_fills_on_entry_keeps_its_sibling_out_of_the_book(
    monkeypatch, tmp_path
) -> None:
    """X17: leg 1 buys all it wants at 99 on entry. Leg 2, a buy stop at 99
    the last print has already reached, would trigger on entry and buy at
    100: both legs filled. It is acked, then pulled, and never posted."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=10, gateway_id="GW02", price=99.0)  # fmt: skip
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=10, gateway_id="GW02", price=100.0)  # fmt: skip
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=1, gateway_id="GW03", price=99.0)  # fmt: skip
    limit_leg, stop_leg = oco(
        engine,
        "GW01",
        9,
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 9900},
        {"side": "BUY", "order_type": "STOP", "stop_price_ticks": 9900},
    )

    assert [t["quantity"] for t in traded(pub, limit_leg)] == [9]
    assert traded(pub, stop_leg) == []
    assert [
        topic.rsplit(".", 1)[0]
        for topic, p in all_msgs(pub)
        if stop_leg in (p.get("order_id"), p.get("cancelled_order_id"))
    ] == ["order.ack", "oco.cancelled"]
    assert stop_leg not in resting_ids(engine.books[SYMBOL])
    assert ("GW01", "OCO1") not in engine._oco_groups
