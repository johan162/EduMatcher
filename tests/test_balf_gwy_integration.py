"""Live integration tests for pm-balf-gwy.

Uses real TCP client sockets and a fake ZMQ engine (PULL + PUB) to exercise
the full round-trip path: framing, authentication, command forwarding, event
delivery, heartbeats, auth-timeout, and disconnect behaviour.

Test structure mirrors tests/test_alf_gwy_integration.py.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from collections.abc import Generator

import pytest
import zmq

from edumatcher.balf_gwy.codec import (
    BALF_MAGIC,
    BALF_VERSION,
    CANCEL_REASON_SYSTEM,
    FRAME_SIZE,
    HEADER_SIZE,
    LOGON_REJECT_ALREADY_CONNECTED,
    LOGON_REJECT_NOT_CONFIGURED,
    LOGON_REJECT_PROTO_MISMATCH,
    MSG_AMEND_ACK,
    MSG_CANCEL_ACK,
    MSG_CANCEL_ORDER,
    MSG_AMEND_ORDER,
    MSG_EXECUTION_REPORT,
    MSG_HEARTBEAT,
    MSG_HEARTBEAT_ACK,
    MSG_LOGON,
    MSG_LOGON_ACK,
    MSG_NEW_ORDER,
    MSG_ORDER_ACK,
    SIDE_BUY,
    STATUS_PARTIAL,
    build_header,
    encode_price,
    now_ns,
)
from edumatcher.balf_gwy.config import BalfGatewayConfig
from edumatcher.balf_gwy.gateway import BalfGateway
from edumatcher.models.message import encode

# ---------------------------------------------------------------------------
# Wire-level helpers — build client-direction frames
# ---------------------------------------------------------------------------


def _build_logon(gateway_id: str = "TRADER01", proto_ver: int = BALF_VERSION) -> bytes:
    body = struct.pack(
        "<16sB7s",
        gateway_id.encode("ascii", errors="replace"),
        proto_ver,
        b"\x00" * 7,
    )
    return build_header(MSG_LOGON, 0) + body


def _build_new_order(
    client_order_id: int = 1,
    symbol: str = "AAPL",
    price: int = encode_price(150.0),
    quantity: int = 100,
    side: int = SIDE_BUY,
    order_type: int = 0x02,  # LIMIT
    tif: int = 0x01,  # DAY
    smp: int = 0x00,
    seq_no: int = 1,
) -> bytes:
    body = struct.pack(
        "<Q8sqqqIIBBBB",
        client_order_id,
        symbol.encode("ascii"),
        price,
        0,
        0,
        quantity,
        0,
        side,
        order_type,
        tif,
        smp,
    )
    return build_header(MSG_NEW_ORDER, seq_no) + body


def _build_cancel_order(
    client_order_id: int,
    balf_order_id: int,
    seq_no: int = 2,
) -> bytes:
    body = struct.pack("<QQ", client_order_id, balf_order_id)
    return build_header(MSG_CANCEL_ORDER, seq_no) + body


def _build_amend_order(
    client_order_id: int,
    balf_order_id: int,
    new_price: int = 0,
    new_quantity: int = 0,
    amend_flags: int = 0x01,
    seq_no: int = 2,
) -> bytes:
    body = struct.pack(
        "<QQqIBxxxxxxx",
        client_order_id,
        balf_order_id,
        new_price,
        new_quantity,
        amend_flags,
    )
    return build_header(MSG_AMEND_ORDER, seq_no) + body


def _build_heartbeat(seq_no: int = 1) -> bytes:
    return build_header(MSG_HEARTBEAT, seq_no) + struct.pack("<Q", now_ns())


# ---------------------------------------------------------------------------
# _BalfClient — binary frame reader for test sockets
# ---------------------------------------------------------------------------


class _BalfClient:
    """Binary framing helper used by integration tests."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = bytearray()

    def send(self, frame: bytes) -> None:
        self._sock.sendall(frame)

    def recv_frame(self, timeout: float = 3.0) -> tuple[int, bytes]:
        """Read and return (msg_type, body) for the next complete BALF frame."""
        deadline = time.monotonic() + timeout

        while len(self._buf) < HEADER_SIZE:
            rem = deadline - time.monotonic()
            if rem <= 0:
                raise TimeoutError("timeout waiting for BALF header")
            self._sock.settimeout(rem)
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RuntimeError("connection closed by gateway")
            self._buf.extend(chunk)

        msg_type = self._buf[2]
        total = FRAME_SIZE.get(msg_type)
        if total is None:
            raise ValueError(f"unknown server msg_type 0x{msg_type:02X}")

        while len(self._buf) < total:
            rem = deadline - time.monotonic()
            if rem <= 0:
                raise TimeoutError("timeout waiting for complete BALF frame")
            self._sock.settimeout(rem)
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RuntimeError("connection closed by gateway")
            self._buf.extend(chunk)

        frame = bytes(self._buf[:total])
        del self._buf[:total]
        return msg_type, frame[HEADER_SIZE:]

    def recv_until(
        self, expected_type: int, timeout: float = 3.0, max_frames: int = 10
    ) -> bytes:
        """Read frames until one of expected_type arrives; return its body."""
        for _ in range(max_frames):
            mt, body = self.recv_frame(timeout=timeout)
            if mt == expected_type:
                return body
        raise TimeoutError(f"never received msg_type 0x{expected_type:02X}")

    def is_closed(self, timeout: float = 1.0) -> bool:
        """Return True if the remote end has closed the connection."""
        try:
            self._sock.settimeout(timeout)
            data = self._sock.recv(1)
            return data == b""
        except socket.timeout:
            return False
        except OSError:
            return True


