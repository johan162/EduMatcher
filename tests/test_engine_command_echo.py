"""The engine re-publishes inbound commands so the audit trail contains them.

`pm-audit` subscribes to the engine's PUB socket and nothing else, and ZMQ
PUSH/PULL cannot be tapped, so before this every command the exchange was asked
to perform was absent from its own audit trail: each effect cited a
`causation_id` naming a message recorded nowhere, and a command that produced no
effect at all left no trace.

What these tests pin is not that a message goes out -- it is that the copy keeps
the *sender's* identity. A re-published command that minted a fresh id would be
its own cause, would match no effect's `causation_id`, and would sort after the
events it triggered.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.engine_harness import FakeSock, connect, make_engine, order_payload
from edumatcher.messaging.bus import CausalPublisher, CausalPusher, SequencedPublisher
from edumatcher.models.message import decode, decode_envelope, decode_push_envelope
from edumatcher.models.order import OrderType, Side


@pytest.fixture
def engine_and_sock(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine, "GW01", "GW02")
    return engine, pub


def submission(topic: bytes, payload: bytes = b'{"id":"O1"}') -> list[bytes]:
    """The frames a gateway's CausalPusher actually puts on the wire."""
    push = FakeSock()
    CausalPusher(push).send_multipart([topic, payload])
    return push.sent[0]


class TestSendWithEnvelope:
    def test_the_senders_envelope_is_preserved_verbatim(self) -> None:
        frames = submission(b"order.new")
        original = decode_push_envelope(frames)
        assert original is not None

        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.send_with_envelope(frames[:2], frames[2])

        echoed = decode_envelope(sock.sent[0])
        assert echoed == original

    def test_a_re_published_command_is_not_its_own_cause(self) -> None:
        """What send_multipart would have done here, and why it is wrong."""
        frames = submission(b"order.new")
        original = decode_push_envelope(frames)
        assert original is not None

        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.set_cause(original)
        pub.send_multipart(frames[:2])
        wrong = decode_envelope(sock.sent[0])
        assert wrong is not None
        assert wrong.causation_id == original.msg_id  # the command caused itself
        assert wrong.msg_id != original.msg_id

        sock2 = FakeSock()
        right = CausalPublisher(SequencedPublisher(sock2))
        right.set_cause(original)
        right.send_with_envelope(frames[:2], frames[2])
        kept = decode_envelope(sock2.sent[0])
        assert kept is not None
        assert kept.msg_id == original.msg_id
        assert kept.causation_id is None

    def test_the_sequence_frame_still_lands_at_index_two(self) -> None:
        """The wire shape pm-audit parses must not change."""
        from edumatcher.models.message import decode_sequence

        frames = submission(b"order.new")
        sock = FakeSock()
        CausalPublisher(SequencedPublisher(sock)).send_with_envelope(
            frames[:2], frames[2]
        )
        assert decode_sequence(sock.sent[0]) == 1
        assert decode_envelope(sock.sent[0]) is not None


