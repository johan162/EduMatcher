"""OCO legs get the gateway's SMP default, like every other order.

Regression tests for X9 (docs-design/EduMatcher-Sim-Forensics-Workplan.md
§9): ``_handle_oco_order`` built both legs without resolving ``smp_action``,
so they carried ``None``, which the sweep treats as ``NONE``. In the sim, OCO
stop legs triggered by a cascade sold into their owner's own resting bids
although every gateway was configured ``CANCEL_AGGRESSOR``.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.order import OrderType, Side, SmpAction
from tests.engine_harness import (
    SYMBOL,
    connect,
    make_engine,
    msgs,
    order_payload,
    terminal_notifications_for,
)


def new_order(engine: Any, **kw: Any) -> str:
    payload = order_payload(**kw)
    engine._handle_new_order(payload)
    return str(payload["id"])


def gateway_default(engine: Any, gw: str, smp: SmpAction) -> None:
    assert engine._engine_config is not None
    engine._engine_config.fix_gateways[gw].smp_action = smp


def submit_oco(
    engine: Any, leg1: dict[str, Any], leg2: dict[str, Any]
) -> tuple[str, str]:
    engine._handle_oco_order(
        {
            "oco_id": "OCO1",
            "gateway_id": "GW01",
            "symbol": SYMBOL,
            "quantity": 30,
            "tif": "DAY",
            "tick_decimals": 2,
            "leg1": leg1,
            "leg2": leg2,
        }
    )
    (ack,) = msgs(engine.pub_sock, "oco.ack.GW01")
    assert ack["accepted"], ack
    return ack["order_id_1"], ack["order_id_2"]


def self_trades(engine: Any) -> list[dict[str, Any]]:
    return [
        t
        for t in msgs(engine.pub_sock, "trade.executed")
        if t["buy_gateway_id"] == t["sell_gateway_id"]
    ]


def triggered_stop_leg_meets_own_bid(
    monkeypatch, tmp_path, smp: SmpAction
) -> tuple[Any, str]:
    """The sim's case: GW03's sell prints 100.00 against GW02, which
    triggers GW01's OCO stop leg; the best bid left is GW01's own."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    gateway_default(engine, "GW01", smp)
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=50, gateway_id="GW01", price=99.0)  # fmt: skip
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=20, gateway_id="GW02", price=100.0)  # fmt: skip
    _, stop_leg = submit_oco(
        engine,
        {"side": "SELL", "order_type": "LIMIT", "price_ticks": 11000},
        {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 10000},
    )
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=20, gateway_id="GW03", price=100.0)  # fmt: skip
    return engine, stop_leg


def test_x9_a_triggered_oco_stop_leg_does_not_trade_with_its_owner(
    monkeypatch, tmp_path
) -> None:
    engine, stop_leg = triggered_stop_leg_meets_own_bid(
        monkeypatch, tmp_path, SmpAction.CANCEL_AGGRESSOR
    )
    assert self_trades(engine) == []
    notes = terminal_notifications_for(engine.pub_sock, "GW01", stop_leg)
    assert [(topic, p.get("cancel_reason")) for topic, p in notes] == [
        ("order.cancelled.GW01", "SELF_MATCH_PREVENTED")
    ]


def test_x9_both_oco_legs_are_acked_with_the_resolved_smp_action(
    monkeypatch, tmp_path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    gateway_default(engine, "GW01", SmpAction.CANCEL_RESTING)
    leg1, leg2 = submit_oco(
        engine,
        {"side": "SELL", "order_type": "LIMIT", "price_ticks": 11000},
        {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9000},
    )
    acks = {a["order_id"]: a for a in msgs(pub, "order.ack.GW01")}
    assert acks[leg1]["smp_action"] == acks[leg2]["smp_action"] == "CANCEL_RESTING"


def test_x9_an_oco_limit_leg_crossing_its_owners_order_on_entry_is_cancelled(
    monkeypatch, tmp_path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    gateway_default(engine, "GW01", SmpAction.CANCEL_AGGRESSOR)
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=10, gateway_id="GW01", price=100.0)  # fmt: skip
    limit_leg, _ = submit_oco(
        engine,
        {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10000},
        {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9000},
    )
    assert self_trades(engine) == []
    notes = terminal_notifications_for(pub, "GW01", limit_leg)
    assert [p.get("cancel_reason") for _, p in notes] == ["SELF_MATCH_PREVENTED"]


def test_x9_a_gateway_that_allows_self_trades_still_gets_them(
    monkeypatch, tmp_path
) -> None:
    """The legs take the gateway's default, not a fixed CANCEL_*: NONE
    means the owner accepts trading with itself."""
    engine, stop_leg = triggered_stop_leg_meets_own_bid(
        monkeypatch, tmp_path, SmpAction.NONE
    )
    (trade,) = self_trades(engine)
    assert trade["sell_order_id"] == stop_leg
