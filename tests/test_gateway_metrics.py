"""Operator dashboard WP-A5: gateway metrics and reporters.

Two layers. Per gateway, the counters move at their real increment sites.
Across all five socket gateways, the *real* ``run()`` loop ticks the reporter
and publishes -- the guard against risk K8 (a gateway whose loop never ticks
would read HUNG for ever).
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from collections import deque
from collections.abc import Callable, MutableMapping, Sequence
from typing import Any

import pytest
import zmq
from fastapi import Request, WebSocket

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway
from edumatcher.api_gateway import main as api_main
from edumatcher.api_gateway.metrics import WS_CHANNELS, ApiMetrics
from edumatcher.balf_gwy.config import BalfGatewayConfig
from edumatcher.balf_gwy.gateway import BalfGateway
from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.dc_gateway.gateway import DcGateway
from edumatcher.health import HealthReporter
from edumatcher.health.samples import gateway_stats_samples
from edumatcher.md_gateway.client_session import ClientSession as MdSession
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway import gateway as md_gateway_module
from edumatcher.md_gateway.gateway import MarketDataGateway
from edumatcher.models.generated.health import MetricSample, parse_health_beacon
from edumatcher.ralf_gateway.config import RalfGatewayConfig
from edumatcher.ralf_gateway.gateway import ClientSession as RalfSession
from edumatcher.ralf_gateway.gateway import RalfGateway
from tests.conftest import free_port


class FakeZmq:
    """A ZMQ socket double the gateways' loops can poll and register."""

    def __init__(self) -> None:
        self.closed = False
        self._r, self._w = os.pipe()  # a real fd for selector.register

    def getsockopt(self, opt: int) -> int:
        return self._r if opt == zmq.FD else 0

    def setsockopt(self, *_a: Any) -> None:
        pass

    def poll(self, *_a: Any, **_k: Any) -> int:
        return 0

    def recv_multipart(self, *_a: Any, **_k: Any) -> list[bytes]:
        raise zmq.Again()

    def send_multipart(self, *_a: Any, **_k: Any) -> None:
        pass

    def close(self, *_a: Any) -> None:
        if not self.closed:
            self.closed = True
            os.close(self._r)
            os.close(self._w)