# ---------------------------------------------------------------------------
# Engine-side helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _drain_pull_until(
    pull: "zmq.Socket[bytes]",
    topic_prefix: str,
    timeout: float = 3.0,
) -> tuple[str, dict]:
    """Drain engine PULL socket until a message whose topic starts with prefix arrives."""
    from edumatcher.models.message import decode as zmq_decode

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ms = max(1, int((deadline - time.monotonic()) * 1000))
        if not pull.poll(timeout=ms):
            continue
        frames = pull.recv_multipart()
        topic, payload = zmq_decode(frames)
        if topic.startswith(topic_prefix):
            return topic, payload
    raise TimeoutError(f"never received '{topic_prefix}' within {timeout}s")


def _balf_authenticate(
    bc: _BalfClient,
    engine_pull: "zmq.Socket[bytes]",
    engine_pub: "zmq.Socket[bytes]",
    gateway_id: str = "TRADER01",
) -> bytes:
    """Complete LOGON → engine auth → LOGON_ACK round-trip.

    Returns the raw LOGON_ACK body.
    """
    bc.send(_build_logon(gateway_id))

    # Wait until gateway_connect lands on the engine PULL.
    _drain_pull_until(engine_pull, "system.gateway_connect", timeout=3.0)

    # Allow ZMQ subscription to propagate before publishing the auth reply.
    time.sleep(0.1)

    engine_pub.send_multipart(
        encode(
            f"system.gateway_auth.{gateway_id}",
            {
                "gateway_id": gateway_id,
                "accepted": True,
                "reason": "",
                "description": "integration test gateway",
            },
        )
    )

    return bc.recv_until(MSG_LOGON_ACK, timeout=3.0)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

GatewayFixture = tuple[BalfGateway, "zmq.Socket[bytes]", "zmq.Socket[bytes]", int]


