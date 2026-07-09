from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.api_gateway.events import (
    gateway_from_topic,
    market_data_symbol,
    websocket_type,
)
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.routers import admin, reference, ws
from edumatcher.api_gateway.schemas import (
    CircuitBreakerResumeRequest,
    CircuitBreakerTriggerRequest,
    SessionTransitionRequest,
    SymbolCancelRequest,
)
from edumatcher.api_gateway.sessions import Session


class AdminFakeEngine:
    """Test double implementing the admin subset of EngineClient."""

    def __init__(self, role: str = "ADMIN", ack_accepted: bool = True) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.role = role
        self.ack_accepted = ack_accepted
        self.admin_sinks: list[Any] = []
        self.cache = SessionCaches()

    def get_caches(self, gateway_id: str) -> SessionCaches:
        self.calls.append(("get_caches", gateway_id))
        return self.cache

    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
        self.calls.append(("authenticate", gateway_id))
        return True, ""

    async def resolve_role(self, gateway_id: str, timeout: float) -> str:
        self.calls.append(("resolve_role", gateway_id))
        return self.role

    async def await_topic(self, topic: str, timeout: float) -> dict[str, Any]:
        return await self.await_event(topic, match=None, timeout=timeout)

    async def await_event(
        self, topic: str, match: dict[str, str] | None, timeout: float
    ) -> dict[str, Any]:
        self.calls.append(("await_event", (topic, match, timeout)))
        if topic.startswith("system.session_schedule."):
            return {"sessions_enabled": True, "schedule": {"pre_open": "09:00"}}
        if topic.startswith("system.gateways."):
            return {
                "gateways": [
                    {"id": "GW01", "role": "ADMIN", "connected": True},
                    {"id": "GW02", "role": "TRADER", "connected": False},
                ]
            }
        if topic.startswith("system.halt_status."):
            return {"halted": [{"symbol": "AAPL"}]}
        if topic.startswith("risk.symbol_halt_ack."):
            return {"accepted": self.ack_accepted, "symbol": "AAPL", "reason": "nope"}
        if topic.startswith("risk.symbol_resume_ack."):
            return {"accepted": self.ack_accepted, "symbol": "AAPL", "reason": "nope"}
        if topic.startswith("risk.cancel_symbol_ack."):
            return {
                "accepted": self.ack_accepted,
                "symbol": "AAPL",
                "reason": "nope",
                "cancelled_orders": 3,
            }
        return {"accepted": self.ack_accepted, "topic": topic}

    def send_session_transition(self, to_state: str) -> None:
        self.calls.append(("send_session_transition", to_state))

    def send_symbol_halt(self, gateway_id: str, symbol: str) -> None:
        self.calls.append(("send_symbol_halt", (gateway_id, symbol)))

    def send_symbol_resume(self, gateway_id: str, symbol: str) -> None:
        self.calls.append(("send_symbol_resume", (gateway_id, symbol)))

    def send_cancel_symbol(self, gateway_id: str, symbol: str) -> None:
        self.calls.append(("send_cancel_symbol", (gateway_id, symbol)))

    def send_disconnect(self, gateway_id: str, reason: str) -> None:
        self.calls.append(("send_disconnect", (gateway_id, reason)))

    def request_gateways(self, gateway_id: str) -> None:
        self.calls.append(("request_gateways", gateway_id))

    def request_session_schedule(self, gateway_id: str) -> None:
        self.calls.append(("request_session_schedule", gateway_id))

    def request_halt_status(self, gateway_id: str) -> None:
        self.calls.append(("request_halt_status", gateway_id))

    def add_admin_sink(self, queue: Any) -> None:
        self.admin_sinks.append(queue)

    def remove_admin_sink(self, queue: Any) -> None:
        if queue in self.admin_sinks:
            self.admin_sinks.remove(queue)


class TimeoutAdminEngine(AdminFakeEngine):
    async def await_event(
        self, topic: str, match: dict[str, str] | None, timeout: float
    ) -> dict[str, Any]:
        _ = (topic, match, timeout)
        raise TimeoutError("no reply")


def admin_request(engine: AdminFakeEngine, limiter: RateLimiter | None = None) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                engine=engine,
                config=ApiGatewayConfig(),
                rate_limiter=limiter or RateLimiter(100, 100),
            )
        )
    )


def admin_session() -> Session:
    return Session(api_key="key", gateway_id="GW01", description="admin")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_require_admin_allows_admin_role() -> None:
    engine = AdminFakeEngine(role="ADMIN")
    request = admin_request(engine)
    body = SessionTransitionRequest(to_state="CONTINUOUS")
    result = await admin.session_transition(body, request, admin_session())
    assert result == {"requested_state": "CONTINUOUS", "status": "PENDING"}
    assert ("send_session_transition", "CONTINUOUS") in engine.calls