@pytest.fixture
def fake_zmq(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in ("alf_gwy", "balf_gwy", "md_gateway", "ralf_gateway", "dc_gateway"):
        target = f"edumatcher.{module}.gateway"
        monkeypatch.setattr(f"{target}.make_subscriber", lambda *_a, **_k: FakeZmq())
        if module in ("alf_gwy", "balf_gwy"):
            monkeypatch.setattr(f"{target}.make_pusher", lambda *_a, **_k: FakeZmq())


def _gateways() -> dict[str, Callable[[int], Any]]:
    return {
        "alf": lambda port: AlfGateway(
            AlfGatewayConfig(bind_address="127.0.0.1", port=port)
        ),
        "balf": lambda port: BalfGateway(
            BalfGatewayConfig(bind_address="127.0.0.1", port=port)
        ),
        "md": lambda port: MarketDataGateway(
            MarketDataGatewayConfig(bind_address="127.0.0.1", port=port)
        ),
        "ralf": lambda port: RalfGateway(
            RalfGatewayConfig(bind_address="127.0.0.1", port=port)
        ),
        "dc": lambda port: DcGateway(
            DcGatewayConfig(bind_address="127.0.0.1", port=port)
        ),
    }


def _value(samples: Sequence[MetricSample], name: str, label: str = "") -> float:
    found = [s.value for s in samples if s.name == name and s.label == label]
    assert len(found) == 1, f"{name}{{{label}}}: {found}"
    return found[0]


class RecordingReporter:
    """Stands in for HealthReporter in the loop: records what the loop does."""

    def __init__(self) -> None:
        self.ticks = 0
        self.published: list[list[MetricSample]] = []
        self.stopped = False

    def tick_and_publish(self, samples: Callable[[], Sequence[MetricSample]]) -> None:
        self.ticks += 1
        if self.ticks == 1:
            self.published.append(list(samples()))

    def stop(self) -> None:
        self.stopped = True


# ---------------------------------------------------------------------------
# K8: every socket gateway's real loop ticks and publishes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_gateways()))
def test_the_real_loop_ticks_publishes_and_stops_the_reporter(
    name: str, fake_zmq: None
) -> None:
    gateway = _gateways()[name](free_port())
    reporter = RecordingReporter()
    gateway.attach_reporter(reporter)
    runner = threading.Thread(target=gateway.run, daemon=True)
    runner.start()
    deadline = time.monotonic() + 5
    while reporter.ticks < 20 and time.monotonic() < deadline:
        time.sleep(0.01)
    gateway.stop()
    runner.join(timeout=5)
    assert reporter.ticks >= 20, f"{name}: loop ticked {reporter.ticks} times"
    assert reporter.published and reporter.published[0]
    for sample in reporter.published[0]:
        sample.validate()
    assert reporter.stopped, f"{name}: close() did not stop the reporter"


# ---------------------------------------------------------------------------
# A5.1 ALF / BALF: _global_stats exported as they are
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["alf", "balf"])
def test_global_stats_are_exported_verbatim(name: str, fake_zmq: None) -> None:
    gateway = _gateways()[name](free_port())
    gateway._global_stats["auth_failures"] = 3
    gateway._global_stats["connected_clients"] = 2
    samples = gateway.metric_samples()
    for key, value in gateway._global_stats.items():
        sample = next(s for s in samples if s.name == f"gwy.{key}")
        assert sample.value == value
        assert sample.kind == ("GAUGE" if key == "connected_clients" else "COUNTER")
    assert _value(samples, "gwy.clients_max") == gateway.config.max_connections
    gateway.close()


def test_alf_counts_a_rejected_command(fake_zmq: None) -> None:
    """Driven through the real handler: an unauthenticated command."""
    from edumatcher.alf_gwy.gateway import ClientSession

    gateway = _gateways()["alf"](free_port())
    left, right = socket.socketpair()
    session = ClientSession(sock=left, addr=("local", 0))
    session.rate_tokens = 100.0
    gateway._handle_client_line(session, "SYMBOLS")
    samples = gateway.metric_samples()
    assert _value(samples, "gwy.commands_received_total") == 1
    assert samples == gateway_stats_samples(
        gateway._global_stats, gateway.config.max_connections
    )
    left.close()
    right.close()
    gateway.close()


# ---------------------------------------------------------------------------
# A5.2 MD: messages out, disconnects by reason
# ---------------------------------------------------------------------------


def _md_session() -> tuple[MdSession, socket.socket]:
    left, right = socket.socketpair()
    left.setblocking(False)
    return MdSession(sock=left, addr=("local", 0)), right


def test_md_counts_messages_out_and_a_slow_client(fake_zmq: None) -> None:
    gateway = MarketDataGateway(
        MarketDataGatewayConfig(
            bind_address="127.0.0.1", port=free_port(), max_client_queue=3
        )
    )
    session, peer = _md_session()
    gateway._clients[session.sock.fileno()] = session
    for _ in range(3):
        gateway._queue_line(session, "HB", {})
    assert _value(gateway.metric_samples(), "md.msgs_out") == 3

    # Past max_client_queue with a peer that never reads: more bytes than
    # the socketpair buffer can take, so the queue cannot drain below max.
    session.out_queue = deque([b"x" * 262_144] * 20)
    gateway._flush_client_writes()
    samples = gateway.metric_samples()
    assert _value(samples, "md.slow_clients") == 1
    assert _value(samples, "md.closing_clients") == 1
    assert session.close_reason == "slow_client"

    # It never reads its final ERR; the close grace drops it -- as RALF/DC do.
    session.closing_since -= md_gateway_module.CLOSE_GRACE_SEC + 1
    gateway._flush_client_writes()
    samples = gateway.metric_samples()
    assert _value(samples, "md.disconnects", "slow_client") == 1
    assert _value(samples, "md.clients") == 0
    assert _value(samples, "md.clients_max") == gateway.config.max_connections
    peer.close()
    gateway.close()


