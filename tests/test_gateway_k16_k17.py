"""K16/K17: event-loop fairness, blocking I/O and input strictness.

Findings G1 (a write-blocked session busy-spins the ALF select loop), G2 (a
reset peer stays registered because every ``OSError`` is swallowed), B5 (the
BALF SUB drain has no budget and feeds topics dispatch ignores), P6 (history
runs SQLite synchronously inside ``async`` handlers), G3 (the ALF symbol set
is unioned and survives an engine restart) and G4/B6 (config accepts
non-integral numerics for integer fields and ``NaN`` for positive timeouts).

Every test here fails on the pre-fix tree; see
``docs-design/EduMatcher-Key-Component-Fixes-Workplan.md`` §5 K16-K17.
"""

from __future__ import annotations

import asyncio
import errno
import math
import selectors
import socket
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, cast

import pytest

from edumatcher.alf_gwy.config import AlfGatewayConfig, load_alf_gateway_config
from edumatcher.alf_gwy.gateway import AlfGateway
from edumatcher.alf_gwy.gateway import ClientSession as AlfSession
from edumatcher.alf_gwy.protocol import ValidationError
from edumatcher.balf_gwy.config import BalfGatewayConfig, load_balf_gateway_config
from edumatcher.balf_gwy.gateway import BalfGateway
from edumatcher.models.generated.order import PREFIX_ORDER_ACK
from edumatcher.models.generated.system import TOPIC_STARTUP_RECOVERY
from edumatcher.models.message import encode

GW = "TRADER01"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakePush:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        pass


class _FakeSub:
    """A SUB socket backed by a fixed backlog of frames."""

    def __init__(self, frames: list[list[bytes]] | None = None) -> None:
        self.topics: list[bytes] = []
        self.recv_calls = 0
        self._queue: deque[list[bytes]] = deque(frames or ())

    def setsockopt(self, op: int, value: bytes) -> None:
        _ = op
        self.topics.append(value)

    def poll(self, timeout: int = 0) -> int:
        _ = timeout
        return 1 if self._queue else 0

    def recv_multipart(self) -> list[bytes]:
        self.recv_calls += 1
        return self._queue.popleft()

    def close(self) -> None:
        pass


class _BlockingSocket:
    """A client socket whose ``send`` never accepts anything."""

    def __init__(self, fileno: int) -> None:
        self._fileno = fileno
        self.send_calls = 0

    def fileno(self) -> int:
        return self._fileno

    def send(self, data: bytes) -> int:
        self.send_calls += 1
        raise BlockingIOError(errno.EAGAIN, "would block")

    def recv(self, size: int) -> bytes:
        raise BlockingIOError(errno.EAGAIN, "would block")

    def close(self) -> None:
        pass


class _ResetSocket:
    """A client socket whose peer has gone away for good."""

    def __init__(self, fileno: int) -> None:
        self._fileno = fileno

    def fileno(self) -> int:
        return self._fileno

    def send(self, data: bytes) -> int:
        raise ConnectionResetError(errno.ECONNRESET, "reset by peer")

    def recv(self, size: int) -> bytes:
        raise ConnectionResetError(errno.ECONNRESET, "reset by peer")

    def close(self) -> None:
        pass


class _RecordingSelector:
    """Just enough of ``selectors.BaseSelector`` to observe interest changes."""

    def __init__(self) -> None:
        self.events: dict[int, int] = {}
        self.data: dict[int, Any] = {}

    def register(self, fileobj: Any, events: int, data: Any = None) -> None:
        self.events[fileobj.fileno()] = events
        self.data[fileobj.fileno()] = data

    def modify(self, fileobj: Any, events: int, data: Any = None) -> None:
        if fileobj.fileno() not in self.events:
            raise KeyError(fileobj)
        self.events[fileobj.fileno()] = events
        self.data[fileobj.fileno()] = data

    def unregister(self, fileobj: Any) -> None:
        self.events.pop(fileobj.fileno(), None)
        self.data.pop(fileobj.fileno(), None)

    def select(self, timeout: float | None = None) -> list[Any]:
        _ = timeout
        return []

    def close(self) -> None:
        pass


def _alf(monkeypatch: pytest.MonkeyPatch) -> AlfGateway:
    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_pusher", lambda _addr: _FakePush()
    )
    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_subscriber",
        lambda _addr, *topics, **_kw: _FakeSub(),
    )
    gw = AlfGateway(
        AlfGatewayConfig(
            bind_address="127.0.0.1", port=5565, gateway_roles=((GW, "TRADER"),)
        )
    )
    gw._selector = cast(selectors.BaseSelector, _RecordingSelector())
    return gw


