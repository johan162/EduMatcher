from __future__ import annotations

import socket
import time
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
        heartbeat_interval_sec=1,
        idle_timeout_sec=1,
        replay_window_sec=5,
    )
    gw = MarketDataGateway(cfg, known_symbols={"AAPL", "MSFT"})
    try:
        yield gw
    finally:
        gw.close()


def _make_session() -> tuple[ClientSession, socket.socket]:
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)

    sess = ClientSession(sock=left, addr=("local", 0))
    return sess, right


def test_non_hello_requires_auth(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    unit_gateway._clients[sess.sock.fileno()] = sess
    unit_gateway._handle_client_line(sess, "SUB|CH=TOP|SYM=AAPL")
    assert sess.closing is True
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.fields["CODE"] == "AUTH_REQUIRED"
    peer.close()


def test_pre_auth_rate_limited(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    sess.rate_tokens = 0.0
    sess.rate_updated = time.monotonic()
    unit_gateway._clients[sess.sock.fileno()] = sess

    unit_gateway._handle_client_line(sess, "HELLO|CLIENT=x|PROTO=CALF1")

    assert sess.authenticated is False
    assert sess.out_queue
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.fields["CODE"] == "RATE_LIMITED"
    peer.close()


def test_hello_bad_proto(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    unit_gateway._handle_client_line(sess, "HELLO|CLIENT=x|PROTO=NOPE")
    assert sess.closing is True
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.fields["CODE"] == "PROTO_MISMATCH"
    peer.close()


def test_sub_invalid_symbol(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._handle_client_line(sess, "SUB|CH=TOP|SYM=ZZZZ")
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.fields["CODE"] == "INVALID_SYMBOL"
    peer.close()


def test_sub_state_wildcard_allowed(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._handle_client_line(sess, "SUB|CH=STATE|SYM=*")
    assert ("STATE", "*") in sess.subscriptions
    snap = parse_line(sess.out_queue[0].decode("utf-8"))
    assert snap.msg_type == "SNAP"
    assert snap.fields["CH"] == "STATE"
    peer.close()


def test_sub_trade_no_snap(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._handle_client_line(sess, "SUB|CH=TRADE|SYM=AAPL")
    assert ("TRADE", "AAPL") in sess.subscriptions
    assert not sess.out_queue
    peer.close()


def test_resume_bad_lastseq(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    unit_gateway._handle_client_line(
        sess,
        "HELLO|CLIENT=bot|PROTO=CALF1|RESUME=1|CH=TOP|SYM=AAPL|LASTSEQ=abc",
    )
    assert sess.closing is True
    peer.close()


def test_resume_adds_live_subscription(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    unit_gateway._replay.append("TOP", "AAPL", 2, b"MD|CH=TOP|SYM=AAPL|SEQ=2\n")
    unit_gateway._handle_client_line(
        sess,
        "HELLO|CLIENT=bot|PROTO=CALF1|RESUME=1|CH=TOP|SYM=AAPL|LASTSEQ=1",
    )
    assert sess.authenticated is True
    assert ("TOP", "AAPL") in sess.subscriptions
    peer.close()


def test_heartbeat_interval_not_spam(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    now = time.monotonic()
    sess.last_market_data_sent = now - 10
    sess.last_heartbeat_sent = now - 10
    unit_gateway._clients[sess.sock.fileno()] = sess
    unit_gateway._send_heartbeats_if_due()
    first_count = len(sess.out_queue)
    unit_gateway._send_heartbeats_if_due()
    second_count = len(sess.out_queue)
    assert first_count == 1
    assert second_count == 1
    peer.close()


def test_unsub_removes_pair(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    sess.subscriptions.add(("TOP", "AAPL"))
    unit_gateway._subs.set_for_client(sess.sock.fileno(), sess.subscriptions)
    unit_gateway._handle_client_line(sess, "UNSUB|CH=TOP|SYM=AAPL")
    assert ("TOP", "AAPL") not in sess.subscriptions
    peer.close()