# ---------------------------------------------------------------------------
# A5.3 RALF / DC: one shape, and the stuck-client signals (I33)
# ---------------------------------------------------------------------------


def _stream_session(name: str) -> tuple[Any, socket.socket, socket.socket]:
    """A gateway session over a socketpair whose peer never reads."""
    left, right = socket.socketpair()
    left.setblocking(False)
    if name == "dc":
        from edumatcher.dc_gateway.gateway import ClientSession as DcSession

        return DcSession(sock=left, addr=("local", 0)), left, right
    return RalfSession(sock=left, addr=("local", 0)), left, right


def _grace(name: str) -> float:
    import edumatcher.dc_gateway.gateway as dc_mod
    import edumatcher.ralf_gateway.gateway as ralf_mod

    return (dc_mod if name == "dc" else ralf_mod).CLOSE_GRACE_SEC


@pytest.mark.parametrize("name", ["ralf", "dc"])
def test_a_client_that_stops_reading_is_dropped_as_slow(
    name: str, fake_zmq: None
) -> None:
    """Workplan I33, fixed: flagged once, nothing more queued, and
    disconnected once the grace runs out -- as pm-md-gwy drops it."""
    gateway = _gateways()[name](free_port())
    session, left, right = _stream_session(name)
    gateway._clients[left.fileno()] = session
    for _ in range(3):  # three flush passes, the client never reads
        for _ in range(gateway.config.max_client_queue + 5):
            gateway._queue_raw(session, b"x" * 65536)
        gateway._flush_client_writes()

    samples = gateway.metric_samples()
    assert _value(samples, "gwy.slow_clients") == 1  # once, not once per pass
    assert _value(samples, "gwy.closing_clients") == 1
    assert len(session.out_queue) <= 2  # backlog dropped; no growth after
    assert session.close_reason == "slow_client"

    session.closing_since -= _grace(name) + 1  # the grace has run out
    gateway._flush_client_writes()
    samples = gateway.metric_samples()
    assert _value(samples, "gwy.disconnects", "slow_client") == 1
    assert _value(samples, "gwy.clients") == 0
    right.close()
    gateway.close()


@pytest.mark.parametrize("name", ["ralf", "dc"])
def test_an_idle_client_gets_one_exit_and_is_dropped(name: str, fake_zmq: None) -> None:
    gateway = _gateways()[name](free_port())
    session, left, right = _stream_session(name)
    session.authenticated = True
    gateway._clients[left.fileno()] = session
    session.last_activity -= gateway.config.idle_timeout_sec + 1
    for _ in range(5):  # used to queue a fresh EXIT on every pass
        gateway._drop_idle_clients()
    assert sum(b"EXIT" in line for line in session.out_queue) == 1
    assert session.close_reason == "idle_timeout"

    gateway._flush_client_writes()  # the peer's buffer takes one short line
    assert _value(gateway.metric_samples(), "gwy.disconnects", "idle_timeout") == 1
    assert right.recv(4096).startswith(b"EXIT")  # it was told why
    right.close()
    gateway.close()


@pytest.mark.parametrize("name", ["ralf", "dc"])
def test_a_client_without_hello_gets_one_exit_and_is_dropped(
    name: str, fake_zmq: None
) -> None:
    """W3: the same 5 s HELLO deadline as pm-md-gwy, told as EXIT."""
    gateway = _gateways()[name](free_port())
    session, left, right = _stream_session(name)
    gateway._clients[left.fileno()] = session
    session.connected_at -= 6
    for _ in range(3):
        gateway._drop_idle_clients()
    assert sum(b"EXIT" in line for line in session.out_queue) == 1
    assert session.close_reason == "auth_timeout"

    gateway._flush_client_writes()
    assert _value(gateway.metric_samples(), "gwy.disconnects", "auth_timeout") == 1
    assert right.recv(4096).startswith(b"EXIT|REASON=auth_timeout|")
    right.close()
    gateway.close()


