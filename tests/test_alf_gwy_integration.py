"""Live integration tests for pm-alf-gwy.

Uses real TCP client sockets and a fake ZMQ engine (PULL + PUB) to exercise
the full round-trip path: framing, authentication, command forwarding, event
delivery, heartbeats, idle-timeout, and disconnect behaviour.

Test structure mirrors test_ralf_gateway.py and test_md_gateway_runtime_paths.py.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Generator

import pytest
import zmq

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway
from edumatcher.alf_gwy.protocol import parse_alf_line
from edumatcher.models.message import encode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _LineBuffer:
    """Buffered TCP line reader — never assumes one recv() == one line."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = bytearray()

    def recv_line(self, timeout: float = 3.0) -> str:
        """Block until one '\\n'-terminated line is available."""
        deadline = time.monotonic() + timeout
        while True:
            nl = self._buf.find(b"\n")
            if nl >= 0:
                line = bytes(self._buf[:nl]).decode("utf-8", errors="replace")
                del self._buf[: nl + 1]
                return line
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no complete line received within timeout")
            self._sock.settimeout(remaining)
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RuntimeError("connection closed by gateway")
            self._buf.extend(chunk)

    def recv_until(
        self,
        match_fn: Callable[[str], bool],
        timeout: float = 3.0,
        max_lines: int = 30,
    ) -> str:
        """Read lines until match_fn(line) is True; return the matching line."""
        for _ in range(max_lines):
            line = self.recv_line(timeout=timeout)
            if match_fn(line):
                return line
        raise TimeoutError(f"match never found within {max_lines} lines")


def _drain_pull_until(
    pull: zmq.Socket[bytes],
    topic_prefix: str,
    timeout: float = 3.0,
) -> tuple[str, dict[str, object]]:
    """Drain the engine PULL socket until a message with topic_prefix arrives."""
    from edumatcher.models.message import decode

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ms_remaining = max(1, int((deadline - time.monotonic()) * 1000))
        if not pull.poll(timeout=ms_remaining):
            continue
        frames = pull.recv_multipart()
        topic, payload = decode(frames)
        if topic.startswith(topic_prefix):
            return topic, payload
    raise TimeoutError(f"never received topic '{topic_prefix}' within {timeout}s")


def _authenticate(
    cli: socket.socket,
    lb: _LineBuffer,
    engine_pull: zmq.Socket[bytes],
    engine_pub: zmq.Socket[bytes],
    gateway_id: str = "TRADER01",
    client_name: str = "test-client",
) -> str:
    """Complete the HELLO → engine_auth → WELCOME handshake.

    Returns the raw WELCOME line.
    """
    cli.sendall(
        f"HELLO|CLIENT={client_name}|PROTO=ALF1|ID={gateway_id}\n".encode("utf-8")
    )

    # Wait for system.gateway_connect to arrive — this confirms the gateway
    # has processed the HELLO and subscribed to system.gateway_auth.<gw_id>.
    _drain_pull_until(engine_pull, "system.gateway_connect", timeout=3.0)

    # Allow ZMQ subscription to propagate before publishing the reply.
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

    # Skip any SYMBOLS response lines and return the WELCOME line.
    return lb.recv_until(lambda ln: ln.startswith("WELCOME"), timeout=3.0)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def running_gateway() -> Generator[
    tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
    None,
    None,
]:
    """Start a real AlfGateway backed by fake ZMQ engine sockets.

    Yields (gateway, engine_pull, engine_pub, tcp_port).
    engine_pull receives everything the gateway pushes to the engine.
    engine_pub can inject events that the gateway will route to clients.
    """
    engine_pull_port = _free_port()
    engine_pub_port = _free_port()
    gateway_port = _free_port()

    engine_pull_addr = f"tcp://127.0.0.1:{engine_pull_port}"
    engine_pub_addr = f"tcp://127.0.0.1:{engine_pub_port}"

    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()

    # Bind fake engine sockets BEFORE the gateway creates its ZMQ connections.
    engine_pull: zmq.Socket[bytes] = ctx.socket(zmq.PULL)
    engine_pull.bind(engine_pull_addr)

    engine_pub: zmq.Socket[bytes] = ctx.socket(zmq.PUB)
    engine_pub.bind(engine_pub_addr)

    cfg = AlfGatewayConfig(
        name="alf-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        engine_pull_addr=engine_pull_addr,
        engine_pub_addr=engine_pub_addr,
        heartbeat_interval_sec=60,  # disabled by default — individual tests override
        idle_timeout_sec=60,  # disabled by default
        max_connections=16,
        max_client_queue=10_000,
        max_commands_per_second=1000,
        max_errors_before_disconnect=50,
        gateway_roles=(("TRADER01", "TRADER"), ("MM01", "MARKET_MAKER")),
    )

    gw = AlfGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()

    # Allow gateway to bind TCP listener and ZMQ sockets to settle.
    time.sleep(0.15)

    # PUB/SUB subscription handshake window for the global subscriptions
    # (session.state, trade.executed, circuit_breaker.*).
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


