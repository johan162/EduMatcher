"""Integration tests for pm-dc-gwy: a real DcGateway TCP server relaying a
real DropCopyPublisher's ZMQ feed to plain-socket DC1 clients.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Generator

import pytest
import zmq

from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.dc_gateway.gateway import DcGateway
from edumatcher.dc_gateway.protocol import parse_line
from edumatcher.engine.drop_copy import DropCopyPublisher

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


def _wait_for_listener(
    host: str, port: int, deadline: float = _DEFAULT_TIMEOUT
) -> None:
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
        f"DcGateway never started listening on {host}:{port}"
    ) from last_exc


def _settle_subscription(delay: float = 0.2) -> None:
    """Give the gateway's internal ZMQ SUB socket time to finish its
    handshake with the DropCopyPublisher's PUB socket (classic PUB/SUB
    slow-joiner race) before publishing the event under test. The gateway
    subscribes to a client's gateway_id topic synchronously at HELLO time,
    but the underlying ZMQ SUBSCRIBE still needs a moment to propagate to
    the PUB side.
    """
    time.sleep(delay)


@pytest.fixture()
def running_gateway() -> (
    Generator[tuple[DcGateway, DropCopyPublisher, int], None, None]
):
    dc_pub_port = _free_port()
    gateway_port = _free_port()

    dc_pub_addr = f"tcp://127.0.0.1:{dc_pub_port}"
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    pub = DropCopyPublisher(ctx, addr=dc_pub_addr)

    cfg = DcGatewayConfig(
        name="dc-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        drop_copy_pub_addr=dc_pub_addr,
        heartbeat_interval_sec=60,
        idle_timeout_sec=30,
        max_client_queue=1000,
    )

    gw = DcGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()

    _wait_for_listener(cfg.bind_address, gateway_port)

    try:
        yield gw, pub, gateway_port
    finally:
        gw.stop()
        t.join(timeout=2)
        pub.close()


def test_hello_welcome_handshake(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, _, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test01|PROTO=DC1|ID=TRADER01\n")
        welcome = parse_line(_recv_line(cli))
        assert welcome.msg_type == "WELCOME"
        assert welcome.fields["PROTO"] == "DC1"
        assert welcome.fields["ID"] == "TRADER01"
        assert welcome.fields["GW"] == "dc-test"


def test_hello_missing_id_rejected() -> None:
    dc_pub_port = _free_port()
    gateway_port = _free_port()
    dc_pub_addr = f"tcp://127.0.0.1:{dc_pub_port}"
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    pub = DropCopyPublisher(ctx, addr=dc_pub_addr)
    cfg = DcGatewayConfig(
        name="dc-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        drop_copy_pub_addr=dc_pub_addr,
    )
    gw = DcGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()
    _wait_for_listener(cfg.bind_address, gateway_port)

    try:
        with socket.create_connection(
            ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
        ) as cli:
            cli.sendall(b"HELLO|CLIENT=test01|PROTO=DC1\n")
            err = parse_line(_recv_line(cli))
            assert err.msg_type == "ERR"
            assert err.fields["CODE"] == "AUTH_REQUIRED"
    finally:
        gw.stop()
        t.join(timeout=2)
        pub.close()


def test_fill_event_relayed_to_matching_gateway_id(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    gw, pub, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test02|PROTO=DC1|ID=TRADER01\n")
        _ = _recv_line(cli)  # WELCOME
        _settle_subscription()

        deadline = time.time() + _DEFAULT_TIMEOUT
        got_fill = False
        while time.time() < deadline and not got_fill:
            pub.publish(
                "TRADER01",
                "order.fill",
                {
                    "order_id": "ord-1",
                    "symbol": "AAPL",
                    "fill_qty": 100,
                    "fill_price": 150.25,
                    "liquidity_flag": "MAKER",
                },
            )
            try:
                cli.settimeout(0.3)
                frame = parse_line(_recv_line(cli, timeout=0.3))
            except (TimeoutError, RuntimeError):
                continue
            if frame.msg_type == "DC_FILL" and frame.fields.get("ORDER_ID") == "ord-1":
                assert frame.fields["SYMBOL"] == "AAPL"
                assert frame.fields["FILL_QTY"] == "100"
                assert frame.fields["FILL_PRICE"] == "150.25"
                assert frame.fields["LIQUIDITY"] == "MAKER"
                got_fill = True
        assert got_fill


def test_fill_event_not_relayed_to_other_gateway_id(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, pub, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test03|PROTO=DC1|ID=TRADER99\n")
        _ = _recv_line(cli)  # WELCOME
        _settle_subscription()

        # Publish for a different gateway a few times; TRADER99's client
        # should never see a DC_FILL, only its own periodic HB (heartbeat
        # is set to 60s here so none will arrive within the short window).
        for _ in range(5):
            pub.publish(
                "TRADER01",
                "order.fill",
                {"order_id": "ord-x", "symbol": "MSFT", "fill_qty": 10},
            )
            time.sleep(0.05)

        cli.settimeout(0.5)
        with pytest.raises((TimeoutError, socket.timeout)):
            cli.recv(4096)


def test_ping_pong(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, _, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test04|PROTO=DC1|ID=TRADER01\n")
        _ = _recv_line(cli)  # WELCOME
        cli.sendall(b"PING\n")
        frame = parse_line(_recv_line(cli))
        assert frame.msg_type == "PONG"


def test_exit_closes_connection(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, _, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test05|PROTO=DC1|ID=TRADER01\n")
        _ = _recv_line(cli)  # WELCOME
        cli.sendall(b"EXIT\n")
        cli.settimeout(_DEFAULT_TIMEOUT)
        # Server should close the connection (recv returns b"").
        end_time = time.time() + _DEFAULT_TIMEOUT
        closed = False
        while time.time() < end_time:
            chunk = cli.recv(4096)
            if not chunk:
                closed = True
                break
        assert closed


def test_two_clients_same_gateway_id_both_receive(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, pub, gateway_port = running_gateway

    with (
        socket.create_connection(
            ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
        ) as cli1,
        socket.create_connection(
            ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
        ) as cli2,
    ):
        cli1.sendall(b"HELLO|CLIENT=riskA|PROTO=DC1|ID=TRADER07\n")
        _ = _recv_line(cli1)
        cli2.sendall(b"HELLO|CLIENT=riskB|PROTO=DC1|ID=TRADER07\n")
        _ = _recv_line(cli2)

        _settle_subscription()

        deadline = time.time() + _DEFAULT_TIMEOUT
        seen1 = seen2 = False
        while time.time() < deadline and not (seen1 and seen2):
            pub.publish(
                "TRADER07",
                "order.fill",
                {"order_id": "ord-2", "symbol": "IBM", "fill_qty": 5},
            )
            for sock_obj, flag_name in ((cli1, "seen1"), (cli2, "seen2")):
                try:
                    sock_obj.settimeout(0.3)
                    frame = parse_line(_recv_line(sock_obj, timeout=0.3))
                except (TimeoutError, RuntimeError):
                    continue
                if (
                    frame.msg_type == "DC_FILL"
                    and frame.fields.get("ORDER_ID") == "ord-2"
                ):
                    if flag_name == "seen1":
                        seen1 = True
                    else:
                        seen2 = True
        assert seen1 and seen2
