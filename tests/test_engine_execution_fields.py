"""Execution messages carry integer ticks and cumulative quantities (S22).

Each test drives a real Engine through its handlers and reads the messages
it published: the canonical tick fields beside the display floats, a fill's
exact notional, an order's running totals, and what a cancel or expiry
leaves behind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.engine.main import Engine
from edumatcher.engine.persistence import load_gtc_orders, save_gtc_orders
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import (
    SYMBOL,
    FakeSock,
    connect,
    make_engine,
    msgs,
    order_payload,
)

Rig = tuple[Engine, FakeSock]


def new(
    engine: Engine, side: Side, kind: OrderType, qty: int, gw: str, **kw: Any
) -> str:
    p = order_payload(side, kind, qty, gw, **kw)
    engine._handle_new_order(p)
    return str(p["id"])


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Rig:
    e, pub = make_engine(monkeypatch, tmp_path)
    connect(e)
    return e, pub


def test_an_ack_carries_its_prices_in_ticks(engine: Rig) -> None:
    e, pub = engine
    new(e, Side.SELL, OrderType.LIMIT, 5, "GW01", price=100.25)
    new(e, Side.BUY, OrderType.STOP_LIMIT, 5, "GW01", price=101.00, stop_price=100.50)
    new(e, Side.SELL, OrderType.TRAILING_STOP, 5, "GW01", stop_price=99.00, trail_offset=0.75)  # fmt: skip
    limit, stop, trailing = msgs(pub, "order.ack.GW01")
    assert (limit["price"], limit["price_ticks"]) == (100.25, 10025)
    assert (stop["stop_price"], stop["stop_price_ticks"], stop["price_ticks"]) == (100.5, 10050, 10100)  # fmt: skip
    assert (trailing["trail_offset"], trailing["trail_offset_ticks"]) == (0.75, 75)


def test_an_oco_legs_ack_carries_ticks_too(engine: Rig) -> None:
    """The generic ack (ack_detail), not the new-order fast path."""
    e, pub = engine
    e._handle_oco_order(
        {"oco_id": "K1", "gateway_id": "GW01", "symbol": SYMBOL, "quantity": 5, "tif": "DAY", "tick_decimals": 2,  # fmt: skip
         "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10100},
         "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9900}}  # fmt: skip
    )
    leg1, leg2 = msgs(pub, "order.ack.GW01")
    assert leg1["price_ticks"] == 10100 and leg2["stop_price_ticks"] == 9900


def test_a_sweep_fill_is_exact_and_totals_run_across_fills(engine: Rig) -> None:
    """3 @ 100.00 + 2 @ 100.01 is 50002 ticks; the VWAP is no whole tick."""
    e, pub = engine
    new(e, Side.SELL, OrderType.LIMIT, 3, "GW01", price=100.00)
    new(e, Side.SELL, OrderType.LIMIT, 4, "GW01", price=100.01)
    buy = new(e, Side.BUY, OrderType.LIMIT, 9, "GW02", price=100.01)  # rests 2
    new(e, Side.SELL, OrderType.LIMIT, 2, "GW03", price=100.01)  # fills the rest
    first, second = [f for f in msgs(pub, "order.fill.GW02") if f["order_id"] == buy]
    assert (first["fill_qty"], first["fill_notional_ticks"]) == (7, 3 * 10000 + 4 * 10001)  # fmt: skip
    assert (first["cum_qty"], first["cum_notional_ticks"]) == (7, 70004)
    assert first["fill_price"] == pytest.approx(70004 / 7 / 100)
    assert (second["fill_notional_ticks"], second["cum_qty"], second["cum_notional_ticks"]) == (20002, 9, 90006)  # fmt: skip


def test_a_trade_carries_its_price_in_ticks(engine: Rig) -> None:
    e, pub = engine
    new(e, Side.SELL, OrderType.LIMIT, 3, "GW01", price=100.07)
    new(e, Side.BUY, OrderType.LIMIT, 3, "GW02", price=100.07)
    (trade,) = msgs(pub, "trade.executed")
    assert (trade["price"], trade["price_ticks"]) == (100.07, 10007)


def test_a_cancel_says_what_was_left_and_what_had_filled(engine: Rig) -> None:
    e, pub = engine
    new(e, Side.SELL, OrderType.LIMIT, 3, "GW01", price=100.00)
    ioc = new(e, Side.BUY, OrderType.IOC, 10, "GW02", price=100.00)
    (cancelled,) = msgs(pub, "order.cancelled.GW02")
    assert cancelled["order_id"] == ioc
    assert (cancelled["remaining_qty"], cancelled["cum_qty"]) == (7, 3)

    rest = new(e, Side.SELL, OrderType.LIMIT, 8, "GW01", price=101.00)
    e._handle_cancel({"order_id": rest, "gateway_id": "GW01"})
    (client,) = [c for c in msgs(pub, "order.cancelled.GW01") if c["order_id"] == rest]
    assert (client["remaining_qty"], client["cum_qty"]) == (8, 0)


def test_an_expiry_says_what_was_left_and_what_had_filled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e, pub = make_engine(monkeypatch, tmp_path, sessions_enabled=True)
    connect(e)
    for state in ("PRE_OPEN", "CONTINUOUS"):
        e._handle_session_transition({"to_state": state})
    day = new(e, Side.SELL, OrderType.LIMIT, 10, "GW01", price=100.00)
    new(e, Side.BUY, OrderType.LIMIT, 4, "GW02", price=100.00)
    e._handle_session_transition({"to_state": "CLOSED"})
    (expired,) = [x for x in msgs(pub, "order.expired.GW01") if x["order_id"] == day]
    assert (expired["remaining_qty"], expired["cum_qty"]) == (6, 4)


def test_an_amend_carries_its_price_in_ticks_and_its_new_priority(engine: Rig) -> None:
    e, pub = engine
    oid = new(e, Side.SELL, OrderType.LIMIT, 5, "GW01", price=101.00)
    before = e.books[SYMBOL]._order_index[oid].arrival_seq
    e._handle_amend({"order_id": oid, "gateway_id": "GW01", "price": 101.50})
    (amended,) = msgs(pub, "order.amended.GW01")
    assert (amended["price"], amended["price_ticks"]) == (101.5, 10150)
    assert amended["priority_reset"] is True
    assert amended["priority_seq"] == e.books[SYMBOL]._order_index[oid].arrival_seq
    assert amended["priority_seq"] > before


def test_auction_messages_carry_the_price_in_ticks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e, pub = make_engine(monkeypatch, tmp_path, sessions_enabled=True)
    connect(e)
    for state in ("PRE_OPEN", "OPENING_AUCTION"):
        e._handle_session_transition({"to_state": state})
    new(e, Side.BUY, OrderType.LIMIT, 5, "GW01", price=100.10)
    new(e, Side.SELL, OrderType.LIMIT, 5, "GW02", price=100.10)
    e._last_auction_indicative = float("-inf")
    e._flush_auction_indicative()
    (indicative,) = msgs(pub, f"auction.indicative.{SYMBOL}")
    assert (indicative["eq_price"], indicative["eq_price_ticks"]) == (100.1, 10010)
    e._handle_session_transition({"to_state": "CONTINUOUS"})
    (result,) = msgs(pub, f"auction.result.{SYMBOL}")
    assert (result["eq_price"], result["eq_price_ticks"]) == (100.1, 10010)


def test_the_running_notional_survives_a_restart(engine: Rig, tmp_path: Path) -> None:
    """Not in Order.to_dict() (order.new is built from it), but in the file."""
    e, _ = engine
    new(e, Side.SELL, OrderType.LIMIT, 3, "GW01", price=100.00)
    buy = new(e, Side.BUY, OrderType.LIMIT, 10, "GW02", price=100.00)
    order = e.books[SYMBOL]._order_index[buy]
    assert "cum_notional_ticks" not in order.to_dict()
    save_gtc_orders(e._resting_gtc_orders(), tmp_path / "gtc.json")
    (restored,) = [o for o in load_gtc_orders(tmp_path / "gtc.json") if o.id == buy]
    assert restored.cum_notional_ticks == order.cum_notional_ticks == 30000
