"""A WebSocket the client has closed ends its handler (API gateway review H2).

The private and admin sockets used to read nothing after authentication, so a
client that closed was noticed only when the next event for it failed to
send. An idle trader's handler waited forever, and uvicorn's graceful shutdown
waited with it: SIGTERM did not stop the process.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Generator
from contextlib import contextmanager, suppress
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from edumatcher.api_gateway.config import (
    ApiCredential,
    ApiGatewayConfig,
    TimeoutConfig,
)
from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.routers import ws
from edumatcher.api_gateway.sessions import SessionRegistry
from edumatcher.api_gateway.sim_client import SimClient
from edumatcher.models.message import (
    decode,
    make_orders_msg,
    make_position_snapshot_msg,
)
from tests.api_gateway_harness import TRADER_KEY, make_app

pytestmark = pytest.mark.anyio

CONFIG = ApiGatewayConfig(
    credentials=(ApiCredential("key", "GW01", "test"),),
    timeouts=TimeoutConfig(engine_auth_sec=0.05, engine_reply_sec=0.05),
)


@contextmanager
def _patched_sockets() -> Generator[None]:
    with (
        patch(
            "edumatcher.api_gateway.engine_client.make_pusher",
            return_value=MagicMock(closed=False),
        ),
        patch(
            "edumatcher.api_gateway.engine_client.make_subscriber",
            return_value=MagicMock(),
        ),
        patch(
            "edumatcher.api_gateway.sim_client.make_subscriber",
            return_value=MagicMock(),
        ),
    ):
        yield


def _engine(*, admin: bool = False) -> EngineClient:
    """An EngineClient on the running loop, GW01 already authenticated."""
    with _patched_sockets():
        engine = EngineClient(
            "tcp://127.0.0.1:1", "tcp://127.0.0.1:2", asyncio.get_running_loop()
        )
    engine._authenticated.add("GW01")
    if admin:
        engine._role_cache["GW01"] = "ADMIN"
    return engine


def _sim() -> SimClient:
    with _patched_sockets():
        return SimClient("tcp://127.0.0.1:3", asyncio.get_running_loop())


class ClosingWebSocket:
    """Authenticates, then the client closes: ``receive`` reports it."""

    def __init__(self, engine: EngineClient, sim: SimClient | None = None) -> None:
        self.messages: list[Any] = [{"api_key": "key"}]
        self.sent: list[Any] = []
        self.closed: list[int] = []
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                engine=engine,
                sim=sim,
                config=CONFIG,
                sessions=SessionRegistry.from_config(CONFIG),
            )
        )

    async def accept(self) -> None:
        return None

    async def receive_json(self) -> Any:
        if not self.messages:
            raise WebSocketDisconnect()
        return self.messages.pop(0)

    async def receive(self) -> dict[str, Any]:
        return {"type": "websocket.disconnect", "code": 1000}

    async def send_json(self, value: Any) -> None:
        self.sent.append(json.loads(json.dumps(value)))

    async def close(self, code: int) -> None:
        self.closed.append(code)


async def test_closed_private_socket_ends_its_handler() -> None:
    engine = _engine()
    socket = ClosingWebSocket(engine)

    await asyncio.wait_for(ws.private_events(socket), timeout=1.0)  # type: ignore[arg-type]

    assert not engine._sinks["GW01"]


async def test_closed_admin_sim_socket_ends_its_handler() -> None:
    engine = _engine(admin=True)
    sim = _sim()
    socket = ClosingWebSocket(engine, sim)

    await asyncio.wait_for(ws.admin_sim(socket), timeout=1.0)  # type: ignore[arg-type]

    assert [m["type"] for m in socket.sent] == ["authenticated", "sim.snapshot"]
    assert not sim._sinks


async def test_closed_admin_monitor_socket_ends_its_handler() -> None:
    engine = _engine(admin=True)
    socket = ClosingWebSocket(engine)

    await asyncio.wait_for(ws.admin_monitor(socket), timeout=1.0)  # type: ignore[arg-type]

    assert not engine._admin_sinks


async def test_ws_sessions_gauge_returns_to_zero_after_close() -> None:
    """Through the real app and MetricsMiddleware, not the handler alone."""
    engine = _engine()
    app = make_app(engine)
    app.state.sim = _sim()
    incoming: list[dict[str, Any]] = [
        {"type": "websocket.connect"},
        {"type": "websocket.receive", "text": json.dumps({"api_key": TRADER_KEY})},
    ]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        if incoming:
            return incoming.pop(0)
        return {"type": "websocket.disconnect", "code": 1000}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "path": "/api/v1/ws/private",
        "raw_path": b"/api/v1/ws/private",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "server": ("test", 80),
        "client": ("client", 1),
        "subprotocols": [],
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=1.0)

    assert app.state.health_metrics.ws_sessions["private"] == 0
    assert not engine._sinks["GW01"]


class LiveWebSocket(ClosingWebSocket):
    """A client that stays connected until told to close."""

    def __init__(self, engine: EngineClient, fail_send_after: int = 0) -> None:
        super().__init__(engine)
        self.gone = asyncio.Event()
        self.fail_send_after = fail_send_after

    async def receive(self) -> dict[str, Any]:
        await self.gone.wait()
        return {"type": "websocket.disconnect", "code": 1000}

    async def send_json(self, value: Any) -> None:
        if self.fail_send_after and len(self.sent) >= self.fail_send_after:
            raise WebSocketDisconnect(code=1006)
        await super().send_json(value)


async def _wait_for(predicate: Any) -> None:
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never became true")


async def _answer_snapshot(engine: EngineClient) -> None:
    """Play the engine: answer the private snapshot's two requests."""
    push: Any = engine._push
    await _wait_for(lambda: push.send_multipart.call_count >= 2)
    engine._handle_event(*decode(make_position_snapshot_msg("GW01", [])))
    engine._handle_event(*decode(make_orders_msg("GW01", [])))


async def test_live_private_socket_receives_events_in_order() -> None:
    engine = _engine()
    socket = LiveWebSocket(engine)
    task = asyncio.create_task(ws.private_events(socket))  # type: ignore[arg-type]
    await _answer_snapshot(engine)
    await _wait_for(lambda: len(socket.sent) >= 2)

    for order_id in ("A", "B", "C"):
        engine._handle_event("order.ack.GW01", {"order_id": order_id})
    await _wait_for(lambda: len(socket.sent) >= 5)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    assert [m["data"]["order_id"] for m in socket.sent[2:]] == ["A", "B", "C"]
    assert not engine._sinks["GW01"]


async def test_send_failure_still_removes_the_sink() -> None:
    engine = _engine()
    socket = LiveWebSocket(engine, fail_send_after=2)
    task = asyncio.create_task(ws.private_events(socket))  # type: ignore[arg-type]
    await _answer_snapshot(engine)
    await _wait_for(lambda: len(socket.sent) >= 2)

    engine._handle_event("order.ack.GW01", {"order_id": "A"})
    await asyncio.wait_for(task, timeout=1.0)

    assert not engine._sinks["GW01"]
