"""Tests for the bootstrap aggregate endpoints (routers/bootstrap.py).

The handlers are exercised directly (not through a live ASGI server), mirroring
the pattern in test_api_gateway_admin.py: a fake engine implementing the subset
of EngineClient the handlers touch, and a SimpleNamespace request carrying
app.state.  _query_fills_sync is monkeypatched where a test needs deterministic
fill data without a real stats database.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from edumatcher.api_gateway import routers
from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.routers import bootstrap
from edumatcher.api_gateway.sessions import Session

_REFERENCE_REPLY: dict[str, Any] = {
    "symbols": [{"symbol": "AAPL", "tick_decimals": 2}],
    "risk": {"default_level": "L2", "levels": {}},
    "schedule": {
        "sessions_enabled": True,
        "country": "Sweden",
        "schedule": {"pre_open": "09:00"},
    },
    "config_version": "v1",
}


class BootstrapFakeEngine:
    """Test double implementing the bootstrap subset of EngineClient."""

    def __init__(
        self,
        *,
        role: str = "TRADER",
        raise_prefixes: frozenset[str] = frozenset(),
        active_gateways: tuple[str, ...] = ("GW01",),
        orders: list[dict[str, Any]] | None = None,
        seqs: dict[str, int] | None = None,
    ) -> None:
        self.role = role
        self.raise_prefixes = raise_prefixes
        self._active = set(active_gateways)
        self._orders = orders or []
        self._seqs = seqs or {}
        self.cache = SessionCaches()
        self.calls: list[tuple[str, Any]] = []

    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
        return True, ""

    async def resolve_role(self, gateway_id: str, timeout: float) -> str:
        self.calls.append(("resolve_role", gateway_id))
        return self.role

    def request_reference(self, gid: str) -> None:
        self.calls.append(("request_reference", gid))

    def request_session(self, gid: str) -> None:
        self.calls.append(("request_session", gid))

    def request_orders(self, gid: str) -> None:
        self.calls.append(("request_orders", gid))

    def request_quote_bootstrap(self, gid: str, symbol: str = "") -> None:
        self.calls.append(("request_quote_bootstrap", gid))

    def request_quote_legs(self, gid: str, symbol: str = "", show: str = "ALL") -> None:
        self.calls.append(("request_quote_legs", gid))

    def request_gateways(self, gid: str) -> None:
        self.calls.append(("request_gateways", gid))

    def request_halt_status(self, gid: str) -> None:
        self.calls.append(("request_halt_status", gid))

    def get_caches(self, gid: str) -> SessionCaches:
        return self.cache

    def all_orders(self) -> list[dict[str, Any]]:
        return list(self._orders)

    def active_gateways(self) -> set[str]:
        return set(self._active)

    def stream_seq(self, gid: str) -> int:
        return self._seqs.get(gid, 0)

    async def await_topic(self, topic: str, timeout: float) -> dict[str, Any]:
        for prefix in self.raise_prefixes:
            if topic.startswith(prefix):
                raise TimeoutError(f"no reply for {topic}")
        if topic.startswith("system.reference."):
            return dict(_REFERENCE_REPLY)
        if topic.startswith("system.session_status."):
            return {"state": "CONTINUOUS", "since": "2026-07-27T09:30:00.000Z"}
        if topic.startswith("order.orders."):
            return {"orders": self._orders}
        if topic.startswith("system.quote_bootstrap."):
            return {"quotes": []}
        if topic.startswith("system.quote_legs."):
            return {"legs": []}
        if topic.startswith("system.gateways."):
            return {"gateways": [{"id": "GW01", "role": "TRADER", "connected": True}]}
        if topic.startswith("system.halt_status."):
            return {"halted": []}
        return {}


def boot_request(
    engine: BootstrapFakeEngine,
    *,
    config: ApiGatewayConfig | None = None,
    index_running: bool = True,
) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                engine=engine,
                config=config or ApiGatewayConfig(),
                index_client=SimpleNamespace(is_running=lambda: index_running),
                rate_limiter=RateLimiter(100, 100),
            )
        )
    )


def trading_session(gateway_id: str = "GW01") -> Session:
    return Session(api_key="key", gateway_id=gateway_id, description="")


def readonly_session() -> Session:
    return Session(api_key="ro-key", gateway_id=None, description="dashboard")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _fills_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: fills query returns a fixed envelope so tests don't touch a
    real stats DB.  Individual tests override this to test failure paths."""
    monkeypatch.setattr(
        bootstrap,
        "_query_fills_sync",
        lambda config, gid, limit: {"events": [{"order_id": "O1"}], "count": 1},
    )


