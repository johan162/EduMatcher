"""Cost and wire tests for the bus wrappers (Messaging review 2026-11).

Cost is asserted by counting calls, not by timing, so the tests are
deterministic under coverage and parallel runs (see
``docs-design/reviews/EduMatcher-Messaging-Review-2026-11.md`` §4 P1).
"""

from __future__ import annotations

import os
import types
from typing import Any

import pytest

from edumatcher.messaging.bus import CausalPublisher, CausalPusher, SequencedPublisher
from edumatcher.models import envelope
from edumatcher.models.envelope import Envelope, new_ulid, ulid_millis
from tests.conftest import opened
from edumatcher.models.message import (
    decode_envelope,
    decode_publisher_sequence,
    decode_push_envelope,
    decode_sequence,
)


class FakeSock:
    """Records frames instead of sending them."""

    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> None:
        self.sent.append(frames)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Holds ``new_ulid``'s clock at a chosen nanosecond value, and restores
    the generator's state afterwards so later ids are not stuck in the
    future."""
    now = [0]
    fake = types.SimpleNamespace(time_ns=lambda: now[0], time=lambda: now[0] / 1e9)
    monkeypatch.setattr(envelope, "time", fake)
    for name in ("_last_ms", "_last_rand", "_last_prefix"):
        monkeypatch.setattr(envelope, name, getattr(envelope, name, ""), raising=False)
    monkeypatch.setattr(envelope, "_last_ms", -1)
    return now


class _Counter:
    def __init__(self, fn: Any) -> None:
        self.fn = fn
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return self.fn(*args, **kwargs)


def _reference(ms: int, rand: int) -> str:
    """The encoding before WP-MSG01: 26 Crockford base32 characters."""
    out = ""
    for value, length in ((ms, 10), (rand, 16)):
        chars = [""] * length
        for i in range(length - 1, -1, -1):
            chars[i] = envelope._B32[value & 0x1F]
            value >>= 5
        out += "".join(chars)
    return out


class TestUlidCost:
    def test_one_millisecond_draws_randomness_and_encodes_its_time_once(
        self, clock: list[int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock[0] = 1_763_200_000_123 * 1_000_000
        urandom = _Counter(os.urandom)
        encode = _Counter(envelope._encode_b32)
        monkeypatch.setattr(os, "urandom", urandom)
        monkeypatch.setattr(envelope, "_encode_b32", encode)

        ids = [new_ulid() for _ in range(10_000)]

        assert urandom.calls == 1
        assert encode.calls == 1  # the time prefix, not per id
        assert ids == sorted(ids) and len(set(ids)) == 10_000

    @pytest.mark.parametrize(
        ("ms", "rand"),
        [
            (0, 0),
            (1, 1),
            (1_763_200_000_123, 0x1234_5678_9ABC_DEF0_1234),
            (2**48 - 1, 2**80 - 1),
            (2**47, 2**79),
        ],
    )
    def test_encoding_is_unchanged(
        self,
        clock: list[int],
        monkeypatch: pytest.MonkeyPatch,
        ms: int,
        rand: int,
    ) -> None:
        clock[0] = ms * 1_000_000 + 999_999  # any instant inside that ms
        monkeypatch.setattr(os, "urandom", lambda n: rand.to_bytes(n, "big"))
        ulid = new_ulid()
        assert ulid == _reference(ms, rand)
        assert ulid_millis(ulid) == ms

    def test_the_randomness_steps_within_a_millisecond(
        self, clock: list[int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock[0] = 5_000_000
        monkeypatch.setattr(os, "urandom", lambda n: (41).to_bytes(n, "big"))
        assert [new_ulid() for _ in range(3)] == [
            _reference(5, 41),
            _reference(5, 42),
            _reference(5, 43),
        ]

    def test_a_clock_step_backwards_keeps_ids_increasing(
        self, clock: list[int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock[0] = 9_000 * 1_000_000
        monkeypatch.setattr(os, "urandom", lambda n: (7).to_bytes(n, "big"))
        first = new_ulid()
        clock[0] = 8_995 * 1_000_000  # NTP stepped the clock back 5 ms
        second = new_ulid()
        assert second > first
        assert second == _reference(9_000, 8)  # the old ms, the next step


class TestPublishBuildsNoEnvelopeObject:
    """The envelope frame is formatted from strings on the publish path; an
    ``Envelope`` object is only the reader's type."""

    @pytest.fixture
    def inits(self, monkeypatch: pytest.MonkeyPatch) -> _Counter:
        counter = _Counter(Envelope.__init__)

        def init(self: Envelope, *args: Any, **kwargs: Any) -> None:
            counter(self, *args, **kwargs)

        monkeypatch.setattr(Envelope, "__init__", init)
        return counter

    def test_publisher_with_a_cause(self, inits: _Counter) -> None:
        cause = Envelope(
            "01JR8Z7Q3K5N2X9V4B6C8D0E1F", None, "01JR8Z7Q3K5N2X9V4B6C8D0E1F"
        )
        inits.calls = 0
        pub = CausalPublisher(SequencedPublisher(FakeSock()))
        pub.set_cause(cause)
        pub.send_multipart([b"order.ack.GW1", b"{}"])
        pub.clear_cause()
        pub.send_multipart([b"book.AAPL", b"{}"])
        pub.begin_unit()
        pub.send_multipart([b"auction.result.AAPL", b"{}"])
        pub.send_multipart([b"trade.executed", b"{}"])
        pub.end_unit()
        assert inits.calls == 0

    def test_pusher(self, inits: _Counter) -> None:
        CausalPusher(FakeSock()).send_multipart([b"order.new", b"{}"])
        assert inits.calls == 0


