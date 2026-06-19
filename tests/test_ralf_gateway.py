from __future__ import annotations

import socket
import threading
import time
from collections.abc import Generator

import pytest
import zmq

from edumatcher.models.message import dumps
from edumatcher.ralf_gateway.config import RalfGatewayConfig
from edumatcher.ralf_gateway.gateway import RalfGateway
from edumatcher.ralf_gateway.protocol import parse_line


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _recv_line(sock: socket.socket, timeout: float = 2.0) -> str:
    sock.settimeout(timeout)
    data = bytearray()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("socket closed")
        data.extend(chunk)
        if b"\n" in data:
            line, _, _ = bytes(data).partition(b"\n")
            return line.decode("utf-8", errors="replace")


@pytest.fixture()
def running_gateway() -> (
    Generator[tuple[RalfGateway, zmq.Socket[bytes], int], None, None]
):
    engine_port = _free_port()
    gateway_port = _free_port()

    engine_addr = f"tcp://127.0.0.1:{engine_port}"
    cfg = RalfGatewayConfig(
        name="ralf-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        engine_pub_addr=engine_addr,
        replay_retention_sec=60,
        heartbeat_interval_sec=60,
        idle_timeout_sec=30,
        max_client_queue=1000,
    )

    gw = RalfGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()

    # Give gateway and ZMQ subscriber time to initialize.
    time.sleep(0.15)

    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.bind(engine_addr)
    time.sleep(0.15)  # PUB/SUB subscription handshake window

    try:
        yield gw, pub, gateway_port
    finally:
        gw.stop()
        t.join(timeout=2)
        pub.close()


def test_hello_and_subscribe_flow(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
) -> None:
    _, _, gateway_port = running_gateway

    with socket.create_connection(("127.0.0.1", gateway_port), timeout=2) as cli:
        cli.sendall(b"HELLO|CLIENT=test01|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=0\n")
        welcome = parse_line(_recv_line(cli))
        assert welcome.msg_type == "WELCOME"
        assert welcome.fields["PROTO"] == "RALF1"

        cli.sendall(b"SUB|CH=CLEARING|SYM=AAPL\n")
        snap = parse_line(_recv_line(cli))
        assert snap.msg_type == "SNAP"


def test_trade_event_emits_exec(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
) -> None:
    _, pub, gateway_port = running_gateway

    with socket.create_connection(("127.0.0.1", gateway_port), timeout=2) as cli:
        cli.sendall(b"HELLO|CLIENT=test02|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=0\n")
        _ = _recv_line(cli)  # WELCOME
        cli.sendall(b"SUB|CH=CLEARING|SYM=AAPL\n")
        _ = _recv_line(cli)  # SNAP

        pub.send_multipart(
            [
                b"trade.executed",
                dumps(
                    {
                        "id": "T1",
                        "symbol": "AAPL",
                        "buy_order_id": "B1",
                        "sell_order_id": "S1",
                        "buy_gateway_id": "GW1",
                        "sell_gateway_id": "GW2",
                        "price": 150.25,
                        "quantity": 100,
                        "aggressor_side": "BUY",
                        "timestamp": time.time(),
                    }
                ),
            ]
        )

        # Receive until EXEC (ignore any extra lines if present).
        deadline = time.time() + 2.0
        got_exec = False
        while time.time() < deadline:
            frame = parse_line(_recv_line(cli, timeout=2.0))
            if frame.msg_type == "EXEC":
                assert frame.fields["CH"] == "CLEARING"
                assert frame.fields["SYM"] == "AAPL"
                assert frame.fields["EXEC_ID"] == "T1"
                got_exec = True
                break
        assert got_exec


def test_replay_from_lastseq(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
) -> None:
    _, pub, gateway_port = running_gateway
    with socket.create_connection(("127.0.0.1", gateway_port), timeout=2) as cli1:
        cli1.sendall(b"HELLO|CLIENT=test03a|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=0\n")
        _ = _recv_line(cli1)  # WELCOME
        cli1.sendall(b"SUB|CH=CLEARING|SYM=AAPL\n")
        _ = _recv_line(cli1)  # SNAP

        pub.send_multipart(
            [
                b"trade.executed",
                dumps(
                    {
                        "id": "R1",
                        "symbol": "AAPL",
                        "buy_order_id": "B1",
                        "sell_order_id": "S1",
                        "buy_gateway_id": "GW1",
                        "sell_gateway_id": "GW2",
                        "price": 150.25,
                        "quantity": 100,
                        "aggressor_side": "BUY",
                        "timestamp": time.time(),
                    }
                ),
            ]
        )
        live = parse_line(_recv_line(cli1))
        assert live.msg_type == "EXEC"
        last_seq = int(live.fields["SEQ"])

    pub.send_multipart(
        [
            b"trade.executed",
            dumps(
                {
                    "id": "R2",
                    "symbol": "AAPL",
                    "buy_order_id": "B2",
                    "sell_order_id": "S2",
                    "buy_gateway_id": "GW1",
                    "sell_gateway_id": "GW2",
                    "price": 150.50,
                    "quantity": 50,
                    "aggressor_side": "SELL",
                    "timestamp": time.time(),
                }
            ),
        ]
    )
    time.sleep(0.1)

    with socket.create_connection(("127.0.0.1", gateway_port), timeout=2) as cli2:
        cli2.sendall(
            f"HELLO|CLIENT=test03b|PROTO=RALF1|ROLE=CLEARING|LASTSEQ={last_seq}\n".encode(
                "utf-8"
            )
        )
        cli2.settimeout(2)
        time.sleep(0.1)
        payload = cli2.recv(8192).decode("utf-8", errors="replace")
        lines = [ln for ln in payload.splitlines() if ln.strip()]
        frames = [parse_line(ln) for ln in lines]

        assert any(f.msg_type == "WELCOME" for f in frames)
        replay_frames = [f for f in frames if f.msg_type == "EXEC"]
        assert replay_frames
        assert int(replay_frames[0].fields["SEQ"]) > last_seq


def test_reject_non_allowed_role(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
) -> None:
    gw, _, gateway_port = running_gateway
    gw.config = RalfGatewayConfig(
        name=gw.config.name,
        bind_address=gw.config.bind_address,
        port=gw.config.port,
        engine_pub_addr=gw.config.engine_pub_addr,
        replay_retention_sec=gw.config.replay_retention_sec,
        heartbeat_interval_sec=gw.config.heartbeat_interval_sec,
        idle_timeout_sec=gw.config.idle_timeout_sec,
        max_client_queue=gw.config.max_client_queue,
        allowed_roles=("CLEARING",),
    )

    with socket.create_connection(("127.0.0.1", gateway_port), timeout=2) as cli:
        cli.sendall(b"HELLO|CLIENT=test04|PROTO=RALF1|ROLE=AUDIT|LASTSEQ=0\n")
        err = parse_line(_recv_line(cli))
        assert err.msg_type == "ERR"
        assert err.fields["CODE"] == "ENTITLEMENT_DENIED"
