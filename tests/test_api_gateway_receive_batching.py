"""The receive thread hands events to the loop in batches; all_orders filters
before it copies.

Both exist for the open burst of 2026-11-07, when one API gateway's event
loop ran out of CPU: per-message call_soon_threadsafe was a cost of its own,
and the admin monitor's gap resync calls GET /admin/orders while the cache
holds ~200k terminal orders.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import zmq

from edumatcher.api_gateway import engine_client as ec
from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.messaging.bus import get_context
from edumatcher.models.message import encode


class _RecordingLoop:
    """Stands in for the asyncio loop: records what the thread hands over."""

    def __init__(self) -> None:
        self.batches: list[list[tuple[str, dict[str, Any]]]] = []

    def call_soon_threadsafe(self, fn: Any, batch: Any) -> None:
        self.batches.append(list(batch))


@pytest.fixture
def pub_and_client() -> (
    Iterator[tuple[zmq.Socket[bytes], EngineClient, _RecordingLoop]]
):
    addr = f"inproc://recv-batch-{time.monotonic_ns()}"
    pub: zmq.Socket[bytes] = get_context().socket(zmq.PUB)
    pub.bind(addr)
    loop = _RecordingLoop()
    with patch(
        "edumatcher.api_gateway.engine_client.make_pusher",
        return_value=MagicMock(closed=False),
    ):
        client = EngineClient("inproc://unused", addr, loop)  # type: ignore[arg-type]
    try:
        yield pub, client, loop
    finally:
        client._running = False
        client._sub.close(linger=0)
        pub.close(linger=0)


def _wait_for(pred: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def _publish_until_subscribed(pub: zmq.Socket[bytes], client: EngineClient) -> None:
    """Defeat the PUB/SUB slow-joiner: wait until a probe gets through."""
    poller = zmq.Poller()
    poller.register(client._sub, zmq.POLLIN)
    while True:
        pub.send_multipart(encode("probe", {}))
        if poller.poll(timeout=20):
            while True:
                try:
                    client._sub.recv_multipart(zmq.NOBLOCK)
                except zmq.Again:
                    return


def test_queued_messages_arrive_in_capped_batches_in_order(
    pub_and_client: tuple[zmq.Socket[bytes], EngineClient, _RecordingLoop],
) -> None:
    pub, client, loop = pub_and_client
    _publish_until_subscribed(pub, client)
    n = ec._RECV_BATCH_MAX + 44
    for i in range(n):
        pub.send_multipart(encode(f"depth.S{i}", {"i": i}))
    time.sleep(0.05)  # let inproc deliver everything before the thread runs

    client._running = True
    thread = threading.Thread(target=client._receive_loop, daemon=True)
    thread.start()
    _wait_for(lambda: sum(len(b) for b in loop.batches) == n)
    client._running = False
    thread.join(timeout=2.0)

    # One hand-off per batch, not per message, and none over the cap.
    assert len(loop.batches) < n
    assert max(len(b) for b in loop.batches) <= ec._RECV_BATCH_MAX
    assert loop.batches[0] and len(loop.batches[0]) == ec._RECV_BATCH_MAX
    flat = [payload["i"] for b in loop.batches for _topic, payload in b]
    assert flat == list(range(n))


def test_a_malformed_message_is_dropped_without_losing_its_batch(
    pub_and_client: tuple[zmq.Socket[bytes], EngineClient, _RecordingLoop],
) -> None:
    pub, client, loop = pub_and_client
    _publish_until_subscribed(pub, client)
    pub.send_multipart(encode("depth.A", {"i": 0}))
    pub.send_multipart([b"depth.B", b"{not json"])
    pub.send_multipart(encode("depth.C", {"i": 2}))
    time.sleep(0.05)

    client._running = True
    thread = threading.Thread(target=client._receive_loop, daemon=True)
    thread.start()
    _wait_for(lambda: sum(len(b) for b in loop.batches) == 2)
    client._running = False
    thread.join(timeout=2.0)

    assert [t for b in loop.batches for t, _ in b] == ["depth.A", "depth.C"]


def test_one_failing_event_does_not_stop_the_rest_of_the_batch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Each event used to be its own loop callback, isolated from the others."""
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
        client = EngineClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", MagicMock())
    seen: list[str] = []

    def handle(topic: str, payload: dict[str, Any]) -> None:
        if topic == "boom":
            raise RuntimeError("bad event")
        seen.append(topic)

    with patch.object(client, "_handle_event", side_effect=handle):
        client._handle_events([("a", {}), ("boom", {}), ("c", {})])

    assert seen == ["a", "c"]
    assert "boom" in caplog.text


# ---------------------------------------------------------------------------
# all_orders filters
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[EngineClient]:
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
        yield EngineClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", MagicMock())


def test_all_orders_filters_case_insensitively(client: EngineClient) -> None:
    for gid, oid, sym in (
        ("GW01", "A", "AAPL"),
        ("GW01", "B", "MSFT"),
        ("GW02", "C", "AAPL"),
    ):
        client._handle_event(
            f"order.ack.{gid}", {"order_id": oid, "accepted": True, "symbol": sym}
        )
    client._handle_event(
        "order.fill.GW02",
        {
            "order_id": "C",
            "status": "FILLED",
            "symbol": "AAPL",
            "fill_qty": 1,
            "fill_price": 1.0,
            "side": "BUY",
        },
    )

    def ids(**kw: str) -> set[str]:
        return {o["order_id"] for o in client.all_orders(**kw)}

    assert ids() == {"A", "B", "C"}
    assert ids(symbol="aapl") == {"A", "C"}
    assert ids(gateway_id="gw01") == {"A", "B"}
    assert ids(status="new") == {"A", "B"}
    assert ids(symbol="AAPL", status="FILLED") == {"C"}
    # The owner is still added on the way out.
    assert {o["gateway_id"] for o in client.all_orders(gateway_id="GW02")} == {"GW02"}


def test_filtered_orders_are_copies(client: EngineClient) -> None:
    client._handle_event(
        "order.ack.GW01", {"order_id": "A", "accepted": True, "symbol": "AAPL"}
    )
    client.all_orders(status="NEW")[0]["status"] = "MUTATED"
    assert client.get_caches("GW01").orders["A"]["status"] == "NEW"
