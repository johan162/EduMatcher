"""Engine silence is a 503, never a role verdict (API gateway review C2, Q4).

``resolve_role`` used to answer ``TRADER`` when the engine did not reply in
time: an ADMIN got ``403 ROLE_DENIED`` (and the audit trail recorded it), and
the clearing routes narrowed an ADMIN to its own gateway in a ``200``. The
answer was also cached for the life of the process, so a role changed by an
engine restart was never seen.
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.api_gateway.config import TimeoutConfig
from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.routers import ws
from edumatcher.models.generated.system import TOPIC_STARTUP_RECOVERY
from edumatcher.models.message import decode, make_gateways_request_msg
from tests.api_gateway_harness import TRADER_KEY, call, make_app
from tests.clearing_api_fixture import build_venue

pytestmark = pytest.mark.anyio

GATEWAYS_REQUEST = decode(make_gateways_request_msg("GW01"))[0]


class _Refusals:
    def __init__(self) -> None:
        self.reported: list[tuple[str, ...]] = []

    def report(self, *args: str) -> None:
        self.reported.append(args)


def _engine() -> EngineClient:
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
    return engine


def _app(engine: EngineClient) -> Any:
    app = make_app(engine)
    app.state.config = dataclasses.replace(
        app.state.config,
        timeouts=TimeoutConfig(
            engine_auth_sec=0.05, engine_reply_sec=0.05, wait_ack_sec=0.05
        ),
    )
    app.state.rejects = _Refusals()
    return app


def _role_requests(engine: EngineClient) -> int:
    push: Any = engine._push
    return sum(
        decode(c.args[0])[0] == GATEWAYS_REQUEST
        for c in push.send_multipart.call_args_list
    )


def _answer_role(engine: EngineClient, role: str) -> None:
    engine._handle_event(
        "system.gateways.GW01", {"gateways": [{"id": "GW01", "role": role}]}
    )


async def test_an_admin_route_answers_503_when_the_engine_is_silent() -> None:
    engine = _engine()
    app = _app(engine)

    status, _, body = await call(app, "POST", "/api/v1/admin/market/halt")

    assert (status, body["error"]["code"]) == (503, "ENGINE_UNAVAILABLE")
    assert app.state.rejects.reported == []


async def test_clearing_answers_503_not_the_callers_own_rows(tmp_path: Path) -> None:
    venue = build_venue(tmp_path)
    engine = _engine()
    app = _app(engine)
    app.state.config = dataclasses.replace(
        app.state.config, clearing_db=venue.clearing_db, eod_db=venue.eod_db
    )

    status, _, body = await call(app, "GET", "/api/v1/clearing/positions")

    assert (status, body["error"]["code"]) == (503, "ENGINE_UNAVAILABLE")


async def test_an_unanswered_lookup_is_not_cached() -> None:
    engine = _engine()
    with pytest.raises(Exception):
        await engine.resolve_role("GW01", 0.05)
    assert _role_requests(engine) == 1

    lookup = asyncio.create_task(engine.resolve_role("GW01", 1.0))
    await asyncio.sleep(0)
    _answer_role(engine, "ADMIN")
    assert await lookup == "ADMIN"
    assert _role_requests(engine) == 2


async def test_an_engine_restart_clears_the_role_cache() -> None:
    engine = _engine()
    lookup = asyncio.create_task(engine.resolve_role("GW01", 1.0))
    await asyncio.sleep(0)
    _answer_role(engine, "TRADER")
    assert await lookup == "TRADER"

    engine._handle_event(TOPIC_STARTUP_RECOVERY, {})
    lookup = asyncio.create_task(engine.resolve_role("GW01", 1.0))
    await asyncio.sleep(0)
    _answer_role(engine, "ADMIN")

    assert await lookup == "ADMIN"
    assert _role_requests(engine) == 2


async def test_a_trader_on_an_admin_route_is_still_role_denied() -> None:
    engine = _engine()
    app = _app(engine)
    app.state.config = dataclasses.replace(
        app.state.config, timeouts=TimeoutConfig(engine_reply_sec=1.0)
    )

    reply = asyncio.create_task(call(app, "POST", "/api/v1/admin/market/halt"))
    for _ in range(200):
        if _role_requests(engine):
            break
        await asyncio.sleep(0.005)
    _answer_role(engine, "TRADER")
    status, _, body = await asyncio.wait_for(reply, timeout=2.0)

    assert (status, body["error"]["code"]) == (403, "ROLE_DENIED")
    assert [r[0] for r in app.state.rejects.reported] == ["ROLE_DENIED"]


class _AdminSocket:
    """An ADMIN key opening an admin socket; the client stays connected."""

    def __init__(self, engine: EngineClient, app: Any) -> None:
        self.messages: list[Any] = [{"api_key": TRADER_KEY}]
        self.sent: list[Any] = []
        self.closed: list[int] = []
        self.app = SimpleNamespace(state=app.state)

    async def accept(self) -> None:
        return None

    async def receive_json(self) -> Any:
        return self.messages.pop(0)

    async def receive(self) -> dict[str, Any]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def send_json(self, value: Any) -> None:
        self.sent.append(value)

    async def close(self, code: int) -> None:
        self.closed.append(code)


@pytest.mark.parametrize("handler", ["admin_monitor", "admin_sim"])
async def test_an_admin_socket_closes_1013_when_the_role_is_unconfirmed(
    handler: str,
) -> None:
    engine = _engine()
    app = _app(engine)
    socket = _AdminSocket(engine, app)

    await asyncio.wait_for(getattr(ws, handler)(socket), timeout=1.0)

    assert socket.closed == [1013]
    assert not any(
        m.get("data", {}).get("message") == "ADMIN role required" for m in socket.sent
    )
