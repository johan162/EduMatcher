"""pm-md-gwy serves past 1024 descriptors and says goodbye on a stop
(For-Later L036, WP-FL11; the port of pm-ralf-gwy's WP-RALF04).

``select()`` refuses a descriptor of 1024 or more: the pass returned without
reading anyone, every pass, with a WARNING each time. ``close()`` closed every
session without a final line, so a planned stop looked like a crash and the
lines still queued were lost.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Generator

import pytest

import edumatcher.md_gateway.gateway as gateway_mod
from edumatcher.md_gateway.client_session import ClientSession
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway.gateway import MarketDataGateway
from edumatcher.md_gateway.protocol import parse_line
from tests.conftest import free_ports

_TIMEOUT = 5.0


def _start(**overrides: object) -> tuple[MarketDataGateway, threading.Thread, int]:
    gateway_port, engine_pub_port = free_ports(2)
    cfg = MarketDataGatewayConfig(
        bind_address="127.0.0.1",
        port=gateway_port,
        engine_pub_addr=f"tcp://127.0.0.1:{engine_pub_port}",
        **overrides,  # type: ignore[arg-type]
    )
    gw = MarketDataGateway(cfg, known_symbols={"AAPL"})
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()
    deadline = time.monotonic() + _TIMEOUT
    while gw._server is None and time.monotonic() < deadline:
        time.sleep(0.01)
    return gw, t, gateway_port


@pytest.fixture
def running() -> Generator[tuple[MarketDataGateway, int], None, None]:
    gw, t, port = _start()
    try:
        yield gw, port
    finally:
        gw.stop()
        t.join(timeout=_TIMEOUT)


def _read_all(cli: socket.socket) -> list[str]:
    cli.settimeout(_TIMEOUT)
    data = bytearray()
    while chunk := cli.recv(65536):
        data.extend(chunk)
    return [ln for ln in data.decode().split("\n") if ln]


def _recv_line(cli: socket.socket) -> str:
    cli.settimeout(_TIMEOUT)
    data = bytearray()
    while not data.endswith(b"\n"):
        chunk = cli.recv(1)
        if not chunk:
            break
        data.extend(chunk)
    return data.decode().rstrip("\n")


def test_a_client_on_a_descriptor_above_1023_is_served(
    running: tuple[MarketDataGateway, int],
    caplog: pytest.LogCaptureFixture,
    descriptors_above_1023: None,
) -> None:
    _gw, port = running
    caplog.set_level(logging.WARNING, logger=gateway_mod.__name__)
    with socket.create_connection(("127.0.0.1", port), timeout=2) as cli:
        cli.sendall(b"HELLO|CLIENT=t|PROTO=CALF1\n")
        assert parse_line(_recv_line(cli)).msg_type == "WELCOME"
        cli.sendall(b"PING\n")
        assert parse_line(_recv_line(cli)).msg_type == "PONG"
    assert not [r for r in caplog.records if "read" in r.getMessage()]


def test_stop_ends_every_session_with_exit_shutdown() -> None:
    gw, t, port = _start()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as cli:
            cli.sendall(b"HELLO|CLIENT=t|PROTO=CALF1\n")
            assert parse_line(_recv_line(cli)).msg_type == "WELCOME"
            gw.stop()
            frames = [parse_line(ln) for ln in _read_all(cli)]
    finally:
        gw.stop()
        t.join(timeout=_TIMEOUT)

    assert frames[-1].msg_type == "EXIT"
    assert frames[-1].fields["REASON"] == "shutdown"
    assert frames[-1].fields["TS"].endswith("Z")
    assert gw._disconnects.get("shutdown") == 1


def test_the_lines_already_queued_go_out_before_the_exit() -> None:
    gateway_port, engine_pub_port = free_ports(2)
    gw = MarketDataGateway(
        MarketDataGatewayConfig(
            bind_address="127.0.0.1",
            port=gateway_port,
            engine_pub_addr=f"tcp://127.0.0.1:{engine_pub_port}",
        ),
        known_symbols={"AAPL"},
    )
    left, right = socket.socketpair()
    left.setblocking(False)
    sess = ClientSession(sock=left, addr=("local", 0))
    sess.authenticated = True
    gw._clients[left.fileno()] = sess
    for n in range(3):
        gw._queue_line(sess, "PONG", {"N": str(n)})

    gw._flush_for_shutdown()
    gw.close()

    frames = [parse_line(ln) for ln in _read_all(right)]
    right.close()
    assert [f.msg_type for f in frames] == ["PONG", "PONG", "PONG", "EXIT"]
    assert frames[-1].fields["REASON"] == "shutdown"


def test_a_client_that_stopped_reading_holds_the_stop_at_most_a_second() -> None:
    gw, t, port = _start(max_client_queue=1_000_000)
    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cli.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    cli.connect(("127.0.0.1", port))
    try:
        cli.sendall(b"HELLO|CLIENT=t|PROTO=CALF1\n")
        deadline = time.monotonic() + _TIMEOUT
        while not gw._clients and time.monotonic() < deadline:
            time.sleep(0.01)
        # Several MB the reader never takes: more than the socket buffers hold.
        cli.sendall(b"PING\n" * 200_000)
        while (
            not any(len(s.out_queue) > 1000 for s in list(gw._clients.values()))
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        started = time.monotonic()
        gw.stop()
        t.join(timeout=_TIMEOUT)
        took = time.monotonic() - started
    finally:
        gw.stop()
        cli.close()

    assert not t.is_alive()
    assert took < 1.5
    assert gw._disconnects.get("shutdown") == 1