@pytest.fixture()
def running_gateway() -> Generator[GatewayFixture, None, None]:
    """Start a real BalfGateway backed by fake ZMQ engine sockets.

    Yields (gateway, engine_pull, engine_pub, tcp_port).
    """
    engine_pull_port = _free_port()
    engine_pub_port = _free_port()
    gateway_port = _free_port()

    engine_pull_addr = f"tcp://127.0.0.1:{engine_pull_port}"
    engine_pub_addr = f"tcp://127.0.0.1:{engine_pub_port}"

    ctx = zmq.Context.instance()
    engine_pull: zmq.Socket[bytes] = ctx.socket(zmq.PULL)
    engine_pull.bind(engine_pull_addr)

    engine_pub: zmq.Socket[bytes] = ctx.socket(zmq.PUB)
    engine_pub.bind(engine_pub_addr)

    cfg = BalfGatewayConfig(
        name="balf-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        engine_pull_addr=engine_pull_addr,
        engine_pub_addr=engine_pub_addr,
        heartbeat_interval_sec=60,  # disabled by default
        heartbeat_timeout_sec=60,
        auth_timeout_sec=60,
        max_connections=16,
        max_client_queue=10_000,
        max_messages_per_second=1000,
        max_errors_before_disconnect=50,
        gateway_roles=(("TRADER01", "TRADER"), ("MM01", "MARKET_MAKER")),
    )

    gw = BalfGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()

    # Allow TCP listener to bind and PUB/SUB subscriptions to settle.
    time.sleep(0.15)
    time.sleep(0.1)

    try:
        yield gw, engine_pull, engine_pub, gateway_port
    finally:
        gw.stop()
        t.join(timeout=2.0)
        engine_pull.close()
        engine_pub.close()


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def test_logon_and_auth_success(running_gateway: GatewayFixture) -> None:
    """LOGON → engine auth → LOGON_ACK accepted round-trip."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        body = _balf_authenticate(bc, pull, pub)
        # body[16] = accepted byte
        assert body[16] == 1


def test_logon_proto_version_mismatch(running_gateway: GatewayFixture) -> None:
    """LOGON with wrong proto version → LOGON_ACK rejected + connection closes."""
    _, _, _, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        bc.send(_build_logon("TRADER01", proto_ver=0x99))

        body = bc.recv_until(MSG_LOGON_ACK, timeout=3.0)
        assert body[16] == 0  # accepted=false
        assert body[17] == LOGON_REJECT_PROTO_MISMATCH
        assert bc.is_closed(timeout=2.0)


def test_logon_invalid_gateway_id(running_gateway: GatewayFixture) -> None:
    """LOGON with empty gateway_id → LOGON_ACK rejected + connection closes."""
    _, _, _, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        bc.send(_build_logon(""))  # empty gateway_id

        body = bc.recv_until(MSG_LOGON_ACK, timeout=3.0)
        assert body[16] == 0
        assert bc.is_closed(timeout=2.0)


def test_auth_failure_closes_connection(running_gateway: GatewayFixture) -> None:
    """Engine returning accepted=false → LOGON_ACK rejected + close."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        bc.send(_build_logon("TRADER01"))

        _drain_pull_until(pull, "system.gateway_connect", timeout=3.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "system.gateway_auth.TRADER01",
                {
                    "gateway_id": "TRADER01",
                    "accepted": False,
                    "reason": "Gateway not configured: TRADER01",
                },
            )
        )

        body = bc.recv_until(MSG_LOGON_ACK, timeout=3.0)
        assert body[16] == 0  # accepted=false
        assert body[17] == LOGON_REJECT_NOT_CONFIGURED
        assert bc.is_closed(timeout=2.0)