@pytest.mark.parametrize("name", ["ralf", "dc"])
def test_lines_after_the_closing_one_are_ignored(name: str, fake_zmq: None) -> None:
    """W3: a HELLO pipelined behind a rejected first line used to log the
    session in (DC also subscribed its topic) although it was closing."""
    gateway = _gateways()[name](free_port())
    session, left, right = _stream_session(name)
    hello = (
        "HELLO|CLIENT=x|PROTO=RALF1|ROLE=AUDIT"
        if name == "ralf"
        else ("HELLO|CLIENT=x|PROTO=DC1|ID=TRADER01")
    )
    session.in_buffer.extend(f"PING\n{hello}\n".encode())
    gateway._drain_lines(session)
    assert session.authenticated is False
    assert not session.in_buffer
    assert [line.split(b"|")[1] for line in session.out_queue] == [
        b"CODE=AUTH_REQUIRED"
    ]
    left.close()
    right.close()
    gateway.close()


@pytest.mark.parametrize("name", ["ralf", "dc"])
def test_a_connection_over_max_connections_is_closed(name: str, fake_zmq: None) -> None:
    port = free_port()
    if name == "ralf":
        gateway: Any = RalfGateway(
            RalfGatewayConfig(bind_address="127.0.0.1", port=port, max_connections=1)
        )
    else:
        gateway = DcGateway(
            DcGatewayConfig(bind_address="127.0.0.1", port=port, max_connections=1)
        )
    gateway._server = socket.create_server(("127.0.0.1", port))
    gateway._server.setblocking(False)
    first = socket.create_connection(("127.0.0.1", port))
    second = socket.create_connection(("127.0.0.1", port))
    time.sleep(0.05)
    gateway._accept_new_clients()
    assert len(gateway._clients) == 1
    assert _value(gateway.metric_samples(), "gwy.clients_max") == 1
    second.settimeout(2)
    assert second.recv(4096) == b""  # closed without a line
    first.close()
    second.close()
    gateway.close()


@pytest.mark.parametrize("name", ["ralf", "dc"])
def test_dropping_the_backlog_keeps_a_half_sent_line(name: str, fake_zmq: None) -> None:
    gateway = _gateways()[name](free_port())
    session, left, right = _stream_session(name)
    session.out_queue.extend([b"partial-line\n", b"next\n", b"later\n"])
    session.out_offset = 4
    gateway._drop_backlog(session)
    assert list(session.out_queue) == [b"partial-line\n"]
    assert session.out_offset == 4
    session.out_offset = 0
    gateway._drop_backlog(session)
    assert not session.out_queue
    left.close()
    right.close()
    gateway.close()


# ---------------------------------------------------------------------------
# A5.4 pm-api-gwy
# ---------------------------------------------------------------------------


