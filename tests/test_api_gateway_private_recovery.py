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
    make_orders_msg,
    make_position_snapshot_msg,
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
    "tick_decimals": 2,
    "quantity": 100,
    "price_ticks": 150.0,
    "combo_parent_id": "CMB-1",
    "leg_index": 0,
}

PLAIN_ORDER = {
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "DAY",
    "tick_decimals": 2,
    "quantity": 100,
    "price_ticks": 150.0,
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
    # is_seed is always present (default false, not omit_when_none) -- see
    # ../docs/books/operator-guide/part-6-observe-and-recover/020-audit-trail.md's audit-completeness section -- so it
    # rides along even when no order detail was supplied.
    ack = _payload(make_ack_msg("GW01", "ORD-1", True))
    assert isinstance(ack.pop("ts_ns"), int)  # the engine clock, A7
    assert ack == {
        "order_id": "ORD-1",
        "accepted": True,
        "reason": "",
        "is_seed": False,
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

    async def receive(self) -> dict[str, Any]:
        await asyncio.Event().wait()  # the client stays connected
        raise AssertionError("unreachable")

    async def send_json(self, value: Any) -> None:
        self.sent.append(json.loads(json.dumps(value)))  # must be serialisable

    async def close(self, code: int) -> None:
        self.closed.append(code)


class _Desk:
    """A real private_events handler on a real EngineClient, engine faked.

    The engine's replies are fed through ``_handle_event`` from the real
    message builders, as the receive thread would deliver them.
    """

    def __init__(self, reply_sec: float = 1.0) -> None:
        from edumatcher.api_gateway.config import (
            ApiCredential,
            ApiGatewayConfig,
            TimeoutConfig,
        )
        from edumatcher.api_gateway.sessions import SessionRegistry

        # Built on the *running* loop: EngineClient creates futures on it.
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
            self.engine = EngineClient(
                "tcp://127.0.0.1:1", "tcp://127.0.0.1:2", asyncio.get_running_loop()
            )
        # The gateway handshake is not what these tests are about.
        self.engine._authenticated.add("GW01")
        config = ApiGatewayConfig(
            credentials=(ApiCredential("key", "GW01", "test"),),
            timeouts=TimeoutConfig(engine_reply_sec=reply_sec),
        )
        self.socket = FakeWebSocket([{"api_key": "key"}], self.engine)
        self.socket.app.state.sessions = SessionRegistry.from_config(config)
        self.socket.app.state.config = config
        self.task: asyncio.Task[None] | None = None

    async def open(self) -> None:
        self.task = asyncio.create_task(ws.private_events(self.socket))  # type: ignore[arg-type]
        await self.until(
            lambda: self.requested() >= 2
            or bool(self.socket.closed)
            or "orders.snapshot" in self.types()
        )

    def requested(self) -> int:
        push: Any = self.engine._push
        return int(push.send_multipart.call_count)

    def deliver(self, frames: list[bytes]) -> None:
        self.engine._handle_event(*decode(frames))

    async def until(self, predicate: Any) -> None:
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(0.005)
        raise AssertionError("condition never became true")

    async def close(self) -> None:
        from contextlib import suppress

        assert self.task is not None
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task

    def types(self) -> list[str]:
        return [m["type"] for m in self.socket.sent]

    def snapshot(self) -> dict[str, Any]:
        (snap,) = [m for m in self.socket.sent if m["type"] == "orders.snapshot"]
        return snap


RESTING = {
    "id": "ORD-R",
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "tif": "GTC",
    "quantity": 5,
    "remaining_qty": 5,
    "gateway_id": "GW01",
    "ts_ns": 1,
    "status": "NEW",
    "tick_decimals": 2,
    "price": 20.0,
}
AAPL_PLUS_10 = [{"symbol": "AAPL", "net_qty": 10, "avg_cost": 20.0}]
BUY_5_AAPL = make_fill_msg(
    "GW01", "ORD-F", 5, 20.0, 0, "FILLED", order={"symbol": "AAPL", "side": "BUY"}
)


@pytest.mark.anyio
async def test_snapshot_is_the_engines_state() -> None:
    """H1: a fresh process (empty cache) still reports the engine's resting
    order and position."""
    desk = _Desk()
    await desk.open()
    desk.deliver(make_position_snapshot_msg("GW01", AAPL_PLUS_10))
    desk.deliver(make_orders_msg("GW01", [RESTING]))
    await desk.until(lambda: "orders.snapshot" in desk.types())
    await desk.close()

    assert desk.types()[:2] == ["authenticated", "orders.snapshot"]
    snapshot = desk.snapshot()
    assert snapshot["gateway_id"] == "GW01"
    assert [o["order_id"] for o in snapshot["data"]["orders"]] == ["ORD-R"]
    assert snapshot["data"]["positions"] == {"AAPL": 10}


@pytest.mark.anyio
async def test_snapshot_is_cut_at_the_orders_reply() -> None:
    """The snapshot's stream_seq is the order.orders reply's. A fill between
    the position snapshot and that reply is in the snapshot's positions and is
    not sent after it; a later fill is sent live with a higher stream_seq."""
    desk = _Desk()
    await desk.open()
    desk.deliver(make_position_snapshot_msg("GW01", AAPL_PLUS_10))
    desk.deliver(BUY_5_AAPL)
    desk.deliver(make_orders_msg("GW01", [RESTING]))
    reply_seq = desk.engine.stream_seq("GW01")
    desk.deliver(BUY_5_AAPL)
    await desk.until(lambda: len(desk.socket.sent) >= 3)
    await desk.close()

    snapshot = desk.snapshot()
    assert snapshot["stream_seq"] == reply_seq
    assert snapshot["data"]["positions"] == {"AAPL": 15}
    live = desk.socket.sent[2:]
    assert [(m["type"], m["stream_seq"]) for m in live] == [
        ("order.fill", reply_seq + 1)
    ]


@pytest.mark.anyio
async def test_an_earlier_orders_reply_is_not_the_cut() -> None:
    """An order.orders reply to someone else's request, published before the
    position snapshot, cannot be the cut: positions would then be newer than
    the orders."""
    desk = _Desk()
    await desk.open()
    desk.deliver(make_orders_msg("GW01", []))
    desk.deliver(make_position_snapshot_msg("GW01", AAPL_PLUS_10))
    desk.deliver(make_orders_msg("GW01", [RESTING]))
    await desk.until(lambda: "orders.snapshot" in desk.types())
    await desk.close()

    assert [o["order_id"] for o in desk.snapshot()["data"]["orders"]] == ["ORD-R"]
    assert desk.snapshot()["stream_seq"] == desk.engine.stream_seq("GW01")


@pytest.mark.anyio
async def test_cached_terminal_orders_stay_in_the_snapshot() -> None:
    desk = _Desk()
    cache = desk.engine.get_caches("GW01")
    cache.orders["ORD-DONE"] = {"order_id": "ORD-DONE", "status": "FILLED"}
    # Working in the cache but not resting at the engine: a missed terminal
    # event. The engine is the truth, so it is not reported as working.
    cache.orders["ORD-GONE"] = {"order_id": "ORD-GONE", "status": "NEW"}
    await desk.open()
    desk.deliver(make_position_snapshot_msg("GW01", []))
    desk.deliver(make_orders_msg("GW01", [RESTING]))
    await desk.until(lambda: "orders.snapshot" in desk.types())
    await desk.close()

    orders = {o["order_id"]: o for o in desk.snapshot()["data"]["orders"]}
    assert set(orders) == {"ORD-R", "ORD-DONE"}
    assert orders["ORD-R"]["status"] == "NEW"
    assert orders["ORD-R"]["client_tag"] is None


@pytest.mark.anyio
async def test_engine_silent_closes_with_try_again_later() -> None:
    desk = _Desk(reply_sec=0.05)
    await desk.open()
    await desk.until(lambda: bool(desk.socket.closed))
    await desk.close()

    assert "orders.snapshot" not in desk.types()
    assert desk.socket.closed == [1013]
    assert not desk.engine._sinks["GW01"]
    assert desk.engine.engine_timeouts == 1


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
