"""Tests for the reusable CALF client library.

The recovery rules are pure logic and are tested directly. The client
itself is exercised against a scripted stub gateway rather than the real
one, because the interesting cases -- a replay that overlaps live traffic,
a payload-less SNAP after REPLAY_MISS, a gateway that restarts and
renumbers -- are precisely the ones a healthy gateway will not produce on
demand.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest

from edumatcher.calf_client import (
    CalfClient,
    CalfClientOptions,
    CalfConnectionError,
    CalfProtocolMismatch,
    Gap,
    MarketState,
    ReferenceData,
    SequenceTracker,
    has_snapshot,
    is_resumable,
)
from edumatcher.md_gateway.protocol import parse_line

# ----------------------------------------------------------------------
# SequenceTracker: the three rules, in isolation
# ----------------------------------------------------------------------


def _observe(tracker: SequenceTracker, seq: int, msg_type: str = "TRADE") -> tuple:
    return tracker.observe(msg_type, "TRADE", "AAPL", seq)


def test_first_message_is_never_a_gap() -> None:
    tracker = SequenceTracker()
    tracker.new_connection()
    # Whatever SEQ it starts at: there is nothing yet for it to be a gap in.
    process, gap = _observe(tracker, 40)
    assert process is True
    assert gap is None


def test_consecutive_sequences_are_not_a_gap() -> None:
    tracker = SequenceTracker()
    tracker.new_connection()
    _observe(tracker, 1)
    process, gap = _observe(tracker, 2)
    assert (process, gap) == (True, None)


def test_gap_is_reported_with_its_range() -> None:
    tracker = SequenceTracker()
    tracker.new_connection()
    _observe(tracker, 1)
    process, gap = _observe(tracker, 4)

    assert process is True
    assert gap is not None
    assert (gap.first_seq, gap.last_seq, gap.count) == (2, 3, 2)


def test_replay_backfill_is_kept_and_duplicates_dropped() -> None:
    """The rule that makes RESUME usable at all.

    ``replay_since`` returns everything past LASTSEQ, and LASTSEQ is the
    position from before the gap -- so the reply mixes the messages that
    were missing with ones already delivered above them.
    """
    tracker = SequenceTracker()
    tracker.new_connection()
    _observe(tracker, 1)
    _observe(tracker, 4)  # hole 2..3, RESUME|LASTSEQ=1

    assert _observe(tracker, 2)[0] is True, "backfill must be kept"
    assert _observe(tracker, 3)[0] is True, "backfill must be kept"
    assert _observe(tracker, 4)[0] is False, "already delivered; must be dropped"
    assert tracker.position("TRADE", "AAPL") == 4, "baseline must not move back"
    assert _observe(tracker, 5)[1] is None, "next live message is not a phantom gap"


def test_snapshot_rebaselines_rather_than_reporting_a_gap() -> None:
    tracker = SequenceTracker()
    tracker.new_connection()
    tracker.observe("SNAP", "TOP", "AAPL", 1)
    # The SNAP answering a REPLAY_MISS lands far ahead. Gap-checking it
    # would ask to replay history it just superseded, and loop.
    process, gap = tracker.observe("SNAP", "TOP", "AAPL", 9001)
    assert (process, gap) == (True, None)
    assert tracker.position("TOP", "AAPL") == 9001


def test_backward_sequence_on_a_new_connection_is_a_restart() -> None:
    """A gateway's counters live in its process, not the connection.

    Reading this as a run of duplicates would black the stream out for as
    long as the new gateway lives.
    """
    tracker = SequenceTracker()
    tracker.new_connection()
    _observe(tracker, 5000)
    assert _observe(tracker, 1)[0] is False, "backward within one connection is a dupe"

    tracker.new_connection()
    assert _observe(tracker, 1)[0] is True, "backward across connections is a restart"
    assert _observe(tracker, 2)[0] is True


def test_unsequenced_message_passes_through_without_baselining() -> None:
    # Baselining at zero would make the next real SEQ a gap and send
    # RESUME|LASTSEQ=0, which the gateway rejects with BAD_MESSAGE rather
    # than REPLAY_MISS -- a hole nobody is told about.
    tracker = SequenceTracker()
    tracker.new_connection()
    assert _observe(tracker, 0)[0] is True
    assert tracker.position("TRADE", "AAPL") is None
    assert _observe(tracker, 7)[1] is None


def test_abandoned_hole_stops_absorbing_late_arrivals() -> None:
    tracker = SequenceTracker()
    tracker.new_connection()
    _observe(tracker, 1)
    _observe(tracker, 9)
    tracker.abandon_holes("TRADE", "AAPL")
    assert _observe(tracker, 5)[0] is False


def test_streams_are_tracked_independently() -> None:
    tracker = SequenceTracker()
    tracker.new_connection()
    tracker.observe("TRADE", "TRADE", "AAPL", 1)
    tracker.observe("TRADE", "TRADE", "MSFT", 1)
    assert tracker.observe("TRADE", "TRADE", "AAPL", 5)[1] is not None
    assert tracker.observe("TRADE", "TRADE", "MSFT", 2)[1] is None


def test_channel_classification() -> None:
    assert has_snapshot("TOP") and has_snapshot("CB")
    assert not has_snapshot("TRADE") and not has_snapshot("AUCTION")
    assert is_resumable("TRADE") and not is_resumable("TOP")


# ----------------------------------------------------------------------
# ReferenceData
# ----------------------------------------------------------------------


def test_reference_data_reads_ref_and_formats_per_symbol() -> None:
    ref = ReferenceData()
    assert ref.advertised is False
    ref.learn("AAPL:2,TSLA:4")

    assert ref.advertised is True
    assert ref.decimals("TSLA") == 4
    assert ref.format_price("TSLA", "250.5") == "250.5000"
    assert ref.format_price("AAPL", "150.1") == "150.10"


def test_reference_data_defaults_to_two_for_unknown_symbols() -> None:
    # The documented fallback, reached knowingly rather than by accident:
    # `advertised` is what tells the two apart.
    ref = ReferenceData()
    assert ref.decimals("NEWCO") == 2
    assert ref.format_price("NEWCO", "1.5") == "1.50"
    assert ref.format_price("NEWCO", None) == "-"


def test_reference_data_merges_and_tolerates_future_tuple_shapes() -> None:
    ref = ReferenceData()
    ref.learn("AAPL:2")
    ref.learn("TSLA:4")  # from the SYMBOLS reply, later
    # Contract multiplier and currency are a written proposal; a tuple that
    # grows must not cost this client the entries it can still read.
    ref.learn("MSFT:3:1:USD,NVDA:5")
    assert ref.decimals("AAPL") == 2
    assert ref.decimals("TSLA") == 4
    assert ref.decimals("NVDA") == 5


# ----------------------------------------------------------------------
# MarketState
# ----------------------------------------------------------------------


def _frame(line: str):
    return parse_line(line)


def test_top_of_book_merges_deltas_rather_than_replacing() -> None:
    """The reason this cache exists.

    An MD omits sides that did not move; treating one as a full replacement
    blanks whichever side was unchanged.
    """
    state = MarketState()
    state.apply(
        _frame(
            "SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=t|BID=150.10|BIDSZ=100|ASK=150.12|ASKSZ=50"
        )
    )
    state.apply(_frame("MD|CH=TOP|SYM=AAPL|SEQ=2|TS=t2|BID=150.11"))

    book = state.top("AAPL")
    assert book is not None
    assert book.bid == "150.11"
    assert book.ask == "150.12", "the untouched side must survive"
    assert book.ask_size == "50"


def test_session_state_is_separate_from_symbol_state() -> None:
    state = MarketState()
    state.apply(
        _frame(
            "STATE|CH=STATE|SYM=*|SEQ=1|TS=t|SESSION=CONTINUOUS|PREV=OPENING_AUCTION"
        )
    )
    state.apply(_frame("STATE|CH=STATE|SYM=AAPL|SEQ=1|TS=t|SESSION=HALTED"))

    # A symbol can be halted while the exchange is continuous; they are
    # different streams and must not overwrite each other.
    assert state.session == "CONTINUOUS"
    assert state.session_prev == "OPENING_AUCTION"
    assert state.symbol_session("AAPL") == "HALTED"


def test_depth_ladder_is_decoded_both_sides() -> None:
    state = MarketState()
    state.apply(
        _frame(
            "SNAP|CH=DEPTH|SYM=AAPL|SEQ=1|TS=t|LEVELS=2"
            "|BIDS=150.10:100:2,150.09:200:3|ASKS=150.12:50:1"
        )
    )
    book = state.depth("AAPL")
    assert book is not None
    assert [level.price for level in book.bids] == ["150.10", "150.09"]
    assert book.bids[1].orders == "3"
    assert len(book.asks) == 1


def test_payloadless_trade_snapshot_is_not_cached_as_a_print() -> None:
    # An older gateway answers a TRADE REPLAY_MISS with an envelope and no
    # payload. Caching it would record a print of nothing at no price.
    state = MarketState()
    state.apply(_frame("SNAP|CH=TRADE|SYM=AAPL|SEQ=9001|TS=t"))
    assert state.last_trade("AAPL") is None

    state.apply(
        _frame("TRADE|CH=TRADE|SYM=AAPL|SEQ=9002|TS=t|PX=150.10|QTY=100|SIDE=BUY")
    )
    assert state.last_trade("AAPL") is not None


def test_halt_status_carries_the_operational_detail() -> None:
    state = MarketState()
    state.apply(
        _frame(
            "CB|CH=CB|SYM=AAPL|SEQ=1|TS=t|STATUS=HALTED|LEVEL=L2"
            "|TRIGGERPX=148.20|REFPX=150.10|RESUMEAT=2026-07-20T15:20:00.000Z|SRC=CB"
        )
    )
    halt = state.halt("AAPL")
    assert halt is not None
    assert halt.halted is True
    assert halt.level == "L2"
    assert halt.resume_at == "2026-07-20T15:20:00.000Z"


# ----------------------------------------------------------------------
# CalfClient against a scripted stub gateway
# ----------------------------------------------------------------------


class StubGateway:
    """A minimal scriptable CALF server.

    Only enough to drive the client: it answers HELLO with a canned
    WELCOME, records what it receives, and sends whatever the test asks it
    to.
    """

    def __init__(self, welcome: str | None = None) -> None:
        self._welcome = welcome or (
            "WELCOME|PROTO=CALF1|GW=stub|HBINT=1|REPLAY=30"
            "|CH_SUPPORTED=TOP,TRADE,STATE,DEPTH,CB,AUCTION,INDEX"
            "|SYMBOLS=AAPL,TSLA|REF=AAPL:2,TSLA:4"
        )
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]
        self.received: list[str] = []
        self._conn: socket.socket | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        self._conn = conn
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
        self.received.append(buf.split(b"\n")[0].decode())
        conn.sendall(f"{self._welcome}\n".encode())
        self._ready.set()
        # Keep draining so the client's SUB/SYMBOLS/RESUME are recorded.
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            for line in chunk.decode().splitlines():
                if line:
                    self.received.append(line)

    def wait_ready(self, timeout: float = 2.0) -> None:
        assert self._ready.wait(timeout), "gateway never completed the handshake"

    def send(self, *lines: str) -> None:
        assert self._conn is not None
        self._conn.sendall("".join(f"{line}\n" for line in lines).encode())

    def sent_matching(self, prefix: str) -> list[str]:
        return [line for line in self.received if line.startswith(prefix)]

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
        try:
            self._srv.close()
        except OSError:
            pass


@pytest.fixture
def gateway() -> Iterator[StubGateway]:
    stub = StubGateway()
    yield stub
    stub.close()


def _client(stub: StubGateway, **overrides) -> CalfClient:
    options = CalfClientOptions(
        host="127.0.0.1",
        port=stub.port,
        symbols=["AAPL"],
        ping_interval_sec=0,
        reconnect=False,
        **overrides,
    )
    return CalfClient(options)


def _run_in_thread(client: CalfClient, **kwargs) -> threading.Thread:
    thread = threading.Thread(target=lambda: client.run(**kwargs), daemon=True)
    thread.start()
    return thread


def _wait_for(predicate, timeout: float = 2.0, label: str = "condition") -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {label}")


def test_client_handshakes_and_learns_reference_data(gateway: StubGateway) -> None:
    client = _client(gateway)
    frames: list = []
    thread = _run_in_thread(client, on_frame=frames.append)
    gateway.wait_ready()

    _wait_for(lambda: gateway.sent_matching("SUB"), label="the SUB")
    assert gateway.sent_matching("HELLO") == ["HELLO|CLIENT=calf-client|PROTO=CALF1"]
    # Asked for explicitly: WELCOME|SYMBOLS= is optional, so the SYMBOLS
    # reply is the reliable route to the universe and to REF.
    assert gateway.sent_matching("SYMBOLS")
    assert client.reference.decimals("TSLA") == 4
    assert client.supports("DEPTH") is True

    client.stop()
    gateway.close()
    thread.join(timeout=2)


def test_client_resumes_a_gap_and_drops_the_duplicates_replay_returns(
    gateway: StubGateway,
) -> None:
    client = _client(gateway)
    seen: list[int] = []

    def on_frame(frame) -> None:
        if frame.msg_type == "TRADE":
            seen.append(int(frame.fields["SEQ"]))

    thread = _run_in_thread(client, on_frame=on_frame)
    gateway.wait_ready()
    _wait_for(lambda: gateway.sent_matching("SUB"), label="the SUB")

    gateway.send("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=149.90|QTY=100|SIDE=BUY")
    _wait_for(lambda: seen == [1], label="the first print")

    # SEQ jumps 1 -> 4: two prints were missed.
    gateway.send("TRADE|CH=TRADE|SYM=AAPL|SEQ=4|TS=t4|PX=150.10|QTY=25|SIDE=BUY")
    _wait_for(
        lambda: gateway.sent_matching("RESUME|CH=TRADE|SYM=AAPL|LASTSEQ=1"),
        label="the RESUME",
    )

    # replay_since returns everything past LASTSEQ=1 -- including SEQ=4,
    # which was already delivered live.
    gateway.send(
        "TRADE|CH=TRADE|SYM=AAPL|SEQ=2|TS=t2|PX=150.00|QTY=50|SIDE=BUY",
        "TRADE|CH=TRADE|SYM=AAPL|SEQ=3|TS=t3|PX=150.05|QTY=75|SIDE=SELL",
        "TRADE|CH=TRADE|SYM=AAPL|SEQ=4|TS=t4|PX=150.10|QTY=25|SIDE=BUY",
    )
    _wait_for(lambda: len(seen) == 4, label="the backfill")
    time.sleep(0.05)  # let a duplicate arrive, if one is going to

    assert seen == [1, 4, 2, 3]
    assert len(set(seen)) == len(seen), "no print may be delivered twice"

    client.stop()
    gateway.close()
    thread.join(timeout=2)


def test_client_drops_the_payloadless_snapshot_after_a_trade_replay_miss(
    gateway: StubGateway,
) -> None:
    client = _client(gateway)
    trades: list = []
    gaps: list[Gap] = []

    def on_frame(frame) -> None:
        # ERR carries CH/SYM too, so channel alone is not enough to mean
        # "a message on the trade stream". A leaked payload-less SNAP
        # would still land here, which is the point of the test.
        if frame.fields.get("CH") == "TRADE" and frame.msg_type != "ERR":
            trades.append(frame)

    thread = _run_in_thread(client, on_frame=on_frame, on_gap=gaps.append)
    gateway.wait_ready()
    _wait_for(lambda: gateway.sent_matching("SUB"), label="the SUB")

    gateway.send("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=149.90|QTY=100|SIDE=BUY")
    _wait_for(lambda: len(trades) == 1, label="the first print")
    gateway.send("TRADE|CH=TRADE|SYM=AAPL|SEQ=9|TS=t9|PX=150.10|QTY=25|SIDE=BUY")
    _wait_for(lambda: gateway.sent_matching("RESUME"), label="the RESUME")

    # An older gateway answers with the ERR *and* a snapshot it cannot
    # fill. Decoded by CH it would read as a print of zero shares at zero.
    gateway.send(
        "ERR|CODE=REPLAY_MISS|CH=TRADE|SYM=AAPL",
        "SNAP|CH=TRADE|SYM=AAPL|SEQ=9001|TS=t",
    )
    _wait_for(lambda: gaps, label="the reported gap")
    time.sleep(0.05)

    assert [int(f.fields["SEQ"]) for f in trades] == [1, 9]
    assert all(f.msg_type == "TRADE" for f in trades)
    assert gaps[0].channel == "TRADE"

    client.stop()
    gateway.close()
    thread.join(timeout=2)


def test_client_tracks_state_so_callers_read_a_merged_book(
    gateway: StubGateway,
) -> None:
    client = _client(gateway)
    seen = threading.Event()

    def on_frame(frame) -> None:
        if frame.fields.get("SEQ") == "2":
            seen.set()

    thread = _run_in_thread(client, on_frame=on_frame)
    gateway.wait_ready()
    _wait_for(lambda: gateway.sent_matching("SUB"), label="the SUB")

    gateway.send(
        "SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=t|BID=150.10|BIDSZ=100|ASK=150.12|ASKSZ=50",
        "MD|CH=TOP|SYM=AAPL|SEQ=2|TS=t2|BID=150.11",
    )
    assert seen.wait(2), "never saw the delta"

    assert client.state is not None
    book = client.state.top("AAPL")
    assert book is not None
    assert (book.bid, book.ask) == ("150.11", "150.12")

    client.stop()
    gateway.close()
    thread.join(timeout=2)


def test_protocol_mismatch_is_not_retried() -> None:
    # Distinct from a connection error because reconnecting cannot help:
    # the client would speak the same wrong version again.
    stub = StubGateway(welcome="ERR|CODE=PROTO_MISMATCH|MSG=unsupported PROTO")
    try:
        client = CalfClient(
            CalfClientOptions(
                host="127.0.0.1", port=stub.port, ping_interval_sec=0, reconnect=True
            )
        )
        with pytest.raises(CalfProtocolMismatch):
            client.run(max_frames=1)
    finally:
        stub.close()


def test_connect_failure_without_reconnect_raises() -> None:
    # Port 1 is reserved and nothing listens there.
    client = CalfClient(
        CalfClientOptions(
            host="127.0.0.1",
            port=1,
            reconnect=False,
            ping_interval_sec=0,
            connect_timeout_sec=0.5,
        )
    )
    with pytest.raises(CalfConnectionError):
        client.run()


def test_passive_mode_neither_resumes_nor_hides_duplicates(
    gateway: StubGateway,
) -> None:
    """What a spy, a tap or a recorder needs.

    A diagnostic tool must show the wire as it is: injecting a RESUME or
    withholding a duplicate would misrepresent the feed it exists to reveal.
    """
    client = _client(gateway, auto_recover=False)
    seen: list[int] = []
    gaps: list[Gap] = []

    def on_frame(frame) -> None:
        if frame.msg_type == "TRADE":
            seen.append(int(frame.fields["SEQ"]))

    thread = _run_in_thread(client, on_frame=on_frame, on_gap=gaps.append)
    gateway.wait_ready()
    _wait_for(lambda: gateway.sent_matching("SUB"), label="the SUB")

    gateway.send(
        "TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=1|QTY=1|SIDE=BUY",
        "TRADE|CH=TRADE|SYM=AAPL|SEQ=4|TS=t4|PX=1|QTY=1|SIDE=BUY",
        "TRADE|CH=TRADE|SYM=AAPL|SEQ=4|TS=t4|PX=1|QTY=1|SIDE=BUY",
    )
    _wait_for(lambda: len(seen) == 3, label="all three lines")
    time.sleep(0.05)

    assert seen == [1, 4, 4], "the duplicate must reach the observer"
    assert gaps and gaps[0].first_seq == 2, "the gap is still reported"
    assert gateway.sent_matching("RESUME") == [], "nothing may be injected"

    client.stop()
    gateway.close()
    thread.join(timeout=2)
