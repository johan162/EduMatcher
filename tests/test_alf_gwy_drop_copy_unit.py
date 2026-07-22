"""Unit tests for pm-alf-gwy drop-copy relay: DC|ON / DC|OFF and DC_FILL.

Mirrors the fake-socket style of test_alf_gwy_gateway_unit.py, but uses two
independent fake SUB sockets (main :5556 vs. drop-copy :5557) since
AlfGateway now owns two separate zmq.SUB connections.
"""

from __future__ import annotations

import socket
import time
from collections import deque

import pytest
import zmq

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway, ClientSession
from edumatcher.alf_gwy.protocol import parse_alf_line
from edumatcher.models.message import encode


class _FakePush:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []
        self.closed = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


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

    def push(self, frames: list[bytes]) -> None:
        self._queue.append(frames)


def _make_session() -> tuple[ClientSession, socket.socket]:
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    session = ClientSession(sock=left, addr=("local", 0))
    session.rate_tokens = 100.0
    session.rate_updated = time.monotonic()
    return session, right


@pytest.fixture()
def gateway(monkeypatch: pytest.MonkeyPatch) -> tuple[AlfGateway, _FakeSub, _FakeSub]:
    fake_push = _FakePush()
    fake_sub = _FakeSub()
    fake_dc_sub = _FakeSub()

    # make_subscriber is called twice in AlfGateway.__init__: once for the
    # main event bus (:5556), once for the drop-copy feed (:5557). Return a
    # distinct fake for each call, keyed on call order.
    calls: list[_FakeSub] = [fake_sub, fake_dc_sub]

    def _fake_make_subscriber(_addr: str, *_topics: str) -> _FakeSub:
        return calls.pop(0)

    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_pusher", lambda _addr: fake_push
    )
    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_subscriber", _fake_make_subscriber
    )

    cfg = AlfGatewayConfig(
        bind_address="127.0.0.1",
        port=5565,
        max_commands_per_second=1000,
        gateway_roles=(("TRADER01", "TRADER"), ("MM01", "MARKET_MAKER")),
    )
    gw = AlfGateway(cfg)
    return gw, fake_sub, fake_dc_sub


def _authed_session(gateway: AlfGateway, gateway_id: str = "TRADER01") -> ClientSession:
    session, _peer = _make_session()
    session.authenticated = True
    session.gateway_id = gateway_id
    session.role = "TRADER"
    session.rate_tokens = 100.0
    gateway._clients[session.sock.fileno()] = session
    gateway._active_gateway_sessions[gateway_id] = session.sock.fileno()
    return session


# ---------------------------------------------------------------------------
# DC|ON / DC|OFF command handling
# ---------------------------------------------------------------------------


def test_dc_on_subscribes_and_acks(
    gateway: tuple[AlfGateway, _FakeSub, _FakeSub],
) -> None:
    gw, _sub, dc_sub = gateway
    session = _authed_session(gw)

    gw._handle_client_line(session, "DC|STATE=ON")

    assert session.dc_enabled is True
    assert (zmq.SUBSCRIBE, b"drop_copy.event.TRADER01") in dc_sub.ops
    frame = parse_alf_line(session.out_queue[-1].decode("utf-8"))
    assert frame.command == "DC_ACK"
    assert frame.fields["STATE"] == "ON"


def test_dc_off_unsubscribes_and_acks(
    gateway: tuple[AlfGateway, _FakeSub, _FakeSub],
) -> None:
    gw, _sub, dc_sub = gateway
    session = _authed_session(gw)

    gw._handle_client_line(session, "DC|STATE=ON")
    gw._handle_client_line(session, "DC|STATE=OFF")

    assert session.dc_enabled is False
    assert (zmq.UNSUBSCRIBE, b"drop_copy.event.TRADER01") in dc_sub.ops
    frame = parse_alf_line(session.out_queue[-1].decode("utf-8"))
    assert frame.command == "DC_ACK"
    assert frame.fields["STATE"] == "OFF"


def test_dc_on_twice_is_idempotent_on_wire(
    gateway: tuple[AlfGateway, _FakeSub, _FakeSub],
) -> None:
    """Refcounted subscribe: a second DC|ON must not re-issue SUBSCRIBE."""
    gw, _sub, dc_sub = gateway
    session = _authed_session(gw)

    gw._handle_client_line(session, "DC|STATE=ON")
    sub_ops_after_first = [op for op in dc_sub.ops if op[0] == zmq.SUBSCRIBE]
    gw._handle_client_line(session, "DC|STATE=ON")
    sub_ops_after_second = [op for op in dc_sub.ops if op[0] == zmq.SUBSCRIBE]

    assert len(sub_ops_after_first) == 1
    assert len(sub_ops_after_second) == 1  # unchanged -- no duplicate SUBSCRIBE


