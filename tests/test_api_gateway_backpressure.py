"""Regression tests for engine review finding E4.

``make_pusher`` sets ``SNDTIMEO=0`` and ``IMMEDIATE=1``, so a send raises
``zmq.Again`` whenever the engine is down, not yet connected, or slower than
the gateway. ALF turned that into a reasoned ``ENGINE_UNAVAILABLE``; the API
gateway let it propagate as a bare 500, which gives a client no way to tell
retryable congestion from a server defect.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
import zmq
from fastapi import HTTPException

from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.models.order import Order, OrderType, Side


@pytest.fixture
def client() -> Iterator[EngineClient]:
    """An EngineClient whose sockets are fakes — binds nothing."""
    loop = asyncio.new_event_loop()
    try:
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
            yield EngineClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", loop)
    finally:
        loop.close()


def _push(client: EngineClient) -> MagicMock:
    """The fake PUSH socket, typed for the mock API."""
    return cast(MagicMock, client._push)


def _order() -> Order:
    return Order.create(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=10000,  # integer ticks
        gateway_id="GW01",
    )


@pytest.mark.parametrize(
    "raised",
    [
        pytest.param(zmq.Again(), id="zmq.Again"),
        pytest.param(zmq.ZMQError(zmq.EAGAIN), id="ZMQError-with-EAGAIN"),
    ],
)
def test_backpressure_becomes_503_not_500(client: EngineClient, raised) -> None:
    """Both shapes reach us: zmq.Again is a ZMQError subclass, but not every
    EAGAIN arrives as one — ALF guards both."""
    _push(client).send_multipart.side_effect = raised
    with pytest.raises(HTTPException) as excinfo:
        client.send_new_order(_order())

    assert excinfo.value.status_code == 503
    detail = cast(dict[str, Any], excinfo.value.detail)
    assert detail["error"]["code"] == "ENGINE_UNAVAILABLE"


def test_a_real_zmq_error_is_not_masked_as_backpressure(client: EngineClient) -> None:
    """ "Engine busy, retry" and "something is broken" must stay distinct."""
    _push(client).send_multipart.side_effect = zmq.ZMQError(zmq.EFSM)
    with pytest.raises(zmq.ZMQError):
        client.send_cancel("ORD-1", "GW01")


def test_every_sender_is_guarded(client: EngineClient) -> None:
    """The finding was not specific to send_new_order — the whole class shares
    the shape, so a new sender that bypasses _send is the regression to catch.
    """
    _push(client).send_multipart.side_effect = zmq.Again()
    calls = [
        lambda: client.send_new_order(_order()),
        lambda: client.send_cancel("ORD-1", "GW01"),
        lambda: client.send_amend("ORD-1", "GW01", price=1.0, qty=1),
        lambda: client.send_combo({}),
        lambda: client.send_combo_cancel("C1", "GW01"),
        lambda: client.send_oco({}),
        lambda: client.send_oco_cancel("O1", "GW01"),
        lambda: client.send_quote({}),
        lambda: client.send_quote_cancel("GW01", "AAPL"),
        lambda: client.send_mass_cancel("GW01"),
        lambda: client.send_session_transition("CONTINUOUS"),
        lambda: client.send_symbol_halt("GW01", "AAPL"),
        lambda: client.send_symbol_resume("GW01", "AAPL"),
        lambda: client.send_cancel_symbol("GW01", "AAPL"),
        lambda: client.send_disconnect("GW01", "bye"),
        lambda: client.request_orders("GW01"),
        lambda: client.request_symbols("GW01"),
        lambda: client.request_session("GW01"),
        lambda: client.request_quote_bootstrap("GW01"),
        lambda: client.request_quote_legs("GW01"),
        lambda: client.request_gateways("GW01"),
        lambda: client.request_session_schedule("GW01"),
        lambda: client.request_halt_status("GW01"),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as excinfo:
            call()
        assert excinfo.value.status_code == 503


def test_best_effort_send_stays_silent(client: EngineClient) -> None:
    """At shutdown the engine being gone is the ordinary case; raising there
    would skip stop_listener() and leak the reader threads."""
    _push(client).send_multipart.side_effect = zmq.Again()
    client.send_disconnect("GW01", "api gateway shutdown", require_engine=False)


def test_a_closed_socket_sends_nothing_and_raises_nothing(
    client: EngineClient,
) -> None:
    """Shutdown ordering can close the socket first."""
    _push(client).closed = True
    client.send_new_order(_order())
    _push(client).send_multipart.assert_not_called()


def test_failed_auth_send_does_not_leak_a_waiter(client: EngineClient) -> None:
    """The waiter is registered before the send (the SUB reader is a separate
    thread), so a send that fails leaves one nothing will ever resolve —
    accumulating on every retry against a down engine.
    """
    _push(client).send_multipart.side_effect = zmq.Again()
    with pytest.raises(HTTPException):
        client._loop.run_until_complete(client.authenticate("GW01", timeout=0.01))

    assert not client._pending, f"waiter left behind: {dict(client._pending)}"