def test_duplicate_session_reject_new(running_gateway: GatewayFixture) -> None:
    """Second LOGON with same gateway_id is rejected when policy=REJECT_NEW."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli1:
        bc1 = _BalfClient(cli1)
        _balf_authenticate(bc1, pull, pub, gateway_id="TRADER01")

        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli2:
            bc2 = _BalfClient(cli2)
            bc2.send(_build_logon("TRADER01"))

            body = bc2.recv_until(MSG_LOGON_ACK, timeout=3.0)
            assert body[16] == 0
            assert body[17] == LOGON_REJECT_ALREADY_CONNECTED
            assert bc2.is_closed(timeout=2.0)


def test_duplicate_session_evict_old(running_gateway: GatewayFixture) -> None:
    """When policy=EVICT_OLD the second LOGON displaces the first session."""
    gw, pull, pub, port = running_gateway

    gw.config = BalfGatewayConfig(
        **{
            **gw.config.__dict__,
            "duplicate_session_policy": "EVICT_OLD",
        }
    )

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli1:
        bc1 = _BalfClient(cli1)
        _balf_authenticate(bc1, pull, pub, gateway_id="TRADER01")

        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli2:
            bc2 = _BalfClient(cli2)
            bc2.send(_build_logon("TRADER01"))

            # Drain the gateway_disconnect for the evicted session, then
            # drain the gateway_connect for the new session.
            _drain_pull_until(pull, "system.gateway_disconnect", timeout=3.0)
            _drain_pull_until(pull, "system.gateway_connect", timeout=3.0)
            time.sleep(0.1)

            pub.send_multipart(
                encode(
                    "system.gateway_auth.TRADER01",
                    {"gateway_id": "TRADER01", "accepted": True, "reason": ""},
                )
            )

            body = bc2.recv_until(MSG_LOGON_ACK, timeout=3.0)
            assert body[16] == 1  # accepted=true


def test_pre_auth_non_logon_hard_closes(running_gateway: GatewayFixture) -> None:
    """Sending any non-LOGON frame before auth must hard-close the connection."""
    _, _, _, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        bc.send(_build_new_order())  # MSG_NEW_ORDER before LOGON
        assert bc.is_closed(timeout=2.0)


def test_bad_magic_hard_closes(running_gateway: GatewayFixture) -> None:
    """A frame with wrong magic byte must hard-close the connection."""
    _, _, _, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        # Craft a 32-byte LOGON frame with bad magic
        bad_frame = b"\xde" + bytes([BALF_VERSION, MSG_LOGON, 0]) + b"\x00" * 28
        cli.sendall(bad_frame)
        assert bc.is_closed(timeout=2.0)


def test_bad_version_hard_closes(running_gateway: GatewayFixture) -> None:
    """A frame with wrong version byte must hard-close the connection."""
    _, _, _, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        bad_frame = bytes([BALF_MAGIC, 0x99, MSG_LOGON, 0]) + b"\x00" * 28
        cli.sendall(bad_frame)
        assert bc.is_closed(timeout=2.0)


def test_auth_timeout_closes_connection(running_gateway: GatewayFixture) -> None:
    """Client that connects but never gets auth response is dropped after auth_timeout."""
    gw, pull, _, port = running_gateway

    gw.config = BalfGatewayConfig(**{**gw.config.__dict__, "auth_timeout_sec": 0.4})

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        bc.send(_build_logon("TRADER01"))
        # Drain gateway_connect but don't reply with auth
        _drain_pull_until(pull, "system.gateway_connect", timeout=3.0)

        # Wait for auth timeout to fire (auth_timeout_sec=0.4, sleep 1.5s)
        assert bc.is_closed(timeout=2.0)


# ---------------------------------------------------------------------------
# Command forwarding
# ---------------------------------------------------------------------------


def test_new_order_forwarded_to_engine(running_gateway: GatewayFixture) -> None:
    """NEW_ORDER frame must reach the engine PULL as order.new with correct fields."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=42, symbol="AAPL"))
        topic, payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        assert topic == "order.new"
        assert str(payload.get("symbol", "")).upper() == "AAPL"
        assert str(payload.get("side", "")).upper() == "BUY"
        assert str(payload.get("gateway_id", "")).upper() == "TRADER01"
        assert "id" in payload  # engine UUID was generated


def test_cancel_order_forwarded_to_engine(running_gateway: GatewayFixture) -> None:
    """After a NEW_ORDER is acked, CANCEL_ORDER must reach the engine as order.cancel."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        # Submit new order
        bc.send(_build_new_order(client_order_id=1))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        # Engine acks the order → client gets ORDER_ACK with balf_order_id
        pub.send_multipart(
            encode(
                "order.ack.TRADER01",
                {"order_id": engine_order_id, "accepted": True, "reason": ""},
            )
        )
        ack_body = bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        # balf_order_id is at body offset 8 (after client_order_id Q)
        balf_oid = struct.unpack_from("<Q", ack_body, 8)[0]
        assert balf_oid > 0

        # Now cancel using the balf_order_id we got back
        bc.send(
            _build_cancel_order(client_order_id=2, balf_order_id=balf_oid, seq_no=2)
        )
        _, cancel_payload = _drain_pull_until(pull, "order.cancel", timeout=3.0)
        assert str(cancel_payload.get("gateway_id", "")).upper() == "TRADER01"


def test_amend_order_forwarded_to_engine(running_gateway: GatewayFixture) -> None:
    """After a NEW_ORDER is acked, AMEND_ORDER must reach engine as order.amend."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=1))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01",
                {"order_id": engine_order_id, "accepted": True, "reason": ""},
            )
        )
        ack_body = bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        balf_oid = struct.unpack_from("<Q", ack_body, 8)[0]

        bc.send(
            _build_amend_order(
                client_order_id=2,
                balf_order_id=balf_oid,
                new_price=encode_price(160.0),
                amend_flags=0x01,
                seq_no=2,
            )
        )
        _, amend_payload = _drain_pull_until(pull, "order.amend", timeout=3.0)
        assert str(amend_payload.get("gateway_id", "")).upper() == "TRADER01"


# ---------------------------------------------------------------------------
# Event delivery
# ---------------------------------------------------------------------------


