from __future__ import annotations

import socket
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from edumatcher.log_srv.config import LogServerConfig
from edumatcher.log_srv.server import LogServer

_HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((_HOST, 0))
        return s.getsockname()[1]


class _RunningServer:
    """Test fixture wrapper: starts a LogServer on a background thread."""

    def __init__(self, tmp_path: Path, **config_overrides: object) -> None:
        self.port = _free_port()
        # LALF-PS binds two more sockets. Ephemeral ports keep concurrent test
        # workers (and any pm-log-srv the developer happens to have running on
        # the default 5601/5602) from colliding.
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
            **config_overrides,
        )
        self.server = LogServer(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        time.sleep(0.3)

    def connect(self, timeout: float = 2.0) -> socket.socket:
        return socket.create_connection((_HOST, self.port), timeout=timeout)

    def stop(self) -> None:
        self.server.stop()
        time.sleep(0.4)

    def db(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))


@pytest.fixture
def running_server(tmp_path: Path):
    rs = _RunningServer(tmp_path)
    rs.start()
    yield rs
    rs.stop()


def _recv_all(sock: socket.socket, timeout: float = 0.5) -> bytes:
    sock.settimeout(timeout)
    chunks = []
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            # Heuristic: LALF responses are short; stop once we've read something
            # and no more arrives within the timeout window.
            sock.settimeout(0.1)
    except socket.timeout:
        pass
    return b"".join(chunks)


def test_hello_welcome_handshake(running_server: _RunningServer) -> None:
    s = running_server.connect()
    s.sendall(b"HELLO|CLIENT=pm-api-gwy|PID=123|HOST=trader-laptop|PROTO=LALF1\n")
    resp = _recv_all(s)
    assert b"WELCOME" in resp
    assert b"SRV=" in resp
    assert b"SESSION=" in resp
    s.close()


def test_hello_rejects_bad_proto(running_server: _RunningServer) -> None:
    s = running_server.connect()
    s.sendall(b"HELLO|CLIENT=x|PID=1|HOST=h|PROTO=BOGUS\n")
    resp = _recv_all(s)
    assert b"ERR" in resp
    assert b"PROTO_MISMATCH" in resp
    s.close()


def test_hello_rejects_missing_field(running_server: _RunningServer) -> None:
    s = running_server.connect()
    s.sendall(b"HELLO|CLIENT=x|PID=1|PROTO=LALF1\n")  # missing HOST
    resp = _recv_all(s)
    assert b"MISSING_FIELD" in resp
    s.close()


def test_hello_timeout_disconnects_client(tmp_path: Path) -> None:
    rs = _RunningServer(tmp_path)
    rs.start()
    try:
        s = rs.connect()
        # Send nothing; server should disconnect after HELLO_TIMEOUT_SEC (5s).
        # We don't want to sleep 5s in a test, so just verify the connection
        # eventually reads EOF within a generous bound instead of asserting
        # exact timing (keeps this test robust against CI scheduling jitter).
        s.settimeout(8.0)
        data = s.recv(4096)
        # Either we get an ERR (HELLO_TIMEOUT) or the socket is closed (b"").
        assert data == b"" or b"HELLO_TIMEOUT" in data
        s.close()
    finally:
        rs.stop()


