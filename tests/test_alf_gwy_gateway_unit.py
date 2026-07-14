from __future__ import annotations

import socket
import time
from collections import deque

import pytest
import zmq

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway, ClientSession
from edumatcher.alf_gwy.protocol import parse_alf_line
from edumatcher.messaging import bus as bus_mod
from edumatcher.models.message import encode


class _FakePush:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []
        self.closed = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


class _ClosedFakePush(_FakePush):
    def __init__(self) -> None:
        super().__init__()
        self.closed = True

    def send_multipart(self, frames: list[bytes]) -> None:
        _ = frames
        raise zmq.ZMQError()


class _EagainFakePush(_FakePush):
    def send_multipart(self, frames: list[bytes]) -> None:
        _ = frames
        raise zmq.Again()


class _FakeSub:
    def __init__(self) -> None:
        self.closed = False
        self._queue: deque[list[bytes]] = deque()
        self.ops: list[tuple[int, bytes]] = []

    def setsockopt(self, op: int, value: bytes) -> None:
        self.ops.append((op, value))

    def poll(self, timeout: int = 0) -> int:
        _ = timeout
        return 1 if self._queue else 0

    def recv_multipart(self) -> list[bytes]:
        return self._queue.popleft()

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def gateway(monkeypatch: pytest.MonkeyPatch) -> AlfGateway:
    fake_push = _FakePush()
    fake_sub = _FakeSub()

    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_pusher", lambda _addr: fake_push
    )
    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_subscriber",
        lambda _addr, *_topics: fake_sub,
    )

    cfg = AlfGatewayConfig(
        bind_address="127.0.0.1",
        port=5565,
        max_commands_per_second=1,
        gateway_roles=(("TRADER01", "TRADER"), ("MM01", "MARKET_MAKER")),
    )
    gw = AlfGateway(cfg)
    gw._push = fake_push
    gw._sub = fake_sub
    return gw


def _make_session() -> tuple[ClientSession, socket.socket]:
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    session = ClientSession(sock=left, addr=("local", 0))
    session.rate_tokens = 100.0
    session.rate_updated = time.monotonic()
    return session, right


