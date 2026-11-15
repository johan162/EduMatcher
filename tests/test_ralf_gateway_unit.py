from __future__ import annotations

import socket
import time
from collections.abc import Generator

import pytest

from edumatcher.ralf_gateway.config import RalfGatewayConfig
from edumatcher.ralf_gateway.gateway import ClientSession, JournalEvent, RalfGateway
from edumatcher.ralf_gateway.protocol import parse_line
from tests.conftest import free_ports


@pytest.fixture()
def unit_gateway() -> Generator[RalfGateway, None, None]:
    gateway_port, engine_pub_port = free_ports(2)
    cfg = RalfGatewayConfig(
        bind_address="127.0.0.1",
        port=gateway_port,
        engine_pub_addr=f"tcp://127.0.0.1:{engine_pub_port}",
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


def _resume(
    gw: RalfGateway,
    sess: ClientSession,
    last_seq: int,
    sub: str,
    *,
    role: str = "CLEARING",
) -> tuple[list[str], list[str]]:
    """HELLO with a checkpoint of this run, then ``sub``: the message types
    queued after the WELCOME, and those queued in reply to the SUB."""
    gw._handle_client_line(
        sess,
        f"HELLO|CLIENT=x|PROTO=RALF1|ROLE={role}|LASTSEQ={last_seq}"
        f"|EPOCH={gw._epoch}",
    )
    after_hello = [parse_line(x.decode()).msg_type for x in sess.out_queue][1:]
    sess.out_queue.clear()
    gw._handle_client_line(sess, sub)
    return after_hello, [parse_line(x.decode()).msg_type for x in sess.out_queue]


def test_replay_miss_is_the_sub_reply(unit_gateway: RalfGateway) -> None:
    """WP-RALF03: HELLO only records the checkpoint; the SUB answers it."""
    sess, peer = _make_session()
    unit_gateway._journal.append(
        JournalEvent(
            seq=100,
            created_mono=time.monotonic(),
            line=b"EXEC|CH=CLEARING|SYM=AAPL|SEQ=100\n",
            channel="CLEARING",
            symbol="AAPL",
        )
    )
    unit_gateway._next_seq_by_channel["CLEARING"] = 101
    after_hello, reply = _resume(unit_gateway, sess, 1, "SUB|CH=CLEARING|SYM=*")
    assert after_hello == []
    assert reply == ["ERR", "SNAP"]
    assert b"CODE=REPLAY_MISS" in sess.out_queue[0]
    peer.close()


def _trade(unit_gateway: RalfGateway, trade_id: str, symbol: str = "AAPL") -> None:
    unit_gateway._handle_trade(
        {"id": trade_id, "symbol": symbol, "quantity": 1, "price": 1.0}
    )


def test_replay_ahead_of_the_journal_is_a_miss(unit_gateway: RalfGateway) -> None:
    """W5: after a gateway restart the journal is empty and a client's
    LASTSEQ is from the old run; that used to be a silent empty replay."""
    sess, peer = _make_session()
    _, reply = _resume(unit_gateway, sess, 10, "SUB|CH=CLEARING|SYM=*")
    assert reply == ["ERR", "SNAP"]
    assert b"CODE=REPLAY_MISS" in sess.out_queue[0]
    assert b"SEQ=0" in sess.out_queue[1]
    peer.close()


def test_replay_after_everything_aged_out_is_a_miss(
    unit_gateway: RalfGateway,
) -> None:
    sess, peer = _make_session()
    for trade_id in ("T1", "T2", "T3"):
        _trade(unit_gateway, trade_id)
    unit_gateway._journal.clear()  # all pruned by retention
    _, reply = _resume(unit_gateway, sess, 1, "SUB|CH=CLEARING|SYM=*")
    assert reply == ["ERR", "SNAP"]
    assert b"SEQ=3" in sess.out_queue[1]
    peer.close()


def test_replay_when_up_to_date_sends_only_the_snap(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    for trade_id in ("T1", "T2"):
        _trade(unit_gateway, trade_id)
    unit_gateway._journal.clear()  # nothing retained, but nothing missed
    _, reply = _resume(unit_gateway, sess, 2, "SUB|CH=CLEARING|SYM=*")
    assert reply == ["SNAP"]
    peer.close()


def test_replay_resends_what_follows_last_seq(unit_gateway: RalfGateway) -> None:
    sess, peer = _make_session()
    for trade_id in ("T1", "T2", "T3"):
        _trade(unit_gateway, trade_id)
    _, reply = _resume(unit_gateway, sess, 1, "SUB|CH=CLEARING|SYM=*")
    assert reply == ["EXEC", "EXEC", "SNAP"]
    assert [b"SEQ=2" in x or b"SEQ=3" in x for x in list(sess.out_queue)[:2]] == [
        True,
        True,
    ]
    peer.close()


def test_replay_audit_role_receives_each_subscribed_channel(
    unit_gateway: RalfGateway,
) -> None:
    """An AUDIT session is replayed every channel it subscribes, once each."""
    sess, peer = _make_session()
    for trade_id in ("T1", "T2"):
        _trade(unit_gateway, trade_id)
    _, reply = _resume(
        unit_gateway, sess, 1, "SUB|CH=CLEARING,DROP_COPY,AUDIT|SYM=*", role="AUDIT"
    )
    assert reply == ["EXEC", "EXEC", "EXEC", "SNAP"]
    channels = [parse_line(x.decode()).fields["CH"] for x in list(sess.out_queue)[:3]]
    assert sorted(channels) == ["AUDIT", "CLEARING", "DROP_COPY"]
    peer.close()


def test_replay_for_a_clearing_role_is_its_channel_only(
    unit_gateway: RalfGateway,
) -> None:
    sess, peer = _make_session()
    for trade_id in ("T1", "T2"):
        _trade(unit_gateway, trade_id)
    _, reply = _resume(unit_gateway, sess, 1, "SUB|CH=CLEARING|SYM=*")
    assert reply == ["EXEC", "SNAP"]
    assert b"CH=CLEARING" in sess.out_queue[0]
    peer.close()


def _clearing_session() -> tuple[ClientSession, socket.socket]:
    sess, peer = _make_session()
    sess.authenticated = True
    sess.role = "CLEARING"
    return sess, peer


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
    drop_copy_lines = [parse_line(x.decode("utf-8")) for x in sess_drop_copy.out_queue]
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


def test_unsub_without_ch_is_bad_message(unit_gateway: RalfGateway) -> None:
    """W6: was silently ignored; pm-md-gwy answers BAD_MESSAGE too."""
    sess, peer = _clearing_session()
    unit_gateway._handle_client_line(sess, "UNSUB|SYM=AAPL")
    err = parse_line(sess.out_queue[0].decode("utf-8"))
    assert err.fields == {"CODE": "BAD_MESSAGE", "DETAIL": "CH required"}
    peer.close()


class _EndlessSub:
    """An engine SUB that always has another trade waiting."""

    closed = False

    def __init__(self) -> None:
        self.reads = 0

    def poll(self, *_a: object, **_k: object) -> int:
        return 1

    def recv_multipart(self) -> list[bytes]:
        from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED

        self.reads += 1
        return [TOPIC_TRADE_EXECUTED.encode(), b'{"id": "T", "symbol": "AAPL"}']

    def close(self) -> None:
        pass


def test_engine_events_are_bounded_per_pass(unit_gateway: RalfGateway) -> None:
    """W6: an unbounded drain let a trade burst starve the client loop."""
    from edumatcher.ralf_gateway import gateway as ralf_mod

    real_sub = unit_gateway._sub
    endless = _EndlessSub()
    unit_gateway._sub = endless
    unit_gateway._poll_engine_events()
    unit_gateway._sub = real_sub
    assert endless.reads == ralf_mod._MAX_ENGINE_EVENTS_PER_LOOP


class _BlockedSocket:
    """A client socket whose peer has stopped reading: every send blocks."""

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def fileno(self) -> int:
        return self._fd

    def send(self, _data: bytes) -> int:
        raise BlockingIOError

    def close(self) -> None:
        pass


def test_replayed_lines_do_not_count_towards_the_slow_client_limit() -> None:
    """WP-RALF03 (review C2): the limit applies to what is queued beyond the
    replay; live overflow after it is still SLOW_CLIENT."""
    gateway_port, engine_pub_port = free_ports(2)
    gw = RalfGateway(
        RalfGatewayConfig(
            bind_address="127.0.0.1",
            port=gateway_port,
            engine_pub_addr=f"tcp://127.0.0.1:{engine_pub_port}",
            max_client_queue=5,
        )
    )
    try:
        sess = ClientSession(sock=_BlockedSocket(9999), addr=("local", 0))  # type: ignore[arg-type]
        gw._clients[9999] = sess
        for n in range(21):
            _trade(gw, f"T{n}")
        _resume(gw, sess, 1, "SUB|CH=CLEARING|SYM=*")
        assert len(sess.out_queue) == 21  # 20 replayed + SNAP
        gw._flush_client_writes()
        assert not sess.closing

        for n in range(4):  # 25 queued: 5 beyond the 20 replayed
            _trade(gw, f"L{n}")
        gw._flush_client_writes()
        assert not sess.closing

        _trade(gw, "L4")  # 26: one live line too many
        gw._flush_client_writes()
        assert sess.closing and sess.close_reason == "slow_client"
    finally:
        gw._clients.clear()
        gw.close()


def test_unsub_removes_only_the_exact_pair(unit_gateway: RalfGateway) -> None:
    """UNSUB of one symbol does not carve it out of a SYM=* subscription
    (found re-walking training ch. 22, exercise 4)."""
    sess, peer = _clearing_session()
    unit_gateway._handle_client_line(sess, "SUB|CH=CLEARING|SYM=*")
    unit_gateway._handle_client_line(sess, "UNSUB|CH=CLEARING|SYM=AAPL")
    assert sess.subscriptions == {("CLEARING", "*")}
    assert unit_gateway._session_wants(sess, "CLEARING", "AAPL")
    peer.close()
