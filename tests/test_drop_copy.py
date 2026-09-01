"""Tests for engine/drop_copy.py — DropCopyPublisher unit tests.

Phase 6.1d moved these from ``publish(gateway_id, event_type, payload_dict)``
to the typed ``publish_fill``. The old calls passed keys no producer has ever
sent — ``qty``, ``n``, ``i`` — and event types ``"a"`` and ``"b"``, which is
how the payload dict came to look like an open map when the single caller had
always sent the same five fields. Section 20.5's lesson pointing the other
way: a capability exercised only by its own tests is not a capability the
system has. Section 27.2.

The assertions themselves are unchanged in intent — two frames, the topic, the
sequence, the buffer bound, the replay window — and now use real fill fields.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.engine.drop_copy import (
    DROP_COPY_BUFFER_SIZE,
    DropCopyMessage,
    DropCopyPublisher,
)


class _FakeSocket:
    """Minimal ZMQ PUB socket stub that records sends."""

    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []
        self.closed = False

    def bind(self, addr: str) -> None:
        pass

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


class _FakeContext:
    def __init__(self) -> None:
        self._socket = _FakeSocket()

    def socket(self, socket_type: int) -> _FakeSocket:
        return self._socket


def _fill(**overrides: Any) -> dict[str, Any]:
    """One valid fill, so a test can name only the field it cares about.

    The builder validates now, so every call needs a complete and legal
    payload — which is the point, and is why the old ad-hoc dicts could not
    survive.
    """
    fill: dict[str, Any] = {
        "order_id": "X1",
        "trade_ids": ["000001-000000001"],
        "symbol": "AAPL",
        "fill_qty": 100,
        "fill_price": 150.25,
        "liquidity_flag": "MAKER",
    }
    fill.update(overrides)
    return fill


@pytest.fixture()
def publisher() -> tuple[DropCopyPublisher, _FakeSocket]:
    ctx = _FakeContext()
    pub = DropCopyPublisher(ctx, addr="tcp://127.0.0.1:15557")  # type: ignore[arg-type]
    # Reuse the socket reference that was injected
    pub._pub = ctx._socket
    return pub, ctx._socket


class TestPublish:
    def test_publish_sends_two_frames(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        pub.publish_fill("GW01", **_fill(order_id="X1", fill_qty=100))
        assert len(sock.sent) == 1
        assert len(sock.sent[0]) == 2

    def test_publish_topic_frame(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        pub.publish_fill("GW01", **_fill(order_id="X1"))
        topic = sock.sent[0][0]
        assert topic == b"drop_copy.event.GW01"

    def test_publish_payload_is_bytes(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        pub.publish_fill("GW02", **_fill(order_id="X2"))
        payload = sock.sent[0][1]
        assert isinstance(payload, bytes)

    def test_publish_payload_contains_fields(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        import json

        pub, sock = publisher
        pub.publish_fill("GW01", **_fill(order_id="X3", fill_qty=50))
        payload = json.loads(sock.sent[0][1])
        assert payload["order_id"] == "X3"
        assert payload["trade_ids"] == ["000001-000000001"]
        assert payload["fill_qty"] == 50
        assert payload["gateway_id"] == "GW01"
        assert payload["event_type"] == "order.fill"

    def test_publish_adds_seq_and_timestamp(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        import json

        pub, sock = publisher
        pub.publish_fill("GW01", **_fill())
        payload = json.loads(sock.sent[0][1])
        assert "seq" in payload
        assert "timestamp" in payload
        assert isinstance(payload["seq"], int)
        assert isinstance(payload["timestamp"], int)

    def test_seq_monotonically_increases(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        import json

        pub, sock = publisher
        pub.publish_fill("GW01", **_fill(order_id="X1"))
        pub.publish_fill("GW01", **_fill(order_id="X2"))
        seq0 = json.loads(sock.sent[0][1])["seq"]
        seq1 = json.loads(sock.sent[1][1])["seq"]
        assert seq1 > seq0

    def test_published_message_stored_in_log(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, _ = publisher
        pub.publish_fill("GW01", **_fill(order_id="X4"))
        assert len(pub._log) == 1
        msg = pub._log[0]
        assert isinstance(msg, DropCopyMessage)
        assert msg.gateway_id == "GW01"
        assert msg.event_type == "order.fill"
        assert msg.order_id == "X4"

    def test_buffer_overflow_drops_oldest(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, _ = publisher
        for i in range(DROP_COPY_BUFFER_SIZE + 10):
            pub.publish_fill("GW01", **_fill(order_id=f"X{i}"))
        assert len(pub._log) == DROP_COPY_BUFFER_SIZE


class TestReplay:
    def test_replay_resends_messages_from_seq(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        pub.publish_fill("GW01", **_fill(order_id="X1"))
        pub.publish_fill("GW01", **_fill(order_id="X2"))
        pub.publish_fill("GW01", **_fill(order_id="X3"))

        first_seq = pub._log[0].seq
        sock.sent.clear()

        replayed = pub.replay("CLIENT1", from_seq=first_seq + 1)
        assert replayed == 2  # messages 2 and 3

    def test_replay_uses_replay_topic(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        pub.publish_fill("GW01", **_fill())
        first_seq = pub._log[0].seq
        sock.sent.clear()

        pub.replay("CLIENT2", from_seq=first_seq)
        assert sock.sent[0][0] == b"drop_copy.replay.CLIENT2"
        import json

        assert json.loads(sock.sent[0][1])["trade_ids"] == ["000001-000000001"]

    def test_replay_from_seq_zero_replays_all(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        for i in range(5):
            pub.publish_fill("GW01", **_fill(order_id=f"X{i}"))
        sock.sent.clear()
        replayed = pub.replay("CLIENT3", from_seq=0)
        assert replayed == 5

    def test_replay_from_beyond_last_seq_replays_nothing(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        pub.publish_fill("GW01", **_fill())
        last_seq = pub._log[-1].seq
        sock.sent.clear()
        replayed = pub.replay("CLIENT4", from_seq=last_seq + 1000)
        assert replayed == 0


class TestClose:
    def test_close_calls_socket_close(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        pub.close()
        assert sock.closed
