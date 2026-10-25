"""Every order-entry path publishes what ``book.process()`` did the same way.

Regression tests for X8d of the simulation forensics
(docs-design/EduMatcher-Sim-Forensics-Workplan.md §9): the engine had seven
near-identical publication loops (seed quote, new order, quote, combo child,
uncross and its stops, OCO leg, amend), and each had drifted from the others
in which follow-ups it ran -- the combo, OCO and quote hooks, the reject code,
the fill message's fields. X15 was one symptom; the cases below are the rest.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.combo import ComboStatus
from edumatcher.models.order import OrderType, Side, SmpAction
from tests.engine_harness import (
    SYMBOL,
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


def combo(engine: Any, gw: str, legs: list[dict[str, Any]]) -> Any:
    engine._handle_combo_order(
        {
            "combo_id": "C1",
            "gateway_id": gw,
            "combo_type": "AON",
            "tif": "DAY",
            "legs": legs,
        }
    )
    (ack,) = msgs(engine.pub_sock, f"combo.ack.{gw}")
    assert ack["accepted"], ack
    return next(c for c in engine._combos.values() if c.combo_id == "C1")


def traded(pub: Any, order_id: str) -> list[dict[str, Any]]:
    return [
        t
        for t in msgs(pub, "trade.executed")
        if order_id in (t["buy_order_id"], t["sell_order_id"])
    ]


def rejects(pub: Any, gw: str) -> dict[str, str]:
    return {
        p["order_id"]: p["reject_code"]
        for p in msgs(pub, f"order.ack.{gw}")
        if not p["accepted"]
    }


def oco_cancelled(pub: Any, gw: str) -> list[str]:
    return [p["cancelled_order_id"] for p in msgs(pub, f"oco.cancelled.{gw}")]


# --- OCO ---------------------------------------------------------------------


def test_an_oco_on_a_halted_symbol_rests_without_matching(monkeypatch, tmp_path) -> None:  # fmt: skip
    """The OCO path ignored the halt flag every other entry path honours
    and matched its legs continuously."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=5, gateway_id="GW02", price=100.0)  # fmt: skip
    engine._halted_symbols[SYMBOL] = True

    leg1, leg2 = oco(
        engine,
        "GW01",
        5,
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 10000},
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 9000},
    )

    assert msgs(pub, "trade.executed") == []
    assert {leg1, leg2} <= resting_ids(engine.books[SYMBOL])


def test_an_oco_leg_rejected_on_a_halted_symbol_says_so_and_ends_its_sibling(
    monkeypatch, tmp_path
) -> None:
    """X12: a leg the book rejects is reported with the halt's code, as
    gate 8 reports an ordinary IOC, and -- a rejected leg being terminal --
    its sibling is acked, pulled, and never posted."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    engine._halted_symbols[SYMBOL] = True

    leg1, leg2 = oco(
        engine,
        "GW01",
        5,
        {"side": "BUY", "order_type": "IOC", "price_ticks": 10000},
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 9000},
    )

    assert rejects(pub, "GW01") == {leg1: "INSTRUMENT_HALTED"}
    assert oco_cancelled(pub, "GW01") == [leg2]
    assert resting_ids(engine.books[SYMBOL]) == set()
    assert engine._oco_groups == {}


def test_a_rejected_fok_leg_ends_its_sibling(monkeypatch, tmp_path) -> None:
    """X12b: the participant guide lists REJECTED among the states that
    end an OCO (its example 4); the OCO path left leg 2 resting alone."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=5, gateway_id="GW02", price=100.0)  # fmt: skip

    leg1, leg2 = oco(
        engine,
        "GW01",
        10,
        {"side": "BUY", "order_type": "FOK", "price_ticks": 10000},
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 9000},
    )

    assert rejects(pub, "GW01") == {leg1: "INSUFFICIENT_LIQUIDITY"}
    assert oco_cancelled(pub, "GW01") == [leg2]
    assert leg2 not in resting_ids(engine.books[SYMBOL])


