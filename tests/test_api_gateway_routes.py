from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.api_gateway.events import (
    envelope,
    gateway_from_topic,
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
from edumatcher.models.generated.order import topic_order_amended, topic_order_cancelled
from edumatcher.models.order import OrderType, Side
from edumatcher.models.price import clear_tick_registry, register_tick_decimals


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.cache = SessionCaches()
        # /healthz reports per-sink drop counts; the real EngineClient exposes
        # this as a property.
        self.dropped_events: dict[str, int] = {}

    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
        self.calls.append(("authenticate", gateway_id))
        return True, ""

    async def await_topic(self, topic: str, timeout: float) -> dict[str, Any]:
        return await self.await_event(topic, match=None, timeout=timeout)

    async def await_event(
        self, topic: str, match: dict[str, str] | None, timeout: float
    ) -> dict[str, Any]:
        self.calls.append(("await_event", (topic, match, timeout)))
        if topic.startswith("order.orders."):
            return {"orders": [{"order_id": "ORD1"}]}
        if topic.startswith("system.position_snapshot."):
            return {"positions": [{"symbol": "AAPL", "net_qty": 5, "avg_cost": 150.0}]}
        if topic.startswith("risk.kill_switch_ack."):
            return {"accepted": True, "cancelled_orders": 1, "cancelled_quotes": 0}
        return {
            "accepted": True,
            "topic": topic,
            "order_id": match.get("order_id", "") if match else "",
        }

    async def await_cancel_or_amend_outcome(
        self,
        *,
        success_topic: str,
        gateway_id: str,
        order_id: str,
        request_tag: str,
        timeout: float,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "await_cancel_or_amend_outcome",
                (success_topic, gateway_id, order_id, request_tag, timeout),
            )
        )
        return {
            "accepted": True,
            "topic": success_topic,
            "order_id": order_id,
            "request_tag": request_tag,
        }

    def get_caches(self, gateway_id: str) -> SessionCaches:
        self.calls.append(("get_caches", gateway_id))
        return self.cache

    def send_new_order(self, order: Any) -> None:
        self.calls.append(("send_new_order", order))

    def send_cancel(
        self, order_id: str, gateway_id: str, request_tag: str | None = None
    ) -> None:
        self.calls.append(("send_cancel", (order_id, gateway_id, request_tag)))

    def send_amend(
        self,
        order_id: str,
        gateway_id: str,
        price: float | None,
        qty: int | None,
        request_tag: str | None = None,
    ) -> None:
        self.calls.append(
            ("send_amend", (order_id, gateway_id, price, qty, request_tag))
        )

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

    async def send_and_await_kill_switch(
        self, gateway_id: str, symbol: str, timeout: float
    ) -> dict[str, Any]:
        self.send_mass_cancel(gateway_id, symbol)
        return await self.await_topic(f"risk.kill_switch_ack.{gateway_id}", timeout)

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

    def request_halt_status(self, gateway_id: str) -> None:
        self.calls.append(("request_halt_status", gateway_id))

    def request_position(self, gateway_id: str) -> None:
        self.calls.append(("request_position", gateway_id))

    def request_gateways(self, gateway_id: str) -> None:
        self.calls.append(("request_gateways", gateway_id))

    async def resolve_role(self, gateway_id: str, timeout: float) -> str:
        self.calls.append(("resolve_role", gateway_id))
        return "TRADER"

    def active_gateways(self) -> set[str]:
        return {"GW01"}

    def is_running(self) -> bool:
        return True


class TimeoutEngine(FakeEngine):
    async def await_event(
        self, topic: str, match: dict[str, str] | None, timeout: float
    ) -> dict[str, Any]:
        _ = (topic, match, timeout)
        raise TimeoutError("no reply")

    async def await_cancel_or_amend_outcome(
        self,
        *,
        success_topic: str,
        gateway_id: str,
        order_id: str,
        request_tag: str,
        timeout: float,
    ) -> dict[str, Any]:
        _ = (success_topic, gateway_id, order_id, request_tag, timeout)
        raise TimeoutError("no reply")


