from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn
from fastapi import HTTPException, WebSocketDisconnect, status

from edumatcher.api_gateway import engine_client, main
from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.routers import history, ws
from edumatcher.api_gateway.sessions import Session, SessionRegistry, auth
from edumatcher.models.message import make_gateway_auth_msg


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []
        self.closed = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self, linger: int = 0) -> None:
        _ = linger
        self.closed = True


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_engine_client_auth_send_and_event_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    push = FakeSocket()
    sub = FakeSocket()
    monkeypatch.setattr(engine_client, "make_pusher", lambda _addr: push)
    monkeypatch.setattr(engine_client, "make_subscriber", lambda _addr, *_topics: sub)
    client = EngineClient("pull", "pub", asyncio.get_running_loop())

    auth_task = asyncio.create_task(client.authenticate("GW01"))
    await asyncio.sleep(0)
    client._handle_event("system.gateway_auth.GW01", {"accepted": True})
    assert await auth_task == (True, "")
    assert "GW01" in client.active_gateways()

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    client.add_sink("GW01", queue)
    client._handle_event(
        "order.ack.GW01",
        {"order_id": "ORD1", "accepted": True, "symbol": "AAPL", "side": "BUY"},
    )
    assert (await queue.get())["type"] == "order.ack"
    assert client.get_caches("GW01").orders["ORD1"]["status"] == "NEW"
    client.remove_sink("GW01", queue)

    md_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    client.add_market_data_sink(md_queue)
    client._handle_event("trade.executed", {"symbol": "AAPL", "price": 150.0})
    assert (await md_queue.get())["type"] == "trade"
    client.remove_market_data_sink(md_queue)

    client.send_cancel("ORD1", "GW01")
    client.send_amend("ORD1", "GW01", 151.0, 10)
    client.send_combo({"combo_id": "C1"})
    client.send_combo_cancel("C1", "GW01")
    client.send_oco({"oco_id": "O1"})
    client.send_oco_cancel("O1", "GW01")
    client.send_quote({"quote_id": "Q1"})
    client.send_quote_cancel("GW01", "AAPL")
    client.send_mass_cancel("GW01", "AAPL")
    client.request_orders("GW01")
    client.request_symbols("GW01")
    client.request_session("GW01")
    client.request_quote_bootstrap("GW01")
    client.request_quote_legs("GW01")
    client.send_disconnect("GW01", "test")
    assert len(push.sent) >= 14
    client.stop_listener()
    assert push.closed is True
    assert sub.closed is True


@pytest.mark.anyio
async def test_engine_client_auth_reject_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_client, "make_pusher", lambda _addr: FakeSocket())
    monkeypatch.setattr(
        engine_client, "make_subscriber", lambda _addr, *_topics: FakeSocket()
    )
    client = EngineClient("pull", "pub", asyncio.get_running_loop())
    task = asyncio.create_task(client.authenticate("GW02"))
    await asyncio.sleep(0)
    client._handle_event(
        "system.gateway_auth.GW02", {"accepted": False, "reason": "no"}
    )
    assert await task == (False, "no")
    client.stop_listener()


