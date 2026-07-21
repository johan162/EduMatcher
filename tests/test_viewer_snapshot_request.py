"""Tests for pm-viewer's initial snapshot request helper.

Regression coverage for a bug where request_snapshot_with_retry (formerly
an inline closure in main()) would let zmq.Again escape uncaught whenever
the PUSH->PULL handshake to the engine hadn't completed by the time the
send happened -- which reliably raced pm-viewer's short startup delay and
printed an unhandled-thread-exception traceback on every launch, even
though the tool otherwise worked fine.

make_pusher() sets IMMEDIATE=1 + SNDTIMEO=0, so send_multipart() raises
zmq.Again (rather than blocking) until the connect handshake finishes.
These tests exercise that exact race using real PUSH/PULL sockets.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest
import zmq

from edumatcher.messaging.bus import get_context
from edumatcher.models.message import decode
from edumatcher.viewer import main as viewer_main


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_request_snapshot_retries_past_slow_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the PULL side binds *after* the first send attempt, the retry loop
    should keep trying instead of raising zmq.Again out of the thread."""
    port = _free_port()
    addr = f"tcp://127.0.0.1:{port}"
    monkeypatch.setattr(viewer_main, "ENGINE_PULL_ADDR", addr)

    received: list[tuple[bytes, bytes]] = []

    def _bind_late() -> None:
        # Delay the bind well past the connect-side's first send attempt so
        # the first send(s) reliably hit zmq.Again before this appears.
        time.sleep(0.3)
        pull = get_context().socket(zmq.PULL)
        pull.bind(addr)
        try:
            frames = pull.recv_multipart()
            received.append(tuple(frames))
        finally:
            pull.close()

    t = threading.Thread(target=_bind_late, daemon=True)
    t.start()

    # Should not raise despite the PULL side not existing yet at call time.
    viewer_main.request_snapshot_with_retry(
        "AAPL",
        initial_delay_sec=0.0,
        retry_timeout_sec=2.0,
        retry_interval_sec=0.05,
    )
    t.join(timeout=2.0)

    assert len(received) == 1
    topic, payload = decode(list(received[0]))
    assert topic == "book.snapshot_request"
    assert payload["symbol"] == "AAPL"


def test_request_snapshot_gives_up_quietly_when_engine_absent(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If nothing ever binds the PULL address, the helper should time out
    and log a warning rather than raising."""
    port = _free_port()
    addr = f"tcp://127.0.0.1:{port}"
    monkeypatch.setattr(viewer_main, "ENGINE_PULL_ADDR", addr)

    with caplog.at_level("WARNING", logger="edumatcher.viewer.main"):
        # Must not raise zmq.Again -- this is the exact bug being fixed.
        viewer_main.request_snapshot_with_retry(
            "AAPL",
            initial_delay_sec=0.0,
            retry_timeout_sec=0.3,
            retry_interval_sec=0.05,
        )

    assert any("could not reach engine" in rec.message for rec in caplog.records)


def test_request_snapshot_succeeds_immediately_when_engine_already_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The common case: engine's PULL socket is already bound, so the first
    send should succeed without needing any retries."""
    port = _free_port()
    addr = f"tcp://127.0.0.1:{port}"
    monkeypatch.setattr(viewer_main, "ENGINE_PULL_ADDR", addr)

    pull = get_context().socket(zmq.PULL)
    pull.bind(addr)
    try:
        # Give the bind a brief moment to be fully ready for connects.
        time.sleep(0.05)
        viewer_main.request_snapshot_with_retry(
            "MSFT",
            initial_delay_sec=0.0,
            retry_timeout_sec=2.0,
            retry_interval_sec=0.05,
        )
        assert pull.poll(timeout=2000)
        frames = pull.recv_multipart()
        topic, payload = decode(frames)
        assert topic == "book.snapshot_request"
        assert payload["symbol"] == "MSFT"
    finally:
        pull.close()
