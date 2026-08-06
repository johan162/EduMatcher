from __future__ import annotations

import errno
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import zmq

from edumatcher.audit.main import AuditProcess


class _FakeSub:
    def __init__(self, frame_count: int) -> None:
        self._remaining = frame_count
        self.closed = False

    def recv_multipart(self) -> list[bytes]:
        if self._remaining <= 0:
            raise AssertionError("recv_multipart called with no frames left")
        self._remaining -= 1
        return [b"topic", b"payload"]

    def close(self) -> None:
        self.closed = True


class _PollerWithNEvents:
    def __init__(self, sub: Any, events: int) -> None:
        self._sub = sub
        self._events = events

    def register(self, _sock: Any, _mask: int) -> None:
        return None

    def poll(self, timeout: int) -> list[tuple[Any, int]]:
        _ = timeout
        if self._events > 0:
            self._events -= 1
            return [(self._sub, zmq.POLLIN)]
        raise zmq.ZMQError(errno.EINTR)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_receive_buffers_and_flushes_audit_lines(tmp_path: Path) -> None:
    """Intent: audit should persist every decodable message line with topic and payload,
    even when receive loop exits via EINTR.
    """
    fake_sub = _FakeSub(frame_count=2)
    log_path = tmp_path / "audit.log"

    with patch("edumatcher.audit.main.make_subscriber", return_value=fake_sub):
        proc = AuditProcess(log_path=log_path, to_terminal=False, buffer_size=100)

    with (
        patch(
            "edumatcher.audit.main.zmq.Poller",
            return_value=_PollerWithNEvents(fake_sub, events=2),
        ),
        patch(
            "edumatcher.audit.main.decode",
            side_effect=[
                ("trade.executed", {"symbol": "AAPL", "price": 100.5}),
                ("order.fill.GW01", {"order_id": "ORD-1", "fill_qty": 5}),
            ],
        ),
    ):
        proc._receive()

    proc._flush_buffer()

    contents = log_path.read_text(encoding="utf-8")
    assert "[trade.executed]" in contents
    assert '"symbol": "AAPL"' in contents
    assert "[order.fill.GW01]" in contents
    assert '"order_id": "ORD-1"' in contents


def test_receive_survives_decode_errors_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Intent: one malformed frame must not kill auditing for subsequent valid frames."""
    fake_sub = _FakeSub(frame_count=2)
    log_path = tmp_path / "audit.log"

    with patch("edumatcher.audit.main.make_subscriber", return_value=fake_sub):
        proc = AuditProcess(log_path=log_path, to_terminal=False, buffer_size=100)

    with (
        patch(
            "edumatcher.audit.main.zmq.Poller",
            return_value=_PollerWithNEvents(fake_sub, events=2),
        ),
        patch(
            "edumatcher.audit.main.decode",
            side_effect=[
                ValueError("bad frame"),
                ("trade.executed", {"symbol": "MSFT", "price": 410.0}),
            ],
        ),
        caplog.at_level(logging.WARNING),
    ):
        proc._receive()

    proc._flush_buffer()

    contents = log_path.read_text(encoding="utf-8")
    assert "[trade.executed]" in contents
    assert '"symbol": "MSFT"' in contents
    assert "failed to decode/log message" in caplog.text