@pytest.mark.anyio
async def test_resolve_pending_does_not_broadcast_to_all_unmatched_waiters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two concurrent match=None waiters on the same topic (e.g. two
    mass-cancel calls whose ack carries no per-call identifier) must each
    resolve off a distinct event — not both resolve off whichever event
    arrives first, which would silently hand the second caller the first
    caller's result.
    """
    monkeypatch.setattr(engine_client, "make_pusher", lambda _addr: FakeSocket())
    monkeypatch.setattr(
        engine_client, "make_subscriber", lambda _addr, *_topics: FakeSocket()
    )
    client = EngineClient("pull", "pub", asyncio.get_running_loop())

    task_a = asyncio.create_task(client.await_topic("risk.kill_switch_ack.GW01", 2.0))
    await asyncio.sleep(0)
    task_b = asyncio.create_task(client.await_topic("risk.kill_switch_ack.GW01", 2.0))
    await asyncio.sleep(0)

    client._handle_event("risk.kill_switch_ack.GW01", {"accepted": True, "call": 1})
    for _ in range(20):
        if task_a.done():
            break
        await asyncio.sleep(0)
    assert task_a.done()
    assert not task_b.done()
    assert (await task_a)["call"] == 1

    client._handle_event("risk.kill_switch_ack.GW01", {"accepted": True, "call": 2})
    assert (await task_b)["call"] == 2
    client.stop_listener()


@pytest.mark.anyio
async def test_resolve_pending_match_disambiguates_concurrent_symbol_waiters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two concurrent match={"symbol": ...} waiters for different symbols on
    the same ack topic (e.g. two admin circuit-breaker calls) must each get
    only the event for their own symbol, regardless of arrival order.
    """
    monkeypatch.setattr(engine_client, "make_pusher", lambda _addr: FakeSocket())
    monkeypatch.setattr(
        engine_client, "make_subscriber", lambda _addr, *_topics: FakeSocket()
    )
    client = EngineClient("pull", "pub", asyncio.get_running_loop())

    task_aapl = asyncio.create_task(
        client.await_event(
            "risk.symbol_halt_ack.GW01", match={"symbol": "AAPL"}, timeout=2.0
        )
    )
    await asyncio.sleep(0)
    task_msft = asyncio.create_task(
        client.await_event(
            "risk.symbol_halt_ack.GW01", match={"symbol": "MSFT"}, timeout=2.0
        )
    )
    await asyncio.sleep(0)

    # MSFT's ack arrives first — must not resolve the AAPL waiter.
    client._handle_event(
        "risk.symbol_halt_ack.GW01", {"accepted": True, "symbol": "MSFT"}
    )
    for _ in range(20):
        if task_msft.done():
            break
        await asyncio.sleep(0)
    assert task_msft.done()
    assert not task_aapl.done()

    client._handle_event(
        "risk.symbol_halt_ack.GW01", {"accepted": True, "symbol": "AAPL"}
    )
    assert (await task_aapl)["symbol"] == "AAPL"
    assert (await task_msft)["symbol"] == "MSFT"
    client.stop_listener()


@pytest.mark.anyio
async def test_send_and_await_kill_switch_serializes_per_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """risk.kill_switch_ack carries no per-call identifier, so concurrent
    mass-cancel calls for the same gateway must be serialized rather than
    raced — the second call's request must not even be sent until the
    first call's ack has been consumed.
    """
    push = FakeSocket()
    monkeypatch.setattr(engine_client, "make_pusher", lambda _addr: push)
    monkeypatch.setattr(
        engine_client, "make_subscriber", lambda _addr, *_topics: FakeSocket()
    )
    client = EngineClient("pull", "pub", asyncio.get_running_loop())

    task_a = asyncio.create_task(client.send_and_await_kill_switch("GW01", "", 2.0))
    await asyncio.sleep(0)
    task_b = asyncio.create_task(client.send_and_await_kill_switch("GW01", "AAPL", 2.0))
    await asyncio.sleep(0)

    # Only the first call's mass-cancel should have gone out so far — the
    # second is blocked on the per-gateway lock until the first ack lands.
    assert len(push.sent) == 1

    client._handle_event("risk.kill_switch_ack.GW01", {"accepted": True, "call": 1})
    result_a = await task_a
    assert result_a["call"] == 1

    for _ in range(20):
        if len(push.sent) == 2:
            break
        await asyncio.sleep(0)
    assert len(push.sent) == 2

    client._handle_event("risk.kill_switch_ack.GW01", {"accepted": True, "call": 2})
    result_b = await task_b
    assert result_b["call"] == 2
    client.stop_listener()


def test_config_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # This test is about how CLI flags merge over a configured instance, not
    # about where that instance is read from, so the deployed configuration is
    # stubbed rather than compiled. `pm-api-gwy` now takes its instance from
    # the compiled artifact via load_default_api_gateway_config.
    deployed = ApiGatewayConfig(
        name="desk",
        host="127.0.0.1",
        port=8080,
        credentials=(ApiCredential(api_key="key", gateway_id="GW01"),),
    )
    monkeypatch.setattr(
        main, "load_default_api_gateway_config", lambda instance=None: deployed
    )
    args = argparse.Namespace(
        instance="desk",
        host="0.0.0.0",
        port=9090,
        engine_host="10.0.0.5",
        stats_db=str(tmp_path / "stats.db"),
        log_level="debug",
    )
    cfg = main._config_with_overrides(args)
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9090
    assert cfg.engine_pull_addr == "tcp://10.0.0.5:5555"
    assert cfg.log_level == "debug"
    # --engine-host overrides pm-index's addresses too, since pm-index runs
    # on the same host as pm-engine in this system's deployment model.
    assert cfg.index_pull_addr == "tcp://10.0.0.5:5559"
    assert cfg.index_pub_addr == "tcp://10.0.0.5:5558"