def test_dc_invalid_state_is_invalid_value(
    gateway: tuple[AlfGateway, _FakeSub, _FakeSub],
) -> None:
    gw, _sub, _dc_sub = gateway
    session = _authed_session(gw)

    gw._handle_client_line(session, "DC|STATE=MAYBE")

    frame = parse_alf_line(session.out_queue[-1].decode("utf-8"))
    assert frame.command == "ERR"
    assert frame.fields["CODE"] == "INVALID_VALUE"


def test_dc_requires_auth(gateway: tuple[AlfGateway, _FakeSub, _FakeSub]) -> None:
    gw, _sub, dc_sub = gateway
    session, _peer = _make_session()

    gw._handle_client_line(session, "DC|STATE=ON")

    frame = parse_alf_line(session.out_queue[-1].decode("utf-8"))
    assert frame.command == "ERR"
    assert frame.fields["CODE"] == "AUTH_REQUIRED"
    assert not any(op[0] == zmq.SUBSCRIBE for op in dc_sub.ops)


def test_disconnect_unsubscribes_dc(
    gateway: tuple[AlfGateway, _FakeSub, _FakeSub],
) -> None:
    gw, _sub, dc_sub = gateway
    session = _authed_session(gw)
    gw._handle_client_line(session, "DC|STATE=ON")

    gw._disconnect(session, reason="test")

    assert (zmq.UNSUBSCRIBE, b"drop_copy.event.TRADER01") in dc_sub.ops


def test_disconnect_without_dc_enabled_does_not_unsubscribe(
    gateway: tuple[AlfGateway, _FakeSub, _FakeSub],
) -> None:
    gw, _sub, dc_sub = gateway
    session = _authed_session(gw)

    gw._disconnect(session, reason="test")

    assert not any(op[0] == zmq.UNSUBSCRIBE for op in dc_sub.ops)


# ---------------------------------------------------------------------------
# Drop-copy event relay (_poll_dc_events)
# ---------------------------------------------------------------------------


def test_dc_event_relayed_as_dc_fill(
    gateway: tuple[AlfGateway, _FakeSub, _FakeSub],
) -> None:
    gw, _sub, dc_sub = gateway
    session = _authed_session(gw)
    gw._handle_client_line(session, "DC|STATE=ON")
    session.out_queue.clear()  # drop the DC_ACK line to isolate DC_FILL

    dc_sub.push(
        encode(
            "drop_copy.event.TRADER01",
            {
                "seq": 42,
                "gateway_id": "TRADER01",
                "event_type": "order.fill",
                "order_id": "ord-001",
                "symbol": "AAPL",
                "fill_qty": 100,
                "fill_price": 150.05,
                "liquidity_flag": "TAKER",
            },
        )
    )

    gw._poll_dc_events()

    assert session.out_queue
    frame = parse_alf_line(session.out_queue[0].decode("utf-8"))
    assert frame.command == "DC_FILL"
    assert frame.fields["SEQ"] == "42"
    assert frame.fields["SYMBOL"] == "AAPL"
    assert frame.fields["FILL_QTY"] == "100"
    assert frame.fields["FILL_PRICE"] == "150.05"
    assert frame.fields["LIQUIDITY"] == "TAKER"
    assert frame.fields["ORDER_ID"] == "ORD-001"  # ALF uppercases field values


def test_dc_event_not_relayed_when_dc_disabled(
    gateway: tuple[AlfGateway, _FakeSub, _FakeSub],
) -> None:
    gw, _sub, dc_sub = gateway
    session = _authed_session(gw)
    # DC never enabled for this session.

    dc_sub.push(
        encode(
            "drop_copy.event.TRADER01",
            {"seq": 1, "gateway_id": "TRADER01", "order_id": "x"},
        )
    )

    gw._poll_dc_events()

    assert not session.out_queue


def test_dc_event_for_other_gateway_not_delivered(
    gateway: tuple[AlfGateway, _FakeSub, _FakeSub],
) -> None:
    """Even if somehow received, an event addressed to a gateway with no
    active session must not be delivered anywhere."""
    gw, _sub, dc_sub = gateway
    session = _authed_session(gw, gateway_id="TRADER01")
    gw._handle_client_line(session, "DC|STATE=ON")
    session.out_queue.clear()

    dc_sub.push(
        encode(
            "drop_copy.event.TRADER99",
            {"seq": 1, "gateway_id": "TRADER99", "order_id": "x"},
        )
    )

    gw._poll_dc_events()

    assert not session.out_queue


def test_dc_replay_topic_not_relayed(
    gateway: tuple[AlfGateway, _FakeSub, _FakeSub],
) -> None:
    """DC relay only understands drop_copy.event.* -- replay topics (a
    different prefix) are ignored, matching the ON-only opt-in scope."""
    gw, _sub, dc_sub = gateway
    session = _authed_session(gw)
    gw._handle_client_line(session, "DC|STATE=ON")
    session.out_queue.clear()

    dc_sub.push(
        encode(
            "drop_copy.replay.TRADER01",
            {"seq": 1, "gateway_id": "TRADER01", "order_id": "x"},
        )
    )

    gw._poll_dc_events()

    assert not session.out_queue
