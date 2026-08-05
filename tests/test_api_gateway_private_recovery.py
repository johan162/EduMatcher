"""Private-event recovery: group ids, the post-auth snapshot, and stream_seq.

Together these remove the reconnect dance the terminal previously had to do —
stitching order state together from `/orders`, `/history/orders` and
best-effort live events, with no way to tell what it had missed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.routers import ws
from edumatcher.models.message import (
    GROUP_ID_FIELDS,
    decode,
    group_ids,
    make_ack_msg,
    make_cancelled_msg,
    make_expired_msg,
    make_fill_msg,
)


@pytest.fixture
def client() -> Iterator[EngineClient]:
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


# ---------------------------------------------------------------------------
# Group ids on order events
# ---------------------------------------------------------------------------

COMBO_LEG = {
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "DAY",
    "quantity": 100,
    "price": 150.0,
    "combo_parent_id": "CMB-1",
    "leg_index": 0,
}

PLAIN_ORDER = {
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "DAY",
    "quantity": 100,
    "price": 150.0,
}


def _payload(frames: list[bytes]) -> dict[str, Any]:
    return decode(frames)[1]


def test_group_ids_extracts_only_what_is_present() -> None:
    assert group_ids(None) == {}
    assert group_ids(PLAIN_ORDER) == {}
    assert group_ids(COMBO_LEG) == {"combo_parent_id": "CMB-1", "leg_index": 0}
    assert group_ids({"oco_group_id": "OCO-9"}) == {"oco_group_id": "OCO-9"}


def test_a_zero_leg_index_survives() -> None:
    """leg_index 0 is falsy but meaningful — it is the first leg, not absent."""
    assert group_ids({"leg_index": 0}) == {"leg_index": 0}


def test_ack_carries_group_ids() -> None:
    payload = _payload(make_ack_msg("GW01", "ORD-1", True, order=COMBO_LEG))
    assert payload["combo_parent_id"] == "CMB-1"
    assert payload["leg_index"] == 0


def test_fill_carries_group_ids() -> None:
    payload = _payload(
        make_fill_msg("GW01", "ORD-1", 50, 150.0, 50, "PARTIAL", order=COMBO_LEG)
    )
    assert payload["combo_parent_id"] == "CMB-1"


def test_cancel_and_expiry_carry_group_ids() -> None:
    cancelled = _payload(make_cancelled_msg("GW01", "ORD-1", order=COMBO_LEG))
    expired = _payload(make_expired_msg("GW01", "ORD-1", order=COMBO_LEG))
    assert cancelled["combo_parent_id"] == "CMB-1"
    assert expired["combo_parent_id"] == "CMB-1"


def test_an_ordinary_order_gains_no_empty_fields() -> None:
    """Omitted, not null: a single order should not grow four fields to say
    it belongs to nothing."""
    for frames in (
        make_ack_msg("GW01", "ORD-1", True, order=PLAIN_ORDER),
        make_fill_msg("GW01", "ORD-1", 1, 1.0, 0, "FILLED", order=PLAIN_ORDER),
        make_cancelled_msg("GW01", "ORD-1", order=PLAIN_ORDER),
        make_expired_msg("GW01", "ORD-1", order=PLAIN_ORDER),
    ):
        payload = _payload(frames)
        assert not (set(GROUP_ID_FIELDS) & set(payload)), payload


def test_events_without_an_order_are_unchanged() -> None:
    """The order argument stays optional, so existing callers still work."""
    assert _payload(make_cancelled_msg("GW01", "ORD-1")) == {"order_id": "ORD-1"}
    assert _payload(make_ack_msg("GW01", "ORD-1", True)) == {
        "order_id": "ORD-1",
        "accepted": True,
        "reason": "",
    }


def test_client_tag_and_group_ids_coexist() -> None:
    payload = _payload(
        make_cancelled_msg(
            "GW01", "ORD-1", client_tag="my-tag", order={"oco_group_id": "OCO-2"}
        )
    )
    assert payload["client_tag"] == "my-tag"
    assert payload["oco_group_id"] == "OCO-2"


# ---------------------------------------------------------------------------
# Per-gateway stream sequence
# ---------------------------------------------------------------------------


def test_stream_seq_is_contiguous_across_a_gateways_topics(
    client: EngineClient,
) -> None:
    """The private socket applies no filtering, so one counter across every
    topic is contiguous — which per-topic seq alone cannot give a client."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=16)
    client.add_sink("GW01", queue)

    client._handle_event("order.ack.GW01", {"order_id": "A"})
    client._handle_event("order.fill.GW01", {"order_id": "A"})
    client._handle_event("order.cancelled.GW01", {"order_id": "A"})

    events = [queue.get_nowait() for _ in range(3)]
    assert [e["stream_seq"] for e in events] == [1, 2, 3]
    # Per-topic seq restarts per topic; both numbers are present.
    assert [e["seq"] for e in events] == [1, 1, 1]