def test_main_cli_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    config = ApiGatewayConfig(host="127.0.0.9", port=9191, log_level="debug")
    monkeypatch.setattr(sys, "argv", ["pm-api-gwy"])
    monkeypatch.setattr(main, "_config_with_overrides", lambda _args: config)
    monkeypatch.setattr(main, "create_app", lambda cfg: {"config": cfg})
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda app, host, port, log_level: calls.append(
            ("run", (app, host, port, log_level))
        ),
    )
    main.main()
    assert calls == [("run", ({"config": config}, "127.0.0.9", 9191, "debug"))]


def test_main_cli_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["pm-api-gwy"])

    def fail(_args: argparse.Namespace) -> ApiGatewayConfig:
        raise ValueError("bad config")

    monkeypatch.setattr(main, "_config_with_overrides", fail)
    with pytest.raises(SystemExit) as excinfo:
        main.main()
    assert excinfo.value.code == 1


def test_main_cli_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["pm-api-gwy"])
    monkeypatch.setattr(
        main, "_config_with_overrides", lambda _args: ApiGatewayConfig(enabled=False)
    )
    with pytest.raises(SystemExit) as excinfo:
        main.main()
    assert excinfo.value.code == 1


@pytest.mark.anyio
async def test_create_app_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEngineClient:
        def __init__(self, pull_addr: str, pub_addr: str, loop: Any) -> None:
            self.args = (pull_addr, pub_addr, loop)
            self.started = False
            self.stopped = False
            self.disconnects: list[tuple[str, str]] = []

        def start_listener(self) -> None:
            self.started = True

        def active_gateways(self) -> set[str]:
            return {"GW01"}

        def send_disconnect(self, gateway_id: str, reason: str) -> None:
            self.disconnects.append((gateway_id, reason))

        def stop_listener(self) -> None:
            self.stopped = True

    class FakeIndexClient:
        def __init__(self, pull_addr: str, pub_addr: str, loop: Any) -> None:
            self.args = (pull_addr, pub_addr, loop)
            self.started = False
            self.stopped = False

        def start_listener(self) -> None:
            self.started = True

        def stop_listener(self) -> None:
            self.stopped = True

    monkeypatch.setattr(main, "EngineClient", FakeEngineClient)
    monkeypatch.setattr(main, "IndexClient", FakeIndexClient)
    app = main.create_app(
        ApiGatewayConfig(credentials=(ApiCredential("k", "GW01", ""),))
    )
    async with app.router.lifespan_context(app):
        engine = app.state.engine
        assert engine.started is True
        assert app.state.sessions.get("k") is not None
        # The gateway also needs its own client for pm-index (structural
        # index events), wired up the same way as the engine client — both
        # must be live for the duration of the app, and both must shut down
        # cleanly together.
        index_client = app.state.index_client
        assert index_client.started is True
    assert engine.stopped is True
    assert engine.disconnects == [("GW01", "api gateway shutdown")]
    assert index_client.stopped is True


@pytest.mark.anyio
async def test_auth_dependency_success_and_failures() -> None:
    class AuthEngine:
        async def authenticate(
            self, gateway_id: str, timeout: float = 3.0
        ) -> tuple[bool, str]:
            if gateway_id == "BAD":
                return False, "denied"
            return True, ""

    registry = SessionRegistry(
        (ApiCredential("good", "GW01", "desk"), ApiCredential("bad", "BAD", ""))
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                sessions=registry,
                engine=AuthEngine(),
                config=ApiGatewayConfig(),
            )
        )
    )
    session = await auth(request, "Bearer good")  # type: ignore[arg-type]  # test double
    assert session.gateway_id == "GW01"
    with pytest.raises(Exception):
        await auth(request, "Token nope")  # type: ignore[arg-type]  # test double
    with pytest.raises(Exception):
        await auth(request, "Bearer missing")  # type: ignore[arg-type]  # test double
    with pytest.raises(Exception):
        await auth(request, "Bearer bad")  # type: ignore[arg-type]  # test double


