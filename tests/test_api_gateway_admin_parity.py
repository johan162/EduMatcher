"""WP-API07: the admin REST surface reaches what ``pm-admin-cli`` can do.

Driven through the real app (tests/api_gateway_harness.py), so FastAPI's
response validation runs: every reply below is checked against its route's
contract model as it is sent.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.models.generated import order as gen_order
from edumatcher.models.generated import risk as gen_risk
from edumatcher.models.generated import system as gen_system
from edumatcher.models.price import clear_tick_registry, register_tick_decimals
from tests.api_gateway_harness import call, make_app, wire

ADMIN = "GW01"  # the harness's trading key


class _Engine:
    """EngineClient double: an ADMIN caller, recorded sends, canned replies."""

    def __init__(self, replies: dict[str, dict[str, Any]], role: str = "ADMIN") -> None:
        self.cache = SessionCaches()
        self.replies = replies
        self.role = role
        self.sent: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.awaited: list[tuple[str, dict[str, str] | None]] = []

    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
        return True, ""

    def get_caches(self, gateway_id: str) -> SessionCaches:
        return self.cache

    async def resolve_role(self, gateway_id: str, timeout: float) -> str:
        return self.role

    def __getattr__(self, name: str) -> Any:
        if name.startswith(("send_", "request_")):

            def record(*args: Any, **kwargs: Any) -> None:
                self.sent.append((name, args, kwargs))

            return record
        raise AttributeError(name)

    def _reply(self, topic: str, match: dict[str, str] | None) -> dict[str, Any]:
        self.awaited.append((topic, match))
        prefix = topic.rsplit(".", 1)[0]
        return {**self.replies[prefix], **(match or {})}

    async def await_event(
        self, topic: str, match: dict[str, str] | None, timeout: float
    ) -> dict[str, Any]:
        return self._reply(topic, match)

    async def await_topic(self, topic: str, timeout: float) -> dict[str, Any]:
        return self._reply(topic, None)


@pytest.fixture(autouse=True)
def _symbols_loaded() -> Iterator[None]:
    clear_tick_registry()
    register_tick_decimals("AAPL", 2)
    yield
    clear_tick_registry()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


_HALT_ALL = wire(
    gen_risk.CircuitBreakerHaltAllAck,
    {"gateway_id": ADMIN, "accepted": True, "halted_symbols": 2,
     "halted_symbol_ids": ["AAPL", "MSFT"], "cancelled_quotes": 2,
     "cancelled_quote_order_ids": ["q1", "q2"]},
)  # fmt: skip
_RESUME_ALL = wire(
    gen_risk.CircuitBreakerResumeAllAck,
    {"gateway_id": ADMIN, "accepted": True, "resumed_symbols": 2,
     "resumed_symbol_ids": ["AAPL", "MSFT"]},
)  # fmt: skip
_UNCROSS = wire(
    gen_risk.ForceUncrossAck,
    {"gateway_id": ADMIN, "accepted": True, "symbol": "AAPL", "dry_run": True,
     "indicative_price": 150.25, "indicative_qty": 400, "surplus": 100,
     "imbalance_side": "BUY", "printed_price": None, "traded_qty": 0},
)  # fmt: skip
_KILL_GW = wire(
    gen_risk.KillSwitchGatewayAck,
    {"gateway_id": ADMIN, "accepted": True, "target_gateway_id": "MM01",
     "symbol": "AAPL", "quotes_only": True, "cancelled_quotes": 2,
     "cancelled_quote_order_ids": ["q1", "q2"]},
)  # fmt: skip
_LEVEL = wire(
    gen_order.PriceLevelOrders,
    {"gateway_id": ADMIN, "symbol": "AAPL", "price": 150.0, "rejected": False,
     "orders": []},
)  # fmt: skip
_VOLUME = wire(
    gen_system.Volume,
    {"gateway_id": ADMIN, "symbols": [{"symbol": "AAPL", "qty": 500,
     "value": 75125.0, "trades": 7}], "total_qty": 500,
     "total_value": 75125.0, "total_trades": 7},
)  # fmt: skip
_ORDERS = wire(gen_order.Orders, {"gateway_id": "MM01", "orders": []})

_REPLIES = {
    "risk.circuit_breaker_halt_all_ack": _HALT_ALL,
    "risk.circuit_breaker_resume_all_ack": _RESUME_ALL,
    "risk.force_uncross_ack": _UNCROSS,
    "risk.kill_switch_gateway_ack": _KILL_GW,
    "order.price_level_orders": _LEVEL,
    "system.volume": _VOLUME,
    "order.orders": _ORDERS,
}


async def _call(
    method: str, path: str, **kw: Any
) -> tuple[int, dict[str, Any], _Engine]:
    engine = _Engine(_REPLIES)
    status, _, body = await call(make_app(engine), method, path, **kw)
    return status, body, engine


@pytest.mark.anyio
async def test_market_halt_and_resume() -> None:
    status, body, engine = await _call("POST", "/api/v1/admin/market/halt")
    assert status == 200 and body["halted_symbol_ids"] == ["AAPL", "MSFT"]
    assert engine.sent[0][0] == "send_halt_all"
    status, body, engine = await _call("POST", "/api/v1/admin/market/resume")
    assert status == 200 and body["resumed_symbols"] == 2
    assert engine.sent[0][0] == "send_resume_all"


@pytest.mark.anyio
async def test_reopen_sends_price_and_dry_run() -> None:
    status, body, engine = await _call(
        "POST",
        "/api/v1/admin/symbols/aapl/reopen",
        body={"price": 150.25, "dry_run": True, "reason": "failed open"},
    )
    assert status == 200 and body["indicative_qty"] == 400
    name, args, kwargs = engine.sent[0]
    assert (name, args[1]) == ("send_force_uncross", "AAPL")
    assert (kwargs["price"], kwargs["dry_run"], kwargs["note"]) == (
        150.25,
        True,
        "failed open",
    )
    # Concurrent reopens are told apart by command_id.
    assert engine.awaited[0][1] == {"command_id": kwargs["command_id"]}


@pytest.mark.anyio
async def test_reopen_refuses_a_price_off_the_tick_grid() -> None:
    status, body, engine = await _call(
        "POST", "/api/v1/admin/symbols/AAPL/reopen", body={"price": 150.255}
    )
    assert status == 400 and body["error"]["reject_code"] == "TICK_VIOLATION"
    assert engine.sent == []


@pytest.mark.anyio
async def test_a_refused_reopen_is_409() -> None:
    engine = _Engine({**_REPLIES, "risk.force_uncross_ack": {**_UNCROSS, "accepted": False, "reason": "AAPL is not halted"}})  # fmt: skip
    status, _, body = await call(
        make_app(engine), "POST", "/api/v1/admin/symbols/AAPL/reopen"
    )
    assert (status, body["error"]["code"]) == (409, "REOPEN_REJECTED")
    assert body["error"]["message"] == "AAPL is not halted"


@pytest.mark.anyio
async def test_gateway_kill_switch_can_be_scoped_to_a_symbol() -> None:
    status, body, engine = await _call(
        "POST", "/api/v1/admin/gateways/mm01/kill-switch?symbol=aapl"
    )
    assert status == 200
    name, args, kwargs = engine.sent[0]
    assert (name, args[1], kwargs["symbol"], kwargs["quotes_only"]) == (
        "send_kill_switch_gateway", "MM01", "AAPL", False,
    )  # fmt: skip


@pytest.mark.anyio
async def test_admin_quote_cancel_uses_the_admin_kill_switch() -> None:
    """Not the participant's own quote.cancel: the audit must name the
    admin, and a disconnected market maker's quote must still be pullable."""
    status, body, engine = await _call(
        "DELETE", "/api/v1/admin/gateways/MM01/quotes/AAPL"
    )
    assert status == 200 and body["cancelled_quotes"] == 2
    name, args, kwargs = engine.sent[0]
    assert (name, args[0], args[1]) == ("send_kill_switch_gateway", ADMIN, "MM01")
    assert (kwargs["symbol"], kwargs["quotes_only"]) == ("AAPL", True)


