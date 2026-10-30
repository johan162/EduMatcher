"""WP-API01: one error model on every path, driven through the real app.

The per-handler tests elsewhere call route functions directly, so they never
reach what this file is about: the app-level exception handlers, the bearer
security dependency and the status code FastAPI finally sends. Requests go
through ``create_app()`` as raw ASGI calls (no HTTP client needed), with
``app.state`` populated by hand instead of by the ZMQ-starting lifespan.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.api_gateway.main import create_app
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.routers import admin, orders
from edumatcher.api_gateway.sessions import SessionRegistry
from edumatcher.models.price import clear_tick_registry, register_tick_decimals


class _Engine:
    """The EngineClient subset the routes below touch."""

    def __init__(self) -> None:
        self.cache = SessionCaches()

    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
        return True, ""

    def get_caches(self, gateway_id: str) -> SessionCaches:
        return self.cache

    def send_new_order(self, order: Any) -> None:
        pass

    def send_cancel(
        self, order_id: str, gateway_id: str, request_tag: str | None = None
    ) -> None:
        pass

    async def await_event(
        self, topic: str, match: dict[str, str] | None, timeout: float
    ) -> dict[str, Any]:
        return {"accepted": True, **(match or {})}

    def request_orders(self, gateway_id: str) -> None:
        raise RuntimeError("boom: internal detail that must not leak")


Response = tuple[int, dict[str, str], dict[str, Any]]


@pytest.fixture(autouse=True)
def _symbols_loaded() -> Iterator[None]:
    clear_tick_registry()
    register_tick_decimals("AAPL", 2)
    yield
    clear_tick_registry()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _app(engine: _Engine | None = None) -> Any:
    config = ApiGatewayConfig(swagger_enabled=False)
    app = create_app(config)
    app.state.config = config
    app.state.engine = engine or _Engine()
    app.state.rate_limiter = RateLimiter(100, 100)
    app.state.sessions = SessionRegistry(
        (
            ApiCredential("key-trader", "GW01", "trader"),
            ApiCredential("key-ro", None, "read-only"),
        )
    )
    return app


async def _call(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    authorization: str | None = "Bearer key-trader",
    engine: _Engine | None = None,
) -> Response:
    """One request through the whole ASGI stack, middleware included."""
    app = _app(engine)
    path, _, query = path.partition("?")
    headers = [(b"content-type", b"application/json")]
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    messages = [
        {
            "type": "http.request",
            "body": json.dumps(body).encode() if body is not None else b"",
            "more_body": False,
        }
    ]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": headers,
        "server": ("test", 80),
        "client": ("client", 1),
    }
    try:
        await app(scope, receive, send)
    except RuntimeError:
        # Starlette re-raises an unhandled error after sending the 500 (so the
        # server can log it); the response is already in `sent`.
        pass
    start = next(m for m in sent if m["type"] == "http.response.start")
    raw = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return (
        int(start["status"]),
        {k.decode().lower(): v.decode() for k, v in start["headers"]},
        json.loads(raw),
    )


def _error(response: Response) -> dict[str, Any]:
    _, _, body = response
    assert set(body) == {"error"}, body
    error: dict[str, Any] = body["error"]
    # Q-decision: `reason` duplicated `message` and is no longer sent.
    assert "reason" not in error
    assert error["message"]
    return error


# --- E1: the envelope on paths no route handles -------------------------------


@pytest.mark.anyio
async def test_unknown_route_uses_the_envelope() -> None:
    response = await _call("GET", "/api/v1/no-such-thing")
    assert response[0] == 404
    assert _error(response)["code"] == "NOT_FOUND"


@pytest.mark.anyio
async def test_wrong_method_uses_the_envelope_and_keeps_allow() -> None:
    response = await _call("PUT", "/api/v1/orders", body={})
    assert response[0] == 405
    assert _error(response)["code"] == "METHOD_NOT_ALLOWED"
    # Passed through from the routing exception (Starlette names only the
    # first route matched at the path, so its contents are not asserted).
    assert response[1]["allow"]


@pytest.mark.anyio
async def test_unhandled_exception_is_a_500_envelope_without_internals() -> None:
    response = await _call("GET", "/api/v1/orders")
    assert response[0] == 500
    error = _error(response)
    assert error["code"] == "INTERNAL_ERROR"
    assert error["reject_code"] == "INTERNAL_ERROR"
    assert "boom" not in json.dumps(response[2])


# --- E2 / S2: missing or malformed credentials are 401, never 400 -------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "authorization",
    [None, "", "Basic dXNlcjpwYXNz", "Bearer", "Bearer ", "Bearer unknown-key"],
)
async def test_bad_credentials_are_401_auth(authorization: str | None) -> None:
    response = await _call("GET", "/api/v1/reference", authorization=authorization)
    assert response[0] == 401
    error = _error(response)
    assert error["code"] == "AUTH"
    assert error["reject_code"] == "AUTH_REQUIRED"
    assert response[1]["www-authenticate"] == "Bearer"


# --- E3: validation is 400 everywhere ------------------------------------------


@pytest.mark.anyio
async def test_body_validation_is_400() -> None:
    response = await _call(
        "POST",
        "/api/v1/orders",
        body={"symbol": "AAPL", "side": "BUY", "order_type": "LIMIT", "quantity": 1},
    )
    assert response[0] == 400
    error = _error(response)
    assert (error["code"], error["reject_code"]) == ("VALIDATION", "MISSING_FIELD")


@pytest.mark.anyio
async def test_history_filter_validation_is_400_and_names_the_field() -> None:
    response = await _call(
        "GET", "/api/v1/history/trades?date=not-a-date", authorization="Bearer key-ro"
    )
    assert response[0] == 400
    error = _error(response)
    assert (error["code"], error["field"]) == ("VALIDATION", "date")
    assert error["reject_code"] == "INVALID_VALUE"


_ORDER = {
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "quantity": 10,
    "price": 150.0,
}


@pytest.mark.anyio
async def test_engine_unavailable_carries_alfs_reject_code() -> None:
    """ALF maps ENGINE_UNAVAILABLE to reject_code INTERNAL_ERROR
    (alf_gwy/protocol.py); REST said UNKNOWN for the same condition."""

    class _Unavailable(_Engine):
        def send_new_order(self, order: Any) -> None:
            # What EngineClient._send raises on zmq.Again.
            raise HTTPException(
                status_code=503,
                detail={"error": {"code": "ENGINE_UNAVAILABLE", "message": "down"}},
            )

    response = await _call("POST", "/api/v1/orders", body=_ORDER, engine=_Unavailable())
    assert response[0] == 503
    error = _error(response)
    assert (error["code"], error["reject_code"]) == (
        "ENGINE_UNAVAILABLE",
        "INTERNAL_ERROR",
    )


# --- E5: unknown order -------------------------------------------------------


@pytest.mark.anyio
async def test_unknown_order_is_404_unknown_order() -> None:
    response = await _call("GET", "/api/v1/orders/NOPE")
    assert response[0] == 404
    assert _error(response)["code"] == "UNKNOWN_ORDER"


# --- E6: 200 when the body carries the outcome, 202 when it does not ----------


@pytest.mark.anyio
async def test_submit_is_202_without_wait_and_200_with_the_verdict() -> None:
    pending = await _call("POST", "/api/v1/orders", body=_ORDER)
    acked = await _call("POST", "/api/v1/orders?wait=ack", body=_ORDER)
    assert (pending[0], pending[2]["status"]) == (202, "PENDING")
    assert (acked[0], acked[2]["status"]) == (200, "ACKED")


@pytest.mark.anyio
async def test_cancel_is_202_without_wait_and_200_with_the_outcome() -> None:
    pending = await _call("DELETE", "/api/v1/orders/ORD1")
    acked = await _call("DELETE", "/api/v1/orders/ORD1?wait=ack")
    assert (pending[0], pending[2]["status"]) == (202, "PENDING_CANCEL")
    assert (acked[0], acked[2]["status"]) == (200, "ACKED")


def test_awaited_admin_commands_declare_200() -> None:
    """Each of these waits for its ack and returns the outcome, so it is 200;
    a disconnect is fire-and-forget and stays 202."""
    routes = {
        (method, route.path): route.status_code
        for route in [*admin.router.routes, *orders.router.routes]
        if isinstance(route, APIRoute)
        for method in route.methods or ()
    }
    for path in (
        "/api/v1/admin/session/transition",
        "/api/v1/admin/reference/reload",
        "/api/v1/admin/circuit-breaker/trigger",
        "/api/v1/admin/circuit-breaker/resume",
        "/api/v1/admin/kill-switch/symbol",
        "/api/v1/admin/kill-switch/gateway",
        "/api/v1/admin/kill-switch/global",
        "/api/v1/admin/indexes/{index_id}/rebalance",
        "/api/v1/mass-cancel",
    ):
        # None is FastAPI's default for a route without status_code: 200.
        assert routes[("POST", path)] in (None, 200), path
    assert routes[("POST", "/api/v1/admin/gateways/{gid}/disconnect")] == 202
