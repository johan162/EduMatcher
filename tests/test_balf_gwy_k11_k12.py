"""K11/K12 regression tests for the BALF gateway (findings B1-B4).

B1  An accepted ``LOGON_ACK`` was sent before symbol metadata existed, so an
    order on a 3-decimal symbol was priced against the shared 2-decimal
    default. ``_known_symbols`` was populated but never consulted.
B2  No startup-recovery branch, so clients stayed authenticated to a session
    the restarted engine had lost.
B3  One ``_PendingRequest`` per engine UUID, so a pipelined second cancel or
    amend overwrote the first and one of the two acks was lost.
B4  ``EVICT_OLD`` looked only in ``_active_gateway_sessions``, so a session
    still waiting for its auth reply was never evicted.

The tests drive ``BalfGateway`` directly over a socketpair with fake ZMQ
sockets: the behaviour under test is all in the dispatch logic, and a real
TCP/ZMQ round trip would only add timing noise.
"""

from __future__ import annotations

import socket
import struct
from collections import deque
from typing import Any

import pytest

from edumatcher.balf_gwy.codec import (
    HEADER_SIZE,
    LOGON_REJECT_OTHER,
    MSG_AMEND_ACK,
    MSG_CANCEL_ACK,
    MSG_LOGON_ACK,
    MSG_LOGOUT,
    MSG_ORDER_ACK,
    SIDE_BUY,
    encode_price,
)
from edumatcher.balf_gwy.config import BalfGatewayConfig
from edumatcher.balf_gwy.gateway import BalfGateway, ClientSession
from edumatcher.balf_gwy.protocol import RC_SYMBOL_NOT_CONFIGURED
from edumatcher.models.message import decode, encode

GW = "TRADER01"
SYM3 = "ZK11A"  # 3 tick decimals
SYM2 = "ZK11B"  # 2 tick decimals


# ---------------------------------------------------------------------------
# Fakes and fixtures
# ---------------------------------------------------------------------------


class _FakePush:
    def __init__(self) -> None:
        self.closed = False
        self.sent: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


class _FakeSub:
    def __init__(self) -> None:
        self.closed = False
        self._queue: deque[list[bytes]] = deque()

    def setsockopt(self, op: int, value: bytes) -> None:
        _ = op, value

    def poll(self, timeout: int = 0) -> int:
        _ = timeout
        return 1 if self._queue else 0

    def recv_multipart(self) -> list[bytes]:
        return self._queue.popleft()

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def gateway(monkeypatch: pytest.MonkeyPatch) -> BalfGateway:
    push, sub = _FakePush(), _FakeSub()
    monkeypatch.setattr("edumatcher.balf_gwy.gateway.make_pusher", lambda _addr: push)
    monkeypatch.setattr(
        "edumatcher.balf_gwy.gateway.make_subscriber",
        lambda _addr, *_topics: sub,
    )
    cfg = BalfGatewayConfig(
        name="balf-k11-k12",
        bind_address="127.0.0.1",
        port=5561,
        auth_timeout_sec=30.0,
        gateway_roles=((GW, "TRADER"),),
    )
    return BalfGateway(cfg)


@pytest.fixture()
def peers() -> Any:
    """Hands out socketpairs and closes every one at teardown."""
    made: list[socket.socket] = []

    def _make() -> socket.socket:
        left, right = socket.socketpair()
        made.extend((left, right))
        return left

    yield _make
    for sock in made:
        sock.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _push(gw: BalfGateway) -> _FakePush:
    assert isinstance(gw._push, _FakePush)
    return gw._push


def _sub(gw: BalfGateway) -> _FakeSub:
    assert isinstance(gw._sub, _FakeSub)
    return gw._sub


def _sent_topics(gw: BalfGateway) -> list[str]:
    return [decode(f)[0] for f in _push(gw).sent]


def _sent(gw: BalfGateway, topic: str) -> list[dict[str, Any]]:
    out = []
    for frames in _push(gw).sent:
        t, payload = decode(frames)
        if t == topic:
            out.append(payload)
    return out


