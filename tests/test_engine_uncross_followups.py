"""What an auction uncross's fills set off: quote and OCO follow-ups, and the
price a stop it triggers is told it filled at.

Regression tests for X8b/X8c (docs-design/EduMatcher-Sim-Forensics-
Workplan.md §9). The uncross's fill loop ran neither the quote refresh
policy nor the OCO sibling cancel that every continuous fill runs, and the
stop loop after it reported each stop's fill at the book's last trade price
instead of the stop's own average.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.order import OrderType, Side
from edumatcher.models.session import SessionState
from tests.engine_harness import (
    SYMBOL,
    connect,
    make_engine,
    msgs,
    order_payload,
    submit_quote,
)


def new_order(engine: Any, **kw: Any) -> str:
    payload = order_payload(**kw)
    engine._handle_new_order(payload)
    return str(payload["id"])


def live(engine: Any) -> set[str]:
    """Every order resting or armed in the book."""
    book = engine.books[SYMBOL]
    return {o.id for gw in ("GW01", "GW02", "GW03") for o in book.orders_for_gateway(gw)}  # fmt: skip


def test_x8b_a_quote_bid_filled_in_the_uncross_pulls_its_ask_before_the_stops_run(
    monkeypatch, tmp_path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path, mm_gateways=("GW03",))
    connect(engine)
    engine._session_state = SessionState.OPENING_AUCTION
    submit_quote(engine, "GW03", bid_price=100.0, ask_price=101.0, bid_qty=100)
    (ack,) = msgs(pub, "quote.ack.GW03")
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=100, gateway_id="GW01", price=100.0)  # fmt: skip
    behind = new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=50, gateway_id="GW02", price=102.0)  # fmt: skip
    stop = new_order(engine, side=Side.BUY, order_type=OrderType.STOP, qty=50, gateway_id="GW01", stop_price=100.0)  # fmt: skip

    engine._run_uncross(reason="SCHEDULED")

    statuses = [m["status"] for m in msgs(pub, "quote.status.GW03")]
    assert statuses[-1] == "INACTIVE_BID_FILLED"
    cancels = {m["order_id"]: m.get("cancel_reason") for m in msgs(pub, "order.cancelled.GW03")}  # fmt: skip
    assert cancels == {ack["ask_order_id"]: "QUOTE_LEG_FILLED"}
    assert engine._quote_index.get("GW03", SYMBOL) is None
    (stop_trade,) = [t for t in msgs(pub, "trade.executed") if t["buy_order_id"] == stop]  # fmt: skip
    assert (stop_trade["sell_order_id"], stop_trade["price"]) == (behind, 102.0)


def test_x8b_an_oco_leg_filled_in_the_closing_auction_cancels_its_sibling(
    monkeypatch, tmp_path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    engine._session_state = SessionState.CONTINUOUS
    engine._handle_oco_order(
        {
            "oco_id": "OCO1",
            "gateway_id": "GW03",
            "symbol": SYMBOL,
            "quantity": 30,
            "tif": "DAY",
            "tick_decimals": 2,
            "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10000},
            "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9000},
        }
    )
    (ack,) = msgs(pub, "oco.ack.GW03")
    engine._session_state = SessionState.CLOSING_AUCTION
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=30, gateway_id="GW01", price=100.0)  # fmt: skip

    engine._run_uncross(reason="SCHEDULED")

    assert [m["cancelled_order_id"] for m in msgs(pub, "oco.cancelled.GW03")] == [
        ack["order_id_2"]
    ]
    assert ack["order_id_2"] not in live(engine)


def test_x8c_a_stop_the_uncross_triggers_reports_its_own_average_price(
    monkeypatch, tmp_path
) -> None:
    """The stop sweeps 10 @ 101 and 10 @ 102: it filled at 101.50, and the
    order at 101 at 101.00 -- neither at the last print."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    engine._session_state = SessionState.OPENING_AUCTION
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=100, gateway_id="GW01", price=100.0)  # fmt: skip
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=100, gateway_id="GW02", price=100.0)  # fmt: skip
    at_101 = new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=10, gateway_id="GW02", price=101.0)  # fmt: skip
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=10, gateway_id="GW02", price=102.0)  # fmt: skip
    stop = new_order(engine, side=Side.BUY, order_type=OrderType.STOP, qty=20, gateway_id="GW03", stop_price=100.0)  # fmt: skip

    engine._run_uncross(reason="SCHEDULED")

    (fill,) = [m for m in msgs(pub, "order.fill.GW03") if m["order_id"] == stop]
    assert (fill["fill_qty"], fill["fill_price"]) == (20, 101.5)
    # The resting order the stop hit first was reported at the last print
    # too (the 2026-10-24 sim: limit sells that printed 93.82, told 92.28).
    (passive,) = [m for m in msgs(pub, "order.fill.GW02") if m["order_id"] == at_101]
    assert passive["fill_price"] == 101.0
