"""
Robustness and security integration tests for pm-balf-gwy.

Uses real TCP client sockets and a fake ZMQ engine (PULL + PUB).

High priority:
  - Malformed BALF frame header: wrong magic, wrong version, unknown msg_type
  - Non-zero flags field: silently ignored, session stays alive
  - Server-direction msg_type sent by authenticated client: silently ignored
  - Pre-auth non-LOGON frame: hard-close
  - Auth timeout: unauthenticated session hard-closed

Medium priority:
  - Partial frame delivery: gateway waits for the complete frame
  - Pipelined frames: two complete frames in one TCP write are both processed
  - Heartbeat timeout: authenticated idle session is disconnected
  - Connection limit: excess connections immediately closed
  - Duplicate session EVICT_OLD policy: old session is evicted by a new LOGON
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from collections.abc import Callable, Generator

import pytest
import zmq

from edumatcher.balf_gwy.codec import (
    BALF_MAGIC,
    BALF_VERSION,
    FRAME_SIZE,
    HEADER_SIZE,
    MSG_HEARTBEAT,
    MSG_HEARTBEAT_ACK,
    MSG_LOGON,
    MSG_LOGON_ACK,
    MSG_NEW_ORDER,
    MSG_ORDER_ACK,
    LOGON_REJECT_OTHER,
    SIDE_BUY,
    build_header,
    encode_price,
    now_ns,
)
from edumatcher.balf_gwy.config import BalfGatewayConfig
from edumatcher.balf_gwy.gateway import BalfGateway
from edumatcher.models.message import decode, encode

# ---------------------------------------------------------------------------
# Wire-level helpers
# ---------------------------------------------------------------------------


def _build_logon(gateway_id: str = "TRADER01", proto_ver: int = BALF_VERSION) -> bytes:
    body = struct.pack(
        "<16sB7s",
        gateway_id.encode("ascii", errors="replace"),
        proto_ver,
        b"\x00" * 7,
    )
    return build_header(MSG_LOGON, 0) + body


def _build_heartbeat(seq_no: int = 1) -> bytes:
    return build_header(MSG_HEARTBEAT, seq_no) + struct.pack("<Q", now_ns())


def _build_new_order(seq_no: int = 1) -> bytes:
    body = struct.pack(
        "<Q8sqqqIIBBBB",
        1,
        b"AAPL\x00\x00\x00\x00",
        encode_price(150.0),
        0,
        0,
        100,
        0,
        SIDE_BUY,
        0x02,  # LIMIT
        0x01,  # DAY
        0x00,
    )
    return build_header(MSG_NEW_ORDER, seq_no) + body


# ---------------------------------------------------------------------------
# Binary framing helper for test clients
# ---------------------------------------------------------------------------


class _BalfClient:
    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = bytearray()

    def send(self, frame: bytes) -> None:
        self._sock.sendall(frame)

    def recv_frame(self, timeout: float = 3.0) -> tuple[int, bytes]:
        """Return (msg_type, body) for the next complete frame."""
        deadline = time.monotonic() + timeout
        while len(self._buf) < HEADER_SIZE:
            rem = max(0.05, deadline - time.monotonic())
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
            rem = max(0.05, deadline - time.monotonic())
            self._sock.settimeout(rem)
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RuntimeError("connection closed by gateway")
            self._buf.extend(chunk)

        frame = bytes(self._buf[:total])
        del self._buf[:total]
        return msg_type, frame[HEADER_SIZE:]

    def recv_until(
        self, expected_type: int, timeout: float = 3.0, max_frames: int = 20
    ) -> bytes:
        for _ in range(max_frames):
            mt, body = self.recv_frame(timeout=timeout)
            if mt == expected_type:
                return body
        raise TimeoutError(f"never received msg_type 0x{expected_type:02X}")

    def is_closed(self, timeout: float = 1.5) -> bool:
        try:
            self._sock.settimeout(timeout)
            return self._sock.recv(1) == b""
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


def _drain_until(
    pull: "zmq.Socket[bytes]",
    prefix: str,
    timeout: float = 3.0,
) -> tuple[str, dict[str, object]]:
    from edumatcher.models.message import decode as zmq_decode

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ms = max(1, int((deadline - time.monotonic()) * 1000))
        if not pull.poll(timeout=ms):
            continue
        topic, payload = zmq_decode(pull.recv_multipart())
        if topic.startswith(prefix):
            return topic, payload
    raise TimeoutError(f"never received '{prefix}'")


def _publish_auth(
    pub: "zmq.Socket[bytes]",
    gateway_id: str = "TRADER01",
    accepted: bool = True,
    reason: str = "",
) -> None:
    pub.send_multipart(
        encode(
            f"system.gateway_auth.{gateway_id}",
            {"gateway_id": gateway_id, "accepted": accepted, "reason": reason},
        )
    )


def _do_auth(
    bc: _BalfClient,
    pull: "zmq.Socket[bytes]",
    pub: "zmq.Socket[bytes]",
    gateway_id: str = "TRADER01",
) -> bytes:
    bc.send(_build_logon(gateway_id))
    _drain_until(pull, "system.gateway_connect")
    time.sleep(0.1)  # allow ZMQ PUB subscription to propagate
    _publish_auth(pub, gateway_id, accepted=True)
    return bc.recv_until(MSG_LOGON_ACK)


# ---------------------------------------------------------------------------
# Factory fixture
# ---------------------------------------------------------------------------

GatewayFixture = tuple[BalfGateway, "zmq.Socket[bytes]", "zmq.Socket[bytes]", int]
FactoryFn = Callable[..., GatewayFixture]


@pytest.fixture()
def balf_gw_factory() -> Generator[FactoryFn, None, None]:
    """Provides a factory that spins up a BalfGateway with custom config fields."""
    instances: list[
        tuple[BalfGateway, threading.Thread, "zmq.Socket[bytes]", "zmq.Socket[bytes]"]
    ] = []

    def _make(**cfg_overrides: object) -> GatewayFixture:
        pull_port = _free_port()
        pub_port = _free_port()
        gw_port = _free_port()

        ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
        pull_sock: zmq.Socket[bytes] = ctx.socket(zmq.PULL)
        pull_sock.bind(f"tcp://127.0.0.1:{pull_port}")
        pub_sock: zmq.Socket[bytes] = ctx.socket(zmq.PUB)
        pub_sock.bind(f"tcp://127.0.0.1:{pub_port}")

        defaults: dict[str, object] = dict(
            name="balf-robustness-test",
            bind_address="127.0.0.1",
            port=gw_port,
            engine_pull_addr=f"tcp://127.0.0.1:{pull_port}",
            engine_pub_addr=f"tcp://127.0.0.1:{pub_port}",
            heartbeat_interval_sec=60,
            heartbeat_timeout_sec=60,
            auth_timeout_sec=60,
            max_connections=16,
            max_client_queue=10_000,
            max_messages_per_second=1_000,
            max_errors_before_disconnect=50,
            gateway_roles=(("TRADER01", "TRADER"),),
        )
        defaults.update(cfg_overrides)

        cfg = BalfGatewayConfig(**defaults)
        gw = BalfGateway(cfg)
        t = threading.Thread(target=gw.run, daemon=True)
        t.start()
        instances.append((gw, t, pull_sock, pub_sock))
        time.sleep(0.2)  # allow listener bind + ZMQ subscriptions
        return gw, pull_sock, pub_sock, gw_port

    yield _make

    for gw, t, pull_sock, pub_sock in instances:
        gw.stop()
        t.join(timeout=3.0)
        pull_sock.close(linger=0)
        pub_sock.close(linger=0)


# ===========================================================================
# Malformed frame header — high priority
# ===========================================================================


class TestMalformedFrameHeader:
    """Invalid header bytes must hard-close the connection without crashing."""

    def test_wrong_magic_hard_closes(self, balf_gw_factory: FactoryFn) -> None:
        _, _, _, port = balf_gw_factory()
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            bad_header = struct.pack("<BBBBI", 0xAB, BALF_VERSION, MSG_LOGON, 0, 0)
            bc.send(bad_header)
            assert bc.is_closed(), "gateway must hard-close on wrong magic"

    def test_wrong_version_hard_closes(self, balf_gw_factory: FactoryFn) -> None:
        _, _, _, port = balf_gw_factory()
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            bad_header = struct.pack("<BBBBI", BALF_MAGIC, 0x99, MSG_LOGON, 0, 0)
            bc.send(bad_header)
            assert bc.is_closed(), "gateway must hard-close on wrong version"

    def test_unknown_msg_type_hard_closes(self, balf_gw_factory: FactoryFn) -> None:
        _, _, _, port = balf_gw_factory()
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            # 0xEE is not in FRAME_SIZE — gateway cannot determine frame length
            bad_header = struct.pack("<BBBBI", BALF_MAGIC, BALF_VERSION, 0xEE, 0, 0)
            bc.send(bad_header)
            assert bc.is_closed(), "gateway must hard-close on unknown msg_type"

    def test_nonzero_flags_does_not_close_connection(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        """Non-zero flags are silently ignored; the frame is still processed."""
        _, pull, pub, port = balf_gw_factory()
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            # Authenticate first using a normal LOGON
            _do_auth(bc, pull, pub)

            # Send a HEARTBEAT with flags=0x01 (non-zero but reserved)
            flagged_header = struct.pack(
                "<BBBBI", BALF_MAGIC, BALF_VERSION, MSG_HEARTBEAT, 0x01, 2
            )
            body = struct.pack("<Q", now_ns())
            bc.send(flagged_header + body)

            # Gateway should respond with HEARTBEAT_ACK (frame processed)
            ack_body = bc.recv_until(MSG_HEARTBEAT_ACK, timeout=3.0)
            assert len(ack_body) > 0

    def test_server_direction_msg_type_after_auth_silently_ignored(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        """MSG_ORDER_ACK sent by client is ignored; session must stay alive."""
        _, pull, pub, port = balf_gw_factory()
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            _do_auth(bc, pull, pub)

            # MSG_ORDER_ACK = 0x11 is in FRAME_SIZE but NOT in CLIENT_MSG_TYPES
            fake_ack = build_header(MSG_ORDER_ACK, seq_no=99) + b"\x00" * (
                FRAME_SIZE[MSG_ORDER_ACK] - HEADER_SIZE
            )
            bc.send(fake_ack)
            time.sleep(0.05)  # give gateway a loop iteration to process

            # Connection must still be alive — verify with a heartbeat
            bc.send(_build_heartbeat(seq_no=5))
            ack_body = bc.recv_until(MSG_HEARTBEAT_ACK, timeout=3.0)
            assert len(ack_body) > 0

    def test_pre_auth_non_logon_hard_closes(self, balf_gw_factory: FactoryFn) -> None:
        """Sending any non-LOGON frame before auth must hard-close the connection."""
        _, _, _, port = balf_gw_factory()
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            # Send MSG_NEW_ORDER without a prior LOGON
            bc.send(_build_new_order(seq_no=1))
            assert bc.is_closed(), "gateway must hard-close on pre-auth non-LOGON"


# ===========================================================================
# Auth timeout — high priority
# ===========================================================================


class TestAuthTimeout:
    """Unauthenticated sessions must be hard-closed after auth_timeout_sec."""

    def test_auth_timeout_closes_idle_connection(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        """A client that connects but never sends LOGON is closed after timeout."""
        _, _, _, port = balf_gw_factory(auth_timeout_sec=0.3)
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            # Do nothing — just wait beyond the auth timeout
            assert bc.is_closed(timeout=2.0), "auth timeout must close idle connection"

    def test_auth_timeout_does_not_fire_before_deadline(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        """Connection is still open before the timeout expires."""
        _, pull, pub, port = balf_gw_factory(auth_timeout_sec=2.0)
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            # Wait only 0.2s — well within the 2.0s timeout
            assert not bc.is_closed(timeout=0.2), "connection should still be open"
            # Clean up by completing auth
            _do_auth(bc, pull, pub)

    def test_auth_timeout_not_extended_by_byte_dribble(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        """Slowloris-style byte dribble must not bypass auth timeout."""
        _, _, _, port = balf_gw_factory(auth_timeout_sec=0.4)
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            for _ in range(8):
                try:
                    cli.sendall(b"\xbe")
                except OSError:
                    break
                time.sleep(0.08)
            assert bc.is_closed(timeout=1.5), "auth timeout must close dribbling peer"


class TestPreAuthHardening:
    """Pre-auth LOGON path should not allow amplification or handshake leaks."""

    def test_duplicate_logon_while_pending_is_rejected_without_second_connect(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        _, pull, _pub, port = balf_gw_factory()
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)

            bc.send(_build_logon("TRADER01"))
            topic, _ = _drain_until(pull, "system.gateway_connect")
            assert topic == "system.gateway_connect"

            bc.send(_build_logon("TRADER01"))
            body = bc.recv_until(MSG_LOGON_ACK, timeout=1.5)
            accepted = body[16]
            reject_code = body[17]
            msg_len = body[18]
            msg = body[20 : 20 + msg_len].decode("ascii", errors="ignore")

            assert accepted == 0
            assert reject_code == LOGON_REJECT_OTHER
            assert "LOGON_ALREADY_PENDING" in msg

            # Ensure the second LOGON did not emit another gateway_connect.
            got_second_connect = False
            deadline = time.monotonic() + 0.4
            while time.monotonic() < deadline:
                if not pull.poll(timeout=20):
                    continue
                evt_topic, _payload = decode(pull.recv_multipart())
                if evt_topic == "system.gateway_connect":
                    got_second_connect = True
                    break
            assert not got_second_connect

    def test_auth_pending_disconnect_emits_gateway_disconnect(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        _, pull, _pub, port = balf_gw_factory()

        cli = socket.create_connection(("127.0.0.1", port), timeout=3)
        bc = _BalfClient(cli)
        bc.send(_build_logon("TRADER01"))
        topic, _ = _drain_until(pull, "system.gateway_connect")
        assert topic == "system.gateway_connect"

        cli.close()
        disc_topic, disc_payload = _drain_until(pull, "system.gateway_disconnect")
        assert disc_topic == "system.gateway_disconnect"
        assert str(disc_payload.get("gateway_id", "")).upper() == "TRADER01"


# ===========================================================================
# Engine unavailable / backpressure fail-fast — critical (C1)
# ===========================================================================


class TestEngineUnavailableFailFast:
    """Gateway must reject instead of hanging when engine PUSH cannot queue."""

    def test_logon_rejected_when_engine_unavailable(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        _, pull, _pub, port = balf_gw_factory()

        # Simulate engine unavailable: close the only PULL peer.
        pull.close(linger=0)
        time.sleep(0.05)

        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            bc.send(_build_logon("TRADER01"))

            body = bc.recv_until(MSG_LOGON_ACK, timeout=1.5)
            accepted = body[16]
            reject_code = body[17]
            msg_len = body[18]
            msg = body[20 : 20 + msg_len].decode("ascii", errors="ignore")

            assert accepted == 0
            assert reject_code == LOGON_REJECT_OTHER
            assert "ENGINE_UNAVAILABLE" in msg

    def test_new_order_rejected_when_engine_unavailable(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        _, pull, pub, port = balf_gw_factory()

        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            _do_auth(bc, pull, pub)

            # Engine goes down after auth.
            pull.close(linger=0)
            time.sleep(0.05)

            bc.send(_build_new_order(seq_no=2))
            body = bc.recv_until(MSG_ORDER_ACK, timeout=1.5)

            # ORDER_ACK body:
            # client_order_id Q | order_id Q | timestamp_ns Q |
            # accepted B | reject_code B | reason_len B | reason[25]
            accepted = body[24]
            reject_code = body[25]
            reason_len = body[26]
            reason = body[27 : 27 + reason_len].decode("ascii", errors="ignore")

            assert accepted == 0
            assert reject_code == 0xFF
            assert "ENGINE_UNAVAILABLE" in reason


# ===========================================================================
# Partial frame delivery and pipelining — medium priority
# ===========================================================================


class TestFrameStreaming:
    """Gateway must buffer partial frames and process pipelined complete frames."""

    def test_partial_frame_waits_for_completion(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        """Sending the LOGON header in two TCP writes still authenticates."""
        _, pull, pub, port = balf_gw_factory()
        logon = _build_logon()
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            # Send just the 8-byte header — gateway needs full 32-byte LOGON
            cli.sendall(logon[:HEADER_SIZE])
            time.sleep(0.05)  # gateway loop runs, sees partial frame, waits

            # Send the remainder
            cli.sendall(logon[HEADER_SIZE:])
            _drain_until(pull, "system.gateway_connect")
            time.sleep(0.1)
            _publish_auth(pub)

            body = bc.recv_until(MSG_LOGON_ACK, timeout=3.0)
            assert body[16] == 1  # accepted

    def test_pipelined_heartbeats_both_acked(self, balf_gw_factory: FactoryFn) -> None:
        """Two complete HEARTBEAT frames sent in one write must each get an ACK."""
        _, pull, pub, port = balf_gw_factory()
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            _do_auth(bc, pull, pub)

            # Pipeline two HEARTBEAT frames
            cli.sendall(_build_heartbeat(seq_no=2) + _build_heartbeat(seq_no=3))

            ack_bodies: list[bytes] = []
            for _ in range(10):  # drain up to 10 frames looking for 2 HB_ACKs
                try:
                    mt, body = bc.recv_frame(timeout=2.0)
                    if mt == MSG_HEARTBEAT_ACK:
                        ack_bodies.append(body)
                        if len(ack_bodies) == 2:
                            break
                except TimeoutError:
                    break

            assert len(ack_bodies) == 2, "both pipelined heartbeats must be acked"


# ===========================================================================
# Heartbeat timeout — medium priority
# ===========================================================================


class TestHeartbeatTimeout:
    """Authenticated sessions that stop sending must be disconnected."""

    def test_idle_authenticated_session_is_disconnected(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        """After heartbeat_timeout_sec of silence the gateway closes the session."""
        _, pull, pub, port = balf_gw_factory(
            heartbeat_timeout_sec=0.3,
            heartbeat_interval_sec=60,  # gateway does not send HBs to client
        )
        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
            bc = _BalfClient(cli)
            _do_auth(bc, pull, pub)

            # Wait beyond the heartbeat timeout
            assert bc.is_closed(
                timeout=2.0
            ), "gateway must close idle authenticated session after heartbeat_timeout_sec"


# ===========================================================================
# Connection limit — medium priority
# ===========================================================================


class TestConnectionLimit:
    """max_connections is enforced; connections beyond the limit are immediately closed."""

    def test_extra_connection_is_closed_when_at_limit(
        self, balf_gw_factory: FactoryFn
    ) -> None:
        _, _, _, port = balf_gw_factory(max_connections=1)

        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli1:
            bc1 = _BalfClient(cli1)
            # cli1 holds the only slot — don't need to authenticate
            time.sleep(0.05)  # gateway loop registers cli1

            with socket.create_connection(("127.0.0.1", port), timeout=3) as cli2:
                bc2 = _BalfClient(cli2)
                # cli2 should be immediately rejected
                assert bc2.is_closed(
                    timeout=2.0
                ), "gateway must close connections beyond max_connections"
                # cli1 must still be alive
                assert not bc1.is_closed(timeout=0.2)

    def test_freed_slot_allows_new_connection(self, balf_gw_factory: FactoryFn) -> None:
        _, _, _, port = balf_gw_factory(max_connections=1)

        cli1 = socket.create_connection(("127.0.0.1", port), timeout=3)
        time.sleep(0.05)
        cli1.close()  # release the slot
        time.sleep(0.05)  # gateway loop detects disconnect

        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli2:
            bc2 = _BalfClient(cli2)
            assert not bc2.is_closed(
                timeout=0.3
            ), "freed slot must allow a new connection"


# ===========================================================================
# Duplicate session EVICT_OLD — medium priority
# ===========================================================================


class TestDuplicateSessionEvictOld:
    """EVICT_OLD policy: a new LOGON for an active gateway_id evicts the old session."""

    def test_evict_old_closes_first_session(self, balf_gw_factory: FactoryFn) -> None:
        _, pull, pub, port = balf_gw_factory(duplicate_session_policy="EVICT_OLD")

        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli1:
            bc1 = _BalfClient(cli1)
            _do_auth(bc1, pull, pub, gateway_id="TRADER01")

            with socket.create_connection(("127.0.0.1", port), timeout=3) as cli2:
                bc2 = _BalfClient(cli2)
                # New LOGON for the same gateway_id triggers eviction of cli1
                cli2.sendall(_build_logon("TRADER01"))
                _drain_until(pull, "system.gateway_connect")
                time.sleep(0.1)
                _publish_auth(pub, gateway_id="TRADER01", accepted=True)

                # cli1 must be closed (evicted)
                assert bc1.is_closed(
                    timeout=2.0
                ), "old session must be evicted on EVICT_OLD policy"

                # cli2 must be authenticated
                body = bc2.recv_until(MSG_LOGON_ACK, timeout=3.0)
                assert body[16] == 1, "new session must be accepted"
