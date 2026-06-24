from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.api_gateway.events import (
    envelope,
    gateway_from_topic,
    market_data_channel,
    market_data_symbol,
    websocket_type,
)
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.routers import orders, reference
from edumatcher.api_gateway.schemas import (
    AmendRequest,
    ComboRequest,
    ComboLegRequest,
    MassCancelRequest,
    OcoLegRequest,
    OcoRequest,
    OrderRequest,
    QuoteRequest,
)
from edumatcher.api_gateway.sessions import Session, SessionRegistry, require_trading


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.cache = SessionCaches()

    async def authenticate(self, gateway_id: str) -> tuple[bool, str]:
        self.calls.append(("authenticate", gateway_id))
        return True, ""

    async def await_topic(self, topic: str, timeout: float) -> dict[str, Any]:
        self.calls.append(("await_topic", (topic, timeout)))
        if topic.startswith("order.orders."):
            return {"orders": [{"order_id": "ORD1"}]}
        if topic.startswith("risk.kill_switch_ack."):
            return {"accepted": True, "cancelled_orders": 1, "cancelled_quotes": 0}
        return {"accepted": True, "topic": topic}

    def get_caches(self, gateway_id: str) -> SessionCaches:
        self.calls.append(("get_caches", gateway_id))
        return self.cache

    def send_new_order(self, order: Any) -> None:
        self.calls.append(("send_new_order", order.id))

    def send_cancel(self, order_id: str, gateway_id: str) -> None:
        self.calls.append(("send_cancel", (order_id, gateway_id)))

    def send_amend(
        self, order_id: str, gateway_id: str, price: float | None, qty: int | None
    ) -> None:
        self.calls.append(("send_amend", (order_id, gateway_id, price, qty)))

    def send_combo(self, payload: dict[str, Any]) -> None:
        self.calls.append(("send_combo", payload))

    def send_combo_cancel(self, combo_id: str, gateway_id: str) -> None:
        self.calls.append(("send_combo_cancel", (combo_id, gateway_id)))

    def send_oco(self, payload: dict[str, Any]) -> None:
        self.calls.append(("send_oco", payload))

    def send_oco_cancel(self, oco_id: str, gateway_id: str) -> None:
        self.calls.append(("send_oco_cancel", (oco_id, gateway_id)))

    def send_quote(self, payload: dict[str, Any]) -> None:
        self.calls.append(("send_quote", payload))

    def send_quote_cancel(self, gateway_id: str, symbol: str) -> None:
        self.calls.append(("send_quote_cancel", (gateway_id, symbol)))

    def send_mass_cancel(self, gateway_id: str, symbol: str = "") -> None:
        self.calls.append(("send_mass_cancel", (gateway_id, symbol)))

    def request_orders(self, gateway_id: str) -> None:
        self.calls.append(("request_orders", gateway_id))

    def request_symbols(self, gateway_id: str) -> None:
        self.calls.append(("request_symbols", gateway_id))

    def request_session(self, gateway_id: str) -> None:
        self.calls.append(("request_session", gateway_id))

    def request_quote_bootstrap(self, gateway_id: str) -> None:
        self.calls.append(("request_quote_bootstrap", gateway_id))

    def request_quote_legs(
        self, gateway_id: str, symbol: str = "", show: str = "ALL"
    ) -> None:
        self.calls.append(("request_quote_legs", (gateway_id, symbol, show)))

    def active_gateways(self) -> set[str]:
        return {"GW01"}


class TimeoutEngine(FakeEngine):
    async def await_topic(self, topic: str, timeout: float) -> dict[str, Any]:
        _ = (topic, timeout)
        raise TimeoutError("no reply")


def fake_request(engine: FakeEngine | None = None) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                engine=engine or FakeEngine(),
                config=ApiGatewayConfig(),
                rate_limiter=RateLimiter(100, 100),
            )
        )
    )


def limited_request(engine: FakeEngine | None = None) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                engine=engine or FakeEngine(),
                config=ApiGatewayConfig(),
                rate_limiter=RateLimiter(1, 1),
            )
        )
    )


def trading_session() -> Session:
    return Session(api_key="key", gateway_id="GW01", description="test")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_session_registry_and_require_trading() -> None:
    registry = SessionRegistry((ApiCredential("k", "GW01", "desk"),))
    assert registry.get("k") is not None
    assert registry.get("missing") is None
    assert require_trading(trading_session()) == "GW01"
    with pytest.raises(Exception):
        require_trading(Session(api_key="ro", gateway_id=None, description=""))


def test_events_helpers() -> None:
    assert gateway_from_topic("order.ack.GW01") == "GW01"
    assert websocket_type("risk.kill_switch_ack.GW01") == "mass_cancel.ack"
    assert websocket_type("trade.executed") == "trade"
    assert market_data_symbol("book.AAPL", {}) == "AAPL"
    assert market_data_symbol("trade.executed", {"symbol": "msft"}) == "MSFT"
    assert market_data_channel("depth.AAPL") == "depth"
    wrapped = envelope("order.fill.GW01", {"order_id": "ORD1"})
    assert wrapped["type"] == "order.fill"
    assert wrapped["gateway_id"] == "GW01"


