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


def test_sub_auction_unknown_symbol_rejected(unit_gateway: MarketDataGateway) -> None:
    """AUCTION follows the same known-symbol validation as every non-INDEX
    channel; it does not get a special exemption."""
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._handle_client_line(sess, "SUB|CH=AUCTION|SYM=ZZZZ")
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.fields["CODE"] == "INVALID_SYMBOL"
    peer.close()


def _authenticated_session(
    gateway: MarketDataGateway,
) -> tuple[ClientSession, socket.socket]:
    """A session that has completed the handshake, ready for RESUME."""
    sess, peer = _make_session()
    gateway._handle_client_line(sess, "HELLO|CLIENT=bot|PROTO=CALF1")
    assert sess.authenticated is True
    sess.out_queue.clear()
    return sess, peer


def _err_codes(sess: ClientSession) -> list[str]:
    frames = [parse_line(line.decode("utf-8")) for line in sess.out_queue]
    return [f.fields["CODE"] for f in frames if f.msg_type == "ERR"]


def test_resume_auction_replays_missed_events(
    unit_gateway: MarketDataGateway,
) -> None:
    sess, peer = _authenticated_session(unit_gateway)
    unit_gateway._replay.append(
        "AUCTION", "AAPL", 2, b"AUCTION|CH=AUCTION|SYM=AAPL|SEQ=2\n"
    )
    unit_gateway._handle_client_line(sess, "RESUME|CH=AUCTION|SYM=AAPL|LASTSEQ=1")
    assert ("AUCTION", "AAPL") in sess.subscriptions
    peer.close()


def test_resume_recovers_several_streams_on_one_connection(
    unit_gateway: MarketDataGateway,
) -> None:
    """The reason RESUME is its own command rather than a HELLO flag.

    A client following more than one stream — the normal case for anything
    watching a whole market — must be able to resume all of them after a
    reconnect. As a HELLO flag it could only ever resume the first, because
    HELLO is dispatched only while the session is unauthenticated.
    """
    sess, peer = _authenticated_session(unit_gateway)
    unit_gateway._replay.append("TOP", "AAPL", 2, b"MD|CH=TOP|SYM=AAPL|SEQ=2\n")
    unit_gateway._replay.append("TOP", "MSFT", 5, b"MD|CH=TOP|SYM=MSFT|SEQ=5\n")

    unit_gateway._handle_client_line(sess, "RESUME|CH=TOP|SYM=AAPL|LASTSEQ=1")
    unit_gateway._handle_client_line(sess, "RESUME|CH=TOP|SYM=MSFT|LASTSEQ=4")
    unit_gateway._handle_client_line(sess, "RESUME|CH=TRADE|SYM=AAPL|LASTSEQ=1")

    assert {("TOP", "AAPL"), ("TOP", "MSFT"), ("TRADE", "AAPL")} <= sess.subscriptions
    assert _err_codes(sess) == []
    peer.close()


def test_resume_after_handshake_is_rejected_as_hello(
    unit_gateway: MarketDataGateway,
) -> None:
    """The old HELLO|RESUME=1 form is gone; a second HELLO is still refused."""
    sess, peer = _authenticated_session(unit_gateway)

    unit_gateway._handle_client_line(
        sess, "HELLO|CLIENT=bot|PROTO=CALF1|RESUME=1|CH=TOP|SYM=AAPL|LASTSEQ=1"
    )

    assert ("TOP", "AAPL") not in sess.subscriptions
    assert _err_codes(sess) == ["BAD_MESSAGE"]
    peer.close()


def test_resume_bad_lastseq_keeps_the_session_open(
    unit_gateway: MarketDataGateway,
) -> None:
    """One malformed RESUME must not cost the client every other stream."""
    sess, peer = _authenticated_session(unit_gateway)

    unit_gateway._handle_client_line(sess, "RESUME|CH=TOP|SYM=AAPL|LASTSEQ=abc")

    assert sess.closing is False
    assert _err_codes(sess) == ["BAD_MESSAGE"]

    # ...and the client can carry on resuming the rest.
    unit_gateway._handle_client_line(sess, "RESUME|CH=TOP|SYM=MSFT|LASTSEQ=1")
    assert ("TOP", "MSFT") in sess.subscriptions
    peer.close()


