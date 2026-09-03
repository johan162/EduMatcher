"""``order.cancelled`` says why the exchange cancelled, not just that it did.

Before this, an exchange-initiated cancel carried no cause at all, so a client
could not tell a self-match prevention from a kill switch, a halt cascade or a
DAY expiry — and neither could the system tests, whose whole job is to prove
which of those happened. ``request_tag=None`` already distinguished "the
exchange did this" from "you did"; ``cancel_reason`` distinguishes *why*.

The two values are the two causes the book decides on its own. Everything else
the exchange cancels still publishes ``cancel_reason=null``, which is honest
rather than complete: null means "the exchange did this, cause unstated", not
"the client asked".
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.generated.order import topic_order_cancelled
from edumatcher.models.order import Order, OrderType, Side, SmpAction, TIF
from edumatcher.models.price import to_ticks
from tests.engine_harness import (
    SYMBOL,
    connect,
    make_engine,
    msgs,
    order_payload,
)


def _cancels(pub_sock: Any, gateway_id: str) -> list[dict[str, Any]]:
    return msgs(pub_sock, topic_order_cancelled(gateway_id))


class TestUnfillableRemainder:
    """A MARKET or IOC order the book cannot satisfy."""

    def test_market_into_empty_book_is_cancelled_with_a_reason(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")

        engine._handle_new_order(order_payload(Side.BUY, OrderType.MARKET, 100, "GW01"))

        cancelled = _cancels(pub, "GW01")
        assert len(cancelled) == 1
        assert cancelled[0]["cancel_reason"] == "INSUFFICIENT_LIQUIDITY"

    def test_partially_filled_market_reports_the_shortfall_not_the_fill(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """The remainder is what was cancelled, so the book running out is the
        cause even though the order did trade."""
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01", "GW02")

        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 40, "GW02", price=100.00)
        )
        engine._handle_new_order(order_payload(Side.BUY, OrderType.MARKET, 100, "GW01"))

        cancelled = _cancels(pub, "GW01")
        assert len(cancelled) == 1
        assert cancelled[0]["cancel_reason"] == "INSUFFICIENT_LIQUIDITY"

    def test_ioc_remainder_reports_the_same_cause(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01", "GW02")

        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 40, "GW02", price=100.00)
        )
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.IOC, 100, "GW01", price=100.00)
        )

        cancelled = _cancels(pub, "GW01")
        assert len(cancelled) == 1
        assert cancelled[0]["cancel_reason"] == "INSUFFICIENT_LIQUIDITY"


class TestSelfMatchPrevention:
    """Each SMP action cancels a different order; all of them say why."""

    @staticmethod
    def _smp_order(
        side: Side, action: SmpAction, price: float, qty: int = 100
    ) -> dict[str, Any]:
        order = Order.create(
            symbol=SYMBOL,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=qty,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=to_ticks(price, SYMBOL),
            smp_action=action,
        )
        return order.to_dict()

    def test_cancel_aggressor(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")

        engine._handle_new_order(self._smp_order(Side.SELL, SmpAction.NONE, 100.00))
        engine._handle_new_order(
            self._smp_order(Side.BUY, SmpAction.CANCEL_AGGRESSOR, 100.00)
        )

        reasons = [c["cancel_reason"] for c in _cancels(pub, "GW01")]
        assert reasons == ["SELF_MATCH_PREVENTED"]

    def test_cancel_resting(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")

        engine._handle_new_order(self._smp_order(Side.SELL, SmpAction.NONE, 100.00))
        engine._handle_new_order(
            self._smp_order(Side.BUY, SmpAction.CANCEL_RESTING, 100.00)
        )

        reasons = [c["cancel_reason"] for c in _cancels(pub, "GW01")]
        assert "SELF_MATCH_PREVENTED" in reasons

    def test_cancel_both(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")

        engine._handle_new_order(self._smp_order(Side.SELL, SmpAction.NONE, 100.00))
        engine._handle_new_order(
            self._smp_order(Side.BUY, SmpAction.CANCEL_BOTH, 100.00)
        )

        reasons = [c["cancel_reason"] for c in _cancels(pub, "GW01")]
        assert reasons.count("SELF_MATCH_PREVENTED") == 2


class TestClientCancelStaysNull:
    """The field must not become "the exchange cancelled this" noise."""

    def test_client_cancel_has_no_reason(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")

        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.00)
        engine._handle_new_order(payload)
        engine._handle_cancel({"order_id": payload["id"], "gateway_id": "GW01"})

        cancelled = _cancels(pub, "GW01")
        assert len(cancelled) == 1
        # omit_when_none: absent rather than null on the wire.
        assert "cancel_reason" not in cancelled[0]


class TestRestSurface:
    """cancel_reason reaches REST clients without a schema change.

    The WebSocket projection forwards the engine payload verbatim and the
    order cache folds it in with ``dict.update``, so the field arrives on both
    REST surfaces for free. That is worth a test rather than an assumption:
    it is the reason no response model changed, and a future filter added to
    either path would silently undo it.
    """

    _CANCEL = {
        "order_id": "ORD1",
        "client_tag": "CT-1",
        "cancel_reason": "SELF_MATCH_PREVENTED",
    }

    def test_websocket_event_carries_it(self) -> None:
        from edumatcher.api_gateway.events import envelope

        event = envelope("order.cancelled.GW01", dict(self._CANCEL))
        assert event["type"] == "order.cancelled"
        assert event["data"]["cancel_reason"] == "SELF_MATCH_PREVENTED"

    def test_order_cache_records_it_for_get_orders(self) -> None:
        from edumatcher.api_gateway.caches import SessionCaches

        caches = SessionCaches()
        caches.apply(
            "order.ack.GW01",
            {"order_id": "ORD1", "accepted": True, "client_tag": "CT-1"},
        )
        caches.apply("order.cancelled.GW01", dict(self._CANCEL))

        cached = caches.orders["ORD1"]
        assert cached["status"] == "CANCELLED"
        assert cached["cancel_reason"] == "SELF_MATCH_PREVENTED"

    def test_a_client_requested_cancel_leaves_it_out(self) -> None:
        """DELETE /orders/{id} is the client's own cancel, so this field is
        always absent there — which is why CancelAccepted does not lift it into
        a named response field the way OrderAccepted lifts reject_code."""
        from edumatcher.api_gateway.caches import SessionCaches

        caches = SessionCaches()
        caches.apply("order.cancelled.GW01", {"order_id": "ORD2"})
        assert "cancel_reason" not in caches.orders["ORD2"]