def test_order_ack_accepted_delivered(running_gateway: GatewayFixture) -> None:
    """order.ack(accepted=True) → client receives ORDER_ACK accepted."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=5))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01",
                {"order_id": engine_order_id, "accepted": True, "reason": ""},
            )
        )

        body = bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        assert body[24] == 1  # accepted=true
        balf_oid = struct.unpack_from("<Q", body, 8)[0]
        assert balf_oid > 0


def test_order_ack_rejected_delivered(running_gateway: GatewayFixture) -> None:
    """order.ack(accepted=False) → client receives ORDER_ACK rejected with classify."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=5))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01",
                {
                    "order_id": engine_order_id,
                    "accepted": False,
                    "reason": "Market is closed",
                },
            )
        )

        body = bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        assert body[24] == 0  # accepted=false
        assert body[25] != 0  # reject_code non-zero


def test_fill_event_delivered(running_gateway: GatewayFixture) -> None:
    """order.fill → client receives EXECUTION_REPORT."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=7))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        # Ack first so mapping is established
        pub.send_multipart(
            encode(
                "order.ack.TRADER01",
                {"order_id": engine_order_id, "accepted": True},
            )
        )
        bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.fill.TRADER01",
                {
                    "order_id": engine_order_id,
                    "fill_price": 150.0,
                    "fill_qty": 50,
                    "remaining_qty": 50,
                    "status": "PARTIAL",
                    "symbol": "AAPL",
                    "side": "BUY",
                    "timestamp": now_ns(),
                },
            )
        )

        body = bc.recv_until(MSG_EXECUTION_REPORT, timeout=3.0)
        # fill_qty at body offset Q+Q+q = 24 → I (4 bytes)
        fill_qty = struct.unpack_from("<I", body, 24)[0]
        assert fill_qty == 50
        # status at body offset Q+Q+q+I+I+Q+8s = 48, status at 49
        assert body[49] == STATUS_PARTIAL


def test_cancelled_event_delivered(running_gateway: GatewayFixture) -> None:
    """order.cancelled (system cancel) → client receives CANCEL_ACK."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=8))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01",
                {"order_id": engine_order_id, "accepted": True},
            )
        )
        bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        time.sleep(0.1)

        # Inject system cancel (no prior CANCEL_ORDER from client)
        pub.send_multipart(
            encode(
                "order.cancelled.TRADER01",
                {"order_id": engine_order_id, "reason": "SMP"},
            )
        )

        body = bc.recv_until(MSG_CANCEL_ACK, timeout=3.0)
        assert body[16] == 1  # accepted=true
        assert body[17] == 255  # cancel_reason SYSTEM


def test_cancelled_event_for_client_cancel(running_gateway: GatewayFixture) -> None:
    """order.cancelled matching pending_cancel → client receives CANCEL_ACK accepted."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=10))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01", {"order_id": engine_order_id, "accepted": True}
            )
        )
        ack_body = bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        balf_oid = struct.unpack_from("<Q", ack_body, 8)[0]
        time.sleep(0.1)

        # Client sends CANCEL_ORDER
        bc.send(
            _build_cancel_order(client_order_id=11, balf_order_id=balf_oid, seq_no=2)
        )
        _drain_pull_until(pull, "order.cancel", timeout=3.0)
        time.sleep(0.1)

        # Engine publishes order.cancelled
        pub.send_multipart(
            encode(
                "order.cancelled.TRADER01",
                {"order_id": engine_order_id},
            )
        )

        body = bc.recv_until(MSG_CANCEL_ACK, timeout=3.0)
        assert body[16] == 1  # accepted=true
        assert body[17] == 0  # cancel_reason CLIENT


def test_expired_event_delivered(running_gateway: GatewayFixture) -> None:
    """order.expired → client receives CANCEL_ACK with CANCEL_REASON_SYSTEM."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=15))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01", {"order_id": engine_order_id, "accepted": True}
            )
        )
        bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode("order.expired.TRADER01", {"order_id": engine_order_id})
        )

        body = bc.recv_until(MSG_CANCEL_ACK, timeout=3.0)
        assert body[16] == 1  # accepted=true
        assert body[17] == CANCEL_REASON_SYSTEM


