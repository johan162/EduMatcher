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
from fastapi import WebSocketDisconnect, status

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


def test_config_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "engine_config.yaml"
    config_path.write_text("""
api_gateways:
  desk:
    host: 127.0.0.1
    port: 8080
    credentials:
      - api_key: key
        gateway_id: GW01
""")
    args = argparse.Namespace(
        config=str(config_path),
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


def test_main_cli_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    config = ApiGatewayConfig(host="127.0.0.9", port=9191, log_level="debug")
    monkeypatch.setattr(sys, "argv", ["pm-api-gateway"])
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
    monkeypatch.setattr(sys, "argv", ["pm-api-gateway"])

    def fail(_args: argparse.Namespace) -> ApiGatewayConfig:
        raise ValueError("bad config")

    monkeypatch.setattr(main, "_config_with_overrides", fail)
    with pytest.raises(SystemExit) as excinfo:
        main.main()
    assert excinfo.value.code == 1


def test_main_cli_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["pm-api-gateway"])
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

    monkeypatch.setattr(main, "EngineClient", FakeEngineClient)
    app = main.create_app(
        ApiGatewayConfig(credentials=(ApiCredential("k", "GW01", ""),))
    )
    async with app.router.lifespan_context(app):
        engine = app.state.engine
        assert engine.started is True
        assert app.state.sessions.get("k") is not None
    assert engine.stopped is True
    assert engine.disconnects == [("GW01", "api gateway shutdown")]


@pytest.mark.anyio
async def test_auth_dependency_success_and_failures() -> None:
    class AuthEngine:
        async def authenticate(self, gateway_id: str) -> tuple[bool, str]:
            if gateway_id == "BAD":
                return False, "denied"
            return True, ""

    registry = SessionRegistry(
        (ApiCredential("good", "GW01", "desk"), ApiCredential("bad", "BAD", ""))
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(sessions=registry, engine=AuthEngine())
        )
    )
    session = await auth(request, "Bearer good")
    assert session.gateway_id == "GW01"
    with pytest.raises(Exception):
        await auth(request, "Token nope")
    with pytest.raises(Exception):
        await auth(request, "Bearer missing")
    with pytest.raises(Exception):
        await auth(request, "Bearer bad")


def prepare_history_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
CREATE TABLE order_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, event_type TEXT, order_id TEXT,
    gateway_id TEXT, symbol TEXT, side TEXT, order_type TEXT, tif TEXT, price REAL,
    quantity INTEGER, remaining_qty INTEGER, status TEXT, fill_price REAL,
    fill_qty INTEGER, trade_id TEXT, reason TEXT, client_order_id TEXT,
    combo_parent_id TEXT, oco_group_id TEXT, priority_reset INTEGER
);
CREATE TABLE trade_log (
    ts TEXT, trade_id TEXT, symbol TEXT, price REAL, quantity INTEGER,
    buy_gateway_id TEXT, sell_gateway_id TEXT
);
CREATE TABLE daily_stats (
    date TEXT, symbol TEXT, open_price REAL, high_price REAL, low_price REAL,
    close_price REAL, open_bid REAL, open_ask REAL, close_bid REAL, close_ask REAL,
    volume INTEGER, trade_count INTEGER, vwap REAL, largest_trade_qty INTEGER,
    largest_trade_price REAL
);
INSERT INTO order_events (ts,event_type,order_id,gateway_id,symbol) VALUES
('2026-06-24T10:00:00','ACK','ORD1','GW01','AAPL'),
('2026-06-24T10:00:01','FILL','ORD1','GW01','AAPL');
INSERT INTO trade_log VALUES ('2026-06-24T10:00:01','TRD1','AAPL',150.0,10,'GW01','GW02');
INSERT INTO daily_stats VALUES ('2026-06-24','AAPL',150,151,149,150.5,NULL,NULL,NULL,NULL,10,1,150,10,150);
""")
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
        await history.history_orders(
            request,
            session,
            symbol=None,
            event_type=None,
            date=None,
            from_ts=None,
            to_ts=None,
            limit=500,
        )
    )["count"] == 2
    assert (await history.history_order_lifecycle("ORD1", request, session))[
        "count"
    ] == 2
    assert (
        await history.history_fills(
            request,
            session,
            symbol=None,
            date=None,
            from_ts=None,
            to_ts=None,
            limit=500,
        )
    )["count"] == 1
    assert (
        await history.history_trades(
            request,
            session,
            symbol=None,
            date=None,
            from_ts=None,
            to_ts=None,
            limit=500,
        )
    )["count"] == 1
    assert (
        await history.history_daily(
            request,
            session,
            symbol=None,
            date=None,
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
    assert await ws._authenticate_ws(authenticated) == ("key", "GW01")

    rejected = FakeWebSocket([{"api_key": "bad"}])
    with pytest.raises(WebSocketDisconnect):
        await ws._authenticate_ws(rejected)
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
        await ws._receive_market_controls(controls, symbols, channels)
    assert controls.sent[0]["data"] == {"symbols": ["AAPL"], "channels": ["trades"]}
    assert controls.sent[1]["data"] == {"symbols": [], "channels": []}
    assert controls.sent[2]["type"] == "error"

    sender = FakeWebSocket([])
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    task = asyncio.create_task(
        ws._send_market_data(sender, queue, {"AAPL"}, {"trades"})
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