class RejectedAckEngine(FakeEngine):
    async def await_event(
        self, topic: str, match: dict[str, str] | None, timeout: float
    ) -> dict[str, Any]:
        self.calls.append(("await_event", (topic, match, timeout)))
        return {
            "order_id": match.get("order_id", "") if match else "",
            "accepted": False,
            "reason": "collar breach",
            "reject_code": "COLLAR_BREACH",
            "client_tag": "REST-ORDER-001",
        }


class RejectedCancelOrAmendEngine(FakeEngine):
    """C1: a rejected cancel/amend races order.ack, not the success topic."""

    async def await_cancel_or_amend_outcome(
        self,
        *,
        success_topic: str,
        gateway_id: str,
        order_id: str,
        request_tag: str,
        timeout: float,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "await_cancel_or_amend_outcome",
                (success_topic, gateway_id, order_id, request_tag, timeout),
            )
        )
        return {
            "gateway_id": gateway_id,
            "order_id": order_id,
            "accepted": False,
            "reason": "collar breach",
            "reject_code": "COLLAR_BREACH",
            "request_tag": request_tag,
        }


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


@pytest.fixture(autouse=True)
def _symbols_loaded() -> Iterator[None]:
    """Stand in for the engine's symbols snapshot.

    The order routes now refuse a symbol whose tick precision has not arrived
    yet: converting a price before it does would apply the two-decimal default
    to an instrument that may not have two decimals. A live gateway registers
    these when it authenticates; these tests call the route functions directly,
    so they register them here.
    """
    clear_tick_registry()
    register_tick_decimals("AAPL", 2)
    register_tick_decimals("MSFT", 2)
    yield
    clear_tick_registry()


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
    wrapped = envelope("order.fill.GW01", {"order_id": "ORD1"})
    assert wrapped["type"] == "order.fill"
    assert wrapped["gateway_id"] == "GW01"