class TestEnvelopeFrameIsUnchanged:
    def test_root_frame_reads_back_as_a_root(self) -> None:
        sock = FakeSock()
        CausalPusher(sock).send_multipart([b"order.new", b"{}"])
        env = decode_push_envelope(sock.sent[0])
        assert env is not None
        assert env.causation_id is None and env.correlation_id == env.msg_id

    def test_a_cause_without_a_chain_starts_the_chain_at_the_cause(self) -> None:
        """``Envelope.caused`` falls back to the cause's own id when it names
        no chain; the string path must do the same."""
        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.set_cause(Envelope("01JR8Z7Q3K5N2X9V4B6C8D0E1F"))
        pub.send_multipart([b"order.ack.GW1", b"{}"])
        env = decode_envelope(sock.sent[0])
        assert env is not None
        assert env.causation_id == "01JR8Z7Q3K5N2X9V4B6C8D0E1F"
        assert env.correlation_id == "01JR8Z7Q3K5N2X9V4B6C8D0E1F"


ULID_A = "01JR8Z7Q3K5N2X9V4B6C8D0E1F"


class TestOneTrailerFrame:
    """WP-MSG02: a published message is ``[topic, payload, trailer]`` with
    ``trailer = seq|eseq|msg_id|causation_id|correlation_id``; PUSH keeps
    ``[topic, payload, msg_id|causation_id|correlation_id]``."""

    def test_a_published_message_has_three_frames(self) -> None:
        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.send_multipart([b"trade.executed", b"{}"])
        (frames,) = sock.sent
        assert len(frames) == 3
        seq, eseq, msg_id, cause, chain = frames[2].split(b"|")
        assert (seq, eseq, cause) == (b"1", b"1", b"")
        assert chain == msg_id and len(msg_id) == 26

    def test_the_helpers_read_the_trailer(self) -> None:
        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.send_multipart([b"depth.AAPL", b"{}"])
        pub.set_cause(Envelope(ULID_A, None, ULID_A))
        pub.send_multipart([b"trade.executed", b"{}"])
        pub.send_multipart([b"trade.executed", b"{}"])
        frames = sock.sent[2]
        assert decode_sequence(frames) == 2
        assert decode_publisher_sequence(frames) == 3
        env = decode_envelope(frames)
        assert env is not None
        assert (env.causation_id, env.correlation_id) == (ULID_A, ULID_A)
        assert env.msg_id == frames[2].split(b"|")[2].decode()

    @pytest.mark.parametrize(
        "trailer",
        [b"", b"7", b"x|y|z", b"1|x|" + ULID_A.encode() + b"||", b"-1|2|", b"\xff"],
    )
    def test_a_trailer_that_is_not_one_reads_as_absent(self, trailer: bytes) -> None:
        frames = [b"t", b"{}", trailer]
        assert decode_sequence(frames) is None
        assert decode_publisher_sequence(frames) is None
        assert decode_envelope(frames) is None

    def test_two_frames_read_as_unsequenced(self) -> None:
        frames = [b"t", b"{}"]
        assert decode_sequence(frames) is None
        assert decode_publisher_sequence(frames) is None
        assert decode_envelope(frames) is None

    def test_a_sequenced_message_without_an_envelope_keeps_its_counters(
        self,
    ) -> None:
        sock = FakeSock()
        SequencedPublisher(sock).send_multipart([b"t", b"{}"])
        (frames,) = sock.sent
        assert frames[2] == b"1|1|"
        assert (decode_sequence(frames), decode_publisher_sequence(frames)) == (1, 1)
        assert decode_envelope(frames) is None

    def test_push_is_unchanged(self) -> None:
        sock = FakeSock()
        CausalPusher(sock).send_multipart([b"order.new", b"{}"])
        (frames,) = sock.sent
        assert len(frames) == 3 and frames[2].count(b"|") == 2
        assert decode_sequence(frames) is None
        assert decode_publisher_sequence(frames) is None
        env = decode_push_envelope(frames)
        assert env is not None and env.causation_id is None

    def test_the_echo_of_a_command_keeps_the_senders_id(self) -> None:
        push = FakeSock()
        CausalPusher(push).send_multipart([b"order.new", b'{"id":"O1"}'])
        received = push.sent[0]
        sent = decode_push_envelope(received)
        assert sent is not None

        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.send_multipart([b"book.AAPL", b"{}"])
        pub.send_with_envelope(received[:2], received[2])
        echoed = sock.sent[1]
        assert len(echoed) == 3 and echoed[:2] == received[:2]
        assert (decode_sequence(echoed), decode_publisher_sequence(echoed)) == (1, 2)
        assert decode_envelope(echoed) == sent

    def test_an_echoed_frame_that_is_no_envelope_keeps_the_counters(self) -> None:
        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.send_with_envelope([b"order.new", b"{}"], b"not-an-envelope")
        (frames,) = sock.sent
        assert (decode_sequence(frames), decode_publisher_sequence(frames)) == (1, 1)
        assert decode_envelope(frames) is None

    def test_the_audit_annotation_is_unchanged(self) -> None:
        from edumatcher.audit.main import _meta_section

        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.set_cause(Envelope(ULID_A, None, ULID_A))
        pub.send_multipart([b"order.ack.GW1", b"{}"])
        msg_id = decode_envelope(sock.sent[0]).msg_id  # type: ignore[union-attr]
        assert _meta_section(sock.sent[0]) == (
            f"seq=1 eseq=1 msg={msg_id} cause={ULID_A} chain={ULID_A}"
        )