class TestEngineEchoesCommands:
    def test_a_submitted_order_appears_in_the_published_stream(
        self, engine_and_sock: Any
    ) -> None:
        engine, pub = engine_and_sock
        frames = submission(b"order.new")
        engine._echo_command("order.new", frames)

        topics = [decode(f)[0] for f in pub.sent]
        assert "order.new" in topics

    def test_the_echo_is_what_every_effect_already_cites(
        self, engine_and_sock: Any
    ) -> None:
        """The point of the whole exercise: the chain root stops dangling.

        Driven through a real ``CausalPublisher`` rather than the harness's
        socket double, because what is under test here is the envelope the
        double deliberately does not stamp.
        """
        import orjson

        engine, _ = engine_and_sock
        sock = FakeSock()
        engine.pub_sock = CausalPublisher(SequencedPublisher(sock))

        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        frames = submission(b"order.new", orjson.dumps(payload))
        cause = decode_push_envelope(frames)
        assert cause is not None

        engine.pub_sock.set_cause(cause)
        try:
            engine._handle_new_order(payload)
        finally:
            engine.pub_sock.clear_cause()
            engine._echo_command("order.new", frames)

        recorded: dict[str, Any] = {}
        for f in sock.sent:
            topic, _ = decode(f)
            env = decode_envelope(f)
            if env is not None:
                recorded.setdefault(topic, env)

        assert recorded["order.new"].msg_id == cause.msg_id
        assert recorded["order.new"].causation_id is None
        assert recorded["order.ack.GW01"].causation_id == cause.msg_id
        assert recorded["order.ack.GW01"].correlation_id == cause.msg_id

    def test_a_query_request_is_not_echoed(self, engine_and_sock: Any) -> None:
        """A read is not a decision the exchange made, and the GUIs poll them."""
        engine, pub = engine_and_sock
        before = len(pub.sent)
        engine._echo_command(
            "book.snapshot_request", submission(b"book.snapshot_request")
        )
        assert len(pub.sent) == before

    def test_a_command_with_no_envelope_is_skipped(self, engine_and_sock: Any) -> None:
        """A client that built its own PUSH socket has no id to preserve, and
        minting one would invent a causal root that nothing cites."""
        engine, pub = engine_and_sock
        before = len(pub.sent)
        engine._echo_command("order.new", [b"order.new", b'{"id":"O1"}'])
        assert len(pub.sent) == before

    def test_a_transport_failure_cannot_stop_the_exchange(
        self, engine_and_sock: Any
    ) -> None:
        """It runs in a `finally`; a raise there would replace the exception in
        flight and end the receive loop. Recording must never do that."""
        engine, _pub = engine_and_sock

        class Exploding:
            def send_with_envelope(self, frames: Any, envelope_frame: Any) -> None:
                raise RuntimeError("socket is gone")

        engine.pub_sock = Exploding()
        engine._echo_command("order.new", submission(b"order.new"))