def test_amended_event_delivered(running_gateway: GatewayFixture) -> None:
    """order.amended → client receives AMEND_ACK accepted."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=20))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01", {"order_id": engine_order_id, "accepted": True}
            )
        )
        ack_body = bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        balf_oid = struct.unpack_from("<Q", ack_body, 8)[0]
        time.sleep(0.1)

        bc.send(
            _build_amend_order(
                client_order_id=21,
                balf_order_id=balf_oid,
                new_price=encode_price(160.0),
                amend_flags=0x01,
                seq_no=2,
            )
        )
        _drain_pull_until(pull, "order.amend", timeout=3.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.amended.TRADER01",
                {
                    "order_id": engine_order_id,
                    "price": 160.0,
                    "qty": 100,
                    "remaining_qty": 100,
                    "priority_reset": False,
                },
            )
        )

        body = bc.recv_until(MSG_AMEND_ACK, timeout=3.0)
        # accepted at body offset Q+Q+q+I+I = 32
        assert body[32] == 1


# ---------------------------------------------------------------------------
# Validation reject paths
# ---------------------------------------------------------------------------


def test_new_order_invalid_side_rejects(running_gateway: GatewayFixture) -> None:
    """NEW_ORDER with invalid side → client receives ORDER_ACK rejected."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=1, side=0x99))  # invalid side

        body = bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        assert body[24] == 0  # accepted=false
        # Gateway must NOT have forwarded it to the engine
        with pytest.raises(TimeoutError):
            _drain_pull_until(pull, "order.new", timeout=0.3)


def test_cancel_unknown_order_rejects_immediately(
    running_gateway: GatewayFixture,
) -> None:
    """CANCEL_ORDER for an unknown balf_order_id → immediate CANCEL_ACK rejected."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_cancel_order(client_order_id=1, balf_order_id=9999, seq_no=2))

        body = bc.recv_until(MSG_CANCEL_ACK, timeout=3.0)
        assert body[16] == 0  # accepted=false


def test_cancel_order_id_zero_rejects(running_gateway: GatewayFixture) -> None:
    """CANCEL_ORDER with balf_order_id=0 → CANCEL_ACK rejected."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_cancel_order(client_order_id=1, balf_order_id=0, seq_no=2))

        body = bc.recv_until(MSG_CANCEL_ACK, timeout=3.0)
        assert body[16] == 0  # accepted=false


def test_amend_unknown_order_rejects_immediately(
    running_gateway: GatewayFixture,
) -> None:
    """AMEND_ORDER for unknown balf_order_id → immediate AMEND_ACK rejected."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(
            _build_amend_order(
                client_order_id=1,
                balf_order_id=9999,
                new_price=1,
                amend_flags=0x01,
                seq_no=2,
            )
        )

        body = bc.recv_until(MSG_AMEND_ACK, timeout=3.0)
        assert body[32] == 0  # accepted=false


def test_amend_invalid_flags_rejects(running_gateway: GatewayFixture) -> None:
    """AMEND_ORDER with amend_flags=0 → AMEND_ACK rejected, session stays open."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=1))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01", {"order_id": engine_order_id, "accepted": True}
            )
        )
        ack_body = bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        balf_oid = struct.unpack_from("<Q", ack_body, 8)[0]

        # amend_flags=0 is invalid
        bc.send(
            _build_amend_order(
                client_order_id=2, balf_order_id=balf_oid, amend_flags=0x00, seq_no=2
            )
        )

        body = bc.recv_until(MSG_AMEND_ACK, timeout=3.0)
        assert body[32] == 0  # rejected

        # Session must still respond to heartbeat
        bc.send(_build_heartbeat(seq_no=3))
        bc.recv_until(MSG_HEARTBEAT_ACK, timeout=3.0)


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def test_heartbeat_from_client_gets_ack(running_gateway: GatewayFixture) -> None:
    """Client HEARTBEAT must receive a HEARTBEAT_ACK in response."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)

        bc.send(_build_heartbeat(seq_no=1))
        bc.recv_until(MSG_HEARTBEAT_ACK, timeout=3.0)


def test_gateway_sends_heartbeat_when_idle(running_gateway: GatewayFixture) -> None:
    """With heartbeat_interval_sec=1 the gateway sends HB when no outbound traffic."""
    gw, pull, pub, port = running_gateway

    gw.config = BalfGatewayConfig(
        **{**gw.config.__dict__, "heartbeat_interval_sec": 1.0}
    )

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)

        # Drain symbols_request so no further traffic
        try:
            _drain_pull_until(pull, "system.symbols_request", timeout=1.5)
        except TimeoutError:
            pass

        # Wait up to 3s for a heartbeat from the gateway
        mt, _ = bc.recv_frame(timeout=3.0)
        assert mt == MSG_HEARTBEAT


def test_heartbeat_timeout_disconnects_client(running_gateway: GatewayFixture) -> None:
    """Authenticated client that goes silent for heartbeat_timeout_sec is disconnected."""
    gw, pull, pub, port = running_gateway

    gw.config = BalfGatewayConfig(
        **{
            **gw.config.__dict__,
            "heartbeat_interval_sec": 60,
            "heartbeat_timeout_sec": 0.4,
        }
    )

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)

        assert bc.is_closed(timeout=2.0)


# ---------------------------------------------------------------------------
# Disconnect behaviour
# ---------------------------------------------------------------------------


def test_logout_sends_gateway_disconnect(running_gateway: GatewayFixture) -> None:
    """Client LOGOUT must forward system.gateway_disconnect to the engine."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(build_header(0x40, 0))  # MSG_LOGOUT, body=none
        _, payload = _drain_pull_until(pull, "system.gateway_disconnect", timeout=3.0)
        assert str(payload.get("gateway_id", "")).upper() == "TRADER01"

        assert bc.is_closed(timeout=2.0)