def test_hello_and_welcome(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """HELLO → engine auth → WELCOME round-trip."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        welcome = _authenticate(cli, lb, pull, pub)

        msg = parse_alf_line(welcome)
        assert msg.command == "WELCOME"
        assert msg.fields["PROTO"] == "ALF1"
        assert msg.fields["ID"] == "TRADER01"
        assert "HBINT" in msg.fields
        assert "IDLE" in msg.fields


def test_welcome_followed_by_symbols_response(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """After WELCOME the gateway auto-requests symbols from the engine.
    Injecting a symbols response should produce SYMBOLS / SYMBOL / END lines."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)

        # Drain the auto-issued symbols_request
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)
        time.sleep(0.1)

        # Inject a symbols response
        pub.send_multipart(
            encode(
                "system.symbols.TRADER01",
                {"symbols": ["AAPL", "MSFT"]},
            )
        )

        header = lb.recv_until(lambda ln: ln.startswith("SYMBOLS"), timeout=3.0)
        assert parse_alf_line(header).fields["COUNT"] == "2"

        rows = [lb.recv_line(timeout=2.0) for _ in range(2)]
        assert all(r.startswith("SYMBOL") for r in rows)

        end = lb.recv_line(timeout=2.0)
        assert parse_alf_line(end).fields["TYPE"] == "SYMBOLS"


