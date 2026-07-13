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
    sess.role = "CLEARING"
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
    sess_audit, peer_audit = _make_session()
    sess_audit.authenticated = True
    sess_audit.subscriptions.add(("AUDIT", "AAPL"))
    unit_gateway._clients[sess_audit.sock.fileno()] = sess_audit

    sess_drop_copy, peer_drop_copy = _make_session()
    sess_drop_copy.authenticated = True
    sess_drop_copy.subscriptions.add(("DROP_COPY", "AAPL"))
    unit_gateway._clients[sess_drop_copy.sock.fileno()] = sess_drop_copy

    unit_gateway._handle_eod({"books": [{"symbol": "AAPL"}]})

    assert sess_audit.out_queue
    audit_lines = [parse_line(x.decode("utf-8")) for x in sess_audit.out_queue]
    assert any(frame.msg_type == "EOD" for frame in audit_lines)
    assert any(frame.fields.get("CH") == "AUDIT" for frame in audit_lines)

    assert sess_drop_copy.out_queue
    drop_copy_lines = [
        parse_line(x.decode("utf-8")) for x in sess_drop_copy.out_queue
    ]
    assert any(frame.msg_type == "EOD" for frame in drop_copy_lines)
    assert any(frame.fields.get("CH") == "DROP_COPY" for frame in drop_copy_lines)

    peer_audit.close()
    peer_drop_copy.close()


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


def test_replay_filters_by_role_entitlement(unit_gateway: RalfGateway) -> None:
    """A CLEARING-role session must not receive DROP_COPY or AUDIT events."""
    sess, peer = _make_session()
    sess.authenticated = True
    sess.role = "CLEARING"

    for seq, ch in ((1, "CLEARING"), (1, "DROP_COPY"), (1, "AUDIT")):
        unit_gateway._journal.append(
            JournalEvent(
                seq=seq,
                created_mono=time.monotonic(),
                line=f"EXEC|CH={ch}|SYM=AAPL|SEQ={seq}\n".encode(),
                channel=ch,
                symbol="AAPL",
            )
        )

    unit_gateway._replay_from(sess, last_seq=0)

    replayed = [parse_line(m.decode()) for m in sess.out_queue]
    channels = [f.fields["CH"] for f in replayed]
    assert channels == ["CLEARING"]
    peer.close()


def test_replay_audit_role_receives_all_channels(unit_gateway: RalfGateway) -> None:
    """An AUDIT-role session must receive events from all channels."""
    sess, peer = _make_session()
    sess.authenticated = True
    sess.role = "AUDIT"

    for seq, ch in ((1, "CLEARING"), (1, "DROP_COPY"), (1, "AUDIT")):
        unit_gateway._journal.append(
            JournalEvent(
                seq=seq,
                created_mono=time.monotonic(),
                line=f"EXEC|CH={ch}|SYM=AAPL|SEQ={seq}\n".encode(),
                channel=ch,
                symbol="AAPL",
            )
        )

    unit_gateway._replay_from(sess, last_seq=0)

    replayed = [parse_line(m.decode()) for m in sess.out_queue]
    channels = [f.fields["CH"] for f in replayed]
    assert set(channels) == {"CLEARING", "DROP_COPY", "AUDIT"}
    peer.close()


def test_emit_event_uses_per_channel_seq(unit_gateway: RalfGateway) -> None:
    unit_gateway._emit_event(
        "EXEC",
        {
            "CH": "CLEARING",
            "SYM": "AAPL",
            "TS": "2026-01-01T00:00:00Z",
            "EXEC_ID": "1",
            "MATCH_ID": "1",
            "BUY_ORDER_ID": "B1",
            "SELL_ORDER_ID": "S1",
            "BUY_GW": "GW1",
            "SELL_GW": "GW2",
            "SIDE": "BUY",
            "QTY": "10",
            "PX": "1.23",
        },
        channel="CLEARING",
        symbol="AAPL",
    )
    unit_gateway._emit_event(
        "EXEC",
        {
            "CH": "DROP_COPY",
            "SYM": "AAPL",
            "TS": "2026-01-01T00:00:01Z",
            "EXEC_ID": "2",
            "MATCH_ID": "2",
            "BUY_ORDER_ID": "B2",
            "SELL_ORDER_ID": "S2",
            "BUY_GW": "GW1",
            "SELL_GW": "GW2",
            "SIDE": "SELL",
            "QTY": "20",
            "PX": "2.34",
        },
        channel="DROP_COPY",
        symbol="AAPL",
    )
    unit_gateway._emit_event(
        "EXEC",
        {
            "CH": "CLEARING",
            "SYM": "AAPL",
            "TS": "2026-01-01T00:00:02Z",
            "EXEC_ID": "3",
            "MATCH_ID": "3",
            "BUY_ORDER_ID": "B3",
            "SELL_ORDER_ID": "S3",
            "BUY_GW": "GW1",
            "SELL_GW": "GW2",
            "SIDE": "BUY",
            "QTY": "30",
            "PX": "3.45",
        },
        channel="CLEARING",
        symbol="AAPL",
    )

    seqs = [
        parse_line(evt.line.decode("utf-8")).fields["SEQ"]
        for evt in unit_gateway._journal
    ]
    assert seqs == ["1", "1", "2"]


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
