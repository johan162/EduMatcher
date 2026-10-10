"""ADMIN-only access to pm-market-sim's true values (WP-D6); public news (WP-E5)."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, WebSocketDisconnect

from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.api_gateway.routers import admin, reference, ws
from edumatcher.api_gateway.sessions import Session, SessionRegistry
from edumatcher.api_gateway.sim_client import SimClient

VALUE = {"seq": 3, "ts_ns": 1, "values": [{"symbol": "AAPL", "value": 101.5}]}
STATE = {"state": "RUNNING", "session": "CONTINUOUS", "seq": 3}
NEWS = {
    "id": "N1",
    "ts_ns": 1,
    "scope": "SYMBOL",
    "targets": ["AAPL"],
    "kind": "EARNINGS",
    "status": "RUMOUR",
    "headline": "AAPL said to beat",
    "sentiment": 0.6,
    "credibility": 0.7,
    "related_id": "",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Engine:
    def __init__(self, role: str) -> None:
        self.role = role

    async def resolve_role(self, gateway_id: str, timeout: float) -> str:
        return self.role


def _sim() -> SimClient:
    with patch(
        "edumatcher.api_gateway.sim_client.make_subscriber", return_value=MagicMock()
    ):
        return SimClient("tcp://127.0.0.1:1", asyncio.get_running_loop())


def _request(role: str, sim: SimClient) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                engine=_Engine(role), config=ApiGatewayConfig(), sim=sim
            )
        )
    )


@pytest.mark.anyio
async def test_admin_sees_the_latest_values() -> None:
    sim = _sim()
    request = _request("ADMIN", sim)
    session = Session(api_key="k", gateway_id="OPS01", description="")
    assert (await admin.market_sim(request, session))["available"] is False
    sim.handle_event("sim.state", STATE)
    sim.handle_event("sim.value", VALUE)
    body = await admin.market_sim(request, session)
    assert body == {"available": True, "state": STATE, "values": VALUE}


@pytest.mark.anyio
async def test_a_trader_gets_403() -> None:
    request = _request("TRADER", _sim())
    with pytest.raises(HTTPException) as exc:
        await admin.market_sim(
            request, Session(api_key="k", gateway_id="TRADER01", description="")
        )
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_a_read_only_key_gets_403() -> None:
    with pytest.raises(HTTPException) as exc:
        await admin.market_sim(
            _request("ADMIN", _sim()),
            Session(api_key="k", gateway_id=None, description=""),
        )
    assert exc.value.status_code == 403


class _Socket:
    def __init__(self, key: str, role: str, sim: SimClient) -> None:
        self.messages: list[Any] = [{"api_key": key}]
        self.sent: list[Any] = []
        self.closed: list[int] = []
        config = ApiGatewayConfig(
            credentials=(
                ApiCredential("admin-key", "OPS01", ""),
                ApiCredential("trader-key", "TRADER01", ""),
            )
        )
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                engine=_Engine(role),
                config=config,
                sessions=SessionRegistry.from_config(config),
                sim=sim,
            )
        )

    async def accept(self) -> None:
        return None

    async def receive_json(self) -> Any:
        if not self.messages:
            raise WebSocketDisconnect()
        return self.messages.pop(0)

    async def send_json(self, value: Any) -> None:
        self.sent.append(json.loads(json.dumps(value)))

    async def close(self, code: int) -> None:
        self.closed.append(code)


@pytest.mark.anyio
async def test_admin_stream_snapshot_then_events() -> None:
    sim = _sim()
    sim.handle_event("sim.state", STATE)
    socket = _Socket("admin-key", "ADMIN", sim)
    task = asyncio.create_task(ws.admin_sim(socket))  # type: ignore[arg-type]
    for _ in range(50):
        if len(socket.sent) >= 2:
            break
        await asyncio.sleep(0.01)
    sim.handle_event("sim.value", VALUE)
    for _ in range(50):
        if len(socket.sent) >= 3:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    assert [m["type"] for m in socket.sent] == [
        "authenticated",
        "sim.snapshot",
        "sim.value",
    ]
    assert socket.sent[1]["data"]["state"] == STATE
    assert socket.sent[2]["data"] == VALUE


@pytest.mark.anyio
async def test_trader_stream_is_refused() -> None:
    socket = _Socket("trader-key", "TRADER", _sim())
    await ws.admin_sim(socket)  # type: ignore[arg-type]
    assert socket.sent == [
        {"type": "error", "data": {"message": "ADMIN role required"}}
    ]
    assert socket.closed


@pytest.mark.anyio
async def test_news_is_kept_and_any_key_reads_it() -> None:
    sim = _sim()
    sim.sectors = {"TECH": frozenset({"MSFT", "AAPL"})}
    for i in range(3):
        sim.handle_event("news.event", {**NEWS, "id": f"N{i}"})
    read_only = Session(api_key="k", gateway_id=None, description="")
    body = await reference.news(_request("TRADER", sim), read_only, limit=2)
    assert [n["id"] for n in body["news"]] == ["N1", "N2"]
    assert body["sectors"] == {"TECH": ["AAPL", "MSFT"]}


@pytest.mark.anyio
async def test_news_goes_to_news_sinks_only() -> None:
    sim = _sim()
    admin_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    news_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    sim.add_sink(admin_q)
    sim.add_news_sink(news_q)
    sim.handle_event("sim.value", VALUE)
    sim.handle_event("news.event", NEWS)
    assert [admin_q.get_nowait()["type"]] == ["sim.value"] and admin_q.empty()
    event = news_q.get_nowait()
    assert (event["type"], event["topic"], event["data"]) == (
        "news",
        "news.event",
        NEWS,
    )
    assert news_q.empty()
    sim.remove_news_sink(news_q)
    sim.handle_event("news.event", NEWS)
    assert news_q.empty()


@pytest.mark.anyio
async def test_market_data_socket_gets_news_without_subscribing() -> None:
    socket = _Socket("trader-key", "TRADER", _sim())
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    queue.put_nowait({"type": "news", "topic": "news.event", "data": NEWS})
    task = asyncio.create_task(
        ws._send_market_data(socket, queue, ws.Subscription())  # type: ignore[arg-type]
    )
    for _ in range(50):
        if socket.sent:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    assert socket.sent == [{"type": "news", "topic": "news.event", "data": NEWS}]
