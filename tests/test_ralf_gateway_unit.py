from __future__ import annotations

import socket
import time
from collections.abc import Generator

import pytest

from edumatcher.ralf_gateway.config import RalfGatewayConfig
from edumatcher.ralf_gateway.gateway import ClientSession, JournalEvent, RalfGateway
from edumatcher.ralf_gateway.protocol import parse_line


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def unit_gateway() -> Generator[RalfGateway, None, None]:
    cfg = RalfGatewayConfig(
        bind_address="127.0.0.1",
        port=_free_port(),
        engine_pub_addr=f"tcp://127.0.0.1:{_free_port()}",
        heartbeat_interval_sec=1,
        idle_timeout_sec=1,
        replay_retention_sec=5,
    )
    gw = RalfGateway(cfg)
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


def test_handle_non_hello_requires_auth(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    unit_gateway._clients[sess.sock.fileno()] = sess
    unit_gateway._handle_client_line(sess, "SUB|CH=CLEARING|SYM=*")
    assert sess.closing is True
    assert sess.out_queue
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.msg_type == "ERR"
    assert frame.fields["CODE"] == "AUTH_REQUIRED"
    peer.close()


def test_handle_hello_with_bad_lastseq(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    unit_gateway._handle_client_line(
        sess,
        "HELLO|CLIENT=x|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=abc",
    )
    assert sess.closing is True
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.fields["CODE"] == "BAD_MESSAGE"
    peer.close()


def test_handle_sub_invalid_channel(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._handle_client_line(sess, "SUB|CH=NOPE|SYM=*")
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.msg_type == "ERR"
    assert frame.fields["CODE"] == "INVALID_CHANNEL"
    peer.close()


def test_ping_and_exit(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._clients[sess.sock.fileno()] = sess

    unit_gateway._handle_client_line(sess, "PING")
    pong = parse_line(sess.out_queue[0].decode("utf-8"))
    assert pong.msg_type == "PONG"

    unit_gateway._handle_client_line(sess, "EXIT")
    assert sess.closing is True
    peer.close()


def test_unknown_message_for_authenticated_session(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._handle_client_line(sess, "WHAT")
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.msg_type == "ERR"
    assert frame.fields["CODE"] == "BAD_MESSAGE"
    peer.close()


def test_parse_error_branch(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    unit_gateway._handle_client_line(sess, "HELLO|BROKEN_FIELD")
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.msg_type == "ERR"
    assert frame.fields["CODE"] == "BAD_MESSAGE"
    peer.close()


def test_replay_miss_emits_err_and_snap(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._journal.append(
        JournalEvent(
            seq=100,
            created_mono=time.monotonic(),
            line=b"EXEC|CH=CLEARING|SYM=AAPL|SEQ=100\n",
            channel="CLEARING",
            symbol="AAPL",
        )
    )
    unit_gateway._replay_from(sess, last_seq=1)
    assert len(sess.out_queue) >= 2
    err = parse_line(sess.out_queue[0].decode("utf-8"))
    snap = parse_line(sess.out_queue[1].decode("utf-8"))
    assert err.msg_type == "ERR"
    assert err.fields["CODE"] == "REPLAY_MISS"
    assert snap.msg_type == "SNAP"
    peer.close()


def test_replay_from_empty_journal_is_noop(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    unit_gateway._replay_from(sess, last_seq=10)
    assert not sess.out_queue
    peer.close()


def test_handle_eod_emits_for_subscribed_channels(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    sess.subscriptions.add(("AUDIT", "AAPL"))
    unit_gateway._clients[sess.sock.fileno()] = sess

    unit_gateway._handle_eod({"books": [{"symbol": "AAPL"}]})
    assert sess.out_queue
    lines = [parse_line(x.decode("utf-8")) for x in sess.out_queue]
    assert any(frame.msg_type == "EOD" for frame in lines)
    peer.close()


def test_handle_unsub_removes_subscription(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    sess.subscriptions.add(("CLEARING", "AAPL"))
    unit_gateway._handle_client_line(sess, "UNSUB|CH=CLEARING|SYM=AAPL")
    assert ("CLEARING", "AAPL") not in sess.subscriptions
    peer.close()


def test_prune_journal(unit_gateway: RalfGateway) -> None:
    unit_gateway._journal.append(
        JournalEvent(
            seq=1,
            created_mono=time.monotonic() - 999,
            line=b"EXEC|CH=CLEARING|SYM=AAPL|SEQ=1\n",
            channel="CLEARING",
            symbol="AAPL",
        )
    )
    unit_gateway._journal.append(
        JournalEvent(
            seq=2,
            created_mono=time.monotonic(),
            line=b"EXEC|CH=CLEARING|SYM=AAPL|SEQ=2\n",
            channel="CLEARING",
            symbol="AAPL",
        )
    )

    unit_gateway._prune_journal()
    assert len(unit_gateway._journal) == 1
    assert unit_gateway._journal[0].seq == 2


def test_drop_idle_clients_marks_for_close(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    sess.last_activity = time.monotonic() - 99
    unit_gateway._clients[sess.sock.fileno()] = sess

    unit_gateway._drop_idle_clients()
    assert sess.closing is True
    assert sess.out_queue
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.msg_type == "EXIT"
    peer.close()


def test_send_heartbeat_enqueues_hb(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._clients[sess.sock.fileno()] = sess
    unit_gateway._last_heartbeat = time.monotonic() - 10

    unit_gateway._send_heartbeat_if_due()
    assert sess.out_queue
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.msg_type == "HB"
    peer.close()


def test_session_wants_wildcard(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    sess.subscriptions.add(("CLEARING", "*"))
    assert unit_gateway._session_wants(sess, "CLEARING", "MSFT") is True
    peer.close()


def test_flush_client_writes_and_disconnect(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    unit_gateway._clients[sess.sock.fileno()] = sess
    unit_gateway._queue_raw(sess, b"PING|TS=1\n")
    sess.closing = True

    unit_gateway._flush_client_writes()
    # Read payload from peer and ensure the client was removed.
    data = peer.recv(1024)
    assert b"PING|TS=1" in data
    assert sess.sock.fileno() not in unit_gateway._clients
    peer.close()
