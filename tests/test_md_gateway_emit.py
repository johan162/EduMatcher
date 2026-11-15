from __future__ import annotations

import socket
from collections.abc import Generator

import pytest

from edumatcher.md_gateway.client_session import ClientSession
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway.gateway import MarketDataGateway
from edumatcher.md_gateway.normaliser import EngineNormaliser
from edumatcher.md_gateway.protocol import parse_line
from tests.conftest import free_ports


@pytest.fixture()
def unit_gateway() -> Generator[MarketDataGateway, None, None]:
    gateway_port, engine_pub_port = free_ports(2)
    cfg = MarketDataGatewayConfig(
        bind_address="127.0.0.1",
        port=gateway_port,
        engine_pub_addr=f"tcp://127.0.0.1:{engine_pub_port}",
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


# ---------------------------------------------------------------------------
# T-M6: next scheduled transition on STATE
# ---------------------------------------------------------------------------


def test_state_carries_the_next_scheduled_transition() -> None:
    """A countdown needs a target, and only the feed can supply one."""
    norm = EngineNormaliser()
    sym, fields = norm.normalise_session_state(
        {
            "state": "CONTINUOUS",
            "prev_state": "OPENING_AUCTION",
            "next": {"state": "CLOSING_AUCTION", "at": "2026-07-30T16:25:00.000Z"},
        }
    )

    assert sym == "*"
    assert fields["NEXTPHASE"] == "CLOSING_AUCTION"
    assert fields["NEXTAT"] == "2026-07-30T16:25:00.000Z"


def test_state_omits_the_transition_when_none_is_scheduled() -> None:
    """Absent means "nothing scheduled", which a client renders as silence.

    Emitting a half-pair would be worse than emitting nothing: a phase with
    no time cannot be counted down to, and a time with no phase does not say
    what happens when it arrives.
    """
    norm = EngineNormaliser()
    _, fields = norm.normalise_session_state({"state": "CONTINUOUS"})

    assert "NEXTPHASE" not in fields
    assert "NEXTAT" not in fields


def test_a_transition_without_a_timetable_clears_the_previous_one() -> None:
    """The clearing is the signal, not an omission.

    A manual or admin-driven transition moves the engine somewhere the
    schedule did not predict. Keeping the old target would count a terminal
    down to a transition nobody is going to perform.
    """
    norm = EngineNormaliser()
    norm.normalise_session_state(
        {
            "state": "CONTINUOUS",
            "next": {"state": "CLOSING_AUCTION", "at": "2026-07-30T16:25:00.000Z"},
        }
    )
    _, fields = norm.normalise_session_state({"state": "CLOSED"})

    assert "NEXTPHASE" not in fields
    assert norm.state_snapshot_fields("*").get("NEXTAT") is None


def test_snapshot_carries_the_transition_for_a_client_joining_mid_session() -> None:
    # Otherwise a terminal opened at 10:00 shows no countdown until the next
    # transition actually fires -- which is hours away, and is exactly when a
    # countdown is most useful.
    norm = EngineNormaliser()
    norm.normalise_session_state(
        {
            "state": "CONTINUOUS",
            "next": {"state": "CLOSING_AUCTION", "at": "2026-07-30T16:25:00.000Z"},
        }
    )

    snap = norm.state_snapshot_fields("*")
    assert snap["NEXTPHASE"] == "CLOSING_AUCTION"
    assert snap["NEXTAT"] == "2026-07-30T16:25:00.000Z"


def test_per_symbol_state_carries_no_timetable() -> None:
    # A per-symbol STATE says whether that instrument is halted, which has
    # nothing to do with the session clock.
    norm = EngineNormaliser()
    norm.normalise_session_state(
        {
            "state": "CONTINUOUS",
            "next": {"state": "CLOSING_AUCTION", "at": "2026-07-30T16:25:00.000Z"},
        }
    )

    assert "NEXTAT" not in norm.state_snapshot_fields("AAPL")


# ---------------------------------------------------------------------------
# T-M1: indicative uncross during a call phase
# ---------------------------------------------------------------------------


def test_indicative_carries_price_size_and_imbalance() -> None:
    norm = EngineNormaliser()
    sym, fields = norm.normalise_auction_indicative(
        {
            "symbol": "aapl",
            "phase": "OPENING_AUCTION",
            "eq_price": 150.10,
            "eq_qty": 48200,
            "imbalance_side": "buy",
            "imbalance_qty": 1400,
        }
    )

    assert sym == "AAPL"
    # Decimal text without padding, the same as EQPX on an uncross. Display
    # precision is the client's job, from REF= — which is precisely why that
    # field exists.
    assert fields["INDICPX"] == "150.1"
    assert fields["INDICQTY"] == "48200"
    assert fields["IMB"] == "BUY"
    assert fields["IMBQTY"] == "1400"
    assert fields["PHASE"] == "OPENING_AUCTION"


def test_indicative_omits_the_price_when_the_book_would_not_cross() -> None:
    """A reading, not a gap.

    The bids and offers collected so far do not overlap, so nothing would
    trade if the phase ended now. Emitting `INDICPX=0` would assert a
    clearing level the book does not have.
    """
    _, fields = norm_fields_no_cross()

    assert "INDICPX" not in fields
    # Zero is a true reading for both of these, so they are always present.
    assert fields["INDICQTY"] == "0"
    assert fields["IMBQTY"] == "0"


def norm_fields_no_cross() -> tuple[str, dict[str, str]]:
    return EngineNormaliser().normalise_auction_indicative(
        {
            "symbol": "TSLA",
            "phase": "CLOSING_AUCTION",
            "eq_price": None,
            "eq_qty": 0,
            "imbalance_side": "",
            "imbalance_qty": 0,
        }
    )


def test_indicative_omits_the_side_when_balanced() -> None:
    # Balanced is what an auction converges toward. It reads as the absence
    # of an imbalance rather than as a zero-sized one.
    _, fields = EngineNormaliser().normalise_auction_indicative(
        {"symbol": "AAPL", "eq_price": 150.0, "eq_qty": 900, "imbalance_qty": 0}
    )

    assert "IMB" not in fields
    assert fields["IMBQTY"] == "0"


def test_session_is_unknown_until_the_engine_says_otherwise() -> None:
    # A CONTINUOUS default told every client a closed exchange was trading.
    assert EngineNormaliser().state_snapshot_fields("*") == {"SESSION": "UNKNOWN"}


def test_next_transition_survives_the_real_engine_encoding() -> None:
    """The engine nests the next transition; reading flat keys lost it."""
    from edumatcher.models.message import decode, make_session_state_msg

    _, payload = decode(
        make_session_state_msg(
            "CONTINUOUS",
            "OPENING_AUCTION",
            "CLOSING_AUCTION",
            "2026-07-30T16:25:00.000Z",
        )
    )
    _, fields = EngineNormaliser().normalise_session_state(payload)

    assert fields["NEXTPHASE"] == "CLOSING_AUCTION"
    assert fields["NEXTAT"] == "2026-07-30T16:25:00.000Z"


def test_a_status_answer_replaces_the_timetable() -> None:
    """The answer carries what the engine holds now, so it wins wholesale."""
    norm = EngineNormaliser()
    norm.normalise_session_state(
        {
            "state": "CONTINUOUS",
            "next": {"state": "CLOSING_AUCTION", "at": "2026-07-30T16:25:00.000Z"},
        }
    )

    assert norm.apply_session_status({"state": "CLOSED"}) == (
        "*",
        {"SESSION": "CLOSED"},
    )
    assert norm.state_snapshot_fields("*") == {"SESSION": "CLOSED"}


def test_an_unchanged_status_answer_is_not_an_event() -> None:
    norm = EngineNormaliser()
    status = {
        "state": "CLOSED",
        "next": {"state": "PRE_OPEN", "at": "2026-07-31T07:00:00.000Z"},
    }

    assert norm.apply_session_status(status) is not None
    assert norm.apply_session_status(status) is None


def test_a_status_answer_with_only_a_new_target_reaches_clients() -> None:
    """How an announced open, with no transition to carry it, gets out."""
    norm = EngineNormaliser()
    norm.apply_session_status({"state": "CLOSED"})
    prior = norm.prior_session_state

    change = norm.apply_session_status(
        {
            "state": "CLOSED",
            "next": {"state": "PRE_OPEN", "at": "2026-07-31T07:00:00.000Z"},
        }
    )

    assert change == (
        "*",
        {
            "SESSION": "CLOSED",
            "NEXTPHASE": "PRE_OPEN",
            "NEXTAT": "2026-07-31T07:00:00.000Z",
        },
    )
    assert norm.prior_session_state == prior
    assert norm.state_snapshot_fields("*")["NEXTPHASE"] == "PRE_OPEN"


# ---------------------------------------------------------------------------
# WP-MDG04: fan-out cost depends on who wants an event
# ---------------------------------------------------------------------------


def _subscribed(
    gw: MarketDataGateway, pairs: set[tuple[str, str]]
) -> tuple[ClientSession, socket.socket]:
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    session = ClientSession(sock=left, addr=("local", 0), authenticated=True)
    session.subscriptions = set(pairs)
    gw._clients[left.fileno()] = session
    gw._subs.set_for_client(left.fileno(), session.subscriptions)
    return session, right


def _trade(gw: MarketDataGateway, sym: str, n: int) -> None:
    gw._emit_stream_event(
        "TRADE", "TRADE", sym, {"TRADE_ID": f"t{n}", "PX": "1", "QTY": "1"}, 0.0
    )


def test_wildcard_and_exact_subscription_deliver_an_event_once(
    unit_gateway: MarketDataGateway,
) -> None:
    session, peer = _subscribed(unit_gateway, {("TRADE", "*"), ("TRADE", "AAPL")})
    _trade(unit_gateway, "AAPL", 1)
    assert len(session.out_queue) == 1
    peer.close()


def test_unsub_and_disconnect_stop_delivery(unit_gateway: MarketDataGateway) -> None:
    unsubbed, peer1 = _subscribed(unit_gateway, {("TRADE", "AAPL")})
    gone, peer2 = _subscribed(unit_gateway, {("TRADE", "*")})
    unit_gateway._handle_unsub(unsubbed, {"CH": "TRADE", "SYM": "AAPL"})
    gone_fd = gone.sock.fileno()
    unit_gateway._disconnect(gone, reason="peer_closed")
    _trade(unit_gateway, "AAPL", 1)
    assert not unsubbed.out_queue
    assert unit_gateway._subs.wanting("TRADE", "AAPL") == set()
    assert gone_fd not in unit_gateway._subs.wanting("TRADE", "MSFT")
    peer1.close()
    peer2.close()


def test_an_event_visits_only_the_sessions_that_want_it(
    unit_gateway: MarketDataGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1: 64 sessions x 600 pairs used to be scanned whole for every event."""
    symbols = [f"S{i:03d}" for i in range(300)]
    peers = []
    for i in range(64):
        pairs = {
            (ch, symbols[(i * 7 + k) % 300])
            for k in range(200)
            for ch in ("TOP", "TRADE", "DEPTH")
        }
        peers.append(_subscribed(unit_gateway, pairs)[1])
    wanted = {
        fd
        for fd, s in unit_gateway._clients.items()
        if ("TRADE", "S000") in s.subscriptions
    }
    visited: list[int] = []
    real = unit_gateway._queue_raw

    def counting(session: ClientSession, payload: bytes, **kw: bool) -> None:
        visited.append(session.sock.fileno())
        real(session, payload, **kw)

    calls = {"n": 0}
    real_wants = unit_gateway._subs.session_wants

    def counting_wants(fd: int, ch: str, sym: str) -> bool:
        calls["n"] += 1
        return real_wants(fd, ch, sym)

    monkeypatch.setattr(unit_gateway, "_queue_raw", counting)
    monkeypatch.setattr(unit_gateway._subs, "session_wants", counting_wants)
    _trade(unit_gateway, "S000", 1)

    assert sorted(visited) == sorted(wanted) and 0 < len(wanted) < 64
    assert calls["n"] <= len(wanted)
    for peer in peers:
        peer.close()