def test_leg_2_filling_on_entry_pulls_leg_1_before_the_cascade(
    monkeypatch, tmp_path
) -> None:
    """Leg 2 buys at 97 on entry; that print triggers GW03's sell stop
    (98). The OCO path deferred its own group's check until after both legs'
    dispatches, so the stop sold into leg 1 at 95: both legs filled."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=1, gateway_id="GW02", price=100.0)  # fmt: skip
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=1, gateway_id="GW03", price=100.0)  # fmt: skip
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=5, gateway_id="GW02", price=97.0)  # fmt: skip
    sell_stop = new_order(engine, side=Side.SELL, order_type=OrderType.STOP, qty=5, gateway_id="GW03", stop_price=98.0)  # fmt: skip

    leg1, leg2 = oco(
        engine,
        "GW01",
        5,
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 9500},
        {"side": "BUY", "order_type": "LIMIT", "price_ticks": 9700},
    )

    assert [t["price"] for t in traded(pub, leg2)] == [97.0]
    assert traded(pub, leg1) == []
    assert traded(pub, sell_stop) == []
    assert oco_cancelled(pub, "GW01") == [leg1]


def test_an_smp_cancel_of_a_resting_leg_ends_its_sibling(monkeypatch, tmp_path) -> None:  # fmt: skip
    """GW01 amends its own bid through its resting OCO ask; CANCEL_RESTING
    pulls the ask. The amend path ran no OCO follow-up, so the stop leg
    stayed live and the group stayed registered."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    leg1, leg2 = oco(
        engine,
        "GW01",
        5,
        {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10100},
        {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9000},
    )
    bid = new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=5, gateway_id="GW01", price=99.0, smp_action=SmpAction.CANCEL_RESTING)  # fmt: skip

    engine._handle_amend({"order_id": bid, "gateway_id": "GW01", "price": 101.0})

    (cancel,) = [p for p in msgs(pub, "order.cancelled.GW01") if p["order_id"] == leg1]
    assert cancel["cancel_reason"] == "SELF_MATCH_PREVENTED"
    assert oco_cancelled(pub, "GW01") == [leg2]
    assert resting_ids(engine.books[SYMBOL]) == {bid}
    assert engine._oco_groups == {}


# --- combo -------------------------------------------------------------------


def test_a_combo_child_rejected_outside_matching_says_why(monkeypatch, tmp_path) -> None:  # fmt: skip
    """X12a: an IOC child posted in PRE_OPEN cannot rest; it was reported
    as short of liquidity rather than as not permitted in this phase."""
    engine, pub = make_engine(
        monkeypatch, tmp_path, symbols=("AAPL", "MSFT"), sessions_enabled=True
    )
    connect(engine)
    engine._handle_session_transition({"to_state": "PRE_OPEN"})

    c = combo(
        engine,
        "GW01",
        [
            {"symbol": "AAPL", "side": "BUY", "order_type": "IOC", "quantity": 5, "price_ticks": 10000},  # fmt: skip
            {"symbol": "MSFT", "side": "BUY", "order_type": "LIMIT", "quantity": 5, "price_ticks": 10000},  # fmt: skip
        ],
    )

    assert rejects(pub, "GW01") == {c.child_order_ids[0]: "SESSION_NOT_PERMITTED"}


def test_a_combo_child_rejected_on_a_halted_symbol_says_so(monkeypatch, tmp_path) -> None:  # fmt: skip
    """X12a: the same, for a halted leg symbol."""
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    engine._halted_symbols["AAPL"] = True

    c = combo(
        engine,
        "GW01",
        [
            {"symbol": "AAPL", "side": "BUY", "order_type": "IOC", "quantity": 5, "price_ticks": 10000},  # fmt: skip
            {"symbol": "MSFT", "side": "BUY", "order_type": "LIMIT", "quantity": 5, "price_ticks": 10000},  # fmt: skip
        ],
    )

    assert rejects(pub, "GW01") == {c.child_order_ids[0]: "INSTRUMENT_HALTED"}