@pytest.mark.anyio
async def test_engine_authoritative_orders_of_any_gateway() -> None:
    status, body, engine = await _call("GET", "/api/v1/admin/gateways/mm01/orders")
    assert status == 200 and body == {"orders": [], "count": 0}
    assert engine.sent[0][:2] == ("request_orders", ("MM01",))
    assert engine.awaited[0][0] == "order.orders.MM01"


@pytest.mark.anyio
async def test_price_level_drill_down() -> None:
    status, body, engine = await _call(
        "GET", "/api/v1/admin/symbols/AAPL/orders?price=150"
    )
    assert status == 200 and (body["symbol"], body["count"]) == ("AAPL", 0)
    name, args, kwargs = engine.sent[0]
    assert (name, args) == ("request_price_level_orders", (ADMIN, "AAPL", 150.0))


@pytest.mark.anyio
async def test_a_refused_price_level_query_is_409() -> None:
    engine = _Engine({**_REPLIES, "order.price_level_orders": {**_LEVEL, "rejected": True, "reason": "Unknown symbol: XYZ"}})  # fmt: skip
    status, _, body = await call(
        make_app(engine), "GET", "/api/v1/admin/symbols/XYZ/orders"
    )
    assert (status, body["error"]["code"]) == (409, "QUERY_REJECTED")


@pytest.mark.anyio
async def test_daily_volume() -> None:
    status, body, engine = await _call("GET", "/api/v1/admin/market/volume")
    assert status == 200
    assert (body["count"], body["total_trades"], body["symbols"][0]["symbol"]) == (
        1,
        7,
        "AAPL",
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/admin/market/halt"),
        ("POST", "/api/v1/admin/symbols/AAPL/reopen"),
        ("DELETE", "/api/v1/admin/gateways/MM01/quotes/AAPL"),
        ("GET", "/api/v1/admin/market/volume"),
    ],
)
async def test_every_new_route_requires_admin(method: str, path: str) -> None:
    engine = _Engine(_REPLIES, role="TRADER")
    status, _, body = await call(make_app(engine), method, path)
    assert (status, body["error"]["code"]) == (403, "ROLE_DENIED")
    assert engine.sent == []
