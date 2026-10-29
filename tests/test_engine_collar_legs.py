"""OCO and combo legs enter inside the price collar; quotes are exempt.

Regression tests for X30 of the simulation forensics
(docs-design/EduMatcher-Sim-Forensics-Workplan.md §9): the collar was
applied in ``order.new`` and amend only, so on the 2026-10-29 run 3 OCO legs
and 5 combo legs entered outside it (D8). Decided 2026-10-29: OCO and combo
legs are collared as an order is, a market maker's quote is not.
"""

from __future__ import annotations

from typing import Any

from edumatcher.engine.collar import CollarConfig
from tests.engine_harness import connect, make_engine, msgs

#: Static band ±20 % around 100.00, no trade yet (no dynamic band).
OUTSIDE = 15_000
INSIDE = 10_100


def collared(monkeypatch: Any, tmp_path: Any) -> tuple[Any, Any]:
    engine, pub = make_engine(
        monkeypatch, tmp_path, symbols=("AAPL", "MSFT"), mm_gateways=("GW03",)
    )
    connect(engine)
    engine._enforce_collars = True
    engine._collars["AAPL"] = CollarConfig("AAPL", reference_price=10_000)
    return engine, pub


def resting(engine: Any) -> list[str]:
    return [o.id for book in engine.books.values() for o in book.resting_orders()]


def oco(price_ticks: int) -> dict[str, Any]:
    return {
        "oco_id": "K1",
        "gateway_id": "GW01",
        "symbol": "AAPL",
        "quantity": 5,
        "tif": "DAY",
        "tick_decimals": 2,
        "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": price_ticks},
        "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9_000},
    }


def combo(price_ticks: int) -> dict[str, Any]:
    leg = {"side": "BUY", "order_type": "LIMIT", "quantity": 5, "tick_decimals": 2}
    return {
        "combo_id": "C1",
        "gateway_id": "GW01",
        "combo_type": "AON",
        "tif": "DAY",
        "legs": [
            {**leg, "symbol": "MSFT", "price_ticks": 5_000},
            {**leg, "symbol": "AAPL", "price_ticks": price_ticks},
        ],
    }


def test_an_oco_with_a_leg_outside_the_collar_is_rejected(monkeypatch, tmp_path) -> None:  # fmt: skip
    engine, pub = collared(monkeypatch, tmp_path)

    engine._handle_oco_order(oco(OUTSIDE))

    (ack,) = msgs(pub, "oco.ack.GW01")
    assert not ack["accepted"]
    assert ack["reason"].startswith("Leg 1: ") and "COLLAR" in ack["reason"]
    assert resting(engine) == [] and engine._oco_groups == {}


def test_a_combo_with_a_leg_outside_the_collar_is_rejected(monkeypatch, tmp_path) -> None:  # fmt: skip
    engine, pub = collared(monkeypatch, tmp_path)

    engine._handle_combo_order(combo(OUTSIDE))

    (ack,) = msgs(pub, "combo.ack.GW01")
    assert not ack["accepted"]
    assert ack["reason"].startswith("Leg 1: ") and "COLLAR" in ack["reason"]
    assert resting(engine) == [] and engine._combos == {}


def test_legs_inside_the_collar_are_accepted(monkeypatch, tmp_path) -> None:
    engine, pub = collared(monkeypatch, tmp_path)

    engine._handle_oco_order(oco(INSIDE))
    engine._handle_combo_order(combo(INSIDE))

    assert [a["accepted"] for a in msgs(pub, "oco.ack.GW01")] == [True]
    assert [a["accepted"] for a in msgs(pub, "combo.ack.GW01")] == [True]


def test_a_market_makers_quote_is_not_collared(monkeypatch, tmp_path) -> None:
    engine, pub = collared(monkeypatch, tmp_path)

    engine._handle_quote_new(
        {
            "gateway_id": "GW03",
            "symbol": "AAPL",
            "tick_decimals": 2,
            "bid_price_ticks": 9_900,
            "bid_qty": 10,
            "ask_price_ticks": OUTSIDE,
            "ask_qty": 10,
            "tif": "DAY",
            "quote_id": "Q1",
        }
    )

    assert [a["accepted"] for a in msgs(pub, "quote.ack.GW03")] == [True]
