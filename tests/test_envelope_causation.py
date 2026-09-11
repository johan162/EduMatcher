"""Causal envelope: ULID properties, frame layout, and end-to-end causation.

The design rests on three claims, and each has its own section below:

1. A ULID is unique and sorts by generation time.
2. The envelope frame sits behind the sequence frame, so `decode_sequence`
   keeps reading `frames[2]` whatever else is on the wire.
3. A gateway submission is a causal root, and everything the engine publishes
   while handling it cites that submission and inherits its chain.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from edumatcher.audit.query import AuditEntry, _parse_line, parse_meta
from edumatcher.messaging.bus import (
    CausalPublisher,
    CausalPusher,
    SequencedPublisher,
)
from edumatcher.models.envelope import Envelope, new_ulid
from edumatcher.models.message import (
    decode,
    decode_envelope,
    decode_push_envelope,
    decode_sequence,
)


class FakeSock:
    """Records frames instead of sending them."""

    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> None:
        self.sent.append(frames)


def _meta_section(frames: list[bytes]) -> str:
    """Mirror of `audit.main._meta_section`, duplicated to keep this module
    importable without pulling in the audit runtime's dependencies."""
    seq, env = decode_sequence(frames), decode_envelope(frames)
    parts: list[str] = []
    if seq is not None:
        parts.append(f"seq={seq}")
    if env is not None:
        parts.append(f"msg={env.msg_id}")
        if env.causation_id:
            parts.append(f"cause={env.causation_id}")
        if env.correlation_id:
            parts.append(f"chain={env.correlation_id}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# 1. ULID
# ---------------------------------------------------------------------------


class TestUlid:
    def test_shape(self) -> None:
        u = new_ulid()
        assert len(u) == 26
        assert set(u) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")

    def test_excludes_the_ambiguous_letters(self) -> None:
        """Crockford base32 omits I, L, O and U so an id cannot be misread."""
        assert not (set("".join(new_ulid() for _ in range(200))) & set("ILOU"))

    def test_unique_in_bulk(self) -> None:
        assert len({new_ulid() for _ in range(20_000)}) == 20_000

    def test_lexicographic_order_is_generation_order(self) -> None:
        """The property that makes a ULID worth more here than a UUID4.

        Generated in a tight loop, so most of these land in the same
        millisecond — which is exactly the case the monotonic counter exists
        to handle. Without it this test fails roughly always.
        """
        ids = [new_ulid() for _ in range(5_000)]
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# 2. Envelope and frame layout
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_root_starts_its_own_chain(self) -> None:
        e = Envelope.root()
        assert e.causation_id is None
        assert e.correlation_id == e.msg_id

    def test_caused_cites_parent_and_inherits_chain(self) -> None:
        root = Envelope.root()
        child = root.caused()
        grandchild = child.caused()

        assert child.causation_id == root.msg_id
        assert grandchild.causation_id == child.msg_id
        # The chain names the root, however deep the descent.
        assert grandchild.correlation_id == root.msg_id

    def test_frame_round_trip(self) -> None:
        for env in (Envelope.root(), Envelope.root().caused()):
            assert Envelope.from_frame(env.to_frame()) == env

    @pytest.mark.parametrize(
        "junk",
        [b"", b"nonsense", b"a|b|c", b"\xff\xfe", b"01ARZ3NDEKTSV4RRFFQ69G5FAV|x"],
    )
    def test_malformed_frame_returns_none_rather_than_raising(
        self, junk: bytes
    ) -> None:
        """A bad envelope must never stop a subscriber reading a good payload."""
        assert Envelope.from_frame(junk) is None


class TestFrameLayout:
    """`decode_sequence` reads frames[2]; the envelope must not displace it."""

    def test_sequence_stays_at_index_two(self) -> None:
        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.send_multipart([b"trade.executed", b"{}"])

        frames = sock.sent[0]
        assert len(frames) == 4
        assert decode_sequence(frames) == 1
        assert decode_envelope(frames) is not None

    def test_sequence_is_still_per_topic(self) -> None:
        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.send_multipart([b"trade.executed", b"{}"])
        pub.send_multipart([b"depth.AAPL", b"{}"])
        pub.send_multipart([b"trade.executed", b"{}"])

        assert [decode_sequence(f) for f in sock.sent] == [1, 1, 2]

    def test_payload_is_untouched(self) -> None:
        """The envelope rides outside the JSON — the payload is byte-identical."""
        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        body = b'{"id":"T1","price":150.5}'
        pub.send_multipart([b"trade.executed", body])

        assert sock.sent[0][1] == body
        assert decode(sock.sent[0])[1] == {"id": "T1", "price": 150.5}


# ---------------------------------------------------------------------------
# 3. End-to-end causation
# ---------------------------------------------------------------------------


class TestCausationEndToEnd:
    @staticmethod
    def _submission() -> tuple[FakeSock, Envelope]:
        push = FakeSock()
        CausalPusher(push).send_multipart([b"order.new", b'{"id":"O1"}'])
        env = decode_push_envelope(push.sent[0])
        assert env is not None
        return push, env

    def test_a_gateway_submission_is_a_causal_root(self) -> None:
        _, env = self._submission()
        assert env.causation_id is None
        assert env.correlation_id == env.msg_id

    def test_the_four_high_value_replies_cite_the_submission(self) -> None:
        """order.ack, order.fill, trade.executed and order.cancelled are the
        links the replay tool leans on hardest (design §5.1.1)."""
        _, submission = self._submission()
        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))

        pub.set_cause(submission)
        for topic in (
            b"order.ack.GW1",
            b"order.fill.GW1",
            b"trade.executed",
            b"order.cancelled.GW1",
        ):
            pub.send_multipart([topic, b"{}"])
        pub.clear_cause()

        for frames in sock.sent:
            env = decode_envelope(frames)
            assert env is not None
            assert env.causation_id == submission.msg_id
            assert env.correlation_id == submission.msg_id

    def test_one_submission_yields_one_chain(self) -> None:
        _, submission = self._submission()
        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.set_cause(submission)
        for _ in range(10):
            pub.send_multipart([b"order.fill.GW1", b"{}"])
        pub.clear_cause()

        chains = {decode_envelope(f).correlation_id for f in sock.sent}  # type: ignore[union-attr]
        msg_ids = {decode_envelope(f).msg_id for f in sock.sent}  # type: ignore[union-attr]
        assert chains == {submission.msg_id}
        assert len(msg_ids) == 10  # each effect is its own message

    def test_uncaused_publishes_claim_no_cause(self) -> None:
        """A scheduler tick or circuit-breaker trip has no external cause, and
        must say so rather than inheriting whatever ran last."""
        _, submission = self._submission()
        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))

        pub.set_cause(submission)
        pub.send_multipart([b"order.ack.GW1", b"{}"])
        pub.clear_cause()
        pub.send_multipart([b"circuit_breaker.halt.AAPL", b"{}"])

        halt = decode_envelope(sock.sent[1])
        assert halt is not None
        assert halt.causation_id is None
        assert halt.correlation_id == halt.msg_id

    def test_cause_does_not_leak_between_messages(self) -> None:
        """The engine clears the cause in a `finally`; this pins the behaviour
        that guard protects."""
        _, first = self._submission()
        _, second = self._submission()
        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))

        pub.set_cause(first)
        pub.send_multipart([b"order.ack.GW1", b"{}"])
        pub.clear_cause()
        pub.set_cause(second)
        pub.send_multipart([b"order.ack.GW2", b"{}"])
        pub.clear_cause()

        assert decode_envelope(sock.sent[0]).causation_id == first.msg_id  # type: ignore[union-attr]
        assert decode_envelope(sock.sent[1]).causation_id == second.msg_id  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# 4. The audit trail records it
