"""A refused cancel or amend never ends a resting order (API gateway review C1).

The order cache told a refused cancel/amend from a refused new order by
``request_tag``, which only a tagged request carries: an untagged refused
amend turned a resting order REJECTED, dropped it from the admin working
view and let the eviction sweep delete it. ``order.ack.request`` (Q2) now
says which request an ack answers.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.models.generated.order import OrderAckRequest
from edumatcher.models.message import decode, make_ack_msg
from tests.api_gateway_harness import call, make_app

ORDER = {"symbol": "AAPL", "side": "BUY", "quantity": 10, "price": 20.0}


def _resting_cache() -> SessionCaches:
    cache = SessionCaches()
    cache.apply(
        *decode(make_ack_msg("GW01", "ORD-1", True, request="NEW", order=ORDER))
    )
    assert cache.orders["ORD-1"]["status"] == "NEW"
    return cache


@pytest.mark.parametrize("request_kind", ["AMEND", "CANCEL"])
def test_an_untagged_refusal_leaves_a_resting_order_working(
    request_kind: OrderAckRequest,
) -> None:
    cache = _resting_cache()
    refusal = make_ack_msg(
        "GW01",
        "ORD-1",
        False,
        "Price not on tick grid",
        reject_code="TICK_VIOLATION",
        request=request_kind,
    )
    cache.apply(*decode(refusal))

    assert cache.orders["ORD-1"]["status"] == "NEW"
    assert cache.evict_terminal_orders(1, now=float("inf")) == 0
    assert "ORD-1" in cache.orders


def test_a_refused_new_order_still_becomes_rejected() -> None:
    cache = SessionCaches()
    refusal = make_ack_msg(
        "GW01",
        "ORD-2",
        False,
        "Unknown symbol",
        reject_code="UNKNOWN_SYMBOL",
        request="NEW",
    )
    cache.apply(*decode(refusal))
    assert cache.orders["ORD-2"]["status"] == "REJECTED"


@pytest.mark.anyio
async def test_untagged_cancel_wait_ack_reports_the_refusal() -> None:
    """``DELETE /orders/{id}?wait=ack`` with no request_tag: the engine's
    refusal is the answer, not an ack timeout."""
    with (
        patch(
            "edumatcher.api_gateway.engine_client.make_pusher",
            return_value=MagicMock(closed=False),
        ),
        patch(
            "edumatcher.api_gateway.engine_client.make_subscriber",
            return_value=MagicMock(),
        ),
    ):
        engine = EngineClient(
            "tcp://127.0.0.1:1", "tcp://127.0.0.1:2", asyncio.get_running_loop()
        )
    engine._authenticated.add("GW01")
    app = make_app(engine)

    reply = asyncio.create_task(call(app, "DELETE", "/api/v1/orders/ORD-1?wait=ack"))
    push: Any = engine._push
    for _ in range(200):
        if push.send_multipart.call_count:
            break
        await asyncio.sleep(0.005)
    engine._handle_event(
        *decode(
            make_ack_msg(
                "GW01",
                "ORD-1",
                False,
                "Order not found",
                reject_code="ORDER_NOT_FOUND",
                request="CANCEL",
            )
        )
    )
    status, _, body = await asyncio.wait_for(reply, timeout=2.0)

    assert status == 200
    assert body["status"] == "REJECTED"
    assert body["reject_code"] == "ORDER_NOT_FOUND"
    assert body["ack_timeout"] is False
