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

import json
import time
from typing import Any

import pytest
import zmq

from edumatcher.engine.drop_copy import (
    DROP_COPY_BUFFER_SIZE,
    DropCopyMessage,
    DropCopyPublisher,
)
from edumatcher.models.message import decode
from tests.conftest import free_ports


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

    def test_buffer_bound_is_shared_across_gateways(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, _ = publisher
        for i in range(DROP_COPY_BUFFER_SIZE):
            pub.publish_fill("GW01", **_fill(order_id=f"X{i}"))
        pub.publish_fill("GW02", **_fill(order_id="Y1"))
        assert len(pub._log) == DROP_COPY_BUFFER_SIZE
        assert pub._log[0].order_id == "X1"
        assert pub._log[-1].gateway_id == "GW02"


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

        replayed = pub.replay("CLIENT1", from_seq=first_seq + 1, gateway_id="GW01")
        assert replayed == 2  # messages 2 and 3

    def test_replay_uses_replay_topic(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        pub.publish_fill("GW01", **_fill())
        first_seq = pub._log[0].seq
        sock.sent.clear()

        pub.replay("CLIENT2", from_seq=first_seq, gateway_id="GW01")
        assert sock.sent[0][0] == b"drop_copy.replay.CLIENT2"
        assert json.loads(sock.sent[0][1])["trade_ids"] == ["000001-000000001"]

    def test_replay_from_seq_zero_replays_all(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        for i in range(5):
            pub.publish_fill("GW01", **_fill(order_id=f"X{i}"))
        sock.sent.clear()
        replayed = pub.replay("CLIENT3", from_seq=0, gateway_id="GW01")
        assert replayed == 5

    def test_replay_from_beyond_last_seq_replays_nothing(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        pub.publish_fill("GW01", **_fill())
        last_seq = pub._log[-1].seq
        sock.sent.clear()
        replayed = pub.replay("CLIENT4", from_seq=last_seq + 1000, gateway_id="GW01")
        assert replayed == 0


def _probe_until_subscribed(
    pub: DropCopyPublisher, subs: list[zmq.Socket[bytes]]
) -> None:
    """Defeat the PUB/SUB slow-joiner: probe until every subscriber hears it.

    The probe goes out on the publisher's own socket but not through
    ``publish_fill``, so it consumes no drop-copy sequence number. Probes
    left queued are skipped by the reader.
    """
    deadline = time.monotonic() + 5.0
    pending = list(subs)
    while pending:
        assert time.monotonic() < deadline, "subscribers never joined"
        pub._pub.send_multipart([b"probe", b"{}"])
        pending = [sub for sub in pending if not sub.poll(timeout=20)]


def test_recipient_subscribers_get_independent_contiguous_sequences() -> None:
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    (port,) = free_ports(1)
    pub = DropCopyPublisher(ctx, addr=f"tcp://127.0.0.1:{port}")
    subscribers: dict[str, zmq.Socket[bytes]] = {}
    try:
        for gateway_id in ("GW01", "GW02"):
            sub = ctx.socket(zmq.SUB)
            sub.connect(f"tcp://127.0.0.1:{port}")
            sub.setsockopt(zmq.SUBSCRIBE, f"drop_copy.event.{gateway_id}".encode())
            sub.setsockopt(zmq.SUBSCRIBE, b"probe")
            subscribers[gateway_id] = sub
        _probe_until_subscribed(pub, list(subscribers.values()))

        for gateway_id, order_id in (
            ("GW01", "A1"),
            ("GW02", "B1"),
            ("GW01", "A2"),
            ("GW02", "B2"),
        ):
            pub.publish_fill(gateway_id, **_fill(order_id=order_id))

        received: dict[str, list[int]] = {"GW01": [], "GW02": []}
        for gateway_id, sub in subscribers.items():
            while len(received[gateway_id]) < 2:
                assert sub.poll(timeout=1000)
                topic, payload = sub.recv_multipart()
                if topic == b"probe":
                    continue
                assert topic == f"drop_copy.event.{gateway_id}".encode()
                received[gateway_id].append(json.loads(payload)["seq"])

        assert received == {"GW01": [1, 2], "GW02": [1, 2]}
    finally:
        for sub in subscribers.values():
            sub.close(linger=0)
        pub.close()


def test_new_publisher_starts_each_gateway_sequence_at_one() -> None:
    ctx = _FakeContext()
    pub = DropCopyPublisher(ctx, addr="tcp://127.0.0.1:15558")  # type: ignore[arg-type]
    pub._pub = ctx._socket
    pub.publish_fill("GW01", **_fill(order_id="before-restart"))
    pub.close()

    restarted_ctx = _FakeContext()
    restarted_pub = DropCopyPublisher(
        restarted_ctx, addr="tcp://127.0.0.1:15559"  # type: ignore[arg-type]
    )
    restarted_pub._pub = restarted_ctx._socket
    restarted_pub.publish_fill("GW01", **_fill(order_id="after-restart"))

    assert json.loads(restarted_ctx._socket.sent[0][1])["seq"] == 1
    restarted_pub.close()


def test_replay_is_scoped_to_the_gateway_sequence(
    publisher: tuple[DropCopyPublisher, _FakeSocket],
) -> None:
    pub, sock = publisher
    pub.publish_fill("GW01", **_fill(order_id="A1"))
    pub.publish_fill("GW02", **_fill(order_id="B1"))
    pub.publish_fill("GW01", **_fill(order_id="A2"))
    sock.sent.clear()

    replayed = pub.replay("RISK01", from_seq=2, gateway_id="GW01")

    assert replayed == 1
    topic, payload = decode(sock.sent[0])
    assert topic == "drop_copy.replay.RISK01"
    assert payload["gateway_id"] == "GW01"
    assert payload["seq"] == 2
    assert payload["order_id"] == "A2"


class TestClose:
    def test_close_calls_socket_close(
        self, publisher: tuple[DropCopyPublisher, _FakeSocket]
    ) -> None:
        pub, sock = publisher
        pub.close()
        assert sock.closed