class TestEchoOrdersBeforeItsEffects:
    def test_file_order_and_id_order_agree(
        self, engine_and_sock: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reason the echo runs before dispatch rather than after it.

        Either placement narrates correctly, because the sender's ULID was
        minted before every effect and pm-audit-replay orders by that. Only
        this one also puts the command first in the *bytes*, which is what
        anyone reading the log with grep or `pm-audit-cli timeline` sees.
        """
        import orjson

        engine, _ = engine_and_sock
        sock = FakeSock()
        engine.pub_sock = CausalPublisher(SequencedPublisher(sock))

        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        frames = submission(b"order.new", orjson.dumps(payload))

        engine._echo_command("order.new", frames)
        engine.pub_sock.set_cause(decode_push_envelope(frames))
        engine._handle_new_order(payload)
        engine.pub_sock.clear_cause()

        published = [(decode(f)[0], decode_envelope(f)) for f in sock.sent]
        topics = [t for t, _ in published]
        ids = [e.msg_id for _, e in published if e is not None]

        assert topics[0] == "order.new"
        assert "order.ack.GW01" in topics
        assert ids == sorted(ids), "mint order and file order must not disagree"

    def test_a_later_echo_would_still_have_sorted_correctly(self) -> None:
        """The property that made the placement a free choice in the first
        place, kept because the replay tool's ordering rests on it."""
        import time

        frames = submission(b"order.new")
        cause = decode_push_envelope(frames)
        assert cause is not None
        time.sleep(0.005)

        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.set_cause(cause)
        pub.send_multipart([b"order.ack.GW01", b"{}"])
        pub.clear_cause()
        pub.send_with_envelope(frames[:2], frames[2])

        ack_env = decode_envelope(sock.sent[0])
        echo_env = decode_envelope(sock.sent[1])
        assert ack_env is not None and echo_env is not None
        assert echo_env.msg_id < ack_env.msg_id


def _real_publisher(engine: Any) -> FakeSock:
    """Swap in the publisher that actually stamps envelopes.

    The harness's socket double has a no-op ``set_cause`` and stamps nothing,
    which is exactly the frame these tests read.
    """
    sock = FakeSock()
    engine.pub_sock = CausalPublisher(SequencedPublisher(sock))
    return sock


class TestTheReceiveLoopCallsIt:
    """The method above is tested; this is about its one call site.

    A feature wired nowhere fails silently, and for a recorder that is the
    worst failure mode there is: the trail simply lacks the commands and
    nothing says so. So this drives the real ``run()`` loop rather than
    calling ``_echo_command`` directly.
    """

    @staticmethod
    def _drive(engine: Any, frames: list[bytes], monkeypatch: Any) -> None:
        """Run exactly one iteration of the receive loop, then stop."""
        import edumatcher.engine.main as em

        delivered = iter([frames])

        class OneShotPuller:
            """Plain class, not FakeSock: the poller keys a dict on the socket
            and a dataclass with a list field is unhashable."""

            def recv_multipart(self) -> list[bytes]:
                return next(delivered)

            def close(self) -> None:
                pass

        class OneShotPoller:
            def __init__(self) -> None:
                self._first = True

            def register(self, *_a: Any, **_k: Any) -> None:
                pass

            def poll(self, timeout: int | None = None) -> dict[Any, int]:
                if self._first:
                    self._first = False
                    return {engine.pull_sock: 1}
                engine._running = False
                return {}

        engine.pull_sock = OneShotPuller()
        # Dotted string form, as test_perf.py uses: `em.zmq` is an attribute
        # access mypy rejects under strict mode, because engine.main does not
        # re-export the module it imported.
        monkeypatch.setattr("edumatcher.engine.main.zmq.Poller", OneShotPoller)
        monkeypatch.setattr(em, "DropCopyPublisher", lambda *a, **k: None)
        # run() sets the run sequence, and make_engine already did; resetting
        # keeps that call from raising "run sequence already set".
        from edumatcher.models.trade import reset_trade_ids_for_tests

        reset_trade_ids_for_tests()
        monkeypatch.setattr(em, "load_and_bump_run_seq", lambda _: 1)
        monkeypatch.setattr(engine, "_restore_gtc", lambda: None)
        monkeypatch.setattr(engine, "_load_config", lambda: None)
        monkeypatch.setattr(engine, "_shutdown", lambda: None)
        engine.run()

    def test_a_command_off_the_wire_reaches_the_published_stream(
        self, engine_and_sock: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import orjson

        engine, pub = engine_and_sock
        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        frames = submission(b"order.new", orjson.dumps(payload))

        self._drive(engine, frames, monkeypatch)

        topics = [decode(f)[0] for f in pub.sent]
        assert "order.new" in topics
        assert "order.ack.GW01" in topics

    def test_it_still_records_when_the_handler_blows_up(
        self, engine_and_sock: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It sits in a `finally` for this: the command you most want recorded
        is the one whose handling went wrong."""
        engine, pub = engine_and_sock

        def explode(_payload: Any) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(engine, "_handle_new_order", explode)
        self._drive(engine, submission(b"order.new"), monkeypatch)

        assert "order.new" in [decode(f)[0] for f in pub.sent]

    def test_a_reply_to_a_query_cites_nothing(
        self, engine_and_sock: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If you do not echo the cause, you may not cite it.

        A query is left out of the echo on purpose (the GUIs poll them), so
        its id is in no trail. Attributing the reply to it anyway made the
        snapshot an orphan citing a message that was never published, which
        ``pm-audit-replay`` can only report as ``CAUSE_NOT_FOUND`` -- it
        cannot tell a cause the engine withheld from one that was dropped.
        """
        import orjson

        engine, _ = engine_and_sock
        sock = _real_publisher(engine)
        engine._book("AAPL")
        frames = submission(b"book.snapshot_request", orjson.dumps({"symbol": "AAPL"}))

        self._drive(engine, frames, monkeypatch)

        books = [f for f in sock.sent if decode(f)[0] == "book.AAPL"]
        assert books, "precondition: the request produced a snapshot"
        env = decode_envelope(books[-1])
        assert env is not None and env.causation_id is None

    def test_a_reply_to_a_command_still_cites_it(
        self, engine_and_sock: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exemption is for reads only."""
        import orjson

        engine, _ = engine_and_sock
        sock = _real_publisher(engine)
        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        frames = submission(b"order.new", orjson.dumps(payload))

        self._drive(engine, frames, monkeypatch)

        envs = {decode(f)[0]: decode_envelope(f) for f in sock.sent}
        ack, new = envs["order.ack.GW01"], envs["order.new"]
        assert ack is not None and new is not None
        assert ack.causation_id == new.msg_id


@pytest.mark.perf
class TestTheEchoStaysCheap:
    """A guard on the echo's cost, as a *ratio* to an ordinary publish.

    The echo is on the path to every ack, so it earns a bound. An absolute one
    would be a machine reading and would flake; the ratio is not, because both
    sides do the same Python work except for the part under test.

    Two regressions it catches, and both matter for more than speed:
    re-minting the envelope makes the recorded command its own cause and
    breaks the link every effect cites; re-encoding the payload would mean the
    recorded bytes are no longer the bytes that arrived.

    Modelled on test_msgen_trade_perf.py: best-of-three against a baseline
    measured in the same run.
    """

    #: The socket is a no-op on both sides, so what is compared is the
    #: publisher wrapper's own work and nothing else -- which is precisely
    #: where the two regressions live. Measured at 0.13 (stable to +/-0.01
    #: across runs); a re-minting echo would be ~1.0, so 0.5 is a wide margin
    #: for a noisy runner and still an unmissable gap.
    #:
    #: Against a *real* PUB socket the ratio is ~0.56 rather than ~0.13,
    #: because the syscall both sides pay then dominates. That is the number
    #: to quote for "what the echo costs in production"; this is the number
    #: that detects a change in it.
    _MAX_RATIO = 0.5

    _ITERATIONS = 20_000

    @classmethod
    def _best_of_three(cls, fn: Any) -> float:
        """Fastest of three. A slow run means the machine was busy, which says
        nothing about the code."""
        import timeit

        n = cls._ITERATIONS
        return min(timeit.repeat(fn, repeat=3, number=n)) / n * 1e6

    def test_the_echo_costs_less_than_an_ordinary_publish(self) -> None:
        import orjson

        class Drain:
            def send_multipart(self, frames: list[bytes]) -> None:
                pass

        payload = orjson.dumps({"id": "O1", "symbol": "AAPL", "price": 7569})
        frames = submission(b"order.new", payload)
        pub = CausalPublisher(SequencedPublisher(Drain()))
        pub.set_cause(decode_push_envelope(frames))

        ordinary = self._best_of_three(
            lambda: pub.send_multipart([b"order.ack.GW01", payload])
        )
        echo = self._best_of_three(
            lambda: pub.send_with_envelope(frames[:2], frames[2])
        )
        ratio = echo / ordinary
        assert ratio < self._MAX_RATIO, (
            f"the command echo costs {ratio:.2f} of an ordinary publish "
            f"({echo:.2f} us vs {ordinary:.2f} us), over the "
            f"{self._MAX_RATIO} budget. If it is minting an envelope again, "
            "the recorded command is also its own cause -- see "
            "CausalPublisher.send_with_envelope."
        )

    def test_the_two_sides_publish_the_same_payload(self) -> None:
        """A ratio is meaningless if the two are not doing comparable work."""
        import orjson

        payload = orjson.dumps({"id": "O1", "symbol": "AAPL", "price": 7569})
        frames = submission(b"order.new", payload)
        assert frames[1] == payload