def _sel(gw: AlfGateway) -> _RecordingSelector:
    return cast(_RecordingSelector, gw._selector)


def _alf_session(gw: AlfGateway, sock: Any) -> AlfSession:
    session = AlfSession(sock=sock, addr=("127.0.0.1", 40000))
    session.authenticated = True
    session.gateway_id = GW
    gw._clients[sock.fileno()] = session
    gw._selector.register(sock, selectors.EVENT_READ, session)
    return session


# ---------------------------------------------------------------------------
# K16 / G1 — a write-blocked session must not spin the loop
# ---------------------------------------------------------------------------


def test_g1_a_blocked_write_registers_write_interest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = _alf(monkeypatch)
    sock = _BlockingSocket(42)
    session = _alf_session(gw, sock)
    gw._queue_raw(session, b"HB|TS=now\n")

    gw._flush_client_writes()

    assert sock.send_calls == 1
    assert (
        _sel(gw).events[42] & selectors.EVENT_WRITE
    ), "the kernel buffer was full; the loop must wait for writability"


def test_g1_a_blocked_session_is_not_retried_until_writable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrying every iteration is the busy-spin: the selector is given a 0
    timeout while anything is dirty, so a blocked client pins a core."""
    gw = _alf(monkeypatch)
    sock = _BlockingSocket(42)
    session = _alf_session(gw, sock)
    gw._queue_raw(session, b"HB|TS=now\n")

    gw._flush_client_writes()
    for _ in range(5):
        gw._flush_client_writes()

    assert sock.send_calls == 1
    assert not gw._has_pending_writes(), "the loop would select() with timeout 0"


def test_g1_write_interest_is_dropped_once_the_queue_drains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = _alf(monkeypatch)
    left, right = socket.socketpair()
    left.setblocking(False)
    try:
        session = _alf_session(gw, left)
        gw._queue_raw(session, b"HB|TS=now\n")
        gw._write_blocked.add(left.fileno())
        gw._selector.modify(left, selectors.EVENT_READ | selectors.EVENT_WRITE, session)

        gw._flush_client_writes(writable={left.fileno()})

        assert not session.out_queue
        assert left.fileno() not in gw._write_blocked
        assert not _sel(gw).events[left.fileno()] & selectors.EVENT_WRITE
    finally:
        left.close()
        right.close()


# ---------------------------------------------------------------------------
# K16 / G2 — a reset peer must be disconnected, not left registered
# ---------------------------------------------------------------------------


def test_g2_a_reset_peer_is_disconnected_on_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = _alf(monkeypatch)
    sock = _ResetSocket(43)
    session = _alf_session(gw, sock)

    gw._read_client_data([session])

    assert 43 not in gw._clients, "a reset peer was left in the client table"
    assert 43 not in _sel(gw).events, "its descriptor was never unregistered"


def test_g2_a_reset_peer_is_disconnected_on_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = _alf(monkeypatch)
    sock = _ResetSocket(43)
    session = _alf_session(gw, sock)
    gw._queue_raw(session, b"HB|TS=now\n")

    gw._flush_client_writes()

    assert 43 not in gw._clients
    assert 43 not in _sel(gw).events
    assert 43 not in gw._dirty, "a dead session kept the loop busy"
    assert 43 not in gw._write_blocked


def test_g2_a_transient_write_error_is_not_a_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``EINTR`` means "try again", not "the peer is gone"."""
    gw = _alf(monkeypatch)

    class _Interrupted(_BlockingSocket):
        def send(self, data: bytes) -> int:
            self.send_calls += 1
            raise OSError(errno.EINTR, "interrupted")

    sock = _Interrupted(44)
    session = _alf_session(gw, sock)
    gw._queue_raw(session, b"HB|TS=now\n")

    gw._flush_client_writes()

    assert 44 in gw._clients


# ---------------------------------------------------------------------------
# K16 / B5 — the BALF SUB drain needs a budget and no dead subscriptions
# ---------------------------------------------------------------------------


def _balf(monkeypatch: pytest.MonkeyPatch, sub: _FakeSub) -> BalfGateway:
    monkeypatch.setattr(
        "edumatcher.balf_gwy.gateway.make_pusher", lambda _addr: _FakePush()
    )
    monkeypatch.setattr(
        "edumatcher.balf_gwy.gateway.make_subscriber", lambda _addr, *_topics: sub
    )
    return BalfGateway(
        BalfGatewayConfig(
            bind_address="127.0.0.1", port=5560, gateway_roles=((GW, "TRADER"),)
        )
    )