def test_requires_hello_first(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    gateway._handle_client_line(session, "SYMBOLS")

    assert session.closing is True
    assert session.out_queue
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "ERR"
    assert frame.fields["CODE"] == "AUTH_REQUIRED"
    peer.close()


def test_ping_requires_hello_first(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    gateway._handle_client_line(session, "PING")

    assert session.closing is True
    assert session.out_queue
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "ERR"
    assert frame.fields["CODE"] == "AUTH_REQUIRED"
    peer.close()


def test_duplicate_gateway_id_is_rejected(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    gateway._active_gateway_sessions["TRADER01"] = 99

    gateway._handle_client_line(session, "HELLO|CLIENT=BOT|PROTO=ALF1|ID=TRADER01")

    assert session.closing is True
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.fields["CODE"] == "GATEWAY_ALREADY_CONNECTED"
    peer.close()


def test_hello_then_auth_success_sends_welcome(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    gateway._clients[session.sock.fileno()] = session

    gateway._handle_client_line(session, "HELLO|CLIENT=BOT|PROTO=ALF1|ID=TRADER01")
    assert session.auth_pending is True

    gateway._handle_gateway_auth("TRADER01", {"accepted": True})
    assert session.authenticated is True
    assert session.role == "TRADER"

    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "WELCOME"
    assert frame.fields["ID"] == "TRADER01"
    peer.close()


def test_quote_rejected_for_non_market_maker(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    session.authenticated = True
    session.gateway_id = "TRADER01"
    session.role = "TRADER"
    session.rate_tokens = 10.0

    gateway._handle_client_line(
        session,
        "QUOTE|SYM=AAPL|BID=1|ASK=2|BID_QTY=1|ASK_QTY=1",
    )

    assert session.out_queue
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.fields["CODE"] == "ROLE_DENIED"
    peer.close()


def test_rate_limited_after_first_command(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    session.authenticated = True
    session.gateway_id = "TRADER01"
    session.role = "TRADER"
    session.rate_tokens = 1.0

    gateway._handle_client_line(session, "SYMBOLS")
    gateway._handle_client_line(session, "ORDERS")

    assert len(session.out_queue) == 1
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "ERR"
    assert frame.fields["CODE"] == "RATE_LIMITED"
    peer.close()


def test_invalid_combo_type_is_invalid_value(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    session.authenticated = True
    session.gateway_id = "TRADER01"
    session.role = "TRADER"
    session.rate_tokens = 10.0

    gateway._handle_client_line(
        session,
        "NEW|TYPE=COMBO|COMBO_ID=spread|COMBO_TYPE=BAD|LEG_COUNT=2|"
        "LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=1|LEG0.PRICE=1|"
        "LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=1|LEG1.PRICE=2",
    )

    assert session.out_queue
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "ERR"
    assert frame.fields["CODE"] == "INVALID_VALUE"
    assert "COMBO_TYPE" in frame.fields["DETAIL"]
    peer.close()


def test_engine_event_routing_to_gateway_session(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    session.authenticated = True
    session.gateway_id = "TRADER01"
    gateway._clients[session.sock.fileno()] = session
    gateway._active_gateway_sessions["TRADER01"] = session.sock.fileno()

    fake_sub = gateway._sub
    assert isinstance(fake_sub, _FakeSub)
    fake_sub._queue.append(
        encode(
            "order.ack.TRADER01",
            {"order_id": "abc", "accepted": True, "reason": ""},
        )
    )

    gateway._poll_engine_events()

    assert session.out_queue
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "ACK"
    assert frame.fields["ORDER_ID"] == "ABC"
    peer.close()


def test_disconnect_sends_gateway_disconnect(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    session.authenticated = True
    session.gateway_id = "TRADER01"
    session.connect_emitted = True
    gateway._clients[session.sock.fileno()] = session
    gateway._active_gateway_sessions["TRADER01"] = session.sock.fileno()

    gateway._disconnect(session, reason="peer_closed")

    fake_push = gateway._push
    assert isinstance(fake_push, _FakePush)
    assert fake_push.sent
    topic = fake_push.sent[-1][0].decode("utf-8")
    assert topic == "system.gateway_disconnect"
    peer.close()


def test_closed_push_during_shutdown_does_not_raise(gateway: AlfGateway) -> None:
    gateway._push = _ClosedFakePush()

    gateway._send_to_engine([b"topic", b"{}"])


def test_send_to_engine_eagain_rejects_command(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    session.authenticated = True
    session.gateway_id = "TRADER01"
    session.rate_tokens = 10.0
    gateway._push = _EagainFakePush()

    gateway._handle_client_line(session, "SYMBOLS")

    assert session.out_queue
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "ERR"
    assert frame.fields["CODE"] == "ENGINE_UNAVAILABLE"
    peer.close()


def test_hello_eagain_returns_engine_unavailable_without_disconnect(
    gateway: AlfGateway,
) -> None:
    session, peer = _make_session()
    gateway._clients[session.sock.fileno()] = session
    gateway._push = _EagainFakePush()

    gateway._handle_client_line(session, "HELLO|CLIENT=BOT|PROTO=ALF1|ID=TRADER01")

    assert session.out_queue
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "ERR"
    assert frame.fields["CODE"] == "ENGINE_UNAVAILABLE"
    assert session.closing is False
    assert session.auth_pending is False
    assert session.gateway_id is None
    peer.close()


def test_duplicate_hello_while_pending_is_rejected_without_disconnect(
    gateway: AlfGateway,
) -> None:
    session, peer = _make_session()
    gateway._clients[session.sock.fileno()] = session

    gateway._handle_client_line(session, "HELLO|CLIENT=BOT|PROTO=ALF1|ID=TRADER01")
    gateway._handle_client_line(session, "HELLO|CLIENT=BOT|PROTO=ALF1|ID=TRADER01")

    assert session.auth_pending is True
    assert session.closing is False
    assert session.out_queue
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "ERR"
    assert frame.fields["CODE"] == "HELLO_ALREADY_PENDING"
    peer.close()


def test_pre_auth_lines_are_rate_limited(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    gateway._clients[session.sock.fileno()] = session
    session.rate_tokens = 0.0

    gateway._handle_client_line(session, "HELLO|CLIENT=BOT|PROTO=ALF1|ID=TRADER01")

    assert session.out_queue
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "ERR"
    assert frame.fields["CODE"] == "RATE_LIMITED"
    assert session.auth_pending is False
    peer.close()


def test_disconnect_sends_gateway_disconnect_for_auth_pending_session(
    gateway: AlfGateway,
) -> None:
    session, peer = _make_session()
    gateway._clients[session.sock.fileno()] = session

    gateway._handle_client_line(session, "HELLO|CLIENT=BOT|PROTO=ALF1|ID=TRADER01")
    assert session.auth_pending is True

    gateway._disconnect(session, reason="peer_closed")

    fake_push = gateway._push
    assert isinstance(fake_push, _FakePush)
    assert fake_push.sent
    topic = fake_push.sent[-1][0].decode("utf-8")
    assert topic == "system.gateway_disconnect"
    peer.close()


def test_handshake_timeout_disconnects_unauthenticated_client(
    gateway: AlfGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1_000.0]
    monkeypatch.setattr("edumatcher.alf_gwy.gateway.time.monotonic", lambda: now[0])

    session, peer = _make_session()
    gateway._clients[session.sock.fileno()] = session
    session.connected_at = 990.0
    gateway.config = AlfGatewayConfig(
        bind_address=gateway.config.bind_address,
        port=gateway.config.port,
        engine_pull_addr=gateway.config.engine_pull_addr,
        engine_pub_addr=gateway.config.engine_pub_addr,
        heartbeat_interval_sec=gateway.config.heartbeat_interval_sec,
        handshake_timeout_sec=5,
        idle_timeout_sec=gateway.config.idle_timeout_sec,
        max_connections=gateway.config.max_connections,
        max_client_queue=gateway.config.max_client_queue,
        max_commands_per_second=gateway.config.max_commands_per_second,
        max_errors_before_disconnect=gateway.config.max_errors_before_disconnect,
        error_window_sec=gateway.config.error_window_sec,
        gateway_roles=gateway.config.gateway_roles,
    )

    gateway._drop_idle_clients()

    assert session.closing is True
    assert session.out_queue
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "ERR"
    assert frame.fields["CODE"] == "AUTH_TIMEOUT"
    peer.close()


class _FakePushSocket:
    def __init__(self) -> None:
        self.opts: list[tuple[int, int]] = []
        self.connected: str | None = None

    def setsockopt(self, opt: int, value: int) -> None:
        self.opts.append((opt, value))

    def connect(self, addr: str) -> None:
        self.connected = addr


class _FakeContext:
    def __init__(self, sock: _FakePushSocket) -> None:
        self._sock = sock

    def socket(self, _sock_type: int) -> _FakePushSocket:
        return self._sock


def test_make_pusher_sets_send_timeout_and_hwm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sock = _FakePushSocket()
    monkeypatch.setattr(bus_mod, "get_context", lambda: _FakeContext(fake_sock))

    bus_mod.make_pusher("tcp://127.0.0.1:5555")

    assert (zmq.SNDTIMEO, 0) in fake_sock.opts
    assert (zmq.SNDHWM, 1000) in fake_sock.opts
    assert (zmq.IMMEDIATE, 1) in fake_sock.opts
    assert fake_sock.connected == "tcp://127.0.0.1:5555"


def test_line_exceeds_max_bytes_adds_bad_message(gateway: AlfGateway) -> None:
    session, peer = _make_session()
    gateway._register_error(
        session, "BAD_MESSAGE", "Line exceeds 4096 bytes", close_connection=False
    )

    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.fields["CODE"] == "BAD_MESSAGE"
    peer.close()
