"""End to end: what the engine puts on the bus, as a subscriber receives it.

Messaging review 2026-11, WP-MSG02 moved the sequences and the causal envelope
into one trailing frame. The unit tests pin the layout against a recorder;
this reads a real exchange (the bundled ``mini`` profile) over real ZeroMQ
while a REST example places, amends and cancels orders, and checks that every
message carries the trailer, that neither counter has a hole, and that an
acknowledgement cites the echoed command that caused it.

End-to-end: runs only with ``-m e2e`` (``make test-e2e``).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.envelope import Envelope
from edumatcher.models.message import (
    decode,
    decode_envelope,
    decode_publisher_sequence,
    decode_sequence,
)
from tests.e2e_exchange import Exchange, running_exchange

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals"),
]

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples" / "REST" / "python"
URL = "http://127.0.0.1:8080"
#: s10-basic's API desk key for TRADER01.
TRADER = "key-trader01-610wpl"


@pytest.fixture(scope="module")
def exchange(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Exchange]:
    with running_exchange(request, tmp_path_factory) as ex:
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(f"{URL}/api/v1/healthz", timeout=2) as r:
                    if json.loads(r.read()).get("ok"):
                        break
            except OSError:
                pass
            assert time.monotonic() < deadline, "the API gateway never became healthy"
            time.sleep(0.5)
        yield ex


def _received_during_an_order_lifecycle() -> list[list[bytes]]:
    sub = make_subscriber("tcp://127.0.0.1:5556", rcvhwm=1_000_000)
    try:
        time.sleep(0.5)  # let the subscription reach the engine
        done = subprocess.run(
            [
                sys.executable, "order_lifecycle.py", "--url", URL, "--key", TRADER,
                "--symbol", "AAPL", "--price", "22.70",
            ],
            cwd=EXAMPLES, capture_output=True, text=True, timeout=90, check=False,
        )  # fmt: skip
        assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
        received: list[list[bytes]] = []
        while sub.poll(1000):
            received.append(sub.recv_multipart())
        return received
    finally:
        sub.close(linger=0)


def test_every_message_carries_one_gap_free_trailer(exchange: Exchange) -> None:
    received = _received_during_an_order_lifecycle()
    assert received, "nothing received from the engine"

    envelopes: dict[str, tuple[str, Envelope]] = {}
    last_seq: dict[str, int] = {}
    eseqs: list[int] = []
    for frames in received:
        topic, _payload = decode(frames)
        assert len(frames) == 3, (topic, frames)
        seq = decode_sequence(frames)
        eseq = decode_publisher_sequence(frames)
        env = decode_envelope(frames)
        assert seq is not None and eseq is not None and env is not None, frames[2]
        if topic in last_seq:
            assert seq == last_seq[topic] + 1, f"{topic}: {last_seq[topic]} -> {seq}"
        last_seq[topic] = seq
        eseqs.append(eseq)
        envelopes[env.msg_id] = (topic, env)

    # A subscriber that takes every topic sees the socket-wide count unbroken.
    assert eseqs == list(range(eseqs[0], eseqs[0] + len(eseqs)))

    # Each acknowledgement cites the command the engine echoed before acting.
    acks = [env for topic, env in envelopes.values() if topic.startswith("order.ack.")]
    assert acks, sorted({t for t, _ in envelopes.values()})
    for ack in acks:
        assert ack.causation_id in envelopes, ack
        cause_topic, cause = envelopes[ack.causation_id]
        assert cause_topic.startswith("order."), cause_topic
        assert cause.causation_id is None  # a gateway's submission is a root
        assert ack.correlation_id == cause.msg_id


def test_a_subscriber_that_reads_only_topic_and_payload_is_unaffected(
    exchange: Exchange,
) -> None:
    """``decode`` reads two frames; the trailer must not reach a payload."""
    for frames in _received_during_an_order_lifecycle():
        _topic, payload = decode(frames)
        assert isinstance(payload, dict)
        assert b"|" not in frames[0]