def test_b5_the_engine_drain_has_a_per_iteration_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unbounded drain starves heartbeats and idle timeouts: the loop
    never reaches them while the engine keeps publishing."""
    backlog = [
        encode(f"{PREFIX_ORDER_ACK}{GW}", {"order_id": str(i)}) for i in range(2000)
    ]
    sub = _FakeSub(backlog)
    gw = _balf(monkeypatch, sub)

    gw._poll_engine_events()

    assert (
        sub.recv_calls <= 256
    ), "the drain never yields, so no client is ever heard from again"
    assert sub.recv_calls > 0


def test_b5_no_subscription_is_made_to_a_topic_dispatch_ignores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscribed: list[str] = []

    def _record(_addr: str, *topics: str) -> _FakeSub:
        subscribed.extend(topics)
        return _FakeSub()

    monkeypatch.setattr(
        "edumatcher.balf_gwy.gateway.make_pusher", lambda _addr: _FakePush()
    )
    monkeypatch.setattr("edumatcher.balf_gwy.gateway.make_subscriber", _record)
    BalfGateway(
        BalfGatewayConfig(
            bind_address="127.0.0.1", port=5560, gateway_roles=((GW, "TRADER"),)
        )
    )

    assert subscribed == [
        TOPIC_STARTUP_RECOVERY
    ], "every other venue-wide topic is decoded and then thrown away"


# ---------------------------------------------------------------------------
# K16 / P6 — history must not block the event loop on SQLite
# ---------------------------------------------------------------------------


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_p6_a_history_query_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A synchronous SQLite read inside an ``async def`` handler stalls every
    other request on the worker, including the engine round-trips the write
    endpoints are waiting on."""
    import edumatcher.api_gateway.routers.history as history_mod
    from edumatcher.api_gateway.sessions import Session

    entered = threading.Event()
    released = threading.Event()
    observed: list[int] = []

    def _blocking_query(*_args: Any, **_kw: Any) -> tuple[list[Any], None]:
        entered.set()
        released.wait(5.0)
        return [], None

    monkeypatch.setattr(history_mod, "query_order_events", _blocking_query)
    monkeypatch.setattr(
        history_mod, "query_order_events_retained_from", lambda *a, **k: None
    )
    monkeypatch.setattr(history_mod, "_open_stats", lambda _request: _FakeConn())
    monkeypatch.setattr(history_mod, "_session_tz", lambda _r, _c: None)

    class _Config:
        stats_db = tmp_path / "stats.db"

    class _Request:
        app = type("App", (), {"state": type("S", (), {"config": _Config()})()})()

    ticks = 0

    async def _ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.001)

    def _watch() -> None:
        """Release SQLite once the loop has proved it is still running."""
        entered.wait(5.0)
        start = ticks
        deadline = time.monotonic() + 1.0
        while ticks - start < 20 and time.monotonic() < deadline:
            time.sleep(0.01)
        observed.append(ticks - start)
        released.set()

    session = Session(api_key="k", gateway_id=GW, description="trader")
    ticker = asyncio.ensure_future(_ticker())
    watcher = threading.Thread(target=_watch, daemon=True)
    watcher.start()
    try:
        await history_mod.history_orders(_Request(), session)  # type: ignore[arg-type]
    finally:
        ticker.cancel()
        watcher.join(timeout=5.0)

    assert (
        observed and observed[0] >= 20
    ), "the event loop made no progress while SQLite was reading"


class _FakeConn:
    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# K17 / G3 — the ALF symbol set is replaced, not accumulated
# ---------------------------------------------------------------------------


def test_g3_an_engine_restart_forgets_the_old_symbol_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = _alf(monkeypatch)
    gw._known_symbols = {"AAPL", "OLD"}
    gw._symbols_snapshot_loaded = True

    gw._handle_engine_restart()

    with pytest.raises(ValidationError):
        gw._validate_symbol("AAPL")  # nothing is known until a fresh snapshot

    gw._handle_symbols_response(GW, {"symbols": [{"symbol": "AAPL"}]})

    gw._validate_symbol("AAPL")
    with pytest.raises(ValidationError):
        gw._validate_symbol("OLD")


