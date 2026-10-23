from __future__ import annotations

import errno
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import zmq

from edumatcher.audit.main import AuditProcess, main


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

    with (
        patch("edumatcher.audit.main.make_subscriber", return_value=fake_sub),
        patch("edumatcher.audit.main.make_replier"),
    ):
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

    with (
        patch("edumatcher.audit.main.make_subscriber", return_value=fake_sub),
        patch("edumatcher.audit.main.make_replier"),
    ):
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


# ---------------------------------------------------------------------------
# _topic_family static method — all branches (lines 235-274)
# ---------------------------------------------------------------------------


class TestTopicFamily:
    """Every branch of _topic_family must return the correct family string."""

    @pytest.mark.parametrize(
        "topic, expected",
        [
            ("book.snapshot.AAPL", "book"),
            ("book.depth.AAPL", "book"),
            ("order.new", "order"),
            ("order.ack.GW1", "order"),
            ("quote.new", "quote"),
            ("quote.ack.GW1", "quote"),
            ("combo.new", "combo"),
            ("combo.ack.GW1", "combo"),
            ("oco.new", "oco"),
            ("oco.ack.GW1", "oco"),
            ("trade.executed", "trade"),
            ("session.state", "session"),
            ("session.transition", "session"),
            ("system.symbols", "system"),
            ("system.eod", "system"),
            ("risk.kill_switch", "risk"),
            ("risk.symbol_halt.GW1", "risk"),
            ("log.event", "other"),
            ("index.value", "other"),
            ("completely.unknown.topic", "other"),
        ],
    )
    def test_all_families(self, topic: str, expected: str, tmp_path: Path) -> None:
        from unittest.mock import patch

        with (
            patch("edumatcher.audit.main.make_subscriber"),
            patch("edumatcher.audit.main.make_replier"),
        ):
            proc = AuditProcess(log_path=tmp_path / "a.log", to_terminal=False)
        assert proc._topic_family(topic) == expected


# ---------------------------------------------------------------------------
# _add_to_buffer: overflow triggers immediate flush (lines 306-308)
# ---------------------------------------------------------------------------


def test_add_to_buffer_flushes_on_overflow(tmp_path: Path) -> None:
    """When buffer reaches buffer_size the flush must happen immediately."""
    from unittest.mock import patch

    log_path = tmp_path / "overflow.log"

    with (
        patch("edumatcher.audit.main.make_subscriber"),
        patch("edumatcher.audit.main.make_replier"),
    ):
        proc = AuditProcess(log_path=log_path, to_terminal=False, buffer_size=3)

    for i in range(3):
        proc._add_to_buffer(f"line {i}")

    # After reaching buffer_size, the buffer should have been flushed.
    assert log_path.read_text(encoding="utf-8").count("line") == 3


def test_flush_timer_is_scheduled_on_first_message(tmp_path: Path) -> None:
    """The flush timer should be started when the first line enters an empty buffer."""
    from unittest.mock import patch

    with (
        patch("edumatcher.audit.main.make_subscriber"),
        patch("edumatcher.audit.main.make_replier"),
    ):
        proc = AuditProcess(
            log_path=tmp_path / "t.log", to_terminal=False, buffer_size=100
        )

    assert proc._flush_timer is None
    proc._add_to_buffer("first line")
    assert proc._flush_timer is not None
    proc._flush_timer.cancel()


def test_flush_buffer_is_idempotent_on_empty(tmp_path: Path) -> None:
    """Calling _flush_buffer when the buffer is empty must be a safe no-op."""
    from unittest.mock import patch

    log_path = tmp_path / "empty.log"
    with (
        patch("edumatcher.audit.main.make_subscriber"),
        patch("edumatcher.audit.main.make_replier"),
    ):
        proc = AuditProcess(log_path=log_path, to_terminal=False)

    proc._flush_buffer()  # Buffer already empty — should not raise.
    # No output written for an empty flush.
    assert not log_path.exists() or log_path.read_text() == ""


# ---------------------------------------------------------------------------
# Health REP socket
# ---------------------------------------------------------------------------


class _FakeReplier:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False

    def recv(self) -> bytes:
        return b"ping"

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True


def test_receive_answers_health_ping_with_utc_timestamp(tmp_path: Path) -> None:
    """Intent: the health ping is answered from the receive loop itself, so a
    reply proves that loop is pumping."""
    from datetime import datetime

    fake_sub = _FakeSub(frame_count=0)
    fake_rep = _FakeReplier()
    with (
        patch("edumatcher.audit.main.make_subscriber", return_value=fake_sub),
        patch("edumatcher.audit.main.make_replier", return_value=fake_rep),
    ):
        proc = AuditProcess(log_path=tmp_path / "audit.log", to_terminal=False)

    with patch(
        "edumatcher.audit.main.zmq.Poller",
        return_value=_PollerWithNEvents(fake_rep, events=1),
    ):
        proc._receive()

    assert len(fake_rep.sent) == 1
    assert datetime.fromisoformat(fake_rep.sent[0].decode()).tzinfo is not None


def _file_handler(proc: AuditProcess) -> RotatingFileHandler:
    return next(h for h in proc.logger.handlers if isinstance(h, RotatingFileHandler))


def test_rotation_defaults_to_10_mb_and_5_backups(tmp_path: Path) -> None:
    with (
        patch("edumatcher.audit.main.make_subscriber", return_value=_FakeSub(0)),
        patch("edumatcher.audit.main.make_replier"),
    ):
        proc = AuditProcess(log_path=tmp_path / "audit.log", to_terminal=False)

    handler = _file_handler(proc)
    assert handler.maxBytes == 10 * 1024 * 1024
    assert handler.backupCount == 5


def test_rotation_size_and_backup_count_are_configurable(tmp_path: Path) -> None:
    """Intent: a long simulation must be able to keep a whole session — the
    default 60 MB held only ~3 minutes of a 100-trader run."""
    with (
        patch("edumatcher.audit.main.make_subscriber", return_value=_FakeSub(0)),
        patch("edumatcher.audit.main.make_replier"),
    ):
        proc = AuditProcess(
            log_path=tmp_path / "audit.log",
            to_terminal=False,
            max_file_mb=256,
            backup_count=100,
        )

    handler = _file_handler(proc)
    assert handler.maxBytes == 256 * 1024 * 1024
    assert handler.backupCount == 100


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--max-file-mb", "0"], "--max-file-mb must be at least 1"),
        (["--backup-count", "0"], "--backup-count must be at least 1"),
    ],
)
def test_main_rejects_non_positive_rotation_options(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        patch("sys.argv", ["pm-audit", "--log-target", "stdout", *argv]),
        patch("edumatcher.audit.main.AuditProcess") as process,
        pytest.raises(SystemExit),
    ):
        main()

    process.assert_not_called()
    assert message in capsys.readouterr().err


def test_failed_health_socket_setup_closes_the_subscriber(tmp_path: Path) -> None:
    fake_sub = _FakeSub(frame_count=0)
    with (
        patch("edumatcher.audit.main.make_subscriber", return_value=fake_sub),
        patch(
            "edumatcher.audit.main.make_replier",
            side_effect=zmq.ZMQError(errno.EADDRINUSE),
        ),
        pytest.raises(zmq.ZMQError),
    ):
        AuditProcess(log_path=tmp_path / "audit.log", to_terminal=False)

    assert fake_sub.closed is True
