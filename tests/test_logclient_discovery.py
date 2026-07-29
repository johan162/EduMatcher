"""Tests for ``edumatcher.logclient.discovery`` (design §8.3, §11).

Covers all five branches of the auto-detection algorithm: explicit
``stdout``/``file`` skip detection; a real server present (via the actual
``LogServer``, mirroring ``tests/test_log_srv_server.py``'s fixture
pattern) attaches a ``TcpLogHandler``; server absent + default falls back
silently to stdout; server absent + explicit ``--log-target server``
prints a stderr message and falls back to stdout.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from pathlib import Path

import pytest

from edumatcher.log_srv.config import LogServerConfig
from edumatcher.log_srv.server import LogServer
from edumatcher.logclient.discovery import resolve_handler
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


@pytest.fixture
def running_server(tmp_path: Path):
    rs = _RunningServer(tmp_path)
    rs.start()
    yield rs
    rs.stop()


def test_explicit_stdout_skips_detection(tmp_path: Path) -> None:
    """§8.3 step 1: --log-target stdout wins unconditionally, no probe."""
    handler = resolve_handler(
        log_target="stdout",
        log_file=None,
        client_name="pm-test",
        instance=None,
        host=_HOST,
        port=_free_port(),  # nothing listening here — must not matter
        connect_timeout_sec=0.1,
        failover_timeout_sec=1.0,
        failover_dir=tmp_path,
    )
    assert isinstance(handler, logging.StreamHandler)
    assert not isinstance(handler, logging.FileHandler)


def test_explicit_file_skips_detection(tmp_path: Path) -> None:
    """§8.3 step 1: --log-target file wins unconditionally, no probe."""
    log_path = tmp_path / "explicit.log"
    handler = resolve_handler(
        log_target="file",
        log_file=str(log_path),
        client_name="pm-test",
        instance=None,
        host=_HOST,
        port=_free_port(),
        connect_timeout_sec=0.1,
        failover_timeout_sec=1.0,
        failover_dir=tmp_path,
    )
    try:
        assert isinstance(handler, logging.FileHandler)
        assert Path(handler.baseFilename) == log_path.resolve()
    finally:
        handler.close()


def test_explicit_file_without_path_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resolve_handler(
            log_target="file",
            log_file=None,
            client_name="pm-test",
            instance=None,
            host=_HOST,
            port=_free_port(),
            connect_timeout_sec=0.1,
            failover_timeout_sec=1.0,
            failover_dir=tmp_path,
        )


def test_server_present_attaches_tcp_handler(
    running_server: _RunningServer, tmp_path: Path
) -> None:
    """§8.3 steps 2-3: a reachable server yields a TcpLogHandler."""
    handler = resolve_handler(
        log_target=None,
        log_file=None,
        client_name="pm-test",
        instance=None,
        host=_HOST,
        port=running_server.port,
        connect_timeout_sec=0.5,
        failover_timeout_sec=5.0,
        failover_dir=tmp_path,
    )
    try:
        assert isinstance(handler, TcpLogHandler)
    finally:
        handler.close()


def test_server_absent_default_falls_back_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§8.3 step 4: no server + unset --log-target -> silent stdout fallback."""
    handler = resolve_handler(
        log_target=None,
        log_file=None,
        client_name="pm-test",
        instance=None,
        host=_HOST,
        port=_free_port(),  # nothing listening
        connect_timeout_sec=0.1,
        failover_timeout_sec=1.0,
        failover_dir=tmp_path,
    )
    assert isinstance(handler, logging.StreamHandler)
    assert not isinstance(handler, logging.FileHandler)
    captured = capsys.readouterr()
    assert captured.err == ""


def test_server_absent_explicit_target_warns_and_falls_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§8.3 step 5: no server + explicit --log-target server -> stderr message + fallback."""
    port = _free_port()
    handler = resolve_handler(
        log_target="server",
        log_file=None,
        client_name="pm-test",
        instance=None,
        host=_HOST,
        port=port,
        connect_timeout_sec=0.1,
        failover_timeout_sec=1.0,
        failover_dir=tmp_path,
    )
    assert isinstance(handler, logging.StreamHandler)
    assert not isinstance(handler, logging.FileHandler)
    captured = capsys.readouterr()
    assert f"{_HOST}:{port}" in captured.err
    assert "falling back to stdout" in captured.err