def _connect(gw: BalfGateway, peers: Any) -> ClientSession:
    sock = peers()
    session = ClientSession(sock=sock, addr=("127.0.0.1", 40000 + sock.fileno()))
    session.rate_tokens = float(gw.config.max_messages_per_second)
    gw._clients[sock.fileno()] = session
    return session


def _logon(gw: BalfGateway, session: ClientSession, gw_id: str = GW) -> None:
    body = struct.pack("<16sB7s", gw_id.encode(), 1, b"\x00" * 7)
    gw._handle_logon(session, body)


def _publish(gw: BalfGateway, topic: str, payload: dict[str, Any]) -> None:
    _sub(gw)._queue.append(encode(topic, payload))
    gw._poll_engine_events()


def _auth_ok(gw: BalfGateway, gw_id: str = GW) -> None:
    _publish(
        gw,
        f"system.gateway_auth.{gw_id}",
        {"gateway_id": gw_id, "accepted": True, "reason": "", "description": "d"},
    )


def _symbols(gw: BalfGateway, gw_id: str = GW) -> None:
    _publish(
        gw,
        f"system.symbols.{gw_id}",
        {
            "symbols": [
                {"symbol": SYM3, "tick_decimals": 3},
                {"symbol": SYM2, "tick_decimals": 2},
            ]
        },
    )


def _frames(session: ClientSession) -> list[tuple[int, bytes]]:
    return [(bytes(f)[2], bytes(f)[HEADER_SIZE:]) for f in session.out_queue]


def _of_type(session: ClientSession, msg_type: int) -> list[bytes]:
    return [body for mt, body in _frames(session) if mt == msg_type]


def _new_order_frame(
    client_order_id: int = 1,
    symbol: str = SYM3,
    price: float = 150.125,
    quantity: int = 100,
) -> bytes:
    return struct.pack(
        "<Q8sqqqIIBBBB",
        client_order_id,
        symbol.encode("ascii").ljust(8, b"\x00"),
        encode_price(price),
        0,
        0,
        quantity,
        0,
        SIDE_BUY,
        0x02,  # LIMIT
        0x01,  # DAY
        0x00,
    )


def _ready_session(gw: BalfGateway, peers: Any) -> ClientSession:
    """A fully logged-on session with symbol metadata in place."""
    session = _connect(gw, peers)
    _logon(gw, session)
    _auth_ok(gw)
    _symbols(gw)
    assert session.authenticated
    session.out_queue.clear()
    _push(gw).sent.clear()
    return session


def _resting_order(gw: BalfGateway, session: ClientSession) -> int:
    """Submit one order, accept it on the engine side, return its BALF id."""
    gw._handle_new_order(session, _new_order_frame())
    engine_uuid = _sent(gw, "order.new")[0]["id"]
    _publish(
        gw,
        f"order.ack.{GW}",
        {"gateway_id": GW, "order_id": engine_uuid, "accepted": True, "reason": ""},
    )
    balf_id = session.engine_to_balf[engine_uuid][0]
    session.out_queue.clear()
    _push(gw).sent.clear()
    return int(balf_id)


# ===========================================================================
# B1 — symbol-metadata readiness gate
# ===========================================================================


def test_b1_logon_ack_is_withheld_until_symbol_metadata_arrives(
    gateway: BalfGateway, peers: Any
) -> None:
    """An accepted auth reply alone must not authenticate the session."""
    session = _connect(gateway, peers)
    _logon(gateway, session)
    _auth_ok(gateway)

    assert not session.authenticated, "logon completed before symbol metadata"
    assert _of_type(session, MSG_LOGON_ACK) == []
    assert "system.symbols_request" in _sent_topics(gateway)

    _symbols(gateway)

    (ack,) = _of_type(session, MSG_LOGON_ACK)
    assert ack[16] == 1  # accepted
    assert session.authenticated


