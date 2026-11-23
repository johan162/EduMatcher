"""Tests for ``edumatcher.logclient.handler.TcpLogHandler`` (design §8.2, §8.6, §11)."""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from edumatcher.log_srv.config import LogServerConfig
from edumatcher.log_srv.server import LogServer
from edumatcher.logclient.handler import TcpLogHandler
from edumatcher.logclient.protocol import template_id
from tests.conftest import free_port, free_ports

_HOST = "127.0.0.1"


class _RunningServer:
    """Starts a real ``LogServer`` on a background thread for a test."""

    def __init__(self, tmp_path: Path, port: int | None = None) -> None:
        self.port, self.pub_port, self.pull_port = free_ports(3)
        if port is not None:
            self.port = port
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

    def tpl_by_message(self) -> dict[str, str | None]:
        import sqlite3

        conn = sqlite3.connect(str(self.db_path))
        try:
            return dict(conn.execute("SELECT message, tpl FROM log_events").fetchall())
        finally:
            conn.close()

    def query(self, sql: str) -> list[tuple]:
        import sqlite3

        conn = sqlite3.connect(str(self.db_path))
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

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
        free_port(),
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


def test_warning_rows_carry_the_template_id_of_their_call_site(
    running_server: _RunningServer, tmp_path: Path
) -> None:
    """The key is the unformatted template, so every occurrence shares it."""
    handler = TcpLogHandler(
        _HOST,
        running_server.port,
        "pm-test",
        connect_timeout_sec=0.5,
        failover_timeout_sec=5.0,
        failover_dir=tmp_path,
    )
    records = [
        logging.LogRecord(
            "edumatcher.t", logging.WARNING, __file__, 1, "slow %s", ("a",), None
        ),
        logging.LogRecord(
            "edumatcher.t", logging.ERROR, __file__, 1, "slow %s", ("b",), None
        ),
        logging.LogRecord(
            "edumatcher.t", logging.INFO, __file__, 1, "fine %s", ("c",), None
        ),
    ]
    try:
        for record in records:
            handler.emit(record)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and running_server.row_count() < 3:
            time.sleep(0.1)
    finally:
        handler.close()

    expected = template_id("edumatcher.t", "slow %s")
    assert running_server.tpl_by_message() == {
        "slow a": expected,
        "slow b": expected,
        "fine c": None,
    }