def test_session_caches_apply_events() -> None:
    cache = SessionCaches()
    cache.apply(
        "system.symbols.GW01",
        {"symbols": [{"symbol": "AAPL", "tick_decimals": 2}]},
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
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=150.0,
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
    assert cancel.event is not None
    assert amend["event"] is not None
    assert listed["orders"]
    assert one["order_id"] == "ORD1"


@pytest.mark.anyio
async def test_cancel_and_amend_route_request_tags_are_forwarded() -> None:
    engine = FakeEngine()
    request = fake_request(engine)
    session = trading_session()

    cancel = await orders.cancel_order(
        "ORD1",
        request,
        session,
        wait="ack",
        request_tag="RT-CXL-001",
    )
    amend = await orders.amend_order(
        "ORD1",
        AmendRequest(price=151.0, request_tag="RT-AMD-001"),
        request,
        session,
        wait="ack",
    )

    assert cancel.request_tag == "RT-CXL-001"
    assert amend["request_tag"] == "RT-AMD-001"
    assert ("send_cancel", ("ORD1", "GW01", "RT-CXL-001")) in engine.calls
    assert ("send_amend", ("ORD1", "GW01", 151.0, None, "RT-AMD-001")) in engine.calls
    # A request_tag is present, so C1's fix races the reject topic
    # (await_cancel_or_amend_outcome) rather than only awaiting the success
    # topic — see test_rejected_cancel_is_reported_not_timed_out below for
    # what that buys when the engine actually rejects.
    assert (
        "await_cancel_or_amend_outcome",
        (
            topic_order_cancelled("GW01"),
            "GW01",
            "ORD1",
            "RT-CXL-001",
            request.app.state.config.timeouts.wait_ack_sec,
        ),
    ) in engine.calls
    assert (
        "await_cancel_or_amend_outcome",
        (
            topic_order_amended("GW01"),
            "GW01",
            "ORD1",
            "RT-AMD-001",
            request.app.state.config.timeouts.wait_ack_sec,
        ),
    ) in engine.calls


@pytest.mark.anyio
async def test_d1_client_tag_round_trips_through_rest_order_cache() -> None:
    engine = FakeEngine()
    request = fake_request(engine)
    session = trading_session()
    order_body = OrderRequest(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=150.0,
        client_tag="T1-LM001-001",
    )

    submitted = await orders.submit_order(order_body, request, session)
    sent_order = next(call[1] for call in engine.calls if call[0] == "send_new_order")
    stored = await orders.get_order(sent_order.id, request, session)

    assert sent_order.client_tag == "T1-LM001-001"
    assert submitted.client_tag == "T1-LM001-001"
    assert stored["client_tag"] == "T1-LM001-001"


@pytest.mark.anyio
async def test_rejected_order_ack_flows_through_rest_wait_response() -> None:
    engine = RejectedAckEngine()
    request = fake_request(engine)
    session = trading_session()
    order_body = OrderRequest(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=150.0,
        client_tag="REST-ORDER-001",
    )

    submitted = await orders.submit_order(order_body, request, session, wait="ack")

    assert submitted.accepted is False
    assert submitted.reject_code == "COLLAR_BREACH"
    assert submitted.client_tag == "REST-ORDER-001"
    assert submitted.event is not None
    assert submitted.event["reject_code"] == "COLLAR_BREACH"
    assert submitted.event["client_tag"] == "REST-ORDER-001"


@pytest.mark.anyio
async def test_replace_order_and_error_paths() -> None:
    request = fake_request(FakeEngine())
    session = trading_session()
    order_body = OrderRequest(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=150.0,
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
        leg1=OcoLegRequest(side=Side.SELL, order_type=OrderType.LIMIT, price=151.0),
        leg2=OcoLegRequest(side=Side.SELL, order_type=OrderType.STOP, stop_price=149.0),
    )
    combo = ComboRequest(
        combo_id="C1",
        legs=[
            ComboLegRequest(symbol="AAPL", side=Side.BUY, quantity=10, price=150.0),
            ComboLegRequest(symbol="MSFT", side=Side.SELL, quantity=5, price=410.0),
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
    assert await reference.halts(request, session)
    assert await reference.quote_bootstrap(request, session)
    engine.cache.quote_legs["Q1"] = {"quote_id": "Q1"}
    assert (await reference.quote_legs(request, session))["legs"]
    engine.cache.last_prices["AAPL"] = 151.0
    result = await reference.positions(request, session)
    assert result["positions"] == [
        {"symbol": "AAPL", "net_qty": 5, "last_price": 151.0}
    ]
    assert ("request_position", "GW01") in engine.calls
    engine.cache.positions["AAPL"] = 5
    summary = await reference.status_summary(request, session)
    assert summary["positions"]
    assert summary["gateway_role"] == "TRADER"
    assert (await reference.healthz(request))["ok"] is True  # test double


@pytest.mark.anyio
async def test_positions_reads_engine_not_local_cache() -> None:
    """M4: GET /positions must be a genuine engine round trip, not this
    gateway process's own local fill cache -- which reads flat after a
    restart even though the engine still holds the position (the review's
    exact scenario). engine.cache.positions is left empty here (as it would
    be right after a restart) while the engine's own snapshot reports a real
    holding; the route must report the engine's number, not zero/empty."""
    engine = FakeEngine()
    request = fake_request(engine)
    session = trading_session()
    engine.cache.last_prices["AAPL"] = 151.0
    assert engine.cache.positions == {}
    result = await reference.positions(request, session)
    assert result["positions"] == [
        {"symbol": "AAPL", "net_qty": 5, "last_price": 151.0}
    ]


@pytest.mark.anyio
async def test_positions_empty_reply_renders_empty_list() -> None:
    class FlatEngine(FakeEngine):
        async def await_event(
            self, topic: str, match: dict[str, str] | None, timeout: float
        ) -> dict[str, Any]:
            if topic.startswith("system.position_snapshot."):
                return {"positions": []}
            return await super().await_event(topic, match, timeout)

    engine = FlatEngine()
    request = fake_request(engine)
    session = trading_session()
    result = await reference.positions(request, session)
    assert result == {"positions": []}


@pytest.mark.anyio
async def test_list_orders_timeout_falls_back_to_cache() -> None:
    engine = TimeoutEngine()
    engine.cache.orders["ORD1"] = {"order_id": "ORD1", "status": "NEW"}
    request = fake_request(engine)
    session = trading_session()
    result = await orders.list_orders(request, session)
    assert result["orders"] == [
        {
            "order_id": "ORD1",
            "status": "NEW",
            "client_tag": None,
        }
    ]


@pytest.mark.anyio
async def test_healthz_reports_unhealthy_when_not_running() -> None:
    class StoppedEngine(FakeEngine):
        def is_running(self) -> bool:
            return False

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                engine=StoppedEngine(),
                config=ApiGatewayConfig(),
                rate_limiter=RateLimiter(100, 100),
            )
        )
    )
    result = await reference.healthz(request)  # type: ignore[arg-type]  # test double
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# C1 — a rejected cancel/amend must not be reported as a timeout, and the
# route response must say REJECTED rather than the misleading PENDING_*/ACKED
# it used to return regardless of what the engine actually decided.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_rejected_cancel_is_reported_not_timed_out() -> None:
    engine = RejectedCancelOrAmendEngine()
    request = fake_request(engine)
    session = trading_session()

    cancelled = await orders.cancel_order(
        "ORD1", request, session, wait="ack", request_tag="RT-CXL-001"
    )

    assert cancelled.status == "REJECTED"
    assert cancelled.accepted is False
    assert cancelled.reject_code == "COLLAR_BREACH"
    assert cancelled.event is not None
    assert cancelled.event["accepted"] is False
    assert (
        "await_cancel_or_amend_outcome",
        (
            topic_order_cancelled("GW01"),
            "GW01",
            "ORD1",
            "RT-CXL-001",
            request.app.state.config.timeouts.wait_ack_sec,
        ),
    ) in engine.calls


