from __future__ import annotations

import socket
from collections.abc import Generator

import pytest

from edumatcher.md_gateway.client_session import ClientSession
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway.gateway import MarketDataGateway
from edumatcher.md_gateway.protocol import parse_line


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def unit_gateway() -> Generator[MarketDataGateway, None, None]:
    cfg = MarketDataGatewayConfig(
        bind_address="127.0.0.1",
        port=_free_port(),
        engine_pub_addr=f"tcp://127.0.0.1:{_free_port()}",
        replay_window_sec=10,
    )
    gw = MarketDataGateway(cfg, known_symbols={"AAPL"})
    try:
        yield gw
    finally:
        gw.close()


def test_emit_stream_event_routes_to_subscriber(
    unit_gateway: MarketDataGateway,
) -> None:
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    session = ClientSession(sock=left, addr=("local", 0), authenticated=True)
    session.subscriptions.add(("TOP", "AAPL"))
    unit_gateway._clients[left.fileno()] = session
    unit_gateway._subs.set_for_client(left.fileno(), session.subscriptions)

    unit_gateway._emit_stream_event(
        "MD",
        "TOP",
        "AAPL",
        {"BID": "150.1", "BIDSZ": "100"},
        ts_seconds=0.0,
    )

    assert session.out_queue
    frame = parse_line(session.out_queue[0].decode("utf-8"))
    assert frame.msg_type == "MD"
    assert frame.fields["CH"] == "TOP"
    assert frame.fields["SYM"] == "AAPL"
    right.close()


def test_emit_auction_routes_to_wildcard_subscriber(
    unit_gateway: MarketDataGateway,
) -> None:
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    session = ClientSession(sock=left, addr=("local", 0), authenticated=True)
    session.subscriptions.add(("AUCTION", "*"))
    unit_gateway._clients[left.fileno()] = session
    unit_gateway._subs.set_for_client(left.fileno(), session.subscriptions)

    unit_gateway._emit_stream_event(
        "AUCTION",
        "AUCTION",
        "AAPL",
        {"EQPX": "150.1", "EQQTY": "48200", "TRADES": "37", "IMBQTY": "1400"},
        ts_seconds=0.0,
    )

    assert session.out_queue
    frame = parse_line(session.out_queue[0].decode("utf-8"))
    assert frame.msg_type == "AUCTION"
    assert frame.fields["CH"] == "AUCTION"
    assert frame.fields["SYM"] == "AAPL"
    assert frame.fields["EQPX"] == "150.1"
    right.close()


def test_emit_cb_routes_to_subscriber(unit_gateway: MarketDataGateway) -> None:
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    session = ClientSession(sock=left, addr=("local", 0), authenticated=True)
    session.subscriptions.add(("CB", "AAPL"))
    unit_gateway._clients[left.fileno()] = session
    unit_gateway._subs.set_for_client(left.fileno(), session.subscriptions)

    unit_gateway._emit_stream_event(
        "CB",
        "CB",
        "AAPL",
        {"STATUS": "HALTED", "LEVEL": "L2", "MODE": "AUCTION"},
        ts_seconds=0.0,
    )

    assert session.out_queue
    frame = parse_line(session.out_queue[0].decode("utf-8"))
    assert frame.msg_type == "CB"
    assert frame.fields["CH"] == "CB"
    assert frame.fields["STATUS"] == "HALTED"
    right.close()