def test_failover_writes_to_fallback_file_after_grace_window(tmp_path: Path) -> None:
    """§8.6: once failover_timeout_sec elapses with no server, switch to file."""
    handler = TcpLogHandler(
        _HOST,
        free_port(),  # nothing listening — connection never succeeds
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
        free_port(),
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
        free_port(),
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


# ---------------------------------------------------------------------------
# WP-LOG01: nothing accepted by emit() is lost without a trace (H1, H2)
# ---------------------------------------------------------------------------


def _wait_for(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _fallback_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_close_drains_the_whole_queue_to_the_server(
    running_server: _RunningServer, tmp_path: Path
) -> None:
    """H1: close() sends every queued record before EXIT."""
    handler = TcpLogHandler(
        _HOST,
        running_server.port,
        "pm-test-drain",
        connect_timeout_sec=0.5,
        failover_timeout_sec=30.0,
        failover_dir=tmp_path,
    )
    for i in range(1000):
        handler.emit(_make_record("edumatcher.test", f"crit {i}", logging.CRITICAL))
    handler.close()

    assert _wait_for(lambda: running_server.row_count() >= 1000)
    assert running_server.row_count() == 1000
    assert handler.dropped_count == 0
    assert not (tmp_path / "pm-test-drain.log").exists()


def test_an_exiting_process_stores_its_last_critical_line(
    running_server: _RunningServer, tmp_path: Path
) -> None:
    """H1: a real interpreter exit (logging.shutdown) loses no record."""
    script = textwrap.dedent(f"""
        import logging, sys
        from edumatcher.logclient.discovery import resolve_handler
        handler = resolve_handler(
            log_target=None, log_file=None, client_name="pm-child", instance=None,
            host="{_HOST}", port={running_server.port}, connect_timeout_sec=0.5,
            failover_timeout_sec=30.0, failover_dir={str(tmp_path)!r},
        )
        logging.basicConfig(level=logging.INFO, handlers=[handler])
        log = logging.getLogger("edumatcher.child")
        log.info("starting")
        for i in range(5):
            log.info("shutting down %d", i)
        log.critical("fatal runtime error: %s", "boom")
        sys.exit(1)
        """)
    result = subprocess.run([sys.executable, "-c", script], timeout=30)
    assert result.returncode == 1

    def _settled() -> bool:
        rows = running_server.query(
            "SELECT disconnect_reason, log_count FROM processes "
            "WHERE process = 'pm-child'"
        )
        return bool(rows) and rows[0][0] is not None and rows[0][1] >= 7

    _wait_for(_settled)
    messages = [
        m
        for (m,) in running_server.query(
            "SELECT message FROM log_events WHERE process = 'pm-child' ORDER BY seq"
        )
    ]
    assert len(messages) == 7
    assert messages[-1] == "fatal runtime error: boom"
    assert running_server.query(
        "SELECT disconnect_reason FROM processes WHERE process = 'pm-child'"
    ) == [("client_exit",)]


def test_failover_files_the_grace_window_backlog_in_order(tmp_path: Path) -> None:
    """H2: records queued while reconnecting go to the file, after the marker."""
    handler = TcpLogHandler(
        _HOST,
        free_port(),
        "pm-test-backlog",
        connect_timeout_sec=0.1,
        failover_timeout_sec=1.0,
        failover_dir=tmp_path,
    )
    try:
        for i in range(200):
            handler.emit(_make_record("edumatcher.test", f"backlog {i}"))
        assert not handler._failed_over
        assert _wait_for(lambda: handler._failed_over)
        path = tmp_path / "pm-test-backlog.log"
        lines = _fallback_lines(path)
    finally:
        handler.close()

    assert "pm-log-srv unreachable" in lines[0]
    assert [line.rsplit(" - ", 1)[1] for line in lines[1:]] == [
        f"backlog {i}" for i in range(200)
    ]


def test_failover_files_the_backlog_and_the_drop_count(tmp_path: Path) -> None:
    """H2: a full queue's drops are stated in the file, once."""
    handler = TcpLogHandler(
        _HOST,
        free_port(),
        "pm-test-dropfile",
        queue_maxsize=10,
        connect_timeout_sec=0.1,
        failover_timeout_sec=1.0,
        failover_dir=tmp_path,
    )
    try:
        for i in range(25):
            handler.emit(_make_record("edumatcher.test", f"rec {i}"))
        assert _wait_for(lambda: handler._failed_over)
        lines = _fallback_lines(tmp_path / "pm-test-dropfile.log")
    finally:
        handler.close()

    bodies = [line.rsplit(" - ", 1)[1] for line in lines[1:]]
    assert bodies[:10] == [f"rec {i}" for i in range(10)]
    assert bodies[10:] == [
        "15 log records dropped: the handler queue was full (queue_maxsize=10)"
    ]
    assert handler.dropped_count == 15


def test_drops_are_reported_to_the_server_once_after_reconnect(
    tmp_path: Path,
) -> None:
    """H2: on (re)connect the backlog drains and one WARNING row states the drops."""
    port = free_port()
    handler = TcpLogHandler(
        _HOST,
        port,
        "pm-test-dropreport",
        queue_maxsize=10,
        connect_timeout_sec=0.1,
        failover_timeout_sec=60.0,
        failover_dir=tmp_path,
    )
    for i in range(25):
        handler.emit(_make_record("edumatcher.test", f"rec {i}"))
    rs = _RunningServer(tmp_path, port=port)
    rs.start()
    try:
        assert _wait_for(lambda: rs.row_count() >= 11)
        time.sleep(0.5)
        rows = rs.query("SELECT level, logger, message FROM log_events ORDER BY seq")
    finally:
        handler.close()
        rs.stop()

    assert [m for (_, _, m) in rows[:10]] == [f"rec {i}" for i in range(10)]
    assert rows[10:] == [
        (
            "WARNING",
            "edumatcher.logclient",
            "15 log records dropped: the handler queue was full (queue_maxsize=10)",
        )
    ]
    assert handler.dropped_count == 15


def test_a_server_restart_loses_at_most_one_record(tmp_path: Path) -> None:
    """H2: the frame whose send failed is sent again on the new connection."""
    rs = _RunningServer(tmp_path)
    rs.start()
    handler = TcpLogHandler(
        _HOST,
        rs.port,
        "pm-test-restart",
        connect_timeout_sec=0.2,
        failover_timeout_sec=30.0,
        failover_dir=tmp_path,
    )
    sent = 0
    rs2: _RunningServer | None = None
    # Holds the port while the server is down. Bound but not listening, it
    # refuses connections like a stopped server, yet the kernel cannot hand
    # the port to another xdist worker's bind(0) or to the handler's own
    # connect (a self-connect); either made the restart fail with EADDRINUSE.
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        for phase in ("before", "down", "after"):
            if phase == "down":
                rs.server.stop()
                rs.thread.join(timeout=5.0)
                holder.bind((_HOST, rs.port))
            if phase == "after":
                holder.close()
                rs2 = _RunningServer(tmp_path, port=rs.port)
                rs2.start()
            for _ in range(100):
                handler.emit(_make_record("edumatcher.test", f"r {sent}"))
                sent += 1
                time.sleep(0.01)
        handler.close()
        assert rs2 is not None
        _wait_for(lambda: rs2.row_count() >= sent - 1, timeout=10.0)
        stored = {m for (m,) in rs2.query("SELECT message FROM log_events")}
    finally:
        holder.close()
        if rs2 is not None:
            rs2.stop()

    missing = [i for i in range(sent) if f"r {i}" not in stored]
    assert len(missing) <= 1, missing
    assert handler.dropped_count == 0


def test_close_against_a_dead_server_files_the_queue_within_its_deadline(
    tmp_path: Path,
) -> None:
    """Q1: close() waits at most connect_timeout_sec + 2 s, then files the rest."""
    handler = TcpLogHandler(
        _HOST,
        free_port(),
        "pm-test-deadclose",
        connect_timeout_sec=0.1,
        failover_timeout_sec=30.0,
        failover_dir=tmp_path,
    )
    for i in range(5):
        handler.emit(_make_record("edumatcher.test", f"last {i}"))
    started = time.monotonic()
    handler.close()
    elapsed = time.monotonic() - started

    assert elapsed < 0.1 + 2.0 + 0.5
    lines = _fallback_lines(tmp_path / "pm-test-deadclose.log")
    assert "did not take 5 records" in lines[0]
    assert [line.rsplit(" - ", 1)[1] for line in lines[1:]] == [
        f"last {i}" for i in range(5)
    ]


def test_close_with_nothing_queued_returns_at_once(tmp_path: Path) -> None:
    """An idle handler against a dead server does not wait for the deadline."""
    handler = TcpLogHandler(
        _HOST,
        free_port(),
        "pm-test-idleclose",
        connect_timeout_sec=0.1,
        failover_timeout_sec=30.0,
        failover_dir=tmp_path,
    )
    started = time.monotonic()
    handler.close()
    assert time.monotonic() - started < 0.5
    assert not (tmp_path / "pm-test-idleclose.log").exists()


# ---------------------------------------------------------------------------
# WP-LOG07: the client follows the LALF specification (C6, C7, C8)
# ---------------------------------------------------------------------------


class _FakePeer:
    """A listening socket whose behaviour per connection a test chooses."""

    def __init__(self, on_conn: Callable[[socket.socket], None]) -> None:
        self.listener = socket.create_server((_HOST, 0))
        self.port = self.listener.getsockname()[1]
        self.conns: list[socket.socket] = []
        self._on_conn = on_conn
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            self.conns.append(conn)
            self._on_conn(conn)

    def close(self) -> None:
        self.listener.close()
        for conn in self.conns:
            conn.close()


def test_seq_restarts_at_one_on_every_connection(tmp_path: Path) -> None:
    """C6: LALF §SEQ — a reconnecting client MUST restart SEQ at 1."""
    from edumatcher.logclient.protocol import FrameReader

    received: list[list[str]] = []

    def _welcome_and_record(conn: socket.socket) -> None:
        conn.recv(4096)
        conn.sendall(b"WELCOME|PROTO=LALF1|SRV=t|HBINT=5|SESSION=s\n")
        seqs: list[str] = []
        received.append(seqs)
        reader = FrameReader()
        conn.settimeout(0.5)
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                reader.feed(data)
                while (frame := reader.next_frame()) is not None:
                    if frame.msg_type == "LOG":
                        seqs.append(frame.fields["SEQ"])
                if len(received) == 1 and len(seqs) >= 3:
                    break  # the first session ends: the "server restarts"
        except OSError:
            pass
        conn.close()

    peer = _FakePeer(_welcome_and_record)
    handler = TcpLogHandler(
        _HOST,
        peer.port,
        "pm-test-seq",
        connect_timeout_sec=0.5,
        failover_timeout_sec=30.0,
        failover_dir=tmp_path,
    )
    try:
        for i in range(3):
            handler.emit(_make_record("edumatcher.test", f"first {i}"))
        assert _wait_for(lambda: len(received) == 1 and len(received[0]) == 3)
        time.sleep(0.3)
        for i in range(3):
            handler.emit(_make_record("edumatcher.test", f"second {i}"))
            time.sleep(0.2)
        assert _wait_for(lambda: len(received) >= 2 and len(received[-1]) >= 2)
    finally:
        handler.close()
        peer.close()
    assert received[0] == ["1", "2", "3"]
    assert received[-1][0] == "1"


def test_a_peer_that_stops_reading_leads_to_failover(tmp_path: Path) -> None:
    """C7: sendall to a silent peer times out instead of blocking for good."""
    blocked: list[socket.socket] = []

    def _welcome_then_never_read(conn: socket.socket) -> None:
        conn.recv(4096)
        if blocked:
            return  # later connections never get a WELCOME
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        conn.sendall(b"WELCOME|PROTO=LALF1|SRV=t|HBINT=5|SESSION=s\n")
        blocked.append(conn)

    peer = _FakePeer(_welcome_then_never_read)
    handler = TcpLogHandler(
        _HOST,
        peer.port,
        "pm-test-silent",
        queue_maxsize=5000,
        connect_timeout_sec=0.2,
        failover_timeout_sec=1.0,
        failover_dir=tmp_path,
    )
    try:
        big = "x" * 20_000
        assert _wait_for(lambda: bool(blocked))
        for _ in range(3000):  # 60 MB: far more than any socket buffer
            handler.emit(_make_record("edumatcher.test", big))
        # failover_timeout_sec + the send timeout (at least 2 s) + slack
        assert _wait_for(lambda: handler._failed_over, timeout=8.0)
    finally:
        handler.close()
        peer.close()


def test_a_failed_handshake_closes_its_socket(tmp_path: Path) -> None:
    """C8: no unclosed socket is left behind by a failed handshake."""
    import gc
    import warnings

    peer = _FakePeer(lambda conn: conn.close())  # hang up before WELCOME
    handler = TcpLogHandler(
        _HOST,
        free_port(),
        "pm-test-leak",
        connect_timeout_sec=0.5,
        failover_timeout_sec=30.0,
        failover_dir=tmp_path,
    )
    handler.close()
    handler._port = peer.port
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            for _ in range(10):
                assert handler._try_connect()[0] is None
            gc.collect()
    finally:
        peer.close()
    assert not [w for w in caught if issubclass(w.category, ResourceWarning)]