# ---------------------------------------------------------------------------
# /bootstrap/trader
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_trader_full_payload() -> None:
    engine = BootstrapFakeEngine(role="TRADER")
    result = await bootstrap.bootstrap_trader(
        boot_request(engine), trading_session(), fills_limit=50
    )
    assert result["gateway_id"] == "GW01"
    assert result["gateway_role"] == "TRADER"
    assert result["incomplete"] == []
    assert result["reference"]["config_version"] == "v1"
    assert result["session"]["state"] == "CONTINUOUS"
    assert result["orders"] == {"orders": []}
    assert result["recent_fills"] == {"events": [{"order_id": "O1"}], "count": 1}
    assert result["capabilities"]["sessions_enabled"] is True


@pytest.mark.anyio
async def test_trader_read_only_key() -> None:
    engine = BootstrapFakeEngine()
    result = await bootstrap.bootstrap_trader(
        boot_request(engine), readonly_session(), fills_limit=50
    )
    assert result["gateway_id"] is None
    assert result["gateway_role"] == "READ_ONLY"
    assert result["orders"] == {"orders": []}
    assert result["positions"] == []
    # session and recent_fills are structurally absent, NOT flagged incomplete.
    assert result["session"] is None
    assert result["recent_fills"] is None
    assert result["incomplete"] == []
    # resolve_role is never called for a keyless credential.
    assert not any(c[0] == "resolve_role" for c in engine.calls)


@pytest.mark.anyio
async def test_trader_required_orders_timeout_returns_503() -> None:
    engine = BootstrapFakeEngine(raise_prefixes=frozenset({"order.orders."}))
    with pytest.raises(HTTPException) as exc:
        await bootstrap.bootstrap_trader(
            boot_request(engine), trading_session(), fills_limit=50
        )
    assert exc.value.status_code == 503
    assert cast(dict[str, Any], exc.value.detail)["error"]["code"] == "ENGINE_TIMEOUT"


@pytest.mark.anyio
async def test_trader_required_reference_timeout_returns_503() -> None:
    engine = BootstrapFakeEngine(raise_prefixes=frozenset({"system.reference."}))
    with pytest.raises(HTTPException) as exc:
        await bootstrap.bootstrap_trader(
            boot_request(engine), trading_session(), fills_limit=50
        )
    assert exc.value.status_code == 503


@pytest.mark.anyio
async def test_trader_optional_session_timeout_is_incomplete() -> None:
    engine = BootstrapFakeEngine(raise_prefixes=frozenset({"system.session_status."}))
    result = await bootstrap.bootstrap_trader(
        boot_request(engine), trading_session(), fills_limit=50
    )
    assert result["session"] is None
    assert "session" in result["incomplete"]
    # orders still populated — a partial response, still 200.
    assert result["orders"] == {"orders": []}


@pytest.mark.anyio
async def test_trader_fills_missing_db_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(config: Any, gid: str, limit: int) -> dict[str, Any]:
        raise FileNotFoundError("no stats db")

    monkeypatch.setattr(bootstrap, "_query_fills_sync", _raise)
    engine = BootstrapFakeEngine()
    result = await bootstrap.bootstrap_trader(
        boot_request(engine), trading_session(), fills_limit=50
    )
    assert result["recent_fills"] is None
    assert "recent_fills" in result["incomplete"]


@pytest.mark.anyio
async def test_trader_fills_limit_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, int] = {}

    def _capture(config: Any, gid: str, limit: int) -> dict[str, Any]:
        seen["limit"] = limit
        return {"events": [], "count": 0}

    monkeypatch.setattr(bootstrap, "_query_fills_sync", _capture)
    engine = BootstrapFakeEngine()
    await bootstrap.bootstrap_trader(
        boot_request(engine), trading_session(), fills_limit=17
    )
    assert seen["limit"] == 17


