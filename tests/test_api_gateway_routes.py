from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException, Response

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
from edumatcher.clearing import query as clearing_query
from edumatcher.compdb import store as compdb
from edumatcher.models.generated.order import topic_order_amended, topic_order_cancelled
from edumatcher.models.order import OrderType, Side
from edumatcher.models.price import clear_tick_registry, register_tick_decimals
from tests.api_gateway_harness import check_contract


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
        if topic.startswith("system.quote_legs."):
            return {
                "legs": [{"quote_id": "Q1", "side": "BUY"}],
                "show_requested": "ALL",
                "complete": True,
                "recent": [],
            }
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
            "fill_price": 150.0,
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
    assert len(cache.orders) == 2


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
    submitted = await orders.submit_order(order_body, request, Response(), session)
    assert submitted.status == "PENDING"
    assert any(call[0] == "send_new_order" for call in engine.calls)

    cancel = await orders.cancel_order("ORD1", request, Response(), session, wait="ack")
    amend = await orders.amend_order(
        "ORD1", AmendRequest(price=151.0), request, Response(), session, wait="ack"
    )
    listed = await orders.list_orders(request, session)
    engine.cache.orders["ORD1"] = {"order_id": "ORD1", "status": "NEW"}
    one = await orders.get_order("ORD1", request, session)
    check_contract(orders.amend_order, amend)
    check_contract(orders.get_order, one)
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
        Response(),
        session,
        wait="ack",
        request_tag="RT-CXL-001",
    )
    amend = await orders.amend_order(
        "ORD1",
        AmendRequest(price=151.0, request_tag="RT-AMD-001"),
        request,
        Response(),
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

    submitted = await orders.submit_order(order_body, request, Response(), session)
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

    submitted = await orders.submit_order(
        order_body, request, Response(), session, wait="ack"
    )

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
    replaced = await orders.replace_order(
        "OLD", order_body, request, Response(), session
    )
    assert replaced.cancelled_order_id == "OLD"

    timed_out = await orders.cancel_order(
        "ORD1", fake_request(TimeoutEngine()), Response(), session, wait="ack"
    )
    assert (timed_out.status, timed_out.ack_timeout) == ("PENDING_CANCEL", True)

    rate_limited = limited_request()
    await orders.cancel_order("ORD1", rate_limited, Response(), session)
    with pytest.raises(Exception):
        await orders.cancel_order("ORD2", rate_limited, Response(), session)


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
    sent = await orders.submit_oco(oco, request, Response(), session)
    assert (sent.oco_id, sent.status) == ("O1", "PENDING")
    check_contract(orders.submit_oco, sent)
    oco_cancel = await orders.cancel_oco("O1", request, session)
    check_contract(orders.cancel_oco, oco_cancel)
    sent_combo = await orders.submit_combo(combo, request, Response(), session)
    assert sent_combo.combo_id == "C1"
    check_contract(orders.submit_combo, sent_combo)
    combo_cancel = await orders.cancel_combo("C1", request, session)
    check_contract(orders.cancel_combo, combo_cancel)
    quoted = await orders.submit_quote(quote, request, Response(), session)
    check_contract(orders.submit_quote, quoted)
    assert (quoted.symbol, quoted.quote_id) == ("AAPL", None)
    quote_cancel = await orders.cancel_quote("aapl", request, session)
    check_contract(orders.cancel_quote, quote_cancel)
    assert quote_cancel["symbol"] == "AAPL"
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
    assert await reference.active_quotes(request, session)
    # Always an engine round trip now, never the leg cache (WP-API04).
    engine.cache.quote_legs["Q1"] = {"quote_id": "Q1"}
    legs = await reference.quote_legs(request, session)
    assert legs["legs"] == [{"quote_id": "Q1", "side": "BUY"}] and legs["count"] == 1
    engine.cache.last_prices["AAPL"] = 151.0
    result = await reference.positions(request, session)
    check_contract(reference.positions, result)
    # No clearing.db in the test environment, so the three realized windows
    # report "unknown" rather than a misleading zero.
    assert result["positions"] == [
        {
            "symbol": "AAPL",
            "net_qty": 5,
            "avg_cost": 150.0,
            "last_price": 151.0,
            "market_value": 755.0,
            "unrealized_pnl": 5.0,
            "realized_pnl_session": None,
            "realized_pnl_mtd": None,
            "realized_pnl_ytd": None,
        }
    ]
    assert ("request_position", "GW01") in engine.calls
    summary = await reference.status_summary(request, session)
    check_contract(reference.status_summary, summary)
    # WP-API04: who-am-I only; the cache counters and the cached (flat after
    # a restart) positions are gone.
    assert summary == {"gateway_id": "GW01", "gateway_role": "TRADER"}
    response = Response()
    assert (await reference.healthz(request, response))["ok"] is True  # test double
    assert response.status_code == 200


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
        {
            "symbol": "AAPL",
            "net_qty": 5,
            "avg_cost": 150.0,
            "last_price": 151.0,
            "market_value": 755.0,
            "unrealized_pnl": 5.0,
            "realized_pnl_session": None,
            "realized_pnl_mtd": None,
            "realized_pnl_ytd": None,
        }
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
    assert result == {"positions": [], "count": 0}


@pytest.mark.anyio
async def test_list_orders_timeout_is_503_not_the_cache() -> None:
    """WP-API05 (R4): an engine timeout used to fall back to the gateway's
    cache without saying so, while every other engine-backed read -- and
    bootstrap, deliberately -- answers 503. A cached list a client cannot
    tell apart from the engine's is the stale-state risk bootstrap refuses."""
    engine = TimeoutEngine()
    engine.cache.orders["ORD1"] = {"order_id": "ORD1", "status": "NEW"}
    request = fake_request(engine)
    session = trading_session()
    with pytest.raises(HTTPException) as exc:
        await orders.list_orders(request, session)
    assert exc.value.status_code == 503
    assert cast(dict[str, Any], exc.value.detail)["error"]["code"] == "ENGINE_TIMEOUT"


@pytest.mark.anyio
async def test_rate_limit_log_does_not_carry_the_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """WP-API05 (O1): the bearer key is the only credential, so it must never
    reach a log record -- the gateway id identifies the caller instead."""
    session = Session(api_key="sekrit-key-123", gateway_id="GW01", description="")
    request = limited_request()
    request.app.state.rate_limiter.allow(session.api_key)  # spend the burst
    with caplog.at_level("DEBUG", logger=orders.log.name):
        with pytest.raises(HTTPException) as exc:
            orders._check_rate_limit(
                request, session
            )  # pyright: ignore[reportPrivateUsage]
    assert exc.value.status_code == 429
    assert "sekrit-key-123" not in caplog.text
    assert "GW01" in caplog.text


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
    response = Response()
    result = await reference.healthz(request, response)  # type: ignore[arg-type]  # test double
    assert result["ok"] is False
    # WP-API05 (O2): probes read the status code, not the body.
    assert response.status_code == 503


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
        "ORD1", request, Response(), session, wait="ack", request_tag="RT-CXL-001"
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
        Response(),
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
        "ORD1", request, Response(), session, wait="ack", request_tag="RT-CXL-002"
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
        Response(),
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

    cancelled = await orders.cancel_order(
        "ORD1", request, Response(), session, wait="ack"
    )

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
async def test_cancel_wait_ack_timeout_with_request_tag_is_pending() -> None:
    """WP-API02 (E7): the cancel was sent, so a timeout is not an error."""
    engine = TimeoutEngine()
    request = fake_request(engine)
    session = trading_session()
    response = Response()

    cancelled = await orders.cancel_order(
        "ORD1", request, response, session, wait="ack", request_tag="RT-CXL-003"
    )
    assert (cancelled.status, cancelled.ack_timeout) == ("PENDING_CANCEL", True)
    check_contract(orders.cancel_order, cancelled)


@pytest.mark.anyio
async def test_cancel_without_wait_does_not_call_the_racing_wait() -> None:
    engine = FakeEngine()
    request = fake_request(engine)
    session = trading_session()

    cancelled = await orders.cancel_order(
        "ORD1", request, Response(), session, request_tag="RT-CXL-004"
    )

    assert cancelled.event is None
    assert cancelled.status == "PENDING_CANCEL"
    assert not any(call[0] == "await_cancel_or_amend_outcome" for call in engine.calls)


# ── Period realized P&L from clearing.db ──────────────────────────────────────


def _clearing_db(path: Path, rows: list[tuple[str, str, float, int]]) -> Path:
    """Minimal clearing ledger holding just what /positions reads."""
    db = path / "clearing.db"
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("CREATE TABLE clearing_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO clearing_meta VALUES ('session_timezone', 'Europe/Stockholm')"
        )
        conn.execute(
            "CREATE TABLE gateway_daily_summary ("
            " trade_date TEXT, gateway_id TEXT, symbol TEXT,"
            " realized_pnl REAL, tick_decimals INTEGER)"
        )
        conn.executemany(
            "INSERT INTO gateway_daily_summary VALUES (?, 'GW01', ?, ?, ?)", rows
        )
    conn.close()
    return db


def _ledger_today() -> str:
    """Today in the ledger's session timezone, which is what the query
    resolves its windows in -- the server's own date drifts from it either
    side of midnight and would make these tests flaky."""
    return datetime.now(ZoneInfo("Europe/Stockholm")).date().isoformat()


def test_period_realized_pnl_splits_today_month_and_year(tmp_path: Path) -> None:
    """Three windows over one symbol's history, each a superset of the last."""
    db = _clearing_db(
        tmp_path,
        [
            ("2026-01-05", "AAPL", 10_000.0, 2),  # earlier this year
            ("2026-10-02", "AAPL", 20_000.0, 2),  # earlier this month
            ("2026-10-15", "AAPL", 40_000.0, 2),  # today
        ],
    )
    conn = clearing_query.open_readonly_connection(db)
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    out = clearing_query.query_period_realized_pnl(conn, gateway_id="GW01", now=now)
    conn.close()

    # Stored in integer ticks; tick_decimals 2 makes 40_000 ticks 400.00.
    assert out["AAPL"].session == pytest.approx(400.0)
    assert out["AAPL"].mtd == pytest.approx(600.0)
    assert out["AAPL"].ytd == pytest.approx(700.0)


def test_period_realized_pnl_excludes_last_year(tmp_path: Path) -> None:
    """YTD is year-to-date, not lifetime -- that was the whole objection to
    reporting clearing's cumulative figure."""
    db = _clearing_db(
        tmp_path,
        [
            ("2025-12-31", "AAPL", 99_000.0, 2),
            ("2026-10-15", "AAPL", 1_000.0, 2),
        ],
    )
    conn = clearing_query.open_readonly_connection(db)
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    out = clearing_query.query_period_realized_pnl(conn, gateway_id="GW01", now=now)
    conn.close()

    assert out["AAPL"].ytd == pytest.approx(10.0)


def test_period_realized_pnl_scales_per_symbol_tick_decimals(tmp_path: Path) -> None:
    """Each symbol carries its own tick size; a shared divisor would render
    one of these 100x off (the CL-H3 failure in the clearing CLI)."""
    db = _clearing_db(
        tmp_path,
        [
            ("2026-10-15", "AAPL", 10_000.0, 2),
            ("2026-10-15", "USDJPY", 10_000.0, 4),
        ],
    )
    conn = clearing_query.open_readonly_connection(db)
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    out = clearing_query.query_period_realized_pnl(conn, gateway_id="GW01", now=now)
    conn.close()

    assert out["AAPL"].session == pytest.approx(100.0)
    assert out["USDJPY"].session == pytest.approx(1.0)


def test_period_boundaries_resolve_in_the_ledgers_timezone(tmp_path: Path) -> None:
    """22:30 UTC is already the next day in Stockholm. Resolving the window
    on the server's clock would put today's trade outside 'today'."""
    db = _clearing_db(tmp_path, [("2026-10-16", "AAPL", 5_000.0, 2)])
    conn = clearing_query.open_readonly_connection(db)
    now = datetime(2026, 10, 15, 22, 30, tzinfo=timezone.utc)
    out = clearing_query.query_period_realized_pnl(conn, gateway_id="GW01", now=now)
    conn.close()

    assert out["AAPL"].session == pytest.approx(50.0)


@pytest.mark.anyio
async def test_positions_reports_realized_pnl_from_clearing(tmp_path: Path) -> None:
    """The point of sourcing realized P&L from the ledger: it survives a
    gateway restart, which wipes every in-memory cache."""
    db = _clearing_db(tmp_path, [(_ledger_today(), "AAPL", 2_500.0, 2)])
    engine = FakeEngine()
    request = fake_request(engine)
    request.app.state.config = ApiGatewayConfig(clearing_db=db)
    session = trading_session()

    result = await reference.positions(request, session)

    row = result["positions"][0]
    assert row["realized_pnl_session"] == pytest.approx(25.0)
    assert row["realized_pnl_ytd"] == pytest.approx(25.0)


@pytest.mark.anyio
async def test_positions_reports_zero_for_a_symbol_with_nothing_closed(
    tmp_path: Path,
) -> None:
    """A reachable ledger with no row for the symbol is a real zero, not an
    unknown -- only a missing ledger is unknown."""
    db = _clearing_db(tmp_path, [(_ledger_today(), "MSFT", 1_000.0, 2)])
    request = fake_request()
    request.app.state.config = ApiGatewayConfig(clearing_db=db)

    result = await reference.positions(request, trading_session())

    assert result["positions"][0]["realized_pnl_session"] == 0.0


@pytest.mark.anyio
async def test_positions_survive_an_unreadable_clearing_db(tmp_path: Path) -> None:
    """Realized P&L is a nicety on a positions row, not the point of it: a
    corrupt or absent ledger must not cost the trader their positions."""
    broken = tmp_path / "clearing.db"
    broken.write_text("not a database")
    request = fake_request()
    request.app.state.config = ApiGatewayConfig(clearing_db=broken)

    result = await reference.positions(request, trading_session())

    assert result["positions"][0]["net_qty"] == 5
    assert result["positions"][0]["realized_pnl_session"] is None


@pytest.fixture
def companies_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "companies.db"
    monkeypatch.setattr(compdb, "COMPANIES_DB", db)
    return db


@pytest.mark.anyio
async def test_company_returns_the_profile_with_derived_columns(
    companies_db: Path,
) -> None:
    compdb.build(companies_db, [r for r in compdb.load_seed() if r["symbol"] == "AAPL"])
    readonly = Session(api_key="ro", gateway_id=None, description="viewer")

    row = await reference.company("aapl", fake_request(), readonly)

    assert row["symbol"] == "AAPL"
    assert row["name"]
    assert row["pe_ratio"] > 0


@pytest.mark.anyio
async def test_company_unknown_symbol_is_404(companies_db: Path) -> None:
    compdb.build(companies_db, [])

    with pytest.raises(HTTPException) as info:
        await reference.company("ZZZ", fake_request(), trading_session())

    assert info.value.status_code == 404
    assert cast(dict[str, Any], info.value.detail)["error"]["code"] == "UNKNOWN_COMPANY"


@pytest.mark.anyio
@pytest.mark.parametrize("content", [None, "not a database"])
async def test_company_without_a_readable_db_is_503(
    companies_db: Path, content: str | None
) -> None:
    if content is not None:
        companies_db.write_text(content)

    with pytest.raises(HTTPException) as info:
        await reference.company("AAPL", fake_request(), trading_session())

    assert info.value.status_code == 503
    detail = cast(dict[str, Any], info.value.detail)
    assert detail["error"]["code"] == "COMPANY_DB_UNAVAILABLE"
