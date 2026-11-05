"""Inbound handling shared by pm-md-gwy, pm-ralf-gwy and pm-dc-gwy (W4 of the
line-gateway alignment workplan): one 4096-byte line limit, checked on both a
complete and an unterminated line, and a reset connection dropped at once."""

from __future__ import annotations

import socket
import struct
from collections.abc import Generator
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
from tests.conftest import free_port

NAMES = ["md", "ralf", "dc"]
OVERSIZED_ERR = b"ERR|CODE=BAD_MESSAGE|DETAIL=line exceeds 4096 bytes\n"


@pytest.fixture
def gateway(request: pytest.FixtureRequest) -> Generator[Any, None, None]:
    name = request.param
    port = free_port()
    gw: Any
    if name == "md":
        gw = MarketDataGateway(
            MarketDataGatewayConfig(bind_address="127.0.0.1", port=port)
        )
    elif name == "ralf":
        gw = RalfGateway(RalfGatewayConfig(bind_address="127.0.0.1", port=port))
    else:
        gw = DcGateway(DcGatewayConfig(bind_address="127.0.0.1", port=port))
    yield gw
    gw.close()


def _session(gw: Any, sock: socket.socket) -> Any:
    cls = {MarketDataGateway: MdSession, RalfGateway: RalfSession, DcGateway: DcSession}
    sess = cls[type(gw)](sock=sock, addr=("local", 0))
    gw._clients[sock.fileno()] = sess
    return sess


@pytest.mark.parametrize("gateway", NAMES, indirect=True)
def test_an_unterminated_line_at_the_limit_is_refused(gateway: Any) -> None:
    left, right = socket.socketpair()
    sess = _session(gateway, left)
    sess.in_buffer.extend(b"X" * 4096)
    gateway._drain_lines(sess)
    assert sess.closing is True
    assert not sess.in_buffer
    assert list(sess.out_queue) == [OVERSIZED_ERR]
    left.close()
    right.close()


@pytest.mark.parametrize("gateway", NAMES, indirect=True)
def test_an_oversized_line_split_over_two_reads_is_refused(gateway: Any) -> None:
    """pm-dc-gwy only checked the unterminated tail, so a 5000-byte line
    whose newline came in the second recv got through; pm-ralf-gwy checked
    nothing at all."""
    left, right = socket.socketpair()
    left.setblocking(False)
    sess = _session(gateway, left)
    right.sendall(b"X" * 3000)
    gateway._read_client_data()
    assert sess.closing is False  # still under the limit
    right.sendall(b"X" * 2000 + b"\n")
    gateway._read_client_data()
    assert sess.closing is True
    assert list(sess.out_queue) == [OVERSIZED_ERR]
    left.close()
    right.close()


@pytest.mark.parametrize("gateway", NAMES, indirect=True)
def test_a_line_of_exactly_4096_bytes_is_accepted(gateway: Any) -> None:
    left, right = socket.socketpair()
    sess = _session(gateway, left)
    line = b"PING|PAD=" + b"X" * (4095 - len(b"PING|PAD="))
    sess.in_buffer.extend(line + b"\n")  # 4096 bytes including the newline
    gateway._drain_lines(sess)
    assert sess.closing is True  # pre-auth PING: AUTH_REQUIRED, not the limit
    assert b"AUTH_REQUIRED" in sess.out_queue[0]
    left.close()
    right.close()


@pytest.mark.parametrize("gateway", NAMES, indirect=True)
def test_a_reset_connection_is_dropped_at_once(gateway: Any) -> None:
    server = socket.create_server(("127.0.0.1", 0))
    client = socket.create_connection(server.getsockname())
    conn, _ = server.accept()
    conn.setblocking(False)
    _session(gateway, conn)
    # SO_LINGER 0: close() sends RST, so the gateway's recv gets ECONNRESET.
    client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    client.close()

    gateway._read_client_data()

    assert not gateway._clients
    assert gateway._disconnects == {"peer_reset": 1}
    server.close()


@pytest.mark.parametrize("gateway", NAMES, indirect=True)
def test_accepted_connections_have_nodelay(gateway: Any) -> None:
    """W6: only pm-dc-gwy set TCP_NODELAY; small lines (HB, PONG, a single
    MD) waited on Nagle in the other two."""
    gateway._server = socket.create_server(("127.0.0.1", 0))
    gateway._server.setblocking(False)
    client = socket.create_connection(gateway._server.getsockname())
    for _ in range(50):
        gateway._accept_new_clients()
        if gateway._clients:
            break
    (sess,) = gateway._clients.values()
    assert sess.sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
    client.close()