def test_an_amend_that_fills_a_combo_child_updates_the_combo(monkeypatch, tmp_path) -> None:  # fmt: skip
    """The amend path ran no combo follow-up: a child that traded on its
    amend left its combo PENDING, with no combo.status."""
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=5, gateway_id="GW02", price=101.0)  # fmt: skip
    c = combo(
        engine,
        "GW01",
        [
            {"symbol": "AAPL", "side": "BUY", "order_type": "LIMIT", "quantity": 5, "price_ticks": 10000},  # fmt: skip
            {"symbol": "MSFT", "side": "BUY", "order_type": "LIMIT", "quantity": 5, "price_ticks": 10000},  # fmt: skip
        ],
    )

    engine._handle_amend(
        {"order_id": c.child_order_ids[0], "gateway_id": "GW01", "price": 101.0}
    )

    assert c.status == ComboStatus.PARTIALLY_MATCHED
    assert [p["status"] for p in msgs(pub, "combo.status.GW01")] == [
        "PARTIALLY_MATCHED"
    ]


def test_a_quote_cascade_that_fills_a_combo_child_updates_the_combo(
    monkeypatch, tmp_path
) -> None:
    """MM01's ask trades at 101 and triggers GW03's buy stop, which lifts
    GW01's resting combo child at 102. The quote path ran no combo
    follow-up for the orders its cascade filled."""
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        symbols=("AAPL", "MSFT"),
        gateways=("GW01", "GW02", "GW03", "MM01"),
        mm_gateways=("MM01",),
    )
    connect(engine, "GW01", "GW02", "GW03", "MM01")
    c = combo(
        engine,
        "GW01",
        [
            {"symbol": "AAPL", "side": "SELL", "order_type": "LIMIT", "quantity": 5, "price_ticks": 10200},  # fmt: skip
            {"symbol": "MSFT", "side": "SELL", "order_type": "LIMIT", "quantity": 5, "price_ticks": 10200},  # fmt: skip
        ],
    )
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=5, gateway_id="GW02", price=101.0)  # fmt: skip
    buy_stop = new_order(engine, side=Side.BUY, order_type=OrderType.STOP, qty=5, gateway_id="GW03", stop_price=100.5)  # fmt: skip

    submit_quote(engine, "MM01", bid_price=95.0, ask_price=101.0, ask_qty=5)

    assert [t["sell_order_id"] for t in traded(pub, buy_stop)] == [c.child_order_ids[0]]
    assert c.status == ComboStatus.PARTIALLY_MATCHED


# --- the fill message ----------------------------------------------------------


def test_every_path_publishes_the_same_fill_fields(monkeypatch, tmp_path) -> None:
    """The new-order hot path built its fill by hand (no tif, no is_seed);
    the other paths went through Order.to_dict(), which has no display
    ``price``, so their fills lost the order's limit price."""
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        gateways=("GW01", "GW02", "MM01"),
        mm_gateways=("MM01",),
    )
    connect(engine, "GW01", "GW02", "MM01")
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=5, gateway_id="GW01", price=100.0)  # fmt: skip
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=2, gateway_id="GW02", price=100.0)  # fmt: skip
    submit_quote(engine, "MM01", bid_price=95.0, ask_price=100.0, ask_qty=3)

    fills = msgs(pub, "order.fill.GW01") + msgs(pub, "order.fill.GW02") + msgs(pub, "order.fill.MM01")  # fmt: skip
    assert len(fills) == 4
    for fill in fills:
        assert {"price", "tif", "is_seed", "side", "order_type", "qty"} <= fill.keys()
        assert fill["price"] == 100.0
    assert len({frozenset(f.keys()) - {"quote_id"} for f in fills}) == 1