def test_g3_a_fresh_snapshot_replaces_rather_than_unions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delisted symbol must stop being tradable the moment the engine stops
    listing it, restart or no restart."""
    gw = _alf(monkeypatch)
    gw._handle_symbols_response(
        GW, {"symbols": [{"symbol": "AAPL"}, {"symbol": "DELISTED"}]}
    )
    gw._validate_symbol("DELISTED")

    gw._handle_symbols_response(GW, {"symbols": [{"symbol": "AAPL"}]})

    gw._validate_symbol("AAPL")
    with pytest.raises(ValidationError):
        gw._validate_symbol("DELISTED")


# ---------------------------------------------------------------------------
# K17 / G4, B6 — config must reject non-integral numerics and NaN
# ---------------------------------------------------------------------------

_ALF_INT_FIELDS = (
    "port",
    "heartbeat_interval_sec",
    "handshake_timeout_sec",
    "idle_timeout_sec",
    "max_connections",
    "max_client_queue",
    "max_commands_per_second",
    "max_errors_before_disconnect",
    "error_window_sec",
)

_BALF_INT_FIELDS = (
    "port",
    "max_connections",
    "max_client_queue",
    "max_messages_per_second",
    "max_errors_before_disconnect",
)

_BALF_FLOAT_FIELDS = (
    "heartbeat_interval_sec",
    "heartbeat_timeout_sec",
    "idle_timeout_sec",
    "auth_timeout_sec",
    "error_window_sec",
)


@pytest.mark.parametrize("field", _ALF_INT_FIELDS)
def test_g4_alf_rejects_a_non_integral_number(tmp_path: Path, field: str) -> None:
    """``int(5565.9)`` is 5565: the gateway would silently listen on another
    port than the operator configured."""
    p = tmp_path / "engine_config.yaml"
    p.write_text(f"alf_gateway:\n  {field}: 5565.9\n")
    with pytest.raises(ValueError):
        load_alf_gateway_config(p)


@pytest.mark.parametrize("field", _BALF_INT_FIELDS)
def test_b6_balf_rejects_a_non_integral_number(tmp_path: Path, field: str) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text(f"balf_gateway:\n  {field}: 1.9\n")
    with pytest.raises(ValueError):
        load_balf_gateway_config(p)


@pytest.mark.parametrize("field", _BALF_FLOAT_FIELDS)
def test_b6_balf_rejects_nan_for_a_positive_number(tmp_path: Path, field: str) -> None:
    """``nan <= 0`` is false, so NaN slid past the positivity check and then
    poisoned every timeout comparison into never firing."""
    p = tmp_path / "engine_config.yaml"
    p.write_text(f"balf_gateway:\n  {field}: .nan\n")
    with pytest.raises(ValueError):
        load_balf_gateway_config(p)


@pytest.mark.parametrize("field", _BALF_FLOAT_FIELDS)
def test_b6_balf_rejects_infinity_for_a_positive_number(
    tmp_path: Path, field: str
) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text(f"balf_gateway:\n  {field}: .inf\n")
    with pytest.raises(ValueError):
        load_balf_gateway_config(p)


def test_g4_an_integral_float_is_still_accepted(tmp_path: Path) -> None:
    """YAML writes ``5565.0`` for a round number often enough that rejecting
    it would be hostile; only a value that would lose information is wrong."""
    p = tmp_path / "engine_config.yaml"
    p.write_text("alf_gateway:\n  port: 5565.0\n")
    assert load_alf_gateway_config(p).port == 5565


_OTHER_CONFIG_LOADERS = (
    ("api_gateway", "edumatcher.api_gateway.config", "load_api_gateway_config"),
    ("dc_gateway", "edumatcher.dc_gateway.config", "load_dc_gateway_config"),
    ("log_server", "edumatcher.log_srv.config", "load_log_server_config"),
    (
        "market_data_gateway",
        "edumatcher.md_gateway.config",
        "load_market_data_gateway_config",
    ),
    (
        "post_trade_gateway",
        "edumatcher.ralf_gateway.config",
        "load_ralf_gateway_config",
    ),
)


@pytest.mark.parametrize(("section", "module", "loader"), _OTHER_CONFIG_LOADERS)
def test_every_config_loader_rejects_a_non_integral_port(
    tmp_path: Path, section: str, module: str, loader: str
) -> None:
    """K17 step 4: this class of bug is not specific to the two gateways."""
    import importlib

    fn = getattr(importlib.import_module(module), loader)
    p = tmp_path / "engine_config.yaml"
    p.write_text(f"{section}:\n  port: 1234.5\n")
    with pytest.raises(ValueError):
        fn(p)


def test_shared_coercion_helpers_reject_nan_and_non_integral() -> None:
    from edumatcher.config_coerce import as_float, as_int

    with pytest.raises(ValueError):
        as_int(1.9, "x.y")
    with pytest.raises(ValueError):
        as_int(math.nan, "x.y")
    assert as_int(2.0, "x.y") == 2
    assert as_int("3", "x.y") == 3

    with pytest.raises(ValueError):
        as_float(math.nan, "x.y")
    with pytest.raises(ValueError):
        as_float(math.inf, "x.y")
    assert as_float("1.5", "x.y") == 1.5
