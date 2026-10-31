"""WP-API03: the frozen v1 resource layout.

The route table below is the whole v1 surface. Adding, removing or renaming an
endpoint is a contract change, so it must show up here as a deliberate edit.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute

from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.api_gateway.routers import (
    admin,
    bootstrap,
    history,
    orders,
    reference,
    ws,
)
from tests.api_gateway_harness import READ_ONLY_KEY, call, make_app

_V1 = "/api/v1"

REST_ROUTES = {
    # orders
    ("POST", "/orders"),
    ("GET", "/orders"),
    ("GET", "/orders/{order_id}"),
    ("PATCH", "/orders/{order_id}"),
    ("DELETE", "/orders/{order_id}"),
    ("POST", "/orders/{order_id}/replace"),
    ("POST", "/oco"),
    ("DELETE", "/oco/{oco_id}"),
    ("POST", "/combos"),
    ("DELETE", "/combos/{combo_id}"),
    ("POST", "/quotes"),
    ("GET", "/quotes"),
    ("GET", "/quotes/legs"),
    ("DELETE", "/quotes/{symbol}"),
    ("POST", "/mass-cancel"),
    # reference and account
    ("GET", "/reference"),
    ("GET", "/reference/config-version"),
    ("GET", "/reference/symbols"),
    ("GET", "/reference/risk"),
    ("GET", "/reference/indexes"),
    ("GET", "/reference/schedule"),
    ("GET", "/symbols"),
    ("GET", "/news"),
    ("GET", "/companies/{symbol}"),
    ("GET", "/session"),
    ("GET", "/halts"),
    ("GET", "/positions"),
    ("GET", "/status"),
    ("GET", "/healthz"),
    # history
    ("GET", "/history/orders"),
    ("GET", "/history/orders/{order_id}"),
    ("GET", "/history/fills"),
    ("GET", "/history/trades"),
    ("GET", "/history/daily"),
    ("GET", "/history/price-snapshots"),
    ("GET", "/history/index-daily"),
    ("GET", "/history/index-snapshots"),
    ("GET", "/history/indexes"),
    ("GET", "/history/index-events"),
    # bootstrap
    ("GET", "/bootstrap/trader"),
    ("GET", "/bootstrap/mm"),
    ("GET", "/bootstrap/admin"),
    # admin: venue, symbols, gateways (D1)
    ("POST", "/admin/session/transition"),
    ("POST", "/admin/reference/reload"),
    ("GET", "/admin/sim"),
    ("GET", "/admin/risk/state"),
    ("POST", "/admin/market/kill-switch"),
    # WP-API07: admin parity with pm-admin-cli
    ("POST", "/admin/market/halt"),
    ("POST", "/admin/market/resume"),
    ("GET", "/admin/market/volume"),
    ("POST", "/admin/symbols/{symbol}/reopen"),
    ("GET", "/admin/symbols/{symbol}/orders"),
    ("GET", "/admin/gateways/{gateway_id}/orders"),
    ("DELETE", "/admin/gateways/{gateway_id}/quotes/{symbol}"),
    ("POST", "/admin/symbols/{symbol}/halt"),
    ("POST", "/admin/symbols/{symbol}/resume"),
    ("POST", "/admin/symbols/{symbol}/cancel-orders"),
    ("GET", "/admin/gateways"),
    ("POST", "/admin/gateways/{gateway_id}/disconnect"),
    ("POST", "/admin/gateways/{gateway_id}/kill-switch"),
    ("GET", "/admin/gateways/{gateway_id}/positions"),
    ("GET", "/admin/orders"),
    ("GET", "/admin/orders/{order_id}/audit"),
    ("POST", "/admin/indexes/{index_id}/rebalance"),
}

WS_ROUTES = {"/ws/private", "/ws/market-data", "/ws/admin/monitor", "/ws/admin/sim"}

_ROUTERS = (orders, reference, history, admin, bootstrap, ws)


def test_rest_routes_are_exactly_the_v1_surface() -> None:
    actual = {
        (method, route.path.removeprefix(_V1))
        for module in _ROUTERS
        for route in module.router.routes
        if isinstance(route, APIRoute)
        for method in route.methods or ()
    }
    assert actual == REST_ROUTES, {
        "unexpected": sorted(actual - REST_ROUTES),
        "missing": sorted(REST_ROUTES - actual),
    }


def test_websockets_live_under_ws() -> None:
    """D5: one prefix, so a proxy can route upgrades separately, and no path
    is both a REST route and a socket (`/admin/sim` used to be both)."""
    actual = {
        route.path.removeprefix(_V1)
        for route in ws.router.routes
        if isinstance(route, APIWebSocketRoute)
    }
    assert actual == WS_ROUTES


# --- C5: public state is open to read-only keys ------------------------------


class _Engine:
    """Answers the two read-only queries and records which id they used."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.cache = SessionCaches()

    def request_session(self, correlation_id: str) -> None:
        self.requests.append(("session", correlation_id))

    def request_halt_status(self, correlation_id: str) -> None:
        self.requests.append(("halts", correlation_id))

    async def await_topic(self, topic: str, timeout: float) -> dict[str, Any]:
        if topic.startswith("system.session_status."):
            return {"state": "CONTINUOUS", "sessions_enabled": True, "next": None}
        return {"halted": [{"symbol": "AAPL"}]}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_read_only_key_gets_session_with_locale() -> None:
    """One GET /session now answers what /session and /history/session split:
    the phase from the engine, plus the timezone and trading date."""
    engine = _Engine()
    status, _, body = await call(
        make_app(engine),
        "GET",
        "/api/v1/session",
        authorization=f"Bearer {READ_ONLY_KEY}",
    )
    assert status == 200
    assert body["state"] == "CONTINUOUS"
    assert body["session_timezone"]
    assert len(body["session_date"]) == len("2026-10-30")


