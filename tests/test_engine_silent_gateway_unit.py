"""A gateway expired for silence is one chain in the audit trail (A4).

Nothing is sent by the client when its heartbeats stop, so the disconnect has
no command behind it.  Its bye and the cancels it causes must share a chain,
or a reader (and the re-run) cannot tell them from unrelated roots.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from edumatcher.messaging.bus import CausalPublisher, SequencedPublisher
from edumatcher.models.message import decode, decode_envelope
from edumatcher.models.order import OrderType, Side
from edumatcher.models.participant import DisconnectBehaviour
from tests.engine_harness import FakeSock, connect, make_engine, order_payload


def test_the_bye_and_the_cancels_share_one_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    engine, _pub = make_engine(monkeypatch, tmp_path)
    connect(engine, "GW01")
    engine._handle_new_order(
        order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=10.0)
    )

    sock = FakeSock()
    engine.pub_sock = CausalPublisher(SequencedPublisher(sock))
    session = engine._sessions["GW01"]
    session.disconnect_behaviour = DisconnectBehaviour.CANCEL_ALL
    session.heartbeat_interval_sec = 1
    session.last_heartbeat = time.monotonic() - 100
    engine._next_silence_check = 0.0

    engine._expire_silent_gateways()

    published = [(decode(f)[0], decode_envelope(f)) for f in sock.sent]
    topics = [t for t, _ in published]
    assert "system.gateway_bye.GW01" in topics
    assert any(t.startswith("order.cancelled.GW01") for t in topics)
    chains = {env.correlation_id for _, env in published if env is not None}
    assert len(chains) == 1, topics