def test_peer_close_sends_gateway_disconnect(running_gateway: GatewayFixture) -> None:
    """Abrupt TCP close must still produce system.gateway_disconnect on the engine."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

    # Socket is now closed; give the gateway one loop tick to detect EOF
    time.sleep(0.2)

    _, payload = _drain_pull_until(pull, "system.gateway_disconnect", timeout=3.0)
    assert str(payload.get("gateway_id", "")).upper() == "TRADER01"


# ---------------------------------------------------------------------------
# Capacity limits
# ---------------------------------------------------------------------------


def test_max_connections_enforced(running_gateway: GatewayFixture) -> None:
    """Connections beyond max_connections are immediately dropped."""
    gw, _, _, port = running_gateway

    gw.config = BalfGatewayConfig(**{**gw.config.__dict__, "max_connections": 2})

    clients: list[socket.socket] = []
    try:
        for _ in range(2):
            s = socket.create_connection(("127.0.0.1", port), timeout=2)
            clients.append(s)
        time.sleep(0.1)

        over = socket.create_connection(("127.0.0.1", port), timeout=2)
        over.settimeout(2.0)
        assert over.recv(64) == b""
        over.close()
    finally:
        for c in clients:
            try:
                c.close()
            except OSError:
                pass


def test_rate_limiting_enforced(running_gateway: GatewayFixture) -> None:
    """Exceeding max_messages_per_second drops frames without closing the session."""
    gw, pull, pub, port = running_gateway

    gw.config = BalfGatewayConfig(
        **{**gw.config.__dict__, "max_messages_per_second": 1}
    )

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        # Flood with NEW_ORDERs faster than the token bucket allows (1/s).
        for i in range(10):
            bc.send(_build_new_order(client_order_id=i + 1, seq_no=i + 1))

        # Wait >1s so the token bucket refills to 1 token before the heartbeat.
        # The session must still be open (rate-limit does not close it).
        time.sleep(1.5)
        bc.send(_build_heartbeat(seq_no=99))
        bc.recv_until(MSG_HEARTBEAT_ACK, timeout=3.0)


# ---------------------------------------------------------------------------
# Additional coverage targets
# ---------------------------------------------------------------------------


def test_second_logon_after_auth_ignored(running_gateway: GatewayFixture) -> None:
    """A second LOGON frame sent after successful auth must be silently ignored."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)

        # Send another LOGON — gateway should ignore it and not hard-close
        bc.send(_build_logon("TRADER01"))
        time.sleep(0.2)

        # Session still alive: heartbeat round-trip succeeds
        bc.send(_build_heartbeat(seq_no=2))
        bc.recv_until(MSG_HEARTBEAT_ACK, timeout=3.0)