@pytest.mark.anyio
async def test_read_only_key_gets_halts() -> None:
    engine = _Engine()
    status, _, body = await call(
        make_app(engine),
        "GET",
        "/api/v1/halts",
        authorization=f"Bearer {READ_ONLY_KEY}",
    )
    assert status == 200
    assert body == {"halted": [{"symbol": "AAPL"}], "count": 1}


@pytest.mark.anyio
async def test_read_only_correlation_id_is_engine_safe_and_stable() -> None:
    """The engine upper-cases and clamps (32) the id it echoes in the reply
    topic, so the raw key cannot be used; and EngineClient keeps state per id
    it sees, so the id must not be fresh per request."""
    engine = _Engine()
    app = make_app(engine)
    for path in ("/api/v1/session", "/api/v1/halts", "/api/v1/session"):
        await call(app, "GET", path, authorization=f"Bearer {READ_ONLY_KEY}")
    ids = {correlation_id for _, correlation_id in engine.requests}
    (only,) = ids
    assert only == only.upper() and len(only) <= 32
    assert only != READ_ONLY_KEY.upper()


@pytest.mark.anyio
async def test_session_date_is_the_trading_day_in_the_exchange_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ported from the retired /history/session: a client's "today" must match
    the ``date`` pm-stats records, which is in the session timezone, not UTC.
    2026-06-14T12:00:00Z is already 2026-06-15 in UTC+14."""
    monkeypatch.setattr(
        reference, "session_timezone", lambda: ZoneInfo("Pacific/Kiritimati")
    )
    monkeypatch.setattr(
        "edumatcher.api_gateway.routers.reference.time.time", lambda: 1_781_438_400.0
    )
    _, _, body = await call(
        make_app(_Engine()),
        "GET",
        "/api/v1/session",
        authorization=f"Bearer {READ_ONLY_KEY}",
    )
    assert (body["session_timezone"], body["session_date"]) == (
        "Pacific/Kiritimati",
        "2026-06-15",
    )