def test_hello_bad_proto_rejected(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """HELLO with wrong PROTO should produce ERR|CODE=PROTO_MISMATCH and close."""
    _, _, _, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        cli.sendall(b"HELLO|CLIENT=bot|PROTO=RALF1|ID=TRADER01\n")

        err_line = lb.recv_until(lambda ln: ln.startswith("ERR"), timeout=3.0)
        msg = parse_alf_line(err_line)
        assert msg.fields["CODE"] == "PROTO_MISMATCH"

        # Connection should close
        cli.settimeout(2.0)
        assert cli.recv(64) == b""


def test_auth_failure_closes_connection(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """Engine returning accepted=false must produce ERR|CODE=AUTH_FAILED and close."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        cli.sendall(b"HELLO|CLIENT=bot|PROTO=ALF1|ID=TRADER01\n")

        _drain_pull_until(pull, "system.gateway_connect", timeout=3.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "system.gateway_auth.TRADER01",
                {
                    "gateway_id": "TRADER01",
                    "accepted": False,
                    "reason": "Gateway not allowed",
                },
            )
        )

        err_line = lb.recv_until(lambda ln: ln.startswith("ERR"), timeout=3.0)
        msg = parse_alf_line(err_line)
        assert msg.fields["CODE"] == "AUTH_FAILED"

        cli.settimeout(2.0)
        assert cli.recv(64) == b""


def test_duplicate_gateway_id_rejected(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """A second connection using the same gateway ID is rejected."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli1:
        lb1 = _LineBuffer(cli1)
        _authenticate(cli1, lb1, pull, pub, gateway_id="TRADER01")

        with socket.create_connection(("127.0.0.1", port), timeout=3) as cli2:
            lb2 = _LineBuffer(cli2)
            cli2.sendall(b"HELLO|CLIENT=bot2|PROTO=ALF1|ID=TRADER01\n")

            err_line = lb2.recv_until(lambda ln: ln.startswith("ERR"), timeout=3.0)
            msg = parse_alf_line(err_line)
            assert msg.fields["CODE"] == "GATEWAY_ALREADY_CONNECTED"

            cli2.settimeout(2.0)
            assert cli2.recv(64) == b""


def test_command_before_hello_rejected(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """Any command sent before HELLO must receive ERR|CODE=AUTH_REQUIRED and close."""
    _, _, _, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        cli.sendall(b"SYMBOLS\n")

        err_line = lb.recv_until(lambda ln: ln.startswith("ERR"), timeout=3.0)
        assert parse_alf_line(err_line).fields["CODE"] == "AUTH_REQUIRED"

        cli.settimeout(2.0)
        assert cli.recv(64) == b""


# ---------------------------------------------------------------------------
# Ping / Exit
# ---------------------------------------------------------------------------


def test_ping_pong(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """PING must produce PONG."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)
        cli.sendall(b"PING\n")
        pong = lb.recv_until(lambda ln: ln.startswith("PONG"), timeout=3.0)
        assert parse_alf_line(pong).command == "PONG"


def test_exit_sends_gateway_disconnect_to_engine(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """EXIT must forward system.gateway_disconnect to the engine PULL socket."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)

        cli.sendall(b"EXIT\n")

        topic, payload = _drain_pull_until(
            pull, "system.gateway_disconnect", timeout=3.0
        )
        assert topic == "system.gateway_disconnect"
        assert str(payload.get("gateway_id", "")).upper() == "TRADER01"

        # TCP connection should close after EXIT is processed
        cli.settimeout(2.0)
        assert cli.recv(64) == b""


# ---------------------------------------------------------------------------
# Command forwarding
# ---------------------------------------------------------------------------


def test_symbols_command_forwarded_to_engine(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """SYMBOLS command must forward system.symbols_request to engine PULL."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)

        # Drain the auto-issued symbols_request from post-auth
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        # Now send an explicit SYMBOLS command
        cli.sendall(b"SYMBOLS\n")
        topic, payload = _drain_pull_until(pull, "system.symbols_request", timeout=3.0)
        assert topic == "system.symbols_request"
        assert str(payload.get("gateway_id", "")).upper() == "TRADER01"


def test_kill_command_forwarded_to_engine(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """KILL must forward risk.kill_switch to engine PULL with correct gateway_id."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)

        # Drain the auto symbols_request
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        cli.sendall(b"KILL\n")
        topic, payload = _drain_pull_until(pull, "risk.kill_switch", timeout=3.0)
        assert topic == "risk.kill_switch"
        assert str(payload.get("gateway_id", "")).upper() == "TRADER01"


def test_new_order_forwarded_to_engine(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """NEW limit order must reach the engine as order.new with correct fields."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "system.symbols.TRADER01",
                {"symbols": ["AAPL"]},
            )
        )
        lb.recv_until(lambda ln: ln.startswith("SYMBOLS"), timeout=3.0)

        cli.sendall(b"NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00\n")
        topic, payload = _drain_pull_until(pull, "order.new", timeout=3.0)
        assert topic == "order.new"
        assert str(payload.get("symbol", "")).upper() == "AAPL"
        assert str(payload.get("side", "")).upper() == "BUY"
        assert str(payload.get("gateway_id", "")).upper() == "TRADER01"


# ---------------------------------------------------------------------------
# Event delivery
# ---------------------------------------------------------------------------


def test_ack_event_delivered_to_client(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """order.ack engine event must be translated to ACK on the client TCP stream."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.ack.TRADER01",
                {
                    "order_id": "order-abc-123",
                    "accepted": True,
                    "reason": "",
                    "symbol": "AAPL",
                    "side": "BUY",
                    "order_type": "LIMIT",
                },
            )
        )

        ack = lb.recv_until(lambda ln: ln.startswith("ACK"), timeout=3.0)
        msg = parse_alf_line(ack)
        assert msg.fields["ORDER_ID"] == "ORDER-ABC-123"
        assert msg.fields["ACCEPTED"] == "TRUE"


def test_fill_event_delivered_to_client(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """order.fill engine event must be translated to FILL on the client TCP stream."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.fill.TRADER01",
                {
                    "order_id": "fill-id-999",
                    "fill_qty": 50,
                    "fill_price": 150.25,
                    "remaining_qty": 50,
                    "status": "PARTIAL",
                },
            )
        )

        fill = lb.recv_until(lambda ln: ln.startswith("FILL"), timeout=3.0)
        msg = parse_alf_line(fill)
        assert msg.fields["ORDER_ID"] == "FILL-ID-999"
        assert msg.fields["FILL_QTY"] == "50"
        assert msg.fields["STATUS"] == "PARTIAL"


def test_session_state_broadcast_delivered(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """session.state engine broadcast must reach every authenticated client."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "session.state",
                {"state": "CONTINUOUS", "prev_state": "OPENING_AUCTION"},
            )
        )

        sess = lb.recv_until(lambda ln: ln.startswith("SESSION"), timeout=3.0)
        msg = parse_alf_line(sess)
        assert msg.fields["STATE"] == "CONTINUOUS"
        assert msg.fields["PREV_STATE"] == "OPENING_AUCTION"


def test_circuit_breaker_halt_broadcast(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """circuit_breaker.halt.* broadcast must produce HALT on the client stream."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "circuit_breaker.halt.AAPL",
                {"symbol": "AAPL", "level": "L1"},
            )
        )

        halt = lb.recv_until(lambda ln: ln.startswith("HALT"), timeout=3.0)
        msg = parse_alf_line(halt)
        assert msg.fields["SYMBOL"] == "AAPL"
        assert msg.fields["LEVEL"] == "L1"


# ---------------------------------------------------------------------------
# Multi-line responses
# ---------------------------------------------------------------------------


def test_orders_multi_line_response(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """order.orders engine reply must produce ORDERS / ORDER* / END framing."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        cli.sendall(b"ORDERS\n")
        _drain_pull_until(pull, "order.orders_request", timeout=3.0)
        time.sleep(0.1)

        pub.send_multipart(
            encode(
                "order.orders.TRADER01",
                {
                    "orders": [
                        {
                            "id": "ORD-1",
                            "symbol": "AAPL",
                            "side": "BUY",
                            "order_type": "LIMIT",
                            "quantity": 100,
                            "remaining_qty": 100,
                            "price": 150.0,
                            "status": "NEW",
                        }
                    ]
                },
            )
        )

        header = lb.recv_until(lambda ln: ln.startswith("ORDERS"), timeout=3.0)
        assert parse_alf_line(header).fields["COUNT"] == "1"

        row = lb.recv_line(timeout=2.0)
        assert row.startswith("ORDER")
        row_msg = parse_alf_line(row)
        assert row_msg.fields["ID"] == "ORD-1"
        assert row_msg.fields["SYM"] == "AAPL"

        end = lb.recv_line(timeout=2.0)
        assert parse_alf_line(end).fields["TYPE"] == "ORDERS"


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def test_heartbeat_sent_when_no_outbound_traffic(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """With a 1-second heartbeat interval the client should receive HB promptly."""
    gw, pull, pub, port = running_gateway

    # Override heartbeat interval on the running gateway (config is frozen, patch object)
    gw.config = AlfGatewayConfig(
        name=gw.config.name,
        bind_address=gw.config.bind_address,
        port=gw.config.port,
        engine_pull_addr=gw.config.engine_pull_addr,
        engine_pub_addr=gw.config.engine_pub_addr,
        heartbeat_interval_sec=1,
        idle_timeout_sec=60,
        max_connections=gw.config.max_connections,
        max_client_queue=gw.config.max_client_queue,
        max_commands_per_second=gw.config.max_commands_per_second,
        max_errors_before_disconnect=gw.config.max_errors_before_disconnect,
        error_window_sec=gw.config.error_window_sec,
        gateway_roles=gw.config.gateway_roles,
    )

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)

        # Drain any SYMBOLS lines from post-auth
        try:
            while True:
                line = lb.recv_line(timeout=0.3)
                if not (line.startswith("SYMBOL") or line.startswith("END")):
                    break
        except TimeoutError:
            pass

        # Wait up to 3 seconds for a heartbeat
        hb = lb.recv_until(lambda ln: ln.startswith("HB"), timeout=3.0)
        assert parse_alf_line(hb).command == "HB"
        assert "TS" in parse_alf_line(hb).fields


# ---------------------------------------------------------------------------
# Idle timeout
# ---------------------------------------------------------------------------


def test_idle_timeout_disconnects_client(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """Client that sends no traffic for idle_timeout_sec must receive ERR|IDLE_TIMEOUT
    and be disconnected."""
    gw, pull, pub, port = running_gateway

    gw.config = AlfGatewayConfig(
        name=gw.config.name,
        bind_address=gw.config.bind_address,
        port=gw.config.port,
        engine_pull_addr=gw.config.engine_pull_addr,
        engine_pub_addr=gw.config.engine_pub_addr,
        heartbeat_interval_sec=60,
        idle_timeout_sec=1,
        max_connections=gw.config.max_connections,
        max_client_queue=gw.config.max_client_queue,
        max_commands_per_second=gw.config.max_commands_per_second,
        max_errors_before_disconnect=gw.config.max_errors_before_disconnect,
        error_window_sec=gw.config.error_window_sec,
        gateway_roles=gw.config.gateway_roles,
    )

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)

        # Wait for idle timeout error
        err = lb.recv_until(lambda ln: ln.startswith("ERR"), timeout=4.0)
        assert parse_alf_line(err).fields["CODE"] == "IDLE_TIMEOUT"

        # Connection should be closed
        cli.settimeout(2.0)
        assert cli.recv(64) == b""


# ---------------------------------------------------------------------------
# Input safety
# ---------------------------------------------------------------------------


def test_oversized_line_produces_error_connection_kept(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """A line exceeding 4096 bytes without a newline must produce ERR|BAD_MESSAGE
    but the connection must remain open."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)

        cli.sendall(b"X" * 5000)  # no newline — fills the buffer beyond the limit
        time.sleep(0.2)  # give the gateway a tick to detect it

        err = lb.recv_until(lambda ln: ln.startswith("ERR"), timeout=3.0)
        assert parse_alf_line(err).fields["CODE"] == "BAD_MESSAGE"

        # Connection must still be alive
        cli.sendall(b"PING\n")
        pong = lb.recv_until(lambda ln: ln.startswith("PONG"), timeout=2.0)
        assert pong.startswith("PONG")


def test_binary_garbage_does_not_crash(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """Invalid UTF-8 followed by a newline must produce BAD_MESSAGE, not a crash."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)

        # NUL bytes + garbage + newline
        cli.sendall(b"\x00\xff\xfe garbage !!!\n")
        err = lb.recv_until(lambda ln: ln.startswith("ERR"), timeout=3.0)
        assert parse_alf_line(err).fields["CODE"] == "BAD_MESSAGE"

        # Gateway must still respond normally
        cli.sendall(b"PING\n")
        lb.recv_until(lambda ln: ln.startswith("PONG"), timeout=2.0)


def test_empty_line_produces_bad_message_not_crash(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """A bare newline must produce ERR|BAD_MESSAGE, not crash or disconnect."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)

        cli.sendall(b"\n")
        err = lb.recv_until(lambda ln: ln.startswith("ERR"), timeout=3.0)
        assert parse_alf_line(err).fields["CODE"] == "BAD_MESSAGE"

        # Still alive
        cli.sendall(b"PING\n")
        lb.recv_until(lambda ln: ln.startswith("PONG"), timeout=2.0)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_rate_limiting_enforced(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """max_commands_per_second=1 means the second rapid command gets RATE_LIMITED."""
    gw, pull, pub, port = running_gateway

    gw.config = AlfGatewayConfig(
        name=gw.config.name,
        bind_address=gw.config.bind_address,
        port=gw.config.port,
        engine_pull_addr=gw.config.engine_pull_addr,
        engine_pub_addr=gw.config.engine_pub_addr,
        heartbeat_interval_sec=60,
        idle_timeout_sec=60,
        max_connections=gw.config.max_connections,
        max_client_queue=gw.config.max_client_queue,
        max_commands_per_second=1,
        max_errors_before_disconnect=gw.config.max_errors_before_disconnect,
        error_window_sec=gw.config.error_window_sec,
        gateway_roles=gw.config.gateway_roles,
    )

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        # Fire two commands back-to-back faster than the 1/s refill rate.
        # SYMBOLS and ORDERS are both rate-limited commands; PING is not.
        # The first command consumes the one available token; the second
        # arrives before any refill and must get RATE_LIMITED.
        cli.sendall(b"SYMBOLS\nORDERS\n")

        err = lb.recv_until(lambda ln: "RATE_LIMITED" in ln, timeout=3.0)
        assert parse_alf_line(err).fields["CODE"] == "RATE_LIMITED"


def test_max_connections_enforced(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """When max_connections is reached new TCP connections are immediately closed."""
    gw, pull, pub, port = running_gateway

    # Lower the limit to 2 so the test runs quickly
    gw.config = AlfGatewayConfig(
        name=gw.config.name,
        bind_address=gw.config.bind_address,
        port=gw.config.port,
        engine_pull_addr=gw.config.engine_pull_addr,
        engine_pub_addr=gw.config.engine_pub_addr,
        heartbeat_interval_sec=60,
        idle_timeout_sec=60,
        max_connections=2,
        max_client_queue=gw.config.max_client_queue,
        max_commands_per_second=gw.config.max_commands_per_second,
        max_errors_before_disconnect=gw.config.max_errors_before_disconnect,
        error_window_sec=gw.config.error_window_sec,
        gateway_roles=gw.config.gateway_roles,
    )

    clients: list[socket.socket] = []
    try:
        # Fill up to the limit (no auth needed — connections count before HELLO)
        for _ in range(2):
            s = socket.create_connection(("127.0.0.1", port), timeout=2)
            clients.append(s)
        time.sleep(0.1)

        # One more must be closed immediately
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


# ---------------------------------------------------------------------------
# Disconnect behaviour
# ---------------------------------------------------------------------------


def test_peer_close_triggers_gateway_disconnect_to_engine(
    running_gateway: tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    """Abrupt TCP close by the client must still cause a gateway_disconnect message."""
    _, pull, pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

    # Connection is now closed; give the gateway a tick to detect EOF
    time.sleep(0.2)

    _, payload = _drain_pull_until(pull, "system.gateway_disconnect", timeout=3.0)
    assert str(payload.get("gateway_id", "")).upper() == "TRADER01"