def test_session_caches_apply_events() -> None:
    cache = SessionCaches()
    cache.apply(
        "system.symbols.GW01",
        {"symbols": ["AAPL"], "symbol_meta": {"AAPL": {"tick_decimals": 2}}},
    )
    cache.apply(
        "order.ack.GW01",
        {"order_id": "ORD1", "accepted": True, "symbol": "AAPL", "side": "BUY"},
    )
    cache.apply(
        "order.fill.GW01",
        {
            "order_id": "ORD1",
            "symbol": "AAPL",
            "side": "BUY",
            "fill_qty": 5,
            "status": "PARTIAL",
        },
    )
    cache.apply("order.amended.GW01", {"order_id": "ORD1", "qty": 10})
    cache.apply("order.cancelled.GW01", {"order_id": "ORD1"})
    cache.apply("order.expired.GW01", {"order_id": "ORD2"})
    cache.apply("quote.ack.GW01", {"quote_id": "Q1", "accepted": True})
    cache.apply("trade.executed", {"symbol": "AAPL", "price": 151.0})
    assert cache.positions["AAPL"] == 5
    assert cache.last_prices["AAPL"] == 151.0
    assert cache.status()["orders"] == 2


@pytest.mark.anyio
async def test_order_routes_send_engine_messages() -> None:
    engine = FakeEngine()
    request = fake_request(engine)
    session = trading_session()
    order_body = OrderRequest(
        symbol="AAPL", side="BUY", order_type="LIMIT", quantity=10, price=150.0
    )
    submitted = await orders.submit_order(order_body, request, session)
    assert submitted.status == "PENDING"
    assert any(call[0] == "send_new_order" for call in engine.calls)

    cancel = await orders.cancel_order("ORD1", request, session, wait="ack")
    amend = await orders.amend_order(
        "ORD1", AmendRequest(price=151.0), request, session, wait="ack"
    )
    listed = await orders.list_orders(request, session)
    engine.cache.orders["ORD1"] = {"order_id": "ORD1"}
    one = await orders.get_order("ORD1", request, session)
    assert cancel["event"] is not None
    assert amend["event"] is not None
    assert listed["orders"]
    assert one["order_id"] == "ORD1"

    @pytest.mark.anyio
    async def test_replace_order_and_error_paths() -> None:
        request = fake_request(FakeEngine())
        session = trading_session()
        order_body = OrderRequest(
            symbol="AAPL", side="BUY", order_type="LIMIT", quantity=10, price=150.0
        )
        replaced = await orders.replace_order("OLD", order_body, request, session)
        assert replaced.cancelled_order_id == "OLD"

        with pytest.raises(Exception):
            await orders.cancel_order(
                "ORD1", fake_request(TimeoutEngine()), session, wait="ack"
            )

        rate_limited = limited_request()
        await orders.cancel_order("ORD1", rate_limited, session)
        with pytest.raises(Exception):
            await orders.cancel_order("ORD2", rate_limited, session)


@pytest.mark.anyio
async def test_composite_quote_and_risk_routes() -> None:
    engine = FakeEngine()
    request = fake_request(engine)
    session = trading_session()
    oco = OcoRequest(
        oco_id="O1",
        symbol="AAPL",
        quantity=10,
        leg1=OcoLegRequest(side="SELL", order_type="LIMIT", price=151.0),
        leg2=OcoLegRequest(side="SELL", order_type="STOP", stop_price=149.0),
    )
    combo = ComboRequest(
        combo_id="C1",
        legs=[
            ComboLegRequest(symbol="AAPL", side="BUY", quantity=10, price=150.0),
            ComboLegRequest(symbol="MSFT", side="SELL", quantity=5, price=410.0),
        ],
    )
    quote = QuoteRequest(
        symbol="AAPL", bid_price=150.0, bid_qty=10, ask_price=150.1, ask_qty=10
    )
    assert (await orders.submit_oco(oco, request, session)).id == "O1"
    assert (await orders.cancel_oco("O1", request, session))["status"]
    assert (await orders.submit_combo(combo, request, session)).id == "C1"
    assert (await orders.cancel_combo("C1", request, session))["status"]
    assert (await orders.submit_quote(quote, request, session)).id == "AAPL"
    assert (await orders.cancel_quote("aapl", request, session))["symbol"] == "AAPL"
    result = await orders.mass_cancel(
        MassCancelRequest(symbol="AAPL"), request, session
    )
    assert result["accepted"] is True


@pytest.mark.anyio
async def test_reference_routes() -> None:
    engine = FakeEngine()
    request = fake_request(engine)
    session = trading_session()
    assert await reference.symbols(request, session)
    assert await reference.session_state(request, session)
    assert await reference.quote_bootstrap(request, session)
    engine.cache.quote_legs["Q1"] = {"quote_id": "Q1"}
    assert (await reference.quote_legs(request, session))["legs"]
    engine.cache.positions["AAPL"] = 5
    engine.cache.last_prices["AAPL"] = 151.0
    assert (await reference.positions(request, session))["positions"]
    assert (await reference.status_summary(request, session))["positions"]
    assert (await reference.healthz(request))["ok"] is True