@pytest.mark.anyio
async def test_rejected_amend_is_reported_not_timed_out() -> None:
    engine = RejectedCancelOrAmendEngine()
    request = fake_request(engine)
    session = trading_session()

    amended = await orders.amend_order(
        "ORD1",
        AmendRequest(price=151.0, request_tag="RT-AMD-001"),
        request,
        session,
        wait="ack",
    )

    assert amended["status"] == "REJECTED"
    assert amended["accepted"] is False
    assert amended["reject_code"] == "COLLAR_BREACH"
    assert amended["event"]["accepted"] is False


@pytest.mark.anyio
async def test_accepted_cancel_still_reports_acked() -> None:
    engine = FakeEngine()
    request = fake_request(engine)
    session = trading_session()

    cancelled = await orders.cancel_order(
        "ORD1", request, session, wait="ack", request_tag="RT-CXL-002"
    )

    assert cancelled.status == "ACKED"
    assert cancelled.accepted is True
    assert cancelled.reject_code is None


@pytest.mark.anyio
async def test_accepted_amend_still_reports_acked() -> None:
    engine = FakeEngine()
    request = fake_request(engine)
    session = trading_session()

    amended = await orders.amend_order(
        "ORD1",
        AmendRequest(price=151.0, request_tag="RT-AMD-002"),
        request,
        session,
        wait="ack",
    )

    assert amended["status"] == "ACKED"
    assert amended["accepted"] is True
    assert amended["reject_code"] is None


@pytest.mark.anyio
async def test_cancel_wait_ack_without_request_tag_falls_back_to_single_topic() -> None:
    """No request_tag means nothing safe to race the reject topic on — this
    keeps the pre-C1-fix behaviour (single-topic wait) rather than guessing."""
    engine = FakeEngine()
    request = fake_request(engine)
    session = trading_session()

    cancelled = await orders.cancel_order("ORD1", request, session, wait="ack")

    assert cancelled.status == "ACKED"
    assert (
        "await_event",
        (
            topic_order_cancelled("GW01"),
            {"order_id": "ORD1"},
            request.app.state.config.timeouts.wait_ack_sec,
        ),
    ) in engine.calls
    assert not any(call[0] == "await_cancel_or_amend_outcome" for call in engine.calls)


@pytest.mark.anyio
async def test_cancel_wait_ack_timeout_still_surfaces_503_with_request_tag() -> None:
    engine = TimeoutEngine()
    request = fake_request(engine)
    session = trading_session()

    with pytest.raises(Exception):
        await orders.cancel_order(
            "ORD1", request, session, wait="ack", request_tag="RT-CXL-003"
        )


@pytest.mark.anyio
async def test_cancel_without_wait_does_not_call_the_racing_wait() -> None:
    engine = FakeEngine()
    request = fake_request(engine)
    session = trading_session()

    cancelled = await orders.cancel_order(
        "ORD1", request, session, request_tag="RT-CXL-004"
    )

    assert cancelled.event is None
    assert cancelled.status == "PENDING_CANCEL"
    assert not any(call[0] == "await_cancel_or_amend_outcome" for call in engine.calls)