def test_resume_rejects_a_zero_lastseq(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _authenticated_session(unit_gateway)
    unit_gateway._handle_client_line(sess, "RESUME|CH=TOP|SYM=AAPL|LASTSEQ=0")
    assert _err_codes(sess) == ["BAD_MESSAGE"]
    peer.close()


def test_resume_rejects_an_unknown_channel(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _authenticated_session(unit_gateway)
    unit_gateway._handle_client_line(sess, "RESUME|CH=BOOK|SYM=AAPL|LASTSEQ=1")
    assert _err_codes(sess) == ["INVALID_CHANNEL"]
    peer.close()


def test_resume_rejects_multiple_streams_in_one_message(
    unit_gateway: MarketDataGateway,
) -> None:
    """LASTSEQ is per-stream, so one message can only ever mean one stream."""
    sess, peer = _authenticated_session(unit_gateway)
    unit_gateway._handle_client_line(sess, "RESUME|CH=TOP|SYM=AAPL,MSFT|LASTSEQ=1")
    assert _err_codes(sess) == ["BAD_MESSAGE"]
    assert ("TOP", "AAPL") not in sess.subscriptions
    peer.close()


def test_resume_wildcard_symbol_rejected(unit_gateway: MarketDataGateway) -> None:
    """RESUME has no per-symbol snapshot-burst path like SUB does, so a
    wildcard resume cannot be served a meaningful baseline on a replay miss
    (top_snapshot_fields("*") would silently return an empty SNAP). SYM=*
    must be rejected for every channel on RESUME, including TOP/TRADE/STATE
    where it is otherwise allowed on SUB.
    """
    sess, peer = _authenticated_session(unit_gateway)

    unit_gateway._handle_client_line(sess, "RESUME|CH=TOP|SYM=*|LASTSEQ=1")

    assert ("TOP", "*") not in sess.subscriptions
    assert sess.closing is False
    assert _err_codes(sess) == ["INVALID_SYMBOL"]
    peer.close()


def test_resume_requires_authentication_first(
    unit_gateway: MarketDataGateway,
) -> None:
    sess, peer = _make_session()
    unit_gateway._clients[sess.sock.fileno()] = sess

    unit_gateway._handle_client_line(sess, "RESUME|CH=TOP|SYM=AAPL|LASTSEQ=1")

    assert _err_codes(sess) == ["AUTH_REQUIRED"]
    peer.close()


def test_resume_falls_back_to_a_snapshot_on_replay_miss(
    unit_gateway: MarketDataGateway,
) -> None:
    """A gap wider than the replay window is recoverable, not fatal."""
    sess, peer = _authenticated_session(unit_gateway)
    # The client is far behind what the buffer still holds, so the gap cannot
    # be filled from replay and it needs a fresh baseline instead.
    unit_gateway._replay.append("TOP", "AAPL", 900, b"MD|CH=TOP|SYM=AAPL|SEQ=900\n")

    unit_gateway._handle_client_line(sess, "RESUME|CH=TOP|SYM=AAPL|LASTSEQ=1")

    frames = [parse_line(line.decode("utf-8")) for line in sess.out_queue]
    assert _err_codes(sess) == ["REPLAY_MISS"]
    assert any(f.msg_type == "SNAP" for f in frames), "expected a baseline SNAP"
    assert sess.closing is False
    peer.close()


def test_resume_adds_live_subscription(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _authenticated_session(unit_gateway)
    unit_gateway._replay.append("TOP", "AAPL", 2, b"MD|CH=TOP|SYM=AAPL|SEQ=2\n")
    unit_gateway._handle_client_line(sess, "RESUME|CH=TOP|SYM=AAPL|LASTSEQ=1")
    assert ("TOP", "AAPL") in sess.subscriptions
    peer.close()


def test_outbound_traffic_keeps_a_passive_listener_connected(
    unit_gateway: MarketDataGateway,
) -> None:
    """A market-data consumer normally has nothing to say after subscribing.

    The idle timer counts traffic in either direction, so successfully writing
    to such a client must refresh it. Before this held, every silent listener
    was dropped on a fixed cycle regardless of how healthy its socket was —
    which is why pm-calf-spy carries a PING thread.
    """
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._clients[sess.sock.fileno()] = sess

    # Nothing inbound for well past idle_timeout_sec (1s for this fixture).
    sess.last_activity = time.monotonic() - 60
    unit_gateway._queue_line(sess, "HB", {"TS": "2026-07-30T09:00:00.000Z"})
    unit_gateway._flush_client_writes()

    unit_gateway._drop_idle_clients()

    assert sess.sock.fileno() in unit_gateway._clients
    peer.close()


def test_idle_client_is_dropped_when_nothing_flows_either_way(
    unit_gateway: MarketDataGateway,
) -> None:
    """The timeout must still fire when there is genuinely no traffic."""
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._clients[sess.sock.fileno()] = sess
    sess.last_activity = time.monotonic() - 60

    unit_gateway._drop_idle_clients()

    assert sess.sock.fileno() not in unit_gateway._clients
    peer.close()


def test_failed_writes_do_not_keep_a_wedged_client_alive(
    unit_gateway: MarketDataGateway,
) -> None:
    """Queuing is not activity — only a send that actually succeeds is.

    Otherwise our own backlog to a client that stopped reading would renew its
    lease forever, which is the opposite of what the timeout is for.
    """
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._clients[sess.sock.fileno()] = sess
    sess.last_activity = time.monotonic() - 60

    peer.close()  # nothing will drain; sends fail
    unit_gateway._queue_line(sess, "HB", {"TS": "2026-07-30T09:00:00.000Z"})
    unit_gateway._flush_client_writes()
    unit_gateway._drop_idle_clients()

    assert sess.sock.fileno() not in unit_gateway._clients


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


def test_sub_auction_wildcard_allowed(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._handle_client_line(sess, "SUB|CH=AUCTION|SYM=*")
    assert ("AUCTION", "*") in sess.subscriptions
    peer.close()


def test_sub_auction_no_snap(unit_gateway: MarketDataGateway) -> None:
    """AUCTION has no persistent current-state to snapshot, like TRADE."""
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._handle_client_line(sess, "SUB|CH=AUCTION|SYM=AAPL")
    assert ("AUCTION", "AAPL") in sess.subscriptions
    assert not sess.out_queue
    peer.close()


def test_sub_cb_wildcard_rejected(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._handle_client_line(sess, "SUB|CH=CB|SYM=*")
    frame = parse_line(sess.out_queue[0].decode("utf-8"))
    assert frame.fields["CODE"] == "INVALID_SYMBOL"
    assert ("CB", "*") not in sess.subscriptions
    peer.close()


def test_sub_cb_snap_active_with_no_history(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._handle_client_line(sess, "SUB|CH=CB|SYM=AAPL")
    assert ("CB", "AAPL") in sess.subscriptions
    snap = parse_line(sess.out_queue[0].decode("utf-8"))
    assert snap.msg_type == "SNAP"
    assert snap.fields["CH"] == "CB"
    assert snap.fields["STATUS"] == "ACTIVE"
    assert "LEVEL" not in snap.fields
    peer.close()


def test_sub_cb_snap_reflects_current_halt(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    unit_gateway._normaliser.normalise_cb_halt(
        "AAPL",
        {
            "trigger_price": 148.20,
            "reference_price": 150.10,
            "resume_at_ns": 1_784_560_800_000_000_000,
            "resumption_mode": "AUCTION",
            "level": "L2",
        },
    )
    unit_gateway._handle_client_line(sess, "SUB|CH=CB|SYM=AAPL")
    snap = parse_line(sess.out_queue[0].decode("utf-8"))
    assert snap.fields["STATUS"] == "HALTED"
    assert snap.fields["LEVEL"] == "L2"
    assert snap.fields["TRIGGERPX"] == "148.2"
    peer.close()


def test_welcome_ch_supported_includes_auction_and_cb(
    unit_gateway: MarketDataGateway,
) -> None:
    sess, peer = _make_session()
    unit_gateway._handle_client_line(sess, "HELLO|CLIENT=x|PROTO=CALF1")
    welcome = parse_line(sess.out_queue[0].decode("utf-8"))
    supported = welcome.fields["CH_SUPPORTED"].split(",")
    assert "AUCTION" in supported
    assert "CB" in supported
    peer.close()


def test_unsub_removes_pair(unit_gateway: MarketDataGateway) -> None:
    sess, peer = _make_session()
    sess.authenticated = True
    sess.subscriptions.add(("TOP", "AAPL"))
    unit_gateway._subs.set_for_client(sess.sock.fileno(), sess.subscriptions)
    unit_gateway._handle_client_line(sess, "UNSUB|CH=TOP|SYM=AAPL")
    assert ("TOP", "AAPL") not in sess.subscriptions
    peer.close()
