"""Every cancel the exchange decides on ends the structure it belongs to.

A client cancel of an OCO leg pulls the sibling and frees the id; a fill
does the same through the book's hook. The exchange's own cancels -- a
kill switch, an admin cancel-symbol, a ``CANCEL_ALL`` disconnect, a TIF
expiry -- used to cancel the orders and nothing else: the pair stayed in
``_oco_groups`` (so the id was "already in use" for the rest of the run)
and a combo stayed PENDING with no ``combo.status`` (review 2026-11, C1 and
C2). These tests pin the one rule for all of them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from edumatcher.engine.persistence import save_gtc_combos
from edumatcher.models.combo import ComboStatus
from edumatcher.models.order import TIF
from edumatcher.models.participant import DisconnectBehaviour
from edumatcher.models.price import to_ticks
from tests.engine_harness import (
    SYMBOL,
    assert_engine_links,
    connect,
    make_engine,
    msgs,
)

OTHER = "MSFT"


def _oco(engine: Any, gw: str, oco_id: str, tif: str = "DAY") -> tuple[str, str]:
    engine._handle_oco_order(
        {"oco_id": oco_id, "gateway_id": gw, "symbol": SYMBOL, "quantity": 5,
         "tif": tif,
         "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10100},
         "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9900}}
    )  # fmt: skip
    ack = msgs(engine.pub_sock, f"oco.ack.{gw}")[-1]
    assert ack["accepted"], ack["reason"]
    return ack["order_id_1"], ack["order_id_2"]


def _combo(engine: Any, gw: str, combo_id: str, tif: str = "DAY") -> Any:
    engine._handle_combo_order(
        {
            "combo_id": combo_id,
            "gateway_id": gw,
            "combo_type": "AON",
            "tif": tif,
            "legs": [
                {"symbol": SYMBOL, "side": "BUY", "order_type": "LIMIT",
                 "quantity": 5, "price_ticks": to_ticks(50.0, SYMBOL)},
                {"symbol": OTHER, "side": "SELL", "order_type": "LIMIT",
                 "quantity": 5, "price_ticks": to_ticks(150.0, OTHER)},
            ],
        }
    )  # fmt: skip
    assert msgs(engine.pub_sock, f"combo.ack.{gw}")[-1]["accepted"]
    (combo,) = [c for c in engine._combos.values() if c.combo_id == combo_id]
    assert combo.status is ComboStatus.PENDING
    return combo


def _resting(engine: Any) -> set[str]:
    return {o.id for b in engine.books.values() for o in b.resting_orders()}


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    eng, _pub = make_engine(
        monkeypatch,
        tmp_path,
        symbols=(SYMBOL, OTHER),
        admin_gateways=("ADMIN",),
        gateways=("GW01", "GW02", "ADMIN"),
    )
    connect(eng, "GW01", "GW02", "ADMIN")
    return eng


def _assert_oco_gone(engine: Any, gw: str, oco_id: str, legs: tuple[str, str]) -> None:
    assert not (set(legs) & _resting(engine))
    assert (gw, oco_id) not in engine._oco_groups
    assert not (set(legs) & engine._order_to_oco.keys())
    assert_engine_links(engine)
    # The id is the client's to use again.
    _oco(engine, gw, oco_id)


def _assert_combo_failed(engine: Any, combo: Any) -> None:
    assert combo.status is ComboStatus.FAILED
    assert not (set(combo.child_order_ids) & _resting(engine))
    assert not (set(combo.child_order_ids) & engine._order_to_combo.keys())
    statuses = [
        (p["status"], p.get("reason", ""))
        for p in msgs(engine.pub_sock, f"combo.status.{combo.gateway_id}")
        if p["combo_id"] == combo.combo_id
    ]
    assert [s for s, _ in statuses] == ["FAILED"], statuses
    assert "CANCELLED" in statuses[0][1]
    assert_engine_links(engine)


# --- OCO -----------------------------------------------------------------


def test_day_expiry_frees_the_oco_id(engine: Any) -> None:
    legs = _oco(engine, "GW01", "BRACKET")
    engine._expire_tif(TIF.DAY)
    expired = [p["order_id"] for p in msgs(engine.pub_sock, "order.expired.GW01")]
    assert sorted(expired) == sorted(legs)
    # Both legs expired on their own: no sibling cancel to report.
    assert msgs(engine.pub_sock, "oco.cancelled.GW01") == []
    _assert_oco_gone(engine, "GW01", "BRACKET", legs)


def test_self_kill_switch_unlinks_the_pair(engine: Any) -> None:
    legs = _oco(engine, "GW01", "BRACKET")
    engine._handle_kill_switch({"gateway_id": "GW01", "command_id": "k1"})
    ack = msgs(engine.pub_sock, "risk.kill_switch_ack.GW01")[-1]
    assert sorted(ack["cancelled_order_ids"]) == sorted(legs)
    reasons = {
        p["order_id"]: p["cancel_reason"]
        for p in msgs(engine.pub_sock, "order.cancelled.GW01")
    }
    assert [reasons[leg] for leg in legs] == ["KILL_SWITCH", "KILL_SWITCH"]
    assert msgs(engine.pub_sock, "oco.cancelled.GW01") == []
    _assert_oco_gone(engine, "GW01", "BRACKET", legs)


def test_admin_kill_switch_on_a_gateway_unlinks_the_pair(engine: Any) -> None:
    legs = _oco(engine, "GW01", "BRACKET")
    engine._handle_kill_switch_gateway(
        {"gateway_id": "ADMIN", "target_gateway_id": "GW01", "command_id": "k2"}
    )
    ack = msgs(engine.pub_sock, "risk.kill_switch_gateway_ack.ADMIN")[-1]
    assert sorted(ack["cancelled_order_ids"]) == sorted(legs)
    _assert_oco_gone(engine, "GW01", "BRACKET", legs)


def test_global_kill_switch_unlinks_the_pair(engine: Any) -> None:
    legs = _oco(engine, "GW01", "BRACKET")
    engine._handle_kill_switch_global({"gateway_id": "ADMIN", "command_id": "k3"})
    ack = msgs(engine.pub_sock, "risk.kill_switch_global_ack.ADMIN")[-1]
    assert sorted(ack["cancelled_order_ids"]) == sorted(legs)
    _assert_oco_gone(engine, "GW01", "BRACKET", legs)


def test_admin_cancel_symbol_unlinks_the_pair(engine: Any) -> None:
    legs = _oco(engine, "GW01", "BRACKET")
    engine._handle_cancel_symbol(
        {"gateway_id": "ADMIN", "symbol": SYMBOL, "command_id": "k4"}
    )
    ack = msgs(engine.pub_sock, "risk.cancel_symbol_ack.ADMIN")[-1]
    assert sorted(ack["cancelled_order_ids"]) == sorted(legs)
    _assert_oco_gone(engine, "GW01", "BRACKET", legs)


def test_cancel_all_disconnect_unlinks_the_pair(engine: Any) -> None:
    engine._sessions["GW01"].disconnect_behaviour = DisconnectBehaviour.CANCEL_ALL
    legs = _oco(engine, "GW01", "BRACKET")
    engine._handle_gateway_disconnect({"gateway_id": "GW01"})
    assert not (set(legs) & _resting(engine))
    assert ("GW01", "BRACKET") not in engine._oco_groups
    assert_engine_links(engine)
    connect(engine, "GW01")
    _oco(engine, "GW01", "BRACKET")


# --- Combo ---------------------------------------------------------------


def test_self_kill_switch_fails_the_combo(engine: Any, tmp_path: Path) -> None:
    combo = _combo(engine, "GW01", "C1")
    engine._handle_kill_switch({"gateway_id": "GW01", "command_id": "k5"})
    ack = msgs(engine.pub_sock, "risk.kill_switch_ack.GW01")[-1]
    assert sorted(ack["cancelled_order_ids"]) == sorted(combo.child_order_ids)
    _assert_combo_failed(engine, combo)
    # A finished combo is not checkpointed as live.
    target = tmp_path / "combos.json"
    save_gtc_combos(list(engine._combos.values()), target)
    assert json.loads(target.read_text()) == []


def test_admin_cancel_symbol_on_one_leg_cascades_the_rest(engine: Any) -> None:
    combo = _combo(engine, "GW01", "C2")
    engine._handle_cancel_symbol(
        {"gateway_id": "ADMIN", "symbol": SYMBOL, "command_id": "k6"}
    )
    # The MSFT leg was never in the command's scope; the combo's own
    # cascade pulls it, and reports it as a plain order.cancelled.
    ack = msgs(engine.pub_sock, "risk.cancel_symbol_ack.ADMIN")[-1]
    assert ack["cancelled_order_ids"] == [combo.child_order_ids[0]]
    cancelled = {p["order_id"] for p in msgs(engine.pub_sock, "order.cancelled.GW01")}
    assert set(combo.child_order_ids) <= cancelled
    _assert_combo_failed(engine, combo)


def test_admin_kill_switch_on_a_gateway_fails_the_combo(engine: Any) -> None:
    combo = _combo(engine, "GW01", "C3")
    engine._handle_kill_switch_gateway(
        {"gateway_id": "ADMIN", "target_gateway_id": "GW01", "command_id": "k7"}
    )
    _assert_combo_failed(engine, combo)


def test_global_kill_switch_fails_the_combo(engine: Any) -> None:
    combo = _combo(engine, "GW01", "C4")
    engine._handle_kill_switch_global({"gateway_id": "ADMIN", "command_id": "k8"})
    _assert_combo_failed(engine, combo)


def test_cancel_all_disconnect_fails_the_combo(engine: Any) -> None:
    engine._sessions["GW01"].disconnect_behaviour = DisconnectBehaviour.CANCEL_ALL
    combo = _combo(engine, "GW01", "C5")
    engine._handle_gateway_disconnect({"gateway_id": "GW01"})
    _assert_combo_failed(engine, combo)


def test_day_expiry_fails_the_combo(engine: Any) -> None:
    combo = _combo(engine, "GW01", "C6")
    engine._expire_tif(TIF.DAY)
    expired = {p["order_id"] for p in msgs(engine.pub_sock, "order.expired.GW01")}
    # Both legs expire in the same sweep; neither is cancelled for the other.
    assert expired == set(combo.child_order_ids)
    assert msgs(engine.pub_sock, "order.cancelled.GW01") == []
    assert combo.status is ComboStatus.FAILED
    assert not (set(combo.child_order_ids) & engine._order_to_combo.keys())
    assert_engine_links(engine)