async def _get(app: Any, path: str) -> int:
    """One GET through the app's full ASGI stack (no httpx in this project;
    same approach as tests/test_tick_validation.py::_post)."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    status = 0
    sent = {"done": False}

    async def receive() -> dict[str, Any]:
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(message["status"])

    try:
        await app(scope, receive, send)
    except RuntimeError:
        pass  # Starlette re-raises an unhandled error after sending the 500
    return status


def test_http_requests_and_5xx_are_counted() -> None:
    from fastapi import FastAPI

    from edumatcher.api_gateway.metrics import install

    app = FastAPI()
    metrics = install(app)

    @app.get("/ok")
    async def ok() -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": True}

    @app.get("/boom")
    async def boom() -> None:  # pyright: ignore[reportUnusedFunction]
        raise RuntimeError("boom")

    async def scenario() -> tuple[int, int]:
        return await _get(app, "/ok"), await _get(app, "/boom")

    assert asyncio.run(scenario()) == (200, 500)
    assert (metrics.http_requests, metrics.http_5xx) == (2, 1)


def test_requests_and_throttles_are_counted_per_key() -> None:
    from fastapi import FastAPI, HTTPException

    from edumatcher.api_gateway.metrics import UNAUTH_LABEL, install

    app = FastAPI()
    metrics = install(app)
    metrics.register_keys(["desk", "idle"])

    @app.get("/as/{who}")
    async def as_(
        who: str, request: Request
    ) -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        request.state.api_key_label = who
        if who == "desk-limited":
            raise HTTPException(status_code=429, detail="slow down")
        return {"ok": True}

    @app.get("/anon")
    async def anon() -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": True}

    async def scenario() -> None:
        for path in ("/as/desk", "/as/desk", "/as/desk-limited", "/anon", "/nope"):
            await _get(app, path)

    asyncio.run(scenario())
    samples = metrics.samples(None)
    assert _value(samples, "api.key_requests", "desk") == 2
    assert _value(samples, "api.key_requests", "desk-limited") == 1
    assert _value(samples, "api.key_throttled", "desk-limited") == 1
    assert _value(samples, "api.key_throttled", "desk") == 0
    assert _value(samples, "api.key_requests", UNAUTH_LABEL) == 2
    assert _value(samples, "api.key_requests", "idle") == 0  # listed while idle
    assert _value(samples, "api.http_requests") == 5


def test_the_key_auth_resolves_is_the_one_counted() -> None:
    """The real app and `auth`: the label `auth` leaves reaches the middleware,
    and a 429 from the write-rate limiter counts against that key."""
    from edumatcher.api_gateway.metrics import UNAUTH_LABEL
    from edumatcher.api_gateway.rate_limit import RateLimiter
    from tests.api_gateway_harness import call, make_app

    class Engine:
        async def authenticate(
            self, gateway_id: str, timeout: float = 3.0
        ) -> tuple[bool, str]:
            return True, ""

    app = make_app(Engine())
    app.state.rate_limiter = RateLimiter(1, 1)
    order = {
        "symbol": "X",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": 1,
        "price": 1.0,
    }

    async def scenario() -> list[int]:
        codes = [(await call(app, "POST", "/api/v1/orders", body=order))[0]]
        codes.append((await call(app, "POST", "/api/v1/orders", body=order))[0])
        codes.append(
            (await call(app, "GET", "/api/v1/orders", authorization="Bearer x"))[0]
        )
        return codes

    codes = asyncio.run(scenario())
    assert codes[1:] == [429, 401]
    samples = app.state.health_metrics.samples(None)
    assert _value(samples, "api.key_requests", "trader") == 2
    assert _value(samples, "api.key_throttled", "trader") == 1
    assert _value(samples, "api.key_requests", UNAUTH_LABEL) == 1


def test_peak_is_the_busiest_second_and_names_the_key() -> None:
    clock = [100.0]
    m = ApiMetrics(clock=lambda: clock[0])
    for _ in range(3):
        m.record("a", 200)
    m.record("b", 200)
    # The second in progress already counts towards the peak.
    samples = m.samples(None)
    assert _value(samples, "api.rps_peak") == 4
    assert _value(samples, "api.key_rps_peak", "a") == 3
    clock[0] = 101.0
    m.record("b", 200)  # a quieter second does not lower it
    m.record("b", 200)
    samples = m.samples(None)
    assert _value(samples, "api.rps_peak") == 4
    assert _value(samples, "api.key_rps_peak", "a") == 3
    assert _value(samples, "api.key_rps_peak", "b") == 2
    # Sampling twice in one second does not split it.
    assert _value(m.samples(None), "api.rps_peak") == 4


def test_key_label_is_never_the_key() -> None:
    from edumatcher.api_gateway.config import ApiCredential
    from edumatcher.api_gateway.sessions import key_label

    assert key_label(ApiCredential("k1", "GW01", "Desk A")) == "Desk A"
    assert key_label(ApiCredential("k1", "GW01")) == "GW01"
    anon = key_label(ApiCredential("sekrit-key", None))
    assert anon.startswith("RO") and "sekrit" not in anon and len(anon) <= 32
    assert len(key_label(ApiCredential("k", None, "x" * 80))) == 32


def test_websocket_sessions_are_counted_per_channel() -> None:
    # WebSocket is imported at module level: with postponed annotations
    # FastAPI resolves `ws: WebSocket` against module globals.
    from fastapi import FastAPI

    from edumatcher.api_gateway.metrics import install

    app = FastAPI()
    metrics = install(app)
    seen_inside: list[int] = []

    @app.websocket("/api/v1/ws/private")
    async def private(ws: WebSocket) -> None:  # pyright: ignore[reportUnusedFunction]
        await ws.accept()
        seen_inside.append(metrics.ws_sessions["private"])
        await ws.close()

    async def scenario() -> None:
        scope = {
            "type": "websocket",
            "path": "/api/v1/ws/private",
            "headers": [],
            "query_string": b"",
            "root_path": "",
            "subprotocols": [],
        }
        messages = [{"type": "websocket.connect"}]

        async def receive() -> dict[str, Any]:
            return messages.pop(0) if messages else {"type": "websocket.disconnect"}

        async def send(message: MutableMapping[str, Any]) -> None:
            pass

        await app(scope, receive, send)

    asyncio.run(scenario())
    assert seen_inside == [1]
    assert metrics.ws_sessions["private"] == 0


def test_api_samples_carry_drops_and_timeouts() -> None:
    class Engine:
        dropped_events = {"private": 4, "market_data": 1}
        engine_timeouts = 2

    samples = ApiMetrics().samples(Engine())
    assert _value(samples, "api.dropped_events", "private") == 4
    assert _value(samples, "api.engine_timeouts") == 2
    assert {s.label for s in samples if s.name == "api.ws_sessions"} == {
        *WS_CHANNELS.values(),
        "other",
    }


def test_engine_client_counts_a_timeout() -> None:
    import asyncio

    from edumatcher.api_gateway.engine_client import EngineClient

    async def scenario() -> int:
        client = EngineClient(
            "tcp://127.0.0.1:1", "tcp://127.0.0.1:2", asyncio.get_running_loop()
        )
        with pytest.raises(TimeoutError):
            await client.await_topic("system.nothing", timeout=0.01)
        return client.engine_timeouts

    assert asyncio.run(scenario()) == 1


class _FakeListener:
    """Stands in for EngineClient / IndexClient / SimClient in the lifespan."""

    dropped_events: dict[str, int] = {}
    engine_timeouts = 0

    def __init__(self, *_a: Any, **_k: Any) -> None:
        pass

    def start_listener(self) -> None:
        pass

    def stop_listener(self) -> None:
        pass

    def active_gateways(self) -> list[str]:
        return []


@pytest.mark.real_health_reporter
def test_a_blocked_event_loop_shows_as_loop_lag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A5.4: block the loop for 1 s in an endpoint -> loop_lag_ms >= 900."""
    from fastapi import FastAPI

    from edumatcher.api_gateway.config import ApiGatewayConfig

    port = free_port()
    sink: zmq.Socket[bytes] = zmq.Context.instance().socket(zmq.PULL)
    sink.setsockopt(zmq.LINGER, 0)
    sink.bind(f"tcp://127.0.0.1:{port}")
    monkeypatch.setattr(
        HealthReporter,
        "from_compiled_config",
        classmethod(
            lambda cls, process, instance=None: cls(
                process, instance, host="127.0.0.1", port=port, interval_sec=0.2
            )
        ),
    )
    for name in ("EngineClient", "IndexClient", "SimClient"):
        monkeypatch.setattr(api_main, name, _FakeListener)
    monkeypatch.setattr(api_main, "load_sectors", lambda _path: {})
    app: FastAPI = api_main.create_app(ApiGatewayConfig(name="desk"), instance="desk")

    @app.get("/_block")
    async def block() -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        time.sleep(1.0)  # deliberately blocks the event loop
        return {"ok": True}

    async def scenario() -> tuple[float, Any]:
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.5)  # let the health task tick normally
            assert await _get(app, "/_block") == 200
            lag, last = 0.0, None
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and lag < 900:
                if sink.poll(0):
                    last = parse_health_beacon(sink.recv_multipart())
                    lag = max(lag, last.loop_lag_ms)
                else:
                    await asyncio.sleep(0.05)
            return lag, last

    try:
        lag, beacon = asyncio.run(scenario())
    finally:
        sink.close()
    assert lag >= 900
    assert beacon.process == "pm-api-gwy" and beacon.instance == "desk"
    assert any(m.name == "api.http_requests" for m in beacon.metrics)


