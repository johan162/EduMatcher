from __future__ import annotations

import socket
from collections.abc import Generator

import pytest

from edumatcher.md_gateway.client_session import ClientSession
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway.gateway import MarketDataGateway
from edumatcher.md_gateway.normaliser import EngineNormaliser
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
            "next_state": "CLOSING_AUCTION",
            "next_at": "2026-07-30T16:25:00.000Z",
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
            "next_state": "CLOSING_AUCTION",
            "next_at": "2026-07-30T16:25:00.000Z",
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
            "next_state": "CLOSING_AUCTION",
            "next_at": "2026-07-30T16:25:00.000Z",
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
            "next_state": "CLOSING_AUCTION",
            "next_at": "2026-07-30T16:25:00.000Z",
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
