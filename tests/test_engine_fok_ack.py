"""An order the book rejects gets one ack: accepted=false, never accepted first.

Regression tests for X5 (docs-design/EduMatcher-Sim-Forensics-Workplan.md
§9): the engine published ``order.ack accepted=true`` before
``book.process()`` and, when the book rejected a FOK for want of liquidity,
a second ``order.ack accepted=false`` -- against the participant guide ("an
unfillable FOK is *rejected* ... rather than accepted and cancelled"). The
sim saw 5 161 such FOK orders in one session. The same held for an OCO leg
and a combo child the book rejects.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.order import TIF, OrderType, Side, SmpAction
from tests.engine_harness import (
    SYMBOL,
    all_msgs,
    connect,
    make_engine,
    msgs,
    order_payload,
)


def new_order(engine: Any, **kw: Any) -> str:
    payload = order_payload(**kw)
    engine._handle_new_order(payload)
    return str(payload["id"])


def about(pub: Any, order_id: str) -> list[tuple[str, Any]]:
    """(topic, accepted / cancel_reason / reject_code) of every message
    naming *order_id* as its own order."""
    out: list[tuple[str, Any]] = []
    for topic, p in all_msgs(pub):
        if p.get("order_id") != order_id:
            continue
        family = topic.rsplit(".", 1)[0]
        if family == "order.ack":
            out.append((family, (p["accepted"], p.get("reject_code"))))
        elif family == "order.cancelled":
            out.append((family, p.get("cancel_reason")))
        else:
            out.append((family, None))
    return out


def test_x5_an_unfillable_fok_gets_one_rejecting_ack(monkeypatch, tmp_path) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=10, gateway_id="GW01", price=100.0)  # fmt: skip
    fok = new_order(engine, side=Side.BUY, order_type=OrderType.FOK, qty=50, gateway_id="GW02", price=100.0)  # fmt: skip
    assert about(pub, fok) == [("order.ack", (False, "INSUFFICIENT_LIQUIDITY"))]
    assert msgs(pub, "trade.executed") == []


def test_x5_a_fillable_fok_is_acked_before_its_fill(monkeypatch, tmp_path) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=50, gateway_id="GW01", price=100.0)  # fmt: skip
    fok = new_order(engine, side=Side.BUY, order_type=OrderType.FOK, qty=50, gateway_id="GW02", price=100.0)  # fmt: skip
    assert about(pub, fok) == [("order.ack", (True, None)), ("order.fill", None)]


def test_x5_a_fok_cancelled_by_smp_is_still_accepted_then_cancelled(
    monkeypatch, tmp_path
) -> None:
    """Risk controls, FOK: with CANCEL_AGGRESSOR and a same-gateway conflict
    the FOK is CANCELLED (SELF_MATCH_PREVENTED), not rejected -- an accepted
    order the exchange cancelled, as for every other order type."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=50, gateway_id="GW01", price=100.0)  # fmt: skip
    fok = new_order(engine, side=Side.BUY, order_type=OrderType.FOK, qty=50, gateway_id="GW01", price=100.0, smp_action=SmpAction.CANCEL_AGGRESSOR)  # fmt: skip
    assert about(pub, fok) == [
        ("order.ack", (True, None)),
        ("order.cancelled", "SELF_MATCH_PREVENTED"),
    ]


def test_x5_cancel_resting_cancels_the_conflict_and_rejects_the_fok_once(
    monkeypatch, tmp_path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    own = new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=50, gateway_id="GW01", price=100.0)  # fmt: skip
    fok = new_order(engine, side=Side.BUY, order_type=OrderType.FOK, qty=50, gateway_id="GW01", price=100.0, smp_action=SmpAction.CANCEL_RESTING)  # fmt: skip
    assert about(pub, fok) == [("order.ack", (False, "INSUFFICIENT_LIQUIDITY"))]
    assert about(pub, own)[-1] == ("order.cancelled", "SELF_MATCH_PREVENTED")


def test_x5_an_unfillable_fok_oco_leg_gets_one_rejecting_ack(
    monkeypatch, tmp_path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=10, gateway_id="GW02", price=99.0)  # fmt: skip
    engine._handle_oco_order(
        {
            "oco_id": "OCO1",
            "gateway_id": "GW01",
            "symbol": SYMBOL,
            "quantity": 30,
            "tif": "DAY",
            "tick_decimals": 2,
            "leg1": {"side": "SELL", "order_type": "FOK", "price_ticks": 9900},
            "leg2": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 11000},
        }
    )
    (ack,) = msgs(pub, "oco.ack.GW01")
    assert about(pub, ack["order_id_1"]) == [
        ("order.ack", (False, "INSUFFICIENT_LIQUIDITY"))
    ]


def test_x5_a_fok_combo_child_the_book_rejects_gets_one_ack(
    monkeypatch, tmp_path
) -> None:
    """An AON combo with an unfillable leg posts its children without
    matching; the book rejects a FOK child it may not match."""
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    combo = ComboOrder.create(
        combo_id="C1",
        gateway_id="GW01",
        combo_type=ComboType.AON,
        tif=TIF.DAY,
        legs=[
            ComboLeg(symbol="AAPL", side=Side.BUY, order_type=OrderType.FOK, quantity=10, tick_decimals=2, price_ticks=10000),  # fmt: skip
            ComboLeg(symbol="MSFT", side=Side.SELL, order_type=OrderType.LIMIT, quantity=10, tick_decimals=2, price_ticks=13000),  # fmt: skip
        ],
    )
    engine._handle_combo_order(combo.to_submission_dict())
    (parent,) = engine._combos.values()
    fok_child = parent.child_order_ids[0]
    acks = [a for a in about(pub, fok_child) if a[0] == "order.ack"]
    assert [accepted for _, (accepted, _) in acks] == [False]