def test_b1_order_is_priced_at_the_symbols_own_tick_scale(
    gateway: BalfGateway, peers: Any
) -> None:
    """A 3-decimal price must convert at 3 decimals, not the 2-decimal default."""
    session = _ready_session(gateway, peers)

    gateway._handle_new_order(session, _new_order_frame(price=150.125))

    (order_new,) = _sent(gateway, "order.new")
    assert order_new["price_ticks"] == 150125
    assert order_new["tick_decimals"] == 3


def test_b1_order_on_an_unknown_symbol_is_rejected_not_defaulted(
    gateway: BalfGateway, peers: Any
) -> None:
    """A symbol the engine never listed must never be priced by default."""
    session = _ready_session(gateway, peers)

    gateway._handle_new_order(session, _new_order_frame(symbol="ZNOPE"))

    assert _sent(gateway, "order.new") == []
    (ack,) = _of_type(session, MSG_ORDER_ACK)
    accepted, reject_code = ack[24], ack[25]
    assert accepted == 0
    assert reject_code == RC_SYMBOL_NOT_CONFIGURED


def test_b1_logon_is_rejected_when_symbol_metadata_never_arrives(
    gateway: BalfGateway, peers: Any
) -> None:
    """A silent engine must fail the logon with a reason, not hang it."""
    session = _connect(gateway, peers)
    _logon(gateway, session)
    _auth_ok(gateway)
    assert session.symbols_pending

    session.symbols_requested_at -= gateway.config.auth_timeout_sec + 1.0
    gateway._drop_stale_clients()

    (ack,) = _of_type(session, MSG_LOGON_ACK)
    assert ack[16] == 0  # rejected
    assert ack[17] == LOGON_REJECT_OTHER
    assert session.closing and not session.authenticated


# ===========================================================================
# B2 — engine-restart session reconciliation
# ===========================================================================


def test_b2_engine_restart_drops_every_balf_session(
    gateway: BalfGateway, peers: Any
) -> None:
    """A restarted engine holds no sessions, so neither may the gateway."""
    live = _ready_session(gateway, peers)
    pending = _connect(gateway, peers)
    _logon(gateway, pending, "TRADER02")

    _publish(gateway, "system.startup_recovery", {"restored_orders": 0})

    assert _of_type(live, MSG_LOGOUT), "authenticated client was not told"
    assert live.closing and not live.authenticated and not live.connect_emitted
    assert pending.closing and not pending.auth_pending
    assert gateway._active_gateway_sessions == {}
    # Its symbol configuration may have changed with it.
    assert gateway._known_symbols == set()
    assert not gateway._symbols_ready


def test_b2_an_order_after_an_engine_restart_is_not_forwarded(
    gateway: BalfGateway, peers: Any
) -> None:
    session = _ready_session(gateway, peers)
    _publish(gateway, "system.startup_recovery", {"restored_orders": 0})
    _push(gateway).sent.clear()

    gateway._process_frame(session, 0x10, 1, _new_order_frame(client_order_id=7))

    assert _sent(gateway, "order.new") == []


# ===========================================================================
# B3 — per-request correlation tags
# ===========================================================================


def test_b3_two_pipelined_cancels_both_get_their_own_ack(
    gateway: BalfGateway, peers: Any
) -> None:
    session = _ready_session(gateway, peers)
    balf_id = _resting_order(gateway, session)

    gateway._handle_cancel_order(session, struct.pack("<QQ", 11, balf_id))
    gateway._handle_cancel_order(session, struct.pack("<QQ", 22, balf_id))

    cancels = _sent(gateway, "order.cancel")
    assert len(cancels) == 2
    tag1, tag2 = cancels[0]["request_tag"], cancels[1]["request_tag"]
    assert tag1 and tag2 and tag1 != tag2
    engine_uuid = cancels[0]["order_id"]

    # First wins; the second is refused because the order is already gone.
    _publish(
        gateway,
        f"order.cancelled.{GW}",
        {"gateway_id": GW, "order_id": engine_uuid, "request_tag": tag1},
    )
    _publish(
        gateway,
        f"order.ack.{GW}",
        {
            "gateway_id": GW,
            "order_id": engine_uuid,
            "accepted": False,
            "reason": "unknown order",
            "request_tag": tag2,
        },
    )

    acks = [struct.unpack_from("<QQBB", b) for b in _of_type(session, MSG_CANCEL_ACK)]
    assert [(clordid, accepted) for clordid, _, accepted, _ in acks] == [
        (11, 1),
        (22, 0),
    ]


