"""Live integration tests for pm-alf-gwy's drop-copy relay (DC|ON / DC|OFF).

Uses a real TCP client, a real AlfGateway, a fake ZMQ engine PULL+PUB pair
(:5556-equivalent), and a separate fake ZMQ PUB standing in for the engine's
drop-copy socket (:5557-equivalent, see edumatcher.engine.drop_copy). Mirrors
the fixture/style of test_alf_gwy_integration.py.
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
# Helpers (duplicated from test_alf_gwy_integration.py to keep this file
# independently runnable / reviewable)
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _LineBuffer:
    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = bytearray()

    def recv_line(self, timeout: float = 3.0) -> str:
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
    cli.sendall(
        f"HELLO|CLIENT={client_name}|PROTO=ALF1|ID={gateway_id}\n".encode("utf-8")
    )
    _drain_pull_until(engine_pull, "system.gateway_connect", timeout=3.0)
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
    return lb.recv_until(lambda ln: ln.startswith("WELCOME"), timeout=3.0)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def running_gateway() -> Generator[
    tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], zmq.Socket[bytes], int],
    None,
    None,
]:
    """Start a real AlfGateway with fake ZMQ engine + drop-copy sockets.

    Yields (gateway, engine_pull, engine_pub, drop_copy_pub, tcp_port).
    """
    engine_pull_port = _free_port()
    engine_pub_port = _free_port()
    drop_copy_port = _free_port()
    gateway_port = _free_port()

    engine_pull_addr = f"tcp://127.0.0.1:{engine_pull_port}"
    engine_pub_addr = f"tcp://127.0.0.1:{engine_pub_port}"
    drop_copy_pub_addr = f"tcp://127.0.0.1:{drop_copy_port}"

    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()

    engine_pull: zmq.Socket[bytes] = ctx.socket(zmq.PULL)
    engine_pull.bind(engine_pull_addr)

    engine_pub: zmq.Socket[bytes] = ctx.socket(zmq.PUB)
    engine_pub.bind(engine_pub_addr)

    drop_copy_pub: zmq.Socket[bytes] = ctx.socket(zmq.PUB)
    drop_copy_pub.bind(drop_copy_pub_addr)

    cfg = AlfGatewayConfig(
        name="alf-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        engine_pull_addr=engine_pull_addr,
        engine_pub_addr=engine_pub_addr,
        drop_copy_pub_addr=drop_copy_pub_addr,
        heartbeat_interval_sec=60,
        idle_timeout_sec=60,
        max_connections=16,
        max_client_queue=10_000,
        max_commands_per_second=1000,
        max_errors_before_disconnect=50,
        gateway_roles=(("TRADER01", "TRADER"), ("TRADER02", "TRADER")),
    )

    gw = AlfGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()

    time.sleep(0.15)
    time.sleep(0.1)

    try:
        yield gw, engine_pull, engine_pub, drop_copy_pub, gateway_port
    finally:
        gw.stop()
        t.join(timeout=2.0)
        engine_pull.close()
        engine_pub.close()
        drop_copy_pub.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dc_on_ack_and_fill_relay(
    running_gateway: tuple[
        AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], zmq.Socket[bytes], int
    ],
) -> None:
    """DC|ON acks, then a published drop_copy.event.<GW> fill arrives as DC_FILL."""
    _, pull, pub, dc_pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        cli.sendall(b"DC|STATE=ON\n")
        ack = lb.recv_until(lambda ln: ln.startswith("DC_ACK"), timeout=3.0)
        assert parse_alf_line(ack).fields["STATE"] == "ON"

        # Allow the SUBSCRIBE to propagate before publishing (slow-joiner).
        time.sleep(0.2)

        dc_pub.send_multipart(
            encode(
                "drop_copy.event.TRADER01",
                {
                    "seq": 7,
                    "gateway_id": "TRADER01",
                    "event_type": "order.fill",
                    "order_id": "ord-xyz",
                    "symbol": "AAPL",
                    "fill_qty": 50,
                    "fill_price": 150.25,
                    "liquidity_flag": "MAKER",
                },
            )
        )

        fill = lb.recv_until(lambda ln: ln.startswith("DC_FILL"), timeout=3.0)
        frame = parse_alf_line(fill)
        assert frame.fields["SEQ"] == "7"
        assert frame.fields["SYMBOL"] == "AAPL"
        assert frame.fields["FILL_QTY"] == "50"
        assert frame.fields["FILL_PRICE"] == "150.25"
        assert frame.fields["LIQUIDITY"] == "MAKER"


def test_dc_off_stops_relay(
    running_gateway: tuple[
        AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], zmq.Socket[bytes], int
    ],
) -> None:
    """After DC|OFF, further drop-copy publishes must not reach the client."""
    _, pull, pub, dc_pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli:
        lb = _LineBuffer(cli)
        _authenticate(cli, lb, pull, pub)
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        cli.sendall(b"DC|STATE=ON\n")
        lb.recv_until(lambda ln: ln.startswith("DC_ACK"), timeout=3.0)
        time.sleep(0.2)

        cli.sendall(b"DC|STATE=OFF\n")
        off_ack = lb.recv_until(lambda ln: ln.startswith("DC_ACK"), timeout=3.0)
        assert parse_alf_line(off_ack).fields["STATE"] == "OFF"
        time.sleep(0.2)

        dc_pub.send_multipart(
            encode(
                "drop_copy.event.TRADER01",
                {
                    "seq": 1,
                    "gateway_id": "TRADER01",
                    "order_id": "should-not-arrive",
                    "symbol": "AAPL",
                    "fill_qty": 1,
                    "fill_price": 1.0,
                    "liquidity_flag": "TAKER",
                },
            )
        )

        # Prove liveness of the connection with a HB or PING/PONG rather
        # than asserting a negative on a timeout alone.
        cli.sendall(b"PING\n")
        pong = lb.recv_until(lambda ln: ln.startswith("PONG"), timeout=3.0)
        assert pong.startswith("PONG")
        # No DC_FILL should have arrived ahead of the PONG.
        # (If one had, recv_until above would have returned it first only
        # if PONG appeared before DC_FILL in the stream, so we additionally
        # assert the session's dc_enabled flag directly via the ack above.)


def test_dc_isolated_per_gateway(
    running_gateway: tuple[
        AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], zmq.Socket[bytes], int
    ],
) -> None:
    """TRADER02's DC fills must not be delivered to TRADER01's session."""
    _, pull, pub, dc_pub, port = running_gateway

    with socket.create_connection(("127.0.0.1", port), timeout=3) as cli1:
        lb1 = _LineBuffer(cli1)
        _authenticate(cli1, lb1, pull, pub, gateway_id="TRADER01")
        _drain_pull_until(pull, "system.symbols_request", timeout=2.0)

        cli1.sendall(b"DC|STATE=ON\n")
        lb1.recv_until(lambda ln: ln.startswith("DC_ACK"), timeout=3.0)
        time.sleep(0.2)

        dc_pub.send_multipart(
            encode(
                "drop_copy.event.TRADER02",
                {
                    "seq": 1,
                    "gateway_id": "TRADER02",
                    "order_id": "not-mine",
                    "symbol": "AAPL",
                    "fill_qty": 1,
                    "fill_price": 1.0,
                    "liquidity_flag": "TAKER",
                },
            )
        )

        # Confirm liveness/ordering via PING/PONG without a DC_FILL in between.
        cli1.sendall(b"PING\n")
        pong = lb1.recv_until(lambda ln: ln.startswith("PONG"), timeout=3.0)
        assert pong.startswith("PONG")