@pytest.mark.parametrize("name", ["ralf", "dc"])
def test_the_real_loop_closes_a_connection_that_never_says_hello(
    name: str, fake_zmq: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: a client that never sends HELLO gets EXIT and then EOF
    from the running gateway -- the socket is really closed, not just marked
    closing. (A HELLO'd client that keeps reading is never idle: the
    heartbeats it receives are traffic.)"""
    import edumatcher.dc_gateway.gateway as dc_mod
    import edumatcher.ralf_gateway.gateway as ralf_mod

    monkeypatch.setattr(
        ralf_mod if name == "ralf" else dc_mod, "HELLO_TIMEOUT_SEC", 0.5
    )
    port = free_port()
    if name == "ralf":
        gateway: Any = RalfGateway(
            RalfGatewayConfig(bind_address="127.0.0.1", port=port, idle_timeout_sec=1)
        )
    else:
        gateway = DcGateway(
            DcGatewayConfig(bind_address="127.0.0.1", port=port, idle_timeout_sec=1)
        )
    runner = threading.Thread(target=gateway.run, daemon=True)
    runner.start()
    try:
        deadline = time.monotonic() + 5
        while True:  # run() binds on the thread; wait until it listens
            try:
                client = socket.create_connection(("127.0.0.1", port), timeout=5)
                break
            except ConnectionRefusedError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        received = b""
        while True:
            chunk = client.recv(4096)  # raises socket.timeout if never closed
            if not chunk:
                break  # EOF: the gateway closed the connection
            received += chunk
        assert b"EXIT" in received and b"auth_timeout" in received
        client.close()
    finally:
        gateway.stop()
        runner.join(timeout=5)


@pytest.mark.parametrize("instance", [None, "desk"])
def test_the_api_beacon_carries_the_command_line_instance(
    monkeypatch: pytest.MonkeyPatch, instance: str | None
) -> None:
    """A+B review, I90: the pm-opctl-cli roster knows a process by its command
    line, so a bare pm-api-gwy beacons without an instance even when it picked
    a configured entry (here named "dashboards")."""
    from edumatcher.api_gateway.config import ApiGatewayConfig

    seen: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        HealthReporter,
        "start_from_compiled_config",
        classmethod(
            lambda cls, process, instance=None: seen.append((process, instance))
        ),
    )
    for name in ("EngineClient", "IndexClient", "SimClient"):
        monkeypatch.setattr(api_main, name, _FakeListener)
    monkeypatch.setattr(api_main, "load_sectors", lambda _path: {})
    app = api_main.create_app(ApiGatewayConfig(name="dashboards"), instance=instance)

    async def scenario() -> None:
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(scenario())
    assert seen == [("pm-api-gwy", instance)]