def test_log_message_persisted_with_full_fidelity(
    running_server: _RunningServer,
) -> None:
    s = running_server.connect()
    s.sendall(b"HELLO|CLIENT=pm-md-gwy|PID=51002|HOST=trader-laptop|PROTO=LALF1\n")
    _recv_all(s)

    message = "slow client|weird\nunicode ünïcödé traceback"
    payload = message.encode("utf-8")
    header = (
        f"LOG|SEQ=1|TS=2026-07-28T14:00:00.000Z|LEVEL=WARNING|"
        f"LOGGER=edumatcher.md_gateway.gateway|LEN={len(payload)}\n"
    ).encode()
    s.sendall(header + payload)
    time.sleep(0.5)
    s.sendall(b"EXIT\n")
    time.sleep(0.3)
    s.close()

    conn = running_server.db()
    rows = conn.execute(
        "SELECT process, level, logger, message, truncated FROM log_events"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "pm-md-gwy"
    assert rows[0][1] == "WARNING"
    assert rows[0][3] == message
    assert rows[0][4] == 0

    procs = conn.execute(
        "SELECT process, pid, host, disconnected_at, log_count FROM processes"
    ).fetchall()
    assert len(procs) == 1
    assert procs[0][4] == 1
    assert procs[0][3] is not None  # disconnected after EXIT


def test_invalid_level_rejected_with_advisory_err(
    running_server: _RunningServer,
) -> None:
    s = running_server.connect()
    s.sendall(b"HELLO|CLIENT=x|PID=1|HOST=h|PROTO=LALF1\n")
    _recv_all(s)
    s.sendall(b"LOG|SEQ=1|TS=x|LEVEL=TRACE|LOGGER=y|LEN=1\nz")
    resp = _recv_all(s)
    assert b"INVALID_LEVEL" in resp
    s.close()


def test_oversized_payload_truncated_not_dropped(tmp_path: Path) -> None:
    rs = _RunningServer(tmp_path, max_message_bytes=10)
    rs.start()
    try:
        s = rs.connect()
        s.sendall(b"HELLO|CLIENT=x|PID=1|HOST=h|PROTO=LALF1\n")
        _recv_all(s)

        message = "this message is definitely longer than ten bytes"
        payload = message.encode("utf-8")
        header = f"LOG|SEQ=1|TS=x|LEVEL=INFO|LOGGER=y|LEN={len(payload)}\n".encode()
        s.sendall(header + payload)
        resp = _recv_all(s)
        assert b"PAYLOAD_TOO_LARGE" in resp
        time.sleep(0.4)
        s.close()

        conn = rs.db()
        rows = conn.execute("SELECT message, truncated FROM log_events").fetchall()
        assert len(rows) == 1
        assert rows[0][1] == 1
        assert len(rows[0][0].encode("utf-8")) <= 10
    finally:
        rs.stop()


def test_ping_pong(running_server: _RunningServer) -> None:
    s = running_server.connect()
    s.sendall(b"HELLO|CLIENT=x|PID=1|HOST=h|PROTO=LALF1\n")
    _recv_all(s)
    s.sendall(b"PING\n")
    resp = _recv_all(s)
    assert b"PONG" in resp
    s.close()


def test_concurrent_clients_all_rows_persisted(tmp_path: Path) -> None:
    """Multiple simultaneous connections writing must not lose or corrupt rows."""
    rs = _RunningServer(tmp_path)
    rs.start()
    try:
        n_clients = 5
        n_msgs_per_client = 20
        sockets = []
        for i in range(n_clients):
            s = rs.connect()
            s.sendall(f"HELLO|CLIENT=pm-c{i}|PID={i}|HOST=h|PROTO=LALF1\n".encode())
            _recv_all(s)
            sockets.append(s)

        for i, s in enumerate(sockets):
            for j in range(n_msgs_per_client):
                msg = f"message {j} from client {i}"
                payload = msg.encode("utf-8")
                header = f"LOG|SEQ={j+1}|TS=x|LEVEL=INFO|LOGGER=y|LEN={len(payload)}\n".encode()
                s.sendall(header + payload)

        time.sleep(1.0)
        for s in sockets:
            s.close()
        time.sleep(0.3)

        conn = rs.db()
        total = conn.execute("SELECT COUNT(*) FROM log_events").fetchone()[0]
        assert total == n_clients * n_msgs_per_client
    finally:
        rs.stop()


def test_retention_pruning_deletes_only_old_rows(tmp_path: Path) -> None:
    rs = _RunningServer(tmp_path, retention_days=30)
    rs.start()
    try:
        from edumatcher.logclient.protocol import iso_utc

        old_ts = iso_utc(time.time() - 40 * 86400)
        new_ts = iso_utc(time.time())
        with rs.server._conn:
            for ts, msg in ((old_ts, "old"), (new_ts, "new")):
                rs.server._conn.execute(
                    "INSERT INTO log_events (client_ts, server_ts, process, instance, "
                    "pid, host, session, level, logger, module, line, has_exception, "
                    "truncated, message) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        ts,
                        ts,
                        "pm-x",
                        None,
                        1,
                        "h",
                        "s1",
                        "INFO",
                        "l",
                        None,
                        None,
                        0,
                        0,
                        msg,
                    ),
                )
        deleted = rs.server._prune_older_than(30)
        assert deleted == 1
        remaining = rs.server._conn.execute("SELECT message FROM log_events").fetchall()
        assert remaining == [("new",)]
    finally:
        rs.stop()