# ---------------------------------------------------------------------------


class TestAuditLineCarriesTheEnvelope:
    @staticmethod
    def _line(frames: list[bytes]) -> str:
        topic, payload = decode(frames)
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        return f"[{ts}] [{topic}] [{_meta_section(frames)}] {json.dumps(payload)}"

    def test_round_trip_through_the_log_line(self) -> None:
        push = FakeSock()
        CausalPusher(push).send_multipart([b"order.new", b'{"id":"O1"}'])
        submission = decode_push_envelope(push.sent[0])
        assert submission is not None

        sock = FakeSock()
        pub = CausalPublisher(SequencedPublisher(sock))
        pub.set_cause(submission)
        pub.send_multipart([b"order.ack.GW1", b'{"order_id":"O1","gateway_id":"GW1"}'])

        parsed = _parse_line(self._line(sock.sent[0]))
        assert parsed is not None
        entry = AuditEntry(*parsed)

        assert entry.seq == 1
        assert entry.msg_id is not None
        assert entry.causation_id == submission.msg_id
        assert entry.correlation_id == submission.msg_id
        # The payload survives untouched alongside the new metadata.
        assert entry.gateway_id == "GW1"
        assert entry.order_id == "O1"

    def test_a_line_without_metadata_still_parses(self) -> None:
        """Archived lines predate the metadata section; reading a mixed archive
        must not need a flag."""
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        parsed = _parse_line(f'[{ts}] [trade.executed] {{"id":"T1"}}')
        assert parsed is not None
        entry = AuditEntry(*parsed)

        assert entry.topic == "trade.executed"
        assert entry.trade_id == "T1"
        assert entry.msg_id is None
        assert entry.seq is None

    def test_unknown_metadata_keys_are_kept(self) -> None:
        """The section is meant to grow; a reader that drops what it does not
        recognise makes adding a key painful."""
        assert parse_meta("seq=3 msg=ABC future=42") == {
            "seq": "3",
            "msg": "ABC",
            "future": "42",
        }

    def test_malformed_metadata_does_not_break_the_line(self) -> None:
        assert parse_meta("") == {}
        assert parse_meta("noequals") == {}