def test_b3_two_pipelined_amends_both_get_their_own_ack(
    gateway: BalfGateway, peers: Any
) -> None:
    session = _ready_session(gateway, peers)
    balf_id = _resting_order(gateway, session)

    amend = struct.pack("<QQqIBxxxxxxx", 11, balf_id, encode_price(150.250), 0, 0x01)
    gateway._handle_amend_order(session, amend)
    amend2 = struct.pack("<QQqIBxxxxxxx", 22, balf_id, encode_price(150.375), 0, 0x01)
    gateway._handle_amend_order(session, amend2)

    amends = _sent(gateway, "order.amend")
    assert len(amends) == 2
    tag1, tag2 = amends[0]["request_tag"], amends[1]["request_tag"]
    assert tag1 and tag2 and tag1 != tag2
    engine_uuid = amends[0]["order_id"]

    _publish(
        gateway,
        f"order.amended.{GW}",
        {
            "gateway_id": GW,
            "order_id": engine_uuid,
            "price": 150.250,
            "qty": 100,
            "remaining_qty": 100,
            "priority_reset": False,
            "request_tag": tag1,
        },
    )
    _publish(
        gateway,
        f"order.ack.{GW}",
        {
            "gateway_id": GW,
            "order_id": engine_uuid,
            "accepted": False,
            "reason": "amend rejected",
            "request_tag": tag2,
        },
    )

    acks = [struct.unpack_from("<QQ", b) for b in _of_type(session, MSG_AMEND_ACK)]
    accepted = [b[32] for b in _of_type(session, MSG_AMEND_ACK)]
    assert [clordid for clordid, _ in acks] == [11, 22]
    assert accepted == [1, 0]


# ===========================================================================
# B4 — EVICT_OLD covers pending sessions
# ===========================================================================


def test_b4_evict_old_closes_a_session_still_awaiting_its_auth_reply(
    gateway: BalfGateway, peers: Any
) -> None:
    gateway.config = BalfGatewayConfig(
        **{**gateway.config.__dict__, "duplicate_session_policy": "EVICT_OLD"}
    )
    first = _connect(gateway, peers)
    _logon(gateway, first)
    assert first.auth_pending

    second = _connect(gateway, peers)
    _logon(gateway, second)

    assert first.sock.fileno() not in gateway._clients, "pending session not evicted"
    assert second.auth_pending

    _auth_ok(gateway)
    _symbols(gateway)
    assert second.authenticated
    assert gateway._active_gateway_sessions == {GW: second.sock.fileno()}


def test_b4_evict_old_still_closes_an_authenticated_session(
    gateway: BalfGateway, peers: Any
) -> None:
    gateway.config = BalfGatewayConfig(
        **{**gateway.config.__dict__, "duplicate_session_policy": "EVICT_OLD"}
    )
    first = _ready_session(gateway, peers)

    second = _connect(gateway, peers)
    _logon(gateway, second)

    assert first.sock.fileno() not in gateway._clients
    _auth_ok(gateway)
    assert second.authenticated  # metadata is already known gateway-wide
    assert gateway._active_gateway_sessions == {GW: second.sock.fileno()}


def test_b4_reject_new_still_refuses_a_duplicate_of_a_pending_session(
    gateway: BalfGateway, peers: Any
) -> None:
    first = _connect(gateway, peers)
    _logon(gateway, first)

    second = _connect(gateway, peers)
    _logon(gateway, second)

    (ack,) = _of_type(second, MSG_LOGON_ACK)
    assert ack[16] == 0
    assert second.closing and first.auth_pending
