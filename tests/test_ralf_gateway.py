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

# Generous upper bounds for CI/parallel test runs under CPU contention. These
# are deadlines for polling loops, not blind sleeps, so fast machines finish
# almost immediately while slow/busy ones get much more headroom than the
# fixed 0.1-0.15s sleeps this file used to rely on.
_DEFAULT_TIMEOUT = 5.0
_POLL_INTERVAL = 0.02


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _recv_line(sock: socket.socket, timeout: float = _DEFAULT_TIMEOUT) -> str:
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


def _recv_all_lines(
    sock: socket.socket,
    quiet_period: float = 0.3,
    deadline: float = _DEFAULT_TIMEOUT,
) -> list[str]:
    """Accumulate every line the peer sends until it goes quiet or times out.

    A single `recv()` call is not guaranteed to return everything the server
    has queued (TCP may deliver it across several packets), so this keeps
    reading until no new data has arrived for `quiet_period` seconds (or the
    overall `deadline` elapses), instead of assuming one fixed-size read is
    enough.
    """
    sock.settimeout(quiet_period)
    buf = bytearray()
    end_time = time.monotonic() + deadline
    while time.monotonic() < end_time:
        try:
            chunk = sock.recv(65536)
        except TimeoutError:
            break
        if not chunk:
            break
        buf.extend(chunk)
    return [
        ln for ln in buf.decode("utf-8", errors="replace").splitlines() if ln.strip()
    ]


def _wait_for_listener(
    host: str, port: int, deadline: float = _DEFAULT_TIMEOUT
) -> None:
    """Poll until the gateway's TCP listener accepts connections.

    Replaces a blind post-thread-start sleep: on a fast/idle machine this
    returns almost instantly, on a slow/contended one it keeps retrying
    instead of racing a fixed guess.
    """
    last_exc: OSError | None = None
    end_time = time.monotonic() + deadline
    while time.monotonic() < end_time:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError as exc:
            last_exc = exc
            time.sleep(_POLL_INTERVAL)
    raise RuntimeError(
        f"RalfGateway never started listening on {host}:{port}"
    ) from last_exc


def _prime_subscriber(
    gw: RalfGateway, pub: zmq.Socket[bytes], deadline: float = _DEFAULT_TIMEOUT
) -> None:
    """Resolve the ZMQ PUB/SUB "slow joiner" race deterministically.

    A freshly-bound PUB socket will silently drop messages published before
    a SUB has finished connecting, so publishing a real test event right
    after `pub.bind()` is inherently racy. Since the gateway thread lives in
    this same process, we can detect the moment its subscriber has actually
    received something by watching `_next_seq` advance, instead of guessing
    a fixed sleep duration. The warmup event is sent before any test client
    subscribes, so it never reaches a real client and only pollutes the
    (unasserted) journal sequence numbers.
    """
    warmup_payload = dumps(
        {
            "id": "WARMUP",
            "symbol": "__WARMUP__",
            "buy_order_id": "W",
            "sell_order_id": "W",
            "buy_gateway_id": "W",
            "sell_gateway_id": "W",
            "price": 0.0,
            "quantity": 0,
            "aggressor_side": "BUY",
            "timestamp": time.time(),
        }
    )
    initial_next_seq = gw._next_seq
    end_time = time.monotonic() + deadline
    while gw._next_seq == initial_next_seq and time.monotonic() < end_time:
        pub.send_multipart([b"trade.executed", warmup_payload])
        time.sleep(_POLL_INTERVAL)
    if gw._next_seq == initial_next_seq:
        raise RuntimeError("ZMQ PUB/SUB handshake did not complete before the deadline")


def _wait_for_seq_advance(
    gw: RalfGateway, baseline_seq: int, deadline: float = _DEFAULT_TIMEOUT
) -> None:
    """Poll until the gateway has journaled at least one event past baseline."""
    end_time = time.monotonic() + deadline
    while gw._next_seq <= baseline_seq and time.monotonic() < end_time:
        time.sleep(_POLL_INTERVAL)


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

    # Wait for the gateway's TCP listener to actually be accepting
    # connections rather than assuming a fixed startup delay.
    _wait_for_listener(cfg.bind_address, gateway_port)

    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.bind(engine_addr)
    # Resolve the PUB/SUB slow-joiner race deterministically instead of a
    # fixed handshake-window sleep.
    _prime_subscriber(gw, pub)

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

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
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

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
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
        deadline = time.time() + _DEFAULT_TIMEOUT
        got_exec = False
        while time.time() < deadline:
            frame = parse_line(_recv_line(cli, timeout=_DEFAULT_TIMEOUT))
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
    gw, pub, gateway_port = running_gateway
    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli1:
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

    seq_before_r2 = gw._next_seq
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
    # Wait until R2 has actually been journaled instead of guessing a fixed
    # delay, so cli2's replay-from-lastseq below never races the engine
    # event loop.
    _wait_for_seq_advance(gw, seq_before_r2)

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli2:
        cli2.sendall(
            f"HELLO|CLIENT=test03b|PROTO=RALF1|ROLE=CLEARING|LASTSEQ={last_seq}\n".encode(
                "utf-8"
            )
        )
        frames = [parse_line(ln) for ln in _recv_all_lines(cli2)]

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

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test04|PROTO=RALF1|ROLE=AUDIT|LASTSEQ=0\n")
        err = parse_line(_recv_line(cli))
        assert err.msg_type == "ERR"
        assert err.fields["CODE"] == "ENTITLEMENT_DENIED"
