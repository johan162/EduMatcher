"""Regression tests for finding C1 in
docs-design/reviews/EduMatcher-Trader-GUI-Review.md:

"A rejected cancel or amend marks a live order REJECTED (GUI and gateway
cache)".

The engine's own order.ack `accepted=false` is shared by three different
events - a rejected NEW order, a rejected cancel, and a rejected amend - and
the *consumers* (the gateway's SessionCaches and the trader-gui order store)
folded all three the same way: mark the order REJECTED. For a cancel/amend
reject the target order never stopped resting, so that overwrote a live
order's status with a lie.

The engine already threads a reliable discriminator through the wire:
request_tag. Every new-order reject path (_handle_new_order and friends)
always publishes request_tag=None (order.new carries no such field); only
_handle_cancel/_handle_amend forward the client's request_tag. These tests
pin that the gateway cache (`SessionCaches.apply`) honours it, and that the
one path that could silently drop request_tag on the way out -
`_reject_after_error`, the engine's handler-exception fallback - carries it
too. The GUI-side fix (`useOrderStore.applyAck`,
`useOrderEventNotifications`) is covered by
web-apps/trader-gui/apps/web/test/orderStore.test.ts and
orderEventNotifications.test.ts.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from edumatcher.api_gateway.caches import SessionCaches
from tests.engine_harness import connect, make_engine, order_payload
from edumatcher.models.message import decode
from edumatcher.models.order import OrderType, Side


def _acked_order_id(pub_sock, gateway_id: str = "GW01") -> str:
    for frames in reversed(pub_sock.sent):
        topic, payload = decode(frames)
        if topic == f"order.ack.{gateway_id}" and payload.get("accepted"):
            return str(payload["order_id"])
    raise AssertionError("no accepted order.ack found")


def _last_ack(pub_sock, gateway_id: str = "GW01") -> dict[str, Any]:
    for frames in reversed(pub_sock.sent):
        topic, payload = decode(frames)
        if topic == f"order.ack.{gateway_id}":
            return payload
    raise AssertionError("no order.ack found")


class TestSessionCachesRejectDiscrimination:
    """The gateway's read model (`GET /orders`, `orders.snapshot`) must not
    mark a resting order REJECTED because a cancel or amend against it was
    rejected."""

    def test_new_order_reject_still_marks_rejected(self) -> None:
        caches = SessionCaches()
        caches.apply(
            "order.ack.GW01",
            {
                "order_id": "ORD1",
                "accepted": False,
                "reason": "collar breach",
                "reject_code": "COLLAR_BREACH",
                # A genuine new-order reject: no request_tag (order.new has
                # no such field, so the engine always omits it here).
            },
        )
        assert caches.orders["ORD1"]["status"] == "REJECTED"

    def test_rejected_cancel_does_not_touch_a_resting_orders_status(self) -> None:
        caches = SessionCaches()
        caches.apply(
            "order.ack.GW01",
            {"order_id": "ORD1", "accepted": True, "qty": 100},
        )
        assert caches.orders["ORD1"]["status"] == "NEW"

        # A late cancel loses the race to a fill and comes back
        # ORDER_NOT_FOUND -- or any other cancel reject; either way the order
        # this ack targets never stopped resting.
        caches.apply(
            "order.ack.GW01",
            {
                "order_id": "ORD1",
                "accepted": False,
                "reason": "Order not found",
                "reject_code": "ORDER_NOT_FOUND",
                "request_tag": "RT-CXL-001",
            },
        )
        assert caches.orders["ORD1"]["status"] == "NEW"
        # The reject detail still lands in the cache for a caller that wants
        # it (e.g. a future `GET /orders` reject surface) -- only `status` is
        # protected.
        assert caches.orders["ORD1"]["reject_code"] == "ORDER_NOT_FOUND"

    def test_rejected_amend_does_not_touch_a_resting_orders_status(self) -> None:
        caches = SessionCaches()
        caches.apply(
            "order.ack.GW01",
            {"order_id": "ORD1", "accepted": True, "qty": 100},
        )
        caches.apply(
            "order.ack.GW01",
            {
                "order_id": "ORD1",
                "accepted": False,
                "reason": "Amend price outside collar",
                "reject_code": "COLLAR_BREACH",
                "request_tag": "RT-AMD-001",
            },
        )
        assert caches.orders["ORD1"]["status"] == "NEW"

    def test_rejected_cancel_on_a_partial_order_leaves_partial_status(self) -> None:
        """A collar-breach amend or a late cancel can arrive after the order
        has already partially filled; the reject must not roll PARTIAL back
        to REJECTED either."""
        caches = SessionCaches()
        caches.apply(
            "order.ack.GW01", {"order_id": "ORD1", "accepted": True, "qty": 100}
        )
        caches.apply(
            "order.fill.GW01",
            {
                "order_id": "ORD1",
                "status": "PARTIAL",
                "fill_qty": 40,
                "remaining_qty": 60,
                "symbol": "AAPL",
                "side": "BUY",
            },
        )
        assert caches.orders["ORD1"]["status"] == "PARTIAL"

        caches.apply(
            "order.ack.GW01",
            {
                "order_id": "ORD1",
                "accepted": False,
                "reason": "collar breach",
                "reject_code": "COLLAR_BREACH",
                "request_tag": "RT-AMD-002",
            },
        )
        assert caches.orders["ORD1"]["status"] == "PARTIAL"

    def test_a_filled_order_is_not_relabelled_rejected_by_a_racing_cancel(
        self,
    ) -> None:
        """P1b from the review: cancel races a fill and comes back
        ORDER_NOT_FOUND after the order already went FILLED. The FILLED
        status must survive the reject."""
        caches = SessionCaches()
        caches.apply(
            "order.ack.GW01", {"order_id": "ORD1", "accepted": True, "qty": 100}
        )
        caches.apply(
            "order.fill.GW01",
            {
                "order_id": "ORD1",
                "status": "FILLED",
                "fill_qty": 100,
                "remaining_qty": 0,
                "symbol": "AAPL",
                "side": "BUY",
            },
        )
        assert caches.orders["ORD1"]["status"] == "FILLED"

        caches.apply(
            "order.ack.GW01",
            {
                "order_id": "ORD1",
                "accepted": False,
                "reason": "Order not found",
                "reject_code": "ORDER_NOT_FOUND",
                "request_tag": "RT-CXL-003",
            },
        )
        assert caches.orders["ORD1"]["status"] == "FILLED"


class TestRejectAfterErrorPreservesRequestTag:
    """`_reject_after_error` answers an order whose handler raised mid-way.
    It is the one path that used to hardcode request_tag=None regardless of
    what the failed command carried -- which would silently reintroduce C1 if
    a cancel or amend handler ever raised: the resulting reject would look
    like a new-order reject to every consumer keyed on request_tag."""

    def test_cancel_handler_exception_preserves_request_tag(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        )
        order_id = _acked_order_id(pub_sock)
        pub_sock.sent.clear()

        with patch.object(engine, "_handle_cancel", side_effect=RuntimeError("boom")):
            engine._dispatch_pull_message(
                "order.cancel",
                {
                    "order_id": order_id,
                    "gateway_id": "GW01",
                    "request_tag": "RT-CXL-CRASH",
                },
            )

        ack = _last_ack(pub_sock)
        assert ack["accepted"] is False
        assert ack["order_id"] == order_id
        assert ack["request_tag"] == "RT-CXL-CRASH"

    def test_amend_handler_exception_preserves_request_tag(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        )
        order_id = _acked_order_id(pub_sock)
        pub_sock.sent.clear()

        with patch.object(engine, "_handle_amend", side_effect=RuntimeError("boom")):
            engine._dispatch_pull_message(
                "order.amend",
                {
                    "order_id": order_id,
                    "gateway_id": "GW01",
                    "qty": 50,
                    "request_tag": "RT-AMD-CRASH",
                },
            )

        ack = _last_ack(pub_sock)
        assert ack["accepted"] is False
        assert ack["order_id"] == order_id
        assert ack["request_tag"] == "RT-AMD-CRASH"

    def test_new_order_handler_exception_still_carries_no_request_tag(
        self, monkeypatch, tmp_path
    ) -> None:
        """Pins the other half of the discriminator: a NEW order's payload
        never carries request_tag in the first place, so the crash path must
        not invent one -- this is what keeps request_tag a reliable
        cancel/amend-only signal."""
        engine, pub_sock = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")

        with patch.object(
            engine, "_handle_new_order", side_effect=RuntimeError("boom")
        ):
            engine._dispatch_pull_message(
                "order.new", {"id": "ORD-CRASH", "gateway_id": "GW01"}
            )

        ack = _last_ack(pub_sock)
        assert ack["accepted"] is False
        assert ack.get("request_tag") is None
