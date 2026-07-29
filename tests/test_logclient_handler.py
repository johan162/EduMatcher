"""Tests for ``edumatcher.logclient.handler.TcpLogHandler`` (design §8.2, §8.6, §11)."""

from __future__ import annotations

import logging
import socket
import threading
import time
from pathlib import Path

import pytest

from edumatcher.log_srv.config import LogServerConfig
from edumatcher.log_srv.server import LogServer
from edumatcher.logclient.handler import TcpLogHandler

_HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((_HOST, 0))
        return s.getsockname()[1]


class _RunningServer:
    """Starts a real ``LogServer`` on a background thread for a test."""

    def __init__(self, tmp_path: Path) -> None:
        self.port = _free_port()
        self.pub_port = _free_port()
        self.pull_port = _free_port()
        self.db_path = tmp_path / "log.db"
        self.config = LogServerConfig(
            bind_address=_HOST,
            port=self.port,
            db_path=self.db_path,
            heartbeat_interval_sec=1,
            pub_port=self.pub_port,
            pull_port=self.pull_port,
        )
        self.server = LogServer(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        time.sleep(0.3)

    def stop(self) -> None:
        self.server.stop()
        time.sleep(0.4)

    def row_count(self) -> int:
        import sqlite3

        conn = sqlite3.connect(str(self.db_path))
        try:
            return int(conn.execute("SELECT COUNT(*) FROM log_events").fetchone()[0])
        finally:
            conn.close()


@pytest.fixture
def running_server(tmp_path: Path):
    rs = _RunningServer(tmp_path)
    rs.start()
    yield rs
    rs.stop()


def _make_record(
    logger_name: str, message: str, level: int = logging.INFO
) -> logging.LogRecord:
    return logging.LogRecord(
        name=logger_name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_emit_never_raises_when_server_absent(tmp_path: Path) -> None:
    """emit() must not raise even though nothing is listening (§8.2)."""
    handler = TcpLogHandler(
        _HOST,
        _free_port(),
        "pm-test",
        connect_timeout_sec=0.1,
        failover_timeout_sec=0.3,
        failover_dir=tmp_path,
    )
    try:
        handler.emit(_make_record("edumatcher.test", "hello"))
    finally:
        handler.close()


def test_delivers_log_record_to_running_server(
    running_server: _RunningServer, tmp_path: Path
) -> None:
    handler = TcpLogHandler(
        _HOST,
        running_server.port,
        "pm-test",
        connect_timeout_sec=0.5,
        failover_timeout_sec=5.0,
        failover_dir=tmp_path,
    )
    try:
        handler.emit(_make_record("edumatcher.test", "hello from test"))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if running_server.row_count() >= 1:
                break
            time.sleep(0.1)
        assert running_server.row_count() >= 1
    finally:
        handler.close()


def test_failover_writes_to_fallback_file_after_grace_window(tmp_path: Path) -> None:
    """§8.6: once failover_timeout_sec elapses with no server, switch to file."""
    handler = TcpLogHandler(
        _HOST,
        _free_port(),  # nothing listening — connection never succeeds
        "pm-test-client",
        connect_timeout_sec=0.1,
        failover_timeout_sec=0.3,
        failover_dir=tmp_path,
    )
    try:
        handler.emit(_make_record("edumatcher.test", "queued before failover"))
        deadline = time.monotonic() + 3.0
        fallback_path = tmp_path / "pm-test-client.log"
        while time.monotonic() < deadline and not fallback_path.exists():
            time.sleep(0.1)
        assert fallback_path.exists()

        # A record emitted after failover must land in the fallback file
        # directly via emit() (§8.6).
        handler.emit(_make_record("edumatcher.test", "after failover"))
        time.sleep(0.2)
        contents = fallback_path.read_text(encoding="utf-8")
        assert "pm-log-srv unreachable" in contents
        assert "after failover" in contents
    finally:
        handler.close()


def test_failover_is_one_way(tmp_path: Path) -> None:
    """§8.6 point 3: once failed over, stays on file logging even if asked again."""
    handler = TcpLogHandler(
        _HOST,
        _free_port(),
        "pm-test-oneway",
        connect_timeout_sec=0.1,
        failover_timeout_sec=0.2,
        failover_dir=tmp_path,
    )
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not handler._failed_over:
            time.sleep(0.1)
        assert handler._failed_over

        handler._trigger_failover()  # must be idempotent, not re-trigger anything
        assert handler._failed_over
    finally:
        handler.close()


def test_dropped_count_increments_when_queue_full(tmp_path: Path) -> None:
    """Bounded queue drops (not blocks) once queue_maxsize is exceeded (§8.2)."""
    handler = TcpLogHandler(
        _HOST,
        _free_port(),
        "pm-test-drop",
        queue_maxsize=1,
        connect_timeout_sec=0.1,
        failover_timeout_sec=60.0,  # long enough that failover doesn't kick in mid-test
        failover_dir=tmp_path,
    )
    try:
        for i in range(10):
            handler.emit(_make_record("edumatcher.test", f"msg {i}"))
        assert handler.dropped_count > 0
    finally:
        handler.close()
