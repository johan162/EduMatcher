"""Regression tests for findings C3 and H1 in
docs-design/reviews/EduMatcher-Trader-GUI-Review.md:

C3 - "Live order rows lack stop_price/visible_qty/trail_offset/smp_action,
so Replace and Undo break." These four fields were not just missing from
the single-order hot path's inline ack dict (the review's literal
suggestion) -- they were not declared fields on order_ack at all
(spec/messages/order.yaml), and make_ack_msg's hand-written wrapper
whitelisted only a fixed set of fields it forwards from its order= dict,
silently dropping anything else. The fix adds the four fields to the spec,
regenerates the message bindings, extends make_ack_msg to forward them, and
extends the single-order hot path's inline dict (which bypasses make_ack_msg
entirely, for perf) with the same four fields.

H1 - "OCO legs are never grouped; 'Cancel group' is unreachable." The OCO
leg ack call site hand-rolled a small dict that never included
oco_group_id, even though oco_group_id is (and always was) a first-class
order_ack field and leg.oco_group_id is set before the ack is sent. The fix
replaces that hand-rolled dict with order_to_display_dict(leg) -- the same
full-order projection the combo leg ack already used -- which also happens
to be the exact change C3 needed at this call site.

The GUI-side fold (useOrderStore.detailPatch for C3, applyCancelled /
applyExpired's new terminalPatch for H1) is covered by
web-apps/trader-gui/apps/web/test/orderStore.test.ts.
"""

from __future__ import annotations

from typing import Any

from tests.engine_harness import connect, make_engine, msgs, order_payload
from edumatcher.models.message import decode
from edumatcher.models.order import OrderType, Side, SmpAction


def _last_ack(pub_sock, gateway_id: str = "GW01") -> dict[str, Any]:
    for frames in reversed(pub_sock.sent):
        topic, payload = decode(frames)
        if topic == f"order.ack.{gateway_id}":
            return payload
    raise AssertionError("no order.ack found")


def _oco_payload(gateway_id: str = "GW01") -> dict[str, Any]:
    return {
        "oco_id": "OCO001",
        "gateway_id": gateway_id,
        "symbol": "AAPL",
        "quantity": 100,
        "tif": "DAY",
        "tick_decimals": 2,
        "leg1": {"side": "BUY", "order_type": "LIMIT", "price_ticks": 9500},
        # STOP leg carries stop_price_ticks -- exactly the field C3 needs to
        # survive the leg ack.
        "leg2": {"side": "BUY", "order_type": "STOP", "stop_price_ticks": 10500},
    }


class TestSingleOrderAckCarriesTheFullOrderRecord:
    """C3, single-order hot path (`_handle_new_order`'s inline ack dict)."""

    def test_stop_limit_order_acks_its_stop_price(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        engine._handle_new_order(
            order_payload(
                Side.BUY,
                OrderType.STOP_LIMIT,
                100,
                "GW01",
                price=150.0,
                stop_price=148.0,
            )
        )
        ack = _last_ack(pub_sock)
        assert ack["accepted"] is True
        assert ack["stop_price"] == 148.0

    def test_iceberg_order_acks_its_visible_qty(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        engine._handle_new_order(
            order_payload(
                Side.BUY,
                OrderType.ICEBERG,
                100,
                "GW01",
                price=150.0,
                visible_qty=20,
            )
        )
        ack = _last_ack(pub_sock)
        assert ack["visible_qty"] == 20

    def test_trailing_stop_order_acks_its_trail_offset(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        engine._handle_new_order(
            order_payload(
                Side.SELL,
                OrderType.TRAILING_STOP,
                100,
                "GW01",
                # An explicit stop_price avoids the reject path that fires
                # when a TRAILING_STOP omits STOP= with no prior trade to
                # derive one from (main.py's TRAILING_STOP initial-stop
                # block) -- irrelevant to what this test pins.
                stop_price=148.0,
                trail_offset=1.5,
            )
        )
        ack = _last_ack(pub_sock)
        assert ack["trail_offset"] == 1.5

    def test_order_acks_its_smp_action(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        engine._handle_new_order(
            order_payload(
                Side.BUY,
                OrderType.LIMIT,
                100,
                "GW01",
                price=150.0,
                smp_action=SmpAction.CANCEL_RESTING,
            )
        )
        ack = _last_ack(pub_sock)
        assert ack["smp_action"] == "CANCEL_RESTING"


class TestOcoLegAckCarriesGroupIdAndFullOrderRecord:
    """H1 (oco_group_id) and C3 (stop_price) at the OCO leg ack call site."""

    def test_both_legs_ack_carries_the_shared_oco_group_id(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        engine._handle_oco_order(_oco_payload())

        oco_ack = msgs(pub_sock, "oco.ack.GW01")[-1]
        assert oco_ack["accepted"] is True
        leg1_id = oco_ack["order_id_1"]
        leg2_id = oco_ack["order_id_2"]

        acks_by_order_id = {m["order_id"]: m for m in msgs(pub_sock, "order.ack.GW01")}
        assert acks_by_order_id[leg1_id]["oco_group_id"] == "OCO001"
        assert acks_by_order_id[leg2_id]["oco_group_id"] == "OCO001"

    def test_stop_leg_ack_carries_its_stop_price(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        engine._handle_oco_order(_oco_payload())

        oco_ack = msgs(pub_sock, "oco.ack.GW01")[-1]
        leg2_id = oco_ack["order_id_2"]  # the STOP leg

        acks_by_order_id = {m["order_id"]: m for m in msgs(pub_sock, "order.ack.GW01")}
        assert acks_by_order_id[leg2_id]["stop_price"] == 105.0