def test_server_direction_frame_from_client_ignored(
    running_gateway: GatewayFixture,
) -> None:
    """Sending a server-direction msg type (e.g. ORDER_ACK) from a client is
    silently ignored; session stays open."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)

        # Send an ORDER_ACK frame (server-direction) from the client side
        bad_frame = build_header(MSG_ORDER_ACK, seq_no=1) + b"\x00" * (
            FRAME_SIZE[MSG_ORDER_ACK] - HEADER_SIZE
        )
        bc.send(bad_frame)
        time.sleep(0.2)

        # Session still alive
        bc.send(_build_heartbeat(seq_no=2))
        bc.recv_until(MSG_HEARTBEAT_ACK, timeout=3.0)


def test_cancel_rejected_by_engine_via_order_ack(
    running_gateway: GatewayFixture,
) -> None:
    """Engine ORDER_ACK(rejected) for a pending cancel → CANCEL_ACK rejected."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=1))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01", {"order_id": engine_order_id, "accepted": True}
            )
        )
        ack_body = bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        balf_oid = struct.unpack_from("<Q", ack_body, 8)[0]
        time.sleep(0.1)

        # Send CANCEL_ORDER then have the engine reject it via ORDER_ACK
        bc.send(
            _build_cancel_order(client_order_id=2, balf_order_id=balf_oid, seq_no=2)
        )
        _drain_pull_until(pull, "order.cancel", timeout=3.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01",
                {
                    "order_id": engine_order_id,
                    "accepted": False,
                    "reason": "order not found",
                },
            )
        )

        body = bc.recv_until(MSG_CANCEL_ACK, timeout=3.0)
        assert body[16] == 0  # accepted=false


def test_amend_rejected_by_engine_via_order_ack(
    running_gateway: GatewayFixture,
) -> None:
    """Engine ORDER_ACK(rejected) for a pending amend → AMEND_ACK rejected."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=1))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01", {"order_id": engine_order_id, "accepted": True}
            )
        )
        ack_body = bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        balf_oid = struct.unpack_from("<Q", ack_body, 8)[0]
        time.sleep(0.1)

        bc.send(
            _build_amend_order(
                client_order_id=2,
                balf_order_id=balf_oid,
                new_price=encode_price(155.0),
                amend_flags=0x01,
                seq_no=2,
            )
        )
        _drain_pull_until(pull, "order.amend", timeout=3.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01",
                {
                    "order_id": engine_order_id,
                    "accepted": False,
                    "reason": "Market is closed",
                },
            )
        )

        body = bc.recv_until(MSG_AMEND_ACK, timeout=3.0)
        assert body[32] == 0  # accepted=false


def test_amend_no_valid_price_field_rejects(
    running_gateway: GatewayFixture,
) -> None:
    """AMEND_ORDER with flags=0x01 but new_price=0 → AMEND_ACK rejected."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        bc.send(_build_new_order(client_order_id=1))
        _, new_payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        engine_order_id = str(new_payload["id"])
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01", {"order_id": engine_order_id, "accepted": True}
            )
        )
        ack_body = bc.recv_until(MSG_ORDER_ACK, timeout=3.0)
        balf_oid = struct.unpack_from("<Q", ack_body, 8)[0]

        # flags=0x01 means "price update" but new_price=0 → price_display=None
        # flags has no 0x02 bit → qty stays None → "no valid amend field set"
        bc.send(
            _build_amend_order(
                client_order_id=2,
                balf_order_id=balf_oid,
                new_price=0,
                amend_flags=0x01,
                seq_no=2,
            )
        )

        body = bc.recv_until(MSG_AMEND_ACK, timeout=3.0)
        assert body[32] == 0  # accepted=false


def test_symbols_response_with_metadata(
    running_gateway: GatewayFixture,
) -> None:
    """Injecting a symbols response with symbol_meta registers tick decimals."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "system.symbols.TRADER01",
                {
                    "symbols": ["AAPL", "MSFT"],
                    "symbol_meta": {
                        "AAPL": {"tick_size": 0.01},
                        "MSFT": {"tick_size": 0.001},
                    },
                },
            )
        )
        # Allow the gateway a tick to process the symbols response
        time.sleep(0.2)

        # Session must still respond normally after processing symbols
        bc.send(_build_heartbeat(seq_no=2))
        bc.recv_until(MSG_HEARTBEAT_ACK, timeout=3.0)


def test_too_many_errors_causes_disconnect(
    running_gateway: GatewayFixture,
) -> None:
    """Exceeding max_errors_before_disconnect within the error window hard-closes."""
    gw, pull, pub, port = running_gateway

    gw.config = BalfGatewayConfig(
        **{**gw.config.__dict__, "max_errors_before_disconnect": 1}
    )

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        bc = _BalfClient(cli)
        _balf_authenticate(bc, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        # Send NEW_ORDER with invalid side → triggers BalfValidationError →
        # _register_error called → 1 error >= max_errors=1 → hard-close
        bc.send(_build_new_order(client_order_id=1, side=0x99))

        # Gateway should hard-close immediately
        assert bc.is_closed(timeout=2.0)