@pytest.mark.anyio
async def test_require_admin_rejects_non_admin_role() -> None:
    engine = AdminFakeEngine(role="TRADER")
    request = admin_request(engine)
    body = SessionTransitionRequest(to_state="CONTINUOUS")
    with pytest.raises(HTTPException) as exc:
        await admin.session_transition(body, request, admin_session())
    assert exc.value.status_code == 403
    assert cast(dict[str, Any], exc.value.detail)["error"]["code"] == "ROLE_DENIED"


@pytest.mark.anyio
async def test_circuit_breaker_trigger_and_resume_accepted() -> None:
    engine = AdminFakeEngine(ack_accepted=True)
    request = admin_request(engine)
    session = admin_session()
    trigger = await admin.circuit_breaker_trigger(
        CircuitBreakerTriggerRequest(symbol="aapl"), request, session
    )
    assert trigger["accepted"] is True
    assert ("send_symbol_halt", ("GW01", "AAPL")) in engine.calls
    resume = await admin.circuit_breaker_resume(
        CircuitBreakerResumeRequest(symbol="aapl"), request, session
    )
    assert resume["accepted"] is True
    assert ("send_symbol_resume", ("GW01", "AAPL")) in engine.calls


@pytest.mark.anyio
async def test_circuit_breaker_rejected_ack_returns_403() -> None:
    engine = AdminFakeEngine(ack_accepted=False)
    request = admin_request(engine)
    with pytest.raises(HTTPException) as exc:
        await admin.circuit_breaker_trigger(
            CircuitBreakerTriggerRequest(symbol="AAPL"), request, admin_session()
        )
    assert exc.value.status_code == 403
    assert cast(dict[str, Any], exc.value.detail)["error"]["message"] == "nope"


@pytest.mark.anyio
async def test_kill_switch_symbol_returns_ack() -> None:
    engine = AdminFakeEngine(ack_accepted=True)
    request = admin_request(engine)
    result = await admin.kill_switch_symbol(
        SymbolCancelRequest(symbol="aapl"), request, admin_session()
    )
    assert result["cancelled_orders"] == 3
    assert ("send_cancel_symbol", ("GW01", "AAPL")) in engine.calls


@pytest.mark.anyio
async def test_halts_gateways_and_schedule_replies() -> None:
    engine = AdminFakeEngine()
    request = admin_request(engine)
    session = admin_session()
    halts = await admin.halt_status(request, session)
    assert halts["halted"][0]["symbol"] == "AAPL"
    gateways = await admin.list_gateways(request, session)
    assert len(gateways["gateways"]) == 2
    schedule = await admin.session_schedule(request, session)
    assert schedule["sessions_enabled"] is True


@pytest.mark.anyio
async def test_reply_timeout_returns_503() -> None:
    engine = TimeoutAdminEngine()
    request = admin_request(engine)
    with pytest.raises(HTTPException) as exc:
        await admin.halt_status(request, admin_session())
    assert exc.value.status_code == 503


@pytest.mark.anyio
async def test_gateway_disconnect_uppercases_id() -> None:
    engine = AdminFakeEngine()
    request = admin_request(engine)
    result = await admin.disconnect_gateway("gw02", request, admin_session())
    assert result == {"gateway_id": "GW02", "status": "DISCONNECTED"}
    assert ("send_disconnect", ("GW02", "admin disconnect")) in engine.calls


@pytest.mark.anyio
async def test_write_endpoint_rate_limited_returns_429() -> None:
    engine = AdminFakeEngine()
    request = admin_request(engine, limiter=RateLimiter(1, 1))
    session = admin_session()
    await admin.disconnect_gateway("gw02", request, session)
    with pytest.raises(HTTPException) as exc:
        await admin.disconnect_gateway("gw03", request, session)
    assert exc.value.status_code == 429


@pytest.mark.anyio
async def test_status_summary_admin_includes_role_and_count() -> None:
    engine = AdminFakeEngine(role="ADMIN")
    request = admin_request(engine)
    summary = await reference.status_summary(request, admin_session())
    assert summary["gateway_role"] == "ADMIN"
    # One gateway in the mock reply is connected.
    assert summary["gateway_count"] == 1
    assert ("request_gateways", "GW01") in engine.calls


def test_events_auction_mapping() -> None:
    assert websocket_type("auction.result.AAPL") == "auction"
    assert market_data_symbol("auction.result.aapl", {}) == "AAPL"
    assert gateway_from_topic("auction.result.AAPL") is None


def test_ws_auction_channel_helpers() -> None:
    assert ws._event_channel("auction") == "auction"
    event = {"type": "auction", "data": {"symbol": "AAPL"}}
    assert ws._topic_from_event(event) == "auction.result.AAPL"
