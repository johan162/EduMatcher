"""A connect-and-close with no bytes is a liveness probe, not a client.

pm-md-gwy, pm-ralf-gwy and pm-dc-gwy log it at DEBUG and leave it out of
their disconnect counters, so a TCP probe once a minute does not read as
hundreds of clients coming and going (pm-opctl-cli's check, a load balancer).
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Callable, Generator
from typing import Any

import pytest

from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.dc_gateway.gateway import ClientSession as DcSession
from edumatcher.dc_gateway.gateway import DcGateway
from edumatcher.md_gateway.client_session import ClientSession as MdSession
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway.gateway import MarketDataGateway
from edumatcher.ralf_gateway.config import RalfGatewayConfig
from edumatcher.ralf_gateway.gateway import ClientSession as RalfSession
from edumatcher.ralf_gateway.gateway import RalfGateway
from tests.conftest import free_ports


def _md() -> tuple[Any, Any]:
    port, pub = free_ports(2)
    cfg = MarketDataGatewayConfig(
        bind_address="127.0.0.1",
        port=port,
        engine_pub_addr=f"tcp://127.0.0.1:{pub}",
    )
    return MarketDataGateway(cfg, known_symbols={"AAPL"}, tick_decimals={"AAPL": 2}), (
        MdSession
    )


def _ralf() -> tuple[Any, Any]:
    port, pub = free_ports(2)
    cfg = RalfGatewayConfig(
        bind_address="127.0.0.1",
        port=port,
        engine_pub_addr=f"tcp://127.0.0.1:{pub}",
    )
    return RalfGateway(cfg), RalfSession


def _dc() -> tuple[Any, Any]:
    pub, port = free_ports(2)
    cfg = DcGatewayConfig(
        name="dc-test",
        bind_address="127.0.0.1",
        port=port,
        drop_copy_pub_addr=f"tcp://127.0.0.1:{pub}",
    )
    return DcGateway(cfg), DcSession


@pytest.fixture(params=[_md, _ralf, _dc], ids=["md", "ralf", "dc"])
def gateway(
    request: pytest.FixtureRequest,
) -> Generator[tuple[Any, Callable[[], tuple[Any, socket.socket]]], None, None]:
    gw, session_cls = request.param()

    def add_session() -> tuple[Any, socket.socket]:
        left, right = socket.socketpair()
        left.setblocking(False)
        sess = session_cls(sock=left, addr=("127.0.0.1", 1234))
        gw._clients[left.fileno()] = sess
        return sess, right

    try:
        yield gw, add_session
    finally:
        gw.close() if hasattr(gw, "close") else gw.stop()


def test_a_probe_is_logged_at_debug_and_not_counted(
    gateway: tuple[Any, Callable[[], tuple[Any, socket.socket]]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    gw, add_session = gateway
    sess, peer = add_session()
    peer.close()
    with caplog.at_level(logging.DEBUG):
        gw._read_client_data()

    assert sess.sock.fileno() not in gw._clients
    assert gw._disconnects == {}
    disconnects = [r for r in caplog.records if "client disconnected" in r.message]
    assert [r.levelno for r in disconnects] == [logging.DEBUG]
    assert not [r for r in caplog.records if r.levelno >= logging.INFO]


def test_a_client_that_sent_something_is_logged_and_counted(
    gateway: tuple[Any, Callable[[], tuple[Any, socket.socket]]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    gw, add_session = gateway
    sess, peer = add_session()
    peer.sendall(b"PING|TS=1\n")
    with caplog.at_level(logging.DEBUG):
        gw._read_client_data()
        peer.close()
        gw._read_client_data()

    assert gw._disconnects == {"peer_closed": 1}
    info = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any(m.startswith("client connected addr=127.0.0.1:1234") for m in info)
    assert any(m.startswith("client disconnected") for m in info)