def test_stream_seq_is_per_gateway(client: EngineClient) -> None:
    q1: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
    client.add_sink("GW01", q1)

    client._handle_event("order.ack.GW01", {"order_id": "A"})
    client._handle_event("order.ack.GW02", {"order_id": "B"})
    client._handle_event("order.ack.GW01", {"order_id": "C"})

    assert [e["stream_seq"] for e in [q1.get_nowait(), q1.get_nowait()]] == [1, 2]
    assert client.stream_seq("GW02") == 1


def test_market_data_has_no_stream_seq(client: EngineClient) -> None:
    """Subscribers filter market data, so a stream-wide counter there would
    show phantom gaps. It is deliberately absent."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
    client.add_market_data_sink(queue)
    client._handle_event("trade.executed", {"symbol": "AAPL"})
    assert "stream_seq" not in queue.get_nowait()


# ---------------------------------------------------------------------------
# The post-auth snapshot
# ---------------------------------------------------------------------------


class FakeWebSocket:
    def __init__(self, messages: list[Any], engine: Any) -> None:
        self.messages = messages
        self.sent: list[Any] = []
        self.closed: list[int] = []
        self.app = SimpleNamespace(state=SimpleNamespace(engine=engine))

    async def accept(self) -> None:
        return None

    async def receive_json(self) -> Any:
        if not self.messages:
            raise WebSocketDisconnect()
        return self.messages.pop(0)

    async def send_json(self, value: Any) -> None:
        self.sent.append(json.loads(json.dumps(value)))  # must be serialisable

    async def close(self, code: int) -> None:
        self.closed.append(code)


@pytest.mark.anyio
async def test_snapshot_follows_authentication() -> None:
    """Drives the real private_events handler rather than reproducing it, so
    the assertions cannot pass against a handler that no longer sends this."""
    from contextlib import suppress

    from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
    from edumatcher.api_gateway.sessions import SessionRegistry

    # Built on the *running* loop: EngineClient creates futures on the loop it
    # was given, and authenticate() awaits one.
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
        client = EngineClient(
            "tcp://127.0.0.1:1", "tcp://127.0.0.1:2", asyncio.get_running_loop()
        )
    # The gateway handshake is not what this test is about.
    client._authenticated.add("GW01")

    cache = client.get_caches("GW01")
    cache.orders["ORD-1"] = {"order_id": "ORD-1", "status": "NEW"}
    cache.positions["AAPL"] = 100

    config = ApiGatewayConfig(credentials=(ApiCredential("key", "GW01", "test"),))
    socket = FakeWebSocket([{"api_key": "key"}], client)
    socket.app.state.sessions = SessionRegistry.from_config(config)
    socket.app.state.config = config

    task = asyncio.create_task(ws.private_events(socket))  # type: ignore[arg-type]
    for _ in range(50):
        if len(socket.sent) >= 2:
            break
        await asyncio.sleep(0)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    assert [m["type"] for m in socket.sent] == ["authenticated", "orders.snapshot"]
    auth, snapshot = socket.sent
    assert auth["gateway_id"] == "GW01"
    assert "stream_seq" in auth
    assert snapshot["data"]["orders"] == [{"order_id": "ORD-1", "status": "NEW"}]
    assert snapshot["data"]["positions"] == {"AAPL": 100}
    # The snapshot names the point it is accurate as of.
    assert snapshot["stream_seq"] == client.stream_seq("GW01")


def test_the_cache_survives_a_disconnect(client: EngineClient) -> None:
    """What makes the snapshot possible at all: removing a sink does not
    discard the gateway's accumulated order state."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
    client.add_sink("GW01", queue)
    client._handle_event("order.ack.GW01", {"order_id": "ORD-1", "accepted": True})
    client.remove_sink("GW01", queue)

    assert "ORD-1" in client.get_caches("GW01").orders


def test_registering_the_sink_before_the_snapshot_cannot_lose_events(
    client: EngineClient,
) -> None:
    """Ordering matters: an event landing between snapshot and subscribe would
    be lost, and the snapshot would look complete. Registering first makes the
    worst case a duplicate instead, which is harmless for idempotent state.
    """
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
    client.add_sink("GW01", queue)  # as private_events() does
    client._handle_event("order.ack.GW01", {"order_id": "ORD-1", "accepted": True})
    snapshot = list(client.get_caches("GW01").orders.values())

    # The same order is both in the snapshot and delivered live.
    assert snapshot[0]["order_id"] == "ORD-1"
    assert queue.get_nowait()["data"]["order_id"] == "ORD-1"