class _FlagOr:
    """Counts pyzmq ``Flag`` arithmetic (``SNDMORE | flags``)."""

    calls = 0


@pytest.fixture
def flag_or(monkeypatch: pytest.MonkeyPatch) -> _FlagOr:
    # ``enum`` copies ``__or__`` into every Flag subclass, so it is patched on
    # pyzmq's own class, not on ``enum.Flag``.
    import zmq

    flag = type(zmq.SNDMORE)
    original = flag.__or__
    counter = _FlagOr()

    def counting_or(self: Any, other: Any) -> Any:
        counter.calls += 1
        return original(self, other)

    monkeypatch.setattr(flag, "__or__", counting_or)
    return counter


class TestSendDoesNoFlagArithmetic:
    """Engine latency review 2026-11, P1: pyzmq's ``send_multipart`` ORs an
    ``IntFlag`` per frame, which costs more than the send itself on 3.14."""

    def test_publisher(self, flag_or: _FlagOr) -> None:
        import uuid

        import zmq

        from edumatcher.messaging.bus import make_publisher

        addr = f"inproc://lat01-pub-{uuid.uuid4().hex}"
        pub = opened(make_publisher(addr))
        sub: zmq.Socket[bytes] = opened(zmq.Context.instance().socket(zmq.SUB))
        sub.connect(addr)
        sub.setsockopt(zmq.SUBSCRIBE, b"")
        received: list[bytes] = []
        for _ in range(200):  # until the subscription has reached the PUB
            pub.send_multipart([b"order.ack.GW1", b"{}"])
            if sub.poll(10):
                received = sub.recv_multipart()
                break
        assert flag_or.calls == 0
        assert received[:2] == [b"order.ack.GW1", b"{}"]
        assert decode_envelope(received) is not None

    def test_pusher_keeps_frames_and_flags(self, flag_or: _FlagOr) -> None:
        import uuid

        import zmq

        from edumatcher.messaging.bus import make_puller, make_pusher

        addr = f"inproc://lat01-push-{uuid.uuid4().hex}"
        pull = opened(make_puller(addr))
        push = opened(make_pusher(addr))
        push.send_multipart([b"order.new", b"{}"], zmq.NOBLOCK)
        assert pull.poll(1000)
        received = pull.recv_multipart()
        assert flag_or.calls == 0
        assert received[:2] == [b"order.new", b"{}"]
        assert decode_push_envelope(received) is not None

    def test_drop_copy(self, flag_or: _FlagOr) -> None:
        import uuid

        import zmq

        from edumatcher.engine.drop_copy import DropCopyPublisher

        dc = opened(
            DropCopyPublisher(
                zmq.Context.instance(), f"inproc://lat01-dc-{uuid.uuid4().hex}"
            )
        )
        dc.publish_fill(
            "GW1",
            order_id="o1",
            trade_ids=["t1"],
            symbol="AAPL",
            fill_qty=1,
            fill_price=1.0,
            liquidity_flag="MAKER",
        )
        assert flag_or.calls == 0