def prepare_history_db(path: Path) -> None:
    """Seed a history DB using the recorder's own DDL.

    Built from ``stats.main.SCHEMA`` rather than a hand-copied duplicate: the
    copy silently drifted out of date twice as columns were added, and each
    time the failure surfaced as an unrelated-looking "no such column" deep in
    a query. Prices are integer ticks, matching what pm-stats writes.
    """
    from edumatcher.stats.main import SCHEMA

    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executescript("""
INSERT INTO order_events (ts,event_type,order_id,gateway_id,symbol) VALUES
('2026-06-24T10:00:00','ACK','ORD1','GW01','AAPL'),
('2026-06-24T10:00:01','FILL','ORD1','GW01','AAPL');
INSERT INTO trade_log (ts,trade_id,symbol,price,quantity,tick_decimals,
                       buy_gateway_id,sell_gateway_id,aggressor_side)
VALUES ('2026-06-24T10:00:01','TRD1','AAPL',15000,10,2,'GW01','GW02','BUY');
INSERT INTO daily_stats (date,symbol,open_price,high_price,low_price,close_price,
                         volume,trade_count,turnover,vwap,largest_trade_qty,
                         largest_trade_price,tick_decimals)
VALUES ('2026-06-24','AAPL',15000,15100,14900,15050,10,1,150000,15000,10,15000,2);
""")
    conn.commit()
    conn.close()


@pytest.mark.anyio
async def test_history_routes(tmp_path: Path) -> None:
    db_path = tmp_path / "stats.db"
    prepare_history_db(db_path)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(config=ApiGatewayConfig(stats_db=db_path))
        )
    )
    session = Session(api_key="key", gateway_id="GW01", description="")
    assert (
        await history.history_orders(  # test double
            request,  # type: ignore[arg-type]
            session,
            symbol=None,
            event_type=None,
            date=None,
            from_ts=None,
            to_ts=None,
            limit=500,
        )
    )["count"] == 2
    assert (
        await history.history_order_lifecycle("ORD1", request, session)  # type: ignore[arg-type]  # test double
    )["count"] == 2
    assert (
        await history.history_fills(  # test double
            request,  # type: ignore[arg-type]
            session,
            symbol=None,
            date=None,
            from_ts=None,
            to_ts=None,
            limit=500,
        )
    )["count"] == 1
    assert (
        await history.history_trades(  # test double
            request,  # type: ignore[arg-type]
            session,
            symbol=None,
            date=None,
            from_ts=None,
            to_ts=None,
            limit=500,
        )
    )["count"] == 1
    assert (
        await history.history_daily(  # test double
            request,  # type: ignore[arg-type]
            session,
            symbol=None,
            date=None,
            # Called as a plain coroutine, so FastAPI is not here to resolve
            # the Query() defaults these two carry for their from/to aliases.
            from_date=None,
            to_date=None,
            limit=500,
        )
    )["count"] == 1


def test_websocket_helper_functions() -> None:
    assert ws._event_channel("trade") == "trades"
    assert ws._event_channel("book") == "book"
    assert ws._event_channel("unknown") is None
    assert (
        ws._topic_from_event({"type": "book", "data": {"symbol": "AAPL"}})
        == "book.AAPL"
    )
    assert (
        ws._topic_from_event({"type": "depth", "data": {"symbol": "AAPL"}})
        == "depth.AAPL"
    )
    assert ws._topic_from_event({"type": "trade", "data": {}}) == "trade.executed"
    assert ws._topic_from_event({"type": "session", "data": {}}) == "session.state"
    assert (
        ws._topic_from_event({"type": "circuit_breaker", "data": {}})
        == "circuit_breaker.event"
    )