# ---------------------------------------------------------------------------
# /bootstrap/mm
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mm_success_includes_quote_fields() -> None:
    engine = BootstrapFakeEngine(role="MARKET_MAKER", active_gateways=("MM01",))
    result = await bootstrap.bootstrap_mm(
        boot_request(engine), trading_session("MM01"), fills_limit=50
    )
    assert result["gateway_role"] == "MARKET_MAKER"
    assert result["quote_bootstrap"] == {"quotes": []}
    assert result["quote_legs"] == {"legs": []}
    assert result["incomplete"] == []


@pytest.mark.anyio
async def test_mm_rejects_trader_key() -> None:
    engine = BootstrapFakeEngine(role="TRADER")
    with pytest.raises(HTTPException) as exc:
        await bootstrap.bootstrap_mm(
            boot_request(engine), trading_session(), fills_limit=50
        )
    assert exc.value.status_code == 403
    assert cast(dict[str, Any], exc.value.detail)["error"]["code"] == "ROLE_DENIED"


@pytest.mark.anyio
async def test_mm_rejects_admin_key() -> None:
    engine = BootstrapFakeEngine(role="ADMIN")
    with pytest.raises(HTTPException) as exc:
        await bootstrap.bootstrap_mm(
            boot_request(engine), trading_session(), fills_limit=50
        )
    assert exc.value.status_code == 403
    assert cast(dict[str, Any], exc.value.detail)["error"]["code"] == "ROLE_DENIED"


@pytest.mark.anyio
async def test_mm_rejects_read_only_key() -> None:
    engine = BootstrapFakeEngine(role="MARKET_MAKER")
    with pytest.raises(HTTPException) as exc:
        await bootstrap.bootstrap_mm(
            boot_request(engine), readonly_session(), fills_limit=50
        )
    assert exc.value.status_code == 403
    assert cast(dict[str, Any], exc.value.detail)["error"]["code"] == "READ_ONLY"


# ---------------------------------------------------------------------------
# /bootstrap/admin
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_success_payload() -> None:
    engine = BootstrapFakeEngine(
        role="ADMIN",
        active_gateways=("GW01", "GW02"),
        orders=[{"gateway_id": "GW01", "status": "NEW"}],
        seqs={"GW01": 100, "GW02": 50},
    )
    result = await bootstrap.bootstrap_admin(boot_request(engine), trading_session())
    assert result["gateway_role"] == "ADMIN"
    assert result["gateways"] == {
        "gateways": [{"id": "GW01", "role": "TRADER", "connected": True}]
    }
    assert result["halts"] == {"halted": []}
    # GW02 has no live orders but must still appear with an explicit 0.
    assert result["active_order_counts"] == {"GW01": 1, "GW02": 0}
    assert result["monitor_last_seq"] == {"GW01": 100, "GW02": 50}
    assert result["incomplete"] == []


@pytest.mark.anyio
async def test_admin_rejects_non_admin() -> None:
    engine = BootstrapFakeEngine(role="TRADER")
    with pytest.raises(HTTPException) as exc:
        await bootstrap.bootstrap_admin(boot_request(engine), trading_session())
    assert exc.value.status_code == 403
    assert cast(dict[str, Any], exc.value.detail)["error"]["code"] == "ROLE_DENIED"


@pytest.mark.anyio
async def test_admin_optional_halts_timeout_is_incomplete() -> None:
    engine = BootstrapFakeEngine(
        role="ADMIN",
        active_gateways=("GW01",),
        raise_prefixes=frozenset({"system.halt_status."}),
    )
    result = await bootstrap.bootstrap_admin(boot_request(engine), trading_session())
    assert result["halts"] is None
    assert "halts" in result["incomplete"]
    # reference still present — partial response, still 200.
    assert result["reference"]["config_version"] == "v1"


@pytest.mark.anyio
async def test_admin_required_reference_timeout_returns_503() -> None:
    engine = BootstrapFakeEngine(
        role="ADMIN", raise_prefixes=frozenset({"system.reference."})
    )
    with pytest.raises(HTTPException) as exc:
        await bootstrap.bootstrap_admin(boot_request(engine), trading_session())
    assert exc.value.status_code == 503


def test_bootstrap_router_registered() -> None:
    """The router is wired into the app so the endpoints are reachable."""
    assert routers.bootstrap.router.prefix == "/api/v1/bootstrap"