@pytest.mark.anyio
async def test_websocket_auth_controls_and_filtering() -> None:
    class FakeWebSocket:
        def __init__(self, messages: list[Any]) -> None:
            self.messages = messages
            self.sent: list[Any] = []
            self.closed: list[int] = []
            self.app = SimpleNamespace(
                state=SimpleNamespace(
                    sessions=SessionRegistry.from_config(
                        ApiGatewayConfig(
                            credentials=(ApiCredential("key", "GW01", "test"),)
                        )
                    )
                )
            )

        async def receive_json(self) -> Any:
            if not self.messages:
                raise WebSocketDisconnect()
            return self.messages.pop(0)

        async def send_json(self, value: Any) -> None:
            self.sent.append(value)

        async def close(self, code: int) -> None:
            self.closed.append(code)

    authenticated = FakeWebSocket([{"api_key": "key"}])
    assert await ws._authenticate_ws(authenticated) == ("key", "GW01")  # type: ignore[arg-type]  # test double

    rejected = FakeWebSocket([{"api_key": "bad"}])
    with pytest.raises(WebSocketDisconnect):
        await ws._authenticate_ws(rejected)  # type: ignore[arg-type]  # test double
    assert rejected.closed == [status.WS_1008_POLICY_VIOLATION]

    controls = FakeWebSocket(
        [
            {"action": "subscribe", "symbols": ["aapl"], "channels": ["trades"]},
            {"action": "unsubscribe", "symbols": ["AAPL"], "channels": ["trades"]},
            {"action": "bad", "symbols": [], "channels": []},
        ]
    )
    symbols: set[str] = set()
    channels: set[str] = set()
    with pytest.raises(WebSocketDisconnect):
        await ws._receive_market_controls(controls, symbols, channels)  # type: ignore[arg-type]  # test double
    assert controls.sent[0]["data"] == {"symbols": ["AAPL"], "channels": ["trades"]}
    assert controls.sent[1]["data"] == {"symbols": [], "channels": []}
    assert controls.sent[2]["type"] == "error"

    sender = FakeWebSocket([])
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    task = asyncio.create_task(
        ws._send_market_data(sender, queue, {"AAPL"}, {"trades"})  # type: ignore[arg-type]  # test double
    )
    await queue.put({"type": "session", "data": {}})
    await queue.put({"type": "trade", "data": {"symbol": "AAPL"}})
    await queue.put({"type": "trade", "data": {"symbol": "MSFT"}})
    for _ in range(20):
        if len(sender.sent) >= 2:
            break
        await asyncio.sleep(0)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    assert [event["type"] for event in sender.sent] == ["session", "trade"]


def test_message_builder_import() -> None:
    frames = make_gateway_auth_msg("GW01", True)
    assert frames[0] == b"system.gateway_auth.GW01"


@pytest.mark.anyio
async def test_await_event_filters_by_order_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that await_event only resolves for a matching order_id."""
    monkeypatch.setattr(engine_client, "make_pusher", lambda _addr: FakeSocket())
    monkeypatch.setattr(
        engine_client, "make_subscriber", lambda _addr, *_topics: FakeSocket()
    )
    client = EngineClient("pull", "pub", asyncio.get_running_loop())

    # Pre-authenticate so we can skip the handshake
    client._authenticated.add("GW01")

    # Register a future waiting for a specific order_id
    task = asyncio.create_task(
        client.await_event("order.ack.GW01", match={"order_id": "ORD-A"}, timeout=2.0)
    )
    await asyncio.sleep(0)

    # Deliver an ack for a DIFFERENT order — should NOT resolve the future
    client._handle_event("order.ack.GW01", {"order_id": "ORD-B", "accepted": True})
    await asyncio.sleep(0)
    assert not task.done()

    # Now deliver the matching one
    client._handle_event("order.ack.GW01", {"order_id": "ORD-A", "accepted": True})
    result = await task
    assert result["order_id"] == "ORD-A"
    client.stop_listener()


@pytest.mark.anyio
async def test_await_event_timeout_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify timed-out futures are removed from _pending."""
    monkeypatch.setattr(engine_client, "make_pusher", lambda _addr: FakeSocket())
    monkeypatch.setattr(
        engine_client, "make_subscriber", lambda _addr, *_topics: FakeSocket()
    )
    client = EngineClient("pull", "pub", asyncio.get_running_loop())
    client._authenticated.add("GW01")

    with pytest.raises(TimeoutError):
        await client.await_event(
            "order.ack.GW01", match={"order_id": "NEVER"}, timeout=0.01
        )

    # _pending should be cleaned up
    assert "order.ack.GW01" not in client._pending
    client.stop_listener()


@pytest.mark.anyio
async def test_history_validation_rejects_bad_dates() -> None:
    """Verify malformed date parameters return 422."""
    from edumatcher.api_gateway.routers import history as hist_router

    db_path = Path("/tmp/nonexist_test.db")
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(config=ApiGatewayConfig(stats_db=db_path))
        )
    )
    session = Session(api_key="key", gateway_id="GW01", description="")
    with pytest.raises(HTTPException) as exc_info:
        await hist_router.history_orders(
            request,  # type: ignore[arg-type]
            session,
            symbol=None,
            event_type=None,
            date="not-a-date",
            from_ts=None,
            to_ts=None,
            limit=500,
        )
    assert exc_info.value.status_code == 422
