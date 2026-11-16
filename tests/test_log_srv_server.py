from __future__ import annotations

import socket
import sqlite3
import struct
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from edumatcher.log_srv.config import LogServerConfig
from edumatcher.log_srv.schema import SCHEMA_VERSION, LogDbSchemaError, open_db
from edumatcher.log_srv.server import LogServer
from edumatcher.log_srv.session import LogSession
from edumatcher.log_srv.writer import LogEventRow, WriterThread
from edumatcher.logclient.protocol import iso_utc
from tests.conftest import free_ports, opened

_HOST = "127.0.0.1"


class _RunningServer:
    """Test fixture wrapper: starts a LogServer on a background thread."""

    # `object` makes the **splat below uncheckable; `Any` is the honest type
    # for arbitrary per-test overrides and lets mypy verify the call.
    def __init__(self, tmp_path: Path, **config_overrides: Any) -> None:
        # LALF-PS binds two more sockets. Ephemeral ports keep concurrent test
        # workers (and any pm-log-srv the developer happens to have running on
        # the default 5601/5602) from colliding. They are allocated together
        # so the kernel cannot hand the same port out twice.
        self.port, self.pub_port, self.pull_port = free_ports(3)
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
        self._extra_conns: list[sqlite3.Connection] = []

    def start(self) -> None:
        self.thread.start()
        time.sleep(0.3)

    def connect(self, timeout: float = 2.0) -> socket.socket:
        return socket.create_connection((_HOST, self.port), timeout=timeout)

    def stop(self) -> None:
        self.server.stop()
        time.sleep(0.4)
        for conn in self._extra_conns:
            conn.close()

    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        self._extra_conns.append(conn)
        return conn


@pytest.fixture
def running_server(tmp_path: Path):
    rs = _RunningServer(tmp_path)
    rs.start()
    yield rs
    rs.stop()


def _prune_to_completion(server: LogServer) -> int:
    """Run retention passes until the prune in progress is finished."""
    server._last_retention_check = -1e12  # due now
    server._run_retention_if_due()
    while server._prune_cutoff is not None:
        server._run_retention_if_due()
    return server._pruned


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
        # The ERR is flushed before the close, not discarded with the socket.
        assert b"HELLO_TIMEOUT" in data
        assert s.recv(4096) == b""
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
        # One advisory ERR was sent, so it is counted once, at the next
        # heartbeat flush (heartbeat_interval_sec=1).
        deadline = time.monotonic() + 3.0
        errors = None
        while time.monotonic() < deadline and errors != (1,):
            time.sleep(0.1)
            errors = conn.execute(
                "SELECT total_errors_sent FROM server_stats"
            ).fetchone()
        assert errors == (1,)
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


def test_a_new_log_db_is_stamped_with_the_current_schema_version(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "log.db"
    open_db(db_path).close()

    conn = open_db(db_path)  # reopening a current file is fine
    assert conn.execute("SELECT version FROM schema_version").fetchall() == [
        (SCHEMA_VERSION,)
    ]
    conn.close()
    open_db(db_path, read_only=True).close()


def test_log_gui_bridge_reads_the_same_schema_version() -> None:
    """The bridge refuses any other version, so the two must move together."""
    import re

    bridge = Path(__file__).parent.parent / "web-apps/log-gui/apps/bridge/src/log-db.ts"
    match = re.search(r"LOG_DB_SCHEMA_VERSION = (\d+);", bridge.read_text())
    assert match is not None
    assert int(match.group(1)) == SCHEMA_VERSION


def _write_v1_log_db(db_path: Path) -> None:
    """A log.db as written before the schema_version table existed."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        "CREATE TABLE log_events (seq INTEGER PRIMARY KEY, message TEXT);"
        "INSERT INTO log_events (message) VALUES ('old');"
    )
    conn.commit()
    conn.close()


@pytest.mark.parametrize("read_only", [False, True])
def test_a_log_db_without_a_version_table_is_refused(
    tmp_path: Path, read_only: bool
) -> None:
    db_path = tmp_path / "log.db"
    _write_v1_log_db(db_path)

    with pytest.raises(LogDbSchemaError, match="schema version 1.*delete"):
        open_db(db_path, read_only=read_only)

    # Refused, not migrated: the old file is left exactly as it was.
    conn = sqlite3.connect(str(db_path))
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert tables == {"log_events"}


def test_a_log_db_of_another_version_is_refused(tmp_path: Path) -> None:
    db_path = tmp_path / "log.db"
    open_db(db_path).close()
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION + 1,))
    conn.commit()
    conn.close()

    with pytest.raises(LogDbSchemaError, match=f"schema version {SCHEMA_VERSION + 1}"):
        open_db(db_path)


def test_pm_log_srv_exits_on_an_old_log_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from edumatcher.log_srv import main as log_srv_main

    db_path = tmp_path / "log.db"
    _write_v1_log_db(db_path)
    monkeypatch.setattr("sys.argv", ["pm-log-srv", "--db", str(db_path)])

    with caplog.at_level("CRITICAL"), pytest.raises(SystemExit) as excinfo:
        log_srv_main.main()

    assert excinfo.value.code == 1
    assert "refusing to start" in caplog.text


def test_log_frame_template_id_is_persisted(running_server: _RunningServer) -> None:
    s = running_server.connect()
    s.sendall(b"HELLO|CLIENT=pm-x|PID=1|HOST=h|PROTO=LALF1\n")
    _recv_all(s)
    for level, tpl_field in (("WARNING", "|TPL=0123456789ab"), ("INFO", "")):
        header = f"LOG|SEQ=1|TS=x|LEVEL={level}|LOGGER=y{tpl_field}|LEN=1\n"
        s.sendall(header.encode() + b"z")
    time.sleep(0.5)
    s.close()

    rows = (
        running_server.db()
        .execute("SELECT level, tpl FROM log_events ORDER BY seq")
        .fetchall()
    )
    assert rows == [("WARNING", "0123456789ab"), ("INFO", None)]


def test_heartbeat_advances_last_heartbeat_at(tmp_path: Path) -> None:
    """A quiet client that only heartbeats must still look alive in the DB.

    Guards the false ``process_silence`` diagnosis: ``last_seen_at`` only
    advances on LOG frames, so an idle-but-healthy process needs HB to leave
    a trace of its own.
    """
    rs = _RunningServer(tmp_path)
    rs.start()
    try:
        s = rs.connect()
        s.sendall(b"HELLO|CLIENT=pm-dc-gwy|PID=1|HOST=h|PROTO=LALF1\n")
        _recv_all(s)

        # Registration is deferred to first activity, so the row only
        # exists once the client has heartbeated at least once.
        s.sendall(b"HB\n")
        time.sleep(0.4)
        before = (
            rs.db().execute("SELECT last_heartbeat_at FROM processes").fetchone()[0]
        )

        s.sendall(b"HB\n")
        time.sleep(rs.config.heartbeat_interval_sec + 0.5)

        row = (
            rs.db()
            .execute("SELECT last_seen_at, last_heartbeat_at FROM processes")
            .fetchone()
        )
        assert row[1] is not None
        assert row[1] > before
        # No LOG frame was ever sent, so the log clock must not have moved.
        assert row[0] < row[1]
        s.close()
    finally:
        rs.stop()


def test_exit_frame_records_a_clean_disconnect_reason(tmp_path: Path) -> None:
    """``diagnose`` needs EXIT distinguishable from a process that vanished."""
    rs = _RunningServer(tmp_path)
    rs.start()
    try:
        s = rs.connect()
        s.sendall(b"HELLO|CLIENT=pm-viewer|PID=1|HOST=h|PROTO=LALF1\n")
        _recv_all(s)
        s.sendall(b"HB\n")
        time.sleep(0.3)
        s.sendall(b"EXIT\n")
        time.sleep(0.4)
        row = (
            rs.db()
            .execute("SELECT disconnected_at, disconnect_reason FROM processes")
            .fetchone()
        )
        assert row[0] is not None
        assert row[1] == "client_exit"
        s.close()
    finally:
        rs.stop()


def test_dropped_connection_records_an_abnormal_disconnect_reason(
    tmp_path: Path,
) -> None:
    rs = _RunningServer(tmp_path)
    rs.start()
    try:
        s = rs.connect()
        s.sendall(b"HELLO|CLIENT=pm-viewer|PID=1|HOST=h|PROTO=LALF1\n")
        _recv_all(s)
        s.sendall(b"HB\n")
        time.sleep(0.3)
        s.close()
        time.sleep(0.4)
        reason = (
            rs.db().execute("SELECT disconnect_reason FROM processes").fetchone()[0]
        )
        assert reason == "peer_closed"
    finally:
        rs.stop()


def test_reachability_probe_leaves_no_process_row(tmp_path: Path) -> None:
    """A HELLO/WELCOME probe must not register a process that never ran.

    ``discovery._probe_server`` opens a short-lived socket purely to decide
    whether a server is listening. Registering it made ``processes`` fill
    with phantom rows for tools that were never started — on a live system
    they outnumbered real sessions ten to one and buried every genuine
    process-level diagnostic.
    """
    rs = _RunningServer(tmp_path)
    rs.start()
    try:
        s = rs.connect()
        s.sendall(b"HELLO|CLIENT=pm-viewer|PID=1|HOST=h|PROTO=LALF1\n")
        _recv_all(s)
        s.close()
        time.sleep(0.4)
        assert rs.db().execute("SELECT COUNT(*) FROM processes").fetchone()[0] == 0
    finally:
        rs.stop()


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
        deleted = _prune_to_completion(rs.server)
        assert deleted == 1
        remaining = rs.server._conn.execute("SELECT message FROM log_events").fetchall()
        assert remaining == [("new",)]
    finally:
        rs.stop()


def test_session_bookkeeping_waits_for_the_writer_lock(
    running_server: _RunningServer,
) -> None:
    # The main loop shares the writer thread's connection. Unserialised, a
    # commit from one thread could land inside the other's transaction and
    # kill pm-log-srv ("cannot commit - no transaction is active").
    lock = running_server.server._writer.lock
    s = running_server.connect()
    with lock:
        s.sendall(b"HELLO|CLIENT=pm-test|PID=1|HOST=h|PROTO=LALF1\n")
        assert b"WELCOME" not in _recv_all(s, timeout=0.5)
    assert b"WELCOME" in _recv_all(s, timeout=2.0)
    s.close()


def test_a_reset_connection_records_an_io_error(tmp_path: Path) -> None:
    """A peer that vanishes with RST is a crash, not an idle client."""
    rs = _RunningServer(tmp_path)
    rs.start()
    try:
        s = rs.connect()
        s.sendall(b"HELLO|CLIENT=pm-viewer|PID=1|HOST=h|PROTO=LALF1\n")
        _recv_all(s)
        s.sendall(b"HB\n")
        time.sleep(0.3)
        # Linger 0: close() sends RST instead of FIN.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        s.close()
        time.sleep(0.4)
        reason = (
            rs.db().execute("SELECT disconnect_reason FROM processes").fetchone()[0]
        )
        assert reason == "io_error"
    finally:
        rs.stop()


def test_frames_after_a_protocol_violation_are_not_accepted(
    running_server: _RunningServer,
) -> None:
    s = running_server.connect()
    body = b"x"
    s.sendall(
        b"HELLO|CLIENT=x|PID=1|HOST=h|PROTO=LALF1\n"
        b"HELLO|CLIENT=x|PID=1|HOST=h|PROTO=LALF1\n"
        b"LOG|SEQ=1|TS=2026-07-28T14:00:00.000Z|LEVEL=INFO|LOGGER=y|LEN=1\n" + body
    )
    resp = _recv_all(s, timeout=1.0)
    assert resp.count(b"ERR") == 1
    time.sleep(0.4)
    conn = running_server.db()
    assert conn.execute("SELECT COUNT(*) FROM log_events").fetchone() == (0,)
    s.close()


class _BackloggedWriter:
    """Stands in for WriterThread with a fixed uncommitted-row count."""

    def __init__(self, pending: int) -> None:
        self.pending = pending
        self.lock = threading.Lock()


def test_reads_stop_while_the_writer_is_backlogged(tmp_path: Path) -> None:
    """§5.8/§15.13: a writer backlog throttles producers via TCP, and their
    unread heartbeats do not get them dropped as idle meanwhile."""
    server = LogServer(
        LogServerConfig(
            bind_address=_HOST,
            db_path=tmp_path / "log.db",
            max_client_queue=10,
            pubsub_enabled=False,
        )
    )
    a, b = socket.socketpair()
    try:
        a.setblocking(False)
        session = LogSession(sock=a, addr=(_HOST, 0))
        session.authenticated = True
        session.last_activity = time.monotonic() - 3600
        server._clients[a.fileno()] = session
        b.sendall(b"PING\n")
        time.sleep(0.05)
        real_writer = server._writer
        server._writer = _BackloggedWriter(pending=11)

        server._read_client_data()
        server._drop_idle_clients()
        assert session.out_queue == []  # PING left unread in the kernel
        assert a.fileno() in server._clients  # not dropped as idle

        server._writer = _BackloggedWriter(pending=10)
        server._read_client_data()
        assert any(b"PONG" in line for line in session.out_queue)
        server._writer = real_writer
    finally:
        b.close()
        server.close()


def test_retention_prunes_in_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import edumatcher.log_srv.server as server_mod

    monkeypatch.setattr(server_mod, "PRUNE_CHUNK_ROWS", 2)
    server = LogServer(LogServerConfig(bind_address=_HOST, db_path=tmp_path / "log.db"))
    try:
        with server._conn:
            for ts, msg in [("2000-01-01T00:00:00.000Z", "old")] * 5 + [
                (iso_utc(time.time()), "new")
            ]:
                server._conn.execute(
                    "INSERT INTO log_events (client_ts, server_ts, process, pid, "
                    "host, session, level, logger, message) "
                    "VALUES (?,?,'p',1,'h','s','INFO','l',?)",
                    (ts, ts, msg),
                )
        assert _prune_to_completion(server) == 5
        assert server._conn.execute("SELECT message FROM log_events").fetchall() == [
            ("new",)
        ]
    finally:
        server.close()


def test_log_db_uses_wal(tmp_path: Path) -> None:
    """Readers (pm-log-cli, backfill) must not block the writer's commits."""
    conn = open_db(tmp_path / "log.db")
    assert conn.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    conn.close()


def _event(i: int) -> LogEventRow:
    ts = iso_utc(time.time())
    return LogEventRow(
        ts,
        ts,
        "p",
        None,
        1,
        "h",
        "s",
        "INFO",
        "l",
        None,
        None,
        False,
        False,
        f"m{i}",
        None,
    )


def test_writer_flushes_its_whole_backlog_at_shutdown(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "log.db")
    writer = WriterThread(conn, batch_size=50)
    for i in range(500):
        writer.enqueue(_event(i))
    writer.stop()  # never started: everything is still queued
    assert conn.execute("SELECT COUNT(*) FROM log_events").fetchone() == (500,)
    conn.close()


class _FailingOnceConn:
    """Delegates to a real connection; the first INSERT batch fails."""

    def __init__(
        self, conn: sqlite3.Connection, error: Exception | None = None
    ) -> None:
        self._conn = conn
        self._error = error or sqlite3.OperationalError("database is locked")
        self.failed = False

    def __enter__(self) -> "_FailingOnceConn":
        self._conn.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self._conn.__exit__(*exc)

    def executemany(self, sql: str, rows: Any) -> Any:
        if not self.failed:
            self.failed = True
            raise self._error
        return self._conn.executemany(sql, rows)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def test_writer_retries_a_failed_batch_instead_of_dropping_it(
    tmp_path: Path,
) -> None:
    conn = open_db(tmp_path / "log.db")
    flaky = _FailingOnceConn(conn)
    writer = WriterThread(flaky, batch_size=50)  # type: ignore[arg-type]
    for i in range(3):
        writer.enqueue(_event(i))

    assert writer._drain_and_write(force=True) == 0
    assert writer.pending == 3  # kept, and counted for backpressure
    assert writer._drain_and_write(force=True) == 3
    assert [r[0] for r in conn.execute("SELECT message FROM log_events")] == [
        "m0",
        "m1",
        "m2",
    ]
    conn.close()


# ---------------------------------------------------------------------------
# WP-LOG02: every session row is closed with a reason (C1, C12)
# ---------------------------------------------------------------------------


def _register(rs: _RunningServer, client: str) -> socket.socket:
    s = rs.connect()
    s.sendall(f"HELLO|CLIENT={client}|PID=1|HOST=h|PROTO=LALF1\n".encode())
    _recv_all(s)
    s.sendall(b"HB\n")
    return s


def test_server_stop_closes_every_session_with_server_stop(tmp_path: Path) -> None:
    rs = _RunningServer(tmp_path)
    rs.start()
    socks = [_register(rs, f"pm-proc{i}") for i in range(3)]
    time.sleep(0.3)
    rs.stop()
    try:
        rows = (
            rs.db()
            .execute(
                "SELECT process, disconnected_at, disconnect_reason FROM processes "
                "ORDER BY process"
            )
            .fetchall()
        )
    finally:
        for s in socks:
            s.close()
        for conn in rs._extra_conns:
            conn.close()
    assert [(p, r) for p, _, r in rows] == [
        ("pm-proc0", "server_stop"),
        ("pm-proc1", "server_stop"),
        ("pm-proc2", "server_stop"),
    ]
    assert all(d is not None for _, d, _ in rows)


def test_start_up_closes_sessions_a_crashed_server_left_open(tmp_path: Path) -> None:
    """A row left open by a server that never ran close() is closed at start."""
    crashed = _RunningServer(tmp_path)
    crashed.start()
    s = _register(crashed, "pm-orphan")
    time.sleep(0.3)
    # Simulate the crash: the loop stops, but close() never runs.
    crashed.server._running = False
    crashed.server.close = lambda: None
    crashed.thread.join(timeout=2)
    s.close()
    open_rows = sqlite3.connect(str(tmp_path / "log.db"))
    try:
        before = open_rows.execute(
            "SELECT disconnect_reason FROM processes WHERE disconnected_at IS NULL"
        ).fetchall()
    finally:
        open_rows.close()
    assert before == [(None,)]

    restarted = LogServer(crashed.config)
    try:
        conn = sqlite3.connect(str(tmp_path / "log.db"))
        try:
            rows = conn.execute(
                "SELECT disconnected_at IS NOT NULL, disconnect_reason FROM processes"
            ).fetchall()
        finally:
            conn.close()
    finally:
        restarted.close()
        crashed.server._writer.stop()
        crashed.server._conn.close()
        crashed.server._prune_conn.close()
        if crashed.server._server is not None:
            crashed.server._server.close()
        if crashed.server._pubsub is not None:
            crashed.server._pubsub.stop()
    assert rows == [(1, "server_restart")]


def test_close_twice_writes_the_reasons_once_and_logs_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rs = _RunningServer(tmp_path)
    rs.start()
    s = _register(rs, "pm-once")
    time.sleep(0.3)
    caplog.set_level("INFO", logger="edumatcher.log_srv.server")
    rs.stop()  # run() ends and calls close()
    first = rs.db().execute("SELECT disconnected_at FROM processes").fetchone()[0]
    time.sleep(1.1)
    rs.server.close()  # main() calls it again
    try:
        second = rs.db().execute("SELECT disconnected_at FROM processes").fetchone()[0]
    finally:
        s.close()
        for conn in rs._extra_conns:
            conn.close()
    assert first == second
    closing = [r for r in caplog.records if r.getMessage() == "closing pm-log-srv"]
    assert len(closing) == 1


# ---------------------------------------------------------------------------
# WP-LOG03: no client input stops collection silently (C2, C9)
# ---------------------------------------------------------------------------


def test_hello_with_a_pid_beyond_int64_is_refused(
    running_server: _RunningServer,
) -> None:
    s = running_server.connect()
    s.sendall(f"HELLO|CLIENT=x|PID={2**64}|HOST=h|PROTO=LALF1\n".encode())
    resp = _recv_all(s)
    s.close()
    assert b"ERR|CODE=MISSING_FIELD" in resp
    assert running_server.thread.is_alive()
    s2 = running_server.connect()
    s2.sendall(b"HELLO|CLIENT=x|PID=1|HOST=h|PROTO=LALF1\n")
    assert b"WELCOME" in _recv_all(s2)
    s2.close()


def test_a_line_beyond_int64_is_stored_as_null(running_server: _RunningServer) -> None:
    s = running_server.connect()
    s.sendall(b"HELLO|CLIENT=x|PID=1|HOST=h|PROTO=LALF1\n")
    _recv_all(s)
    s.sendall(
        f"LOG|SEQ=1|TS=x|LEVEL=INFO|LOGGER=y|LINE={2**64}|LEN=3\nbad".encode()
        + b"LOG|SEQ=2|TS=x|LEVEL=INFO|LOGGER=y|LINE=7|LEN=4\ngood"
    )
    deadline = time.monotonic() + 1.0
    rows: list[Any] = []
    while time.monotonic() < deadline and len(rows) < 2:
        time.sleep(0.05)
        rows = (
            running_server.db()
            .execute("SELECT message, line FROM log_events ORDER BY seq")
            .fetchall()
        )
    s.close()
    assert rows == [("bad", None), ("good", 7)]


def test_the_writer_retries_a_batch_after_a_non_sqlite_error(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "log.db")
    writer = WriterThread(conn, batch_size=10, batch_interval_ms=10)
    writer._conn = _FailingOnceConn(conn, OverflowError("boom"))
    writer.start()
    try:
        writer.enqueue(_event(1))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and writer.pending:
            time.sleep(0.02)
        assert writer._thread is not None and writer._thread.is_alive()
    finally:
        writer.stop()
    try:
        assert conn.execute("SELECT COUNT(*) FROM log_events").fetchone() == (1,)
    finally:
        conn.close()


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_dead_writer_thread_stops_the_server(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rs = _RunningServer(tmp_path)
    # close() dies in writer.stop() too, before it reaches the connections.
    opened(rs.server._conn)
    opened(rs.server._prune_conn)

    def _die(*, force: bool) -> int:
        raise RuntimeError("writer bug")

    rs.server._writer._drain_and_write = _die
    errors: list[BaseException] = []

    def _run() -> None:
        try:
            rs.server.run()
        except BaseException as exc:  # noqa: BLE001 - the test inspects it
            errors.append(exc)

    caplog.set_level("CRITICAL", logger="edumatcher.log_srv.server")
    rs.thread = threading.Thread(target=_run, daemon=True)
    rs.thread.start()
    rs.thread.join(timeout=3.0)
    assert not rs.thread.is_alive()
    assert len(errors) == 1 and "writer" in str(errors[0])
    assert any(r.levelname == "CRITICAL" for r in caplog.records)


# ---------------------------------------------------------------------------
# WP-LOG06: the main loop never stalls on retention, error replies or reads
# ---------------------------------------------------------------------------


def _insert_old_rows(server: LogServer, n: int, old: bool = True) -> None:
    ts = "2000-01-01T00:00:00.000Z" if old else iso_utc(time.time())
    with server._conn:
        server._conn.executemany(
            "INSERT INTO log_events (client_ts, server_ts, process, pid, "
            "host, session, level, logger, message) "
            "VALUES (?,?,'p',1,'h','s','INFO','l',?)",
            [(ts, ts, "old" if old else "new") for _ in range(n)],
        )


def test_one_retention_pass_deletes_at_most_one_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import edumatcher.log_srv.server as server_mod

    monkeypatch.setattr(server_mod, "PRUNE_CHUNK_ROWS", 2)
    server = LogServer(LogServerConfig(bind_address=_HOST, db_path=tmp_path / "log.db"))
    try:
        _insert_old_rows(server, 5)
        _insert_old_rows(server, 1, old=False)

        def remaining() -> int:
            return int(
                server._conn.execute("SELECT COUNT(*) FROM log_events").fetchone()[0]
            )

        counts = []
        for _ in range(5):
            server._run_retention_if_due()
            counts.append(remaining())
        assert counts == [4, 2, 1, 1, 1]
        assert server._conn.execute("SELECT message FROM log_events").fetchall() == [
            ("new",)
        ]
    finally:
        server.close()


def test_err_replies_are_counted_without_a_commit_each(tmp_path: Path) -> None:
    server = LogServer(LogServerConfig(bind_address=_HOST, db_path=tmp_path / "log.db"))
    statements: list[str] = []
    server._conn.set_trace_callback(statements.append)
    try:
        a, b = socket.socketpair()
        session = LogSession(sock=a, addr=("x", 0))
        for _ in range(1000):
            server._queue_line(session, "ERR", {"CODE": "BAD_MESSAGE", "MSG": "x"})
        assert not [s for s in statements if "UPDATE server_stats" in s]
        server._last_heartbeat_flush = 0.0
        server._persist_heartbeats_if_due()
        assert server._conn.execute(
            "SELECT total_errors_sent FROM server_stats"
        ).fetchone() == (1000,)
        assert len([s for s in statements if "UPDATE server_stats" in s]) == 1
        a.close()
        b.close()
    finally:
        server._conn.set_trace_callback(None)
        server.close()


def test_one_client_is_ingested_at_several_thousand_rows_a_second(
    tmp_path: Path,
) -> None:
    """P5: measured 1 730 rows/s before (4096 bytes per 10 ms pass)."""
    rs = _RunningServer(tmp_path)
    rs.start()
    try:
        s = rs.connect()
        s.sendall(b"HELLO|CLIENT=x|PID=1|HOST=h|PROTO=LALF1\n")
        _recv_all(s)
        n = 20_000
        body = "x" * 200  # a typical row: 200-byte message, ~240-byte frame
        frames = b"".join(
            f"LOG|SEQ={i}|TS=x|LEVEL=INFO|LOGGER=y|LEN={len(body)}\n".encode()
            + body.encode()
            for i in range(1, n + 1)
        )
        s.settimeout(None)  # writer backpressure may pause reads for a while
        started = time.monotonic()
        sender = threading.Thread(target=s.sendall, args=(frames,), daemon=True)
        sender.start()
        conn = rs.db()
        count = 0
        while time.monotonic() - started < 20 and count < n:
            time.sleep(0.05)
            count = conn.execute("SELECT COUNT(*) FROM log_events").fetchone()[0]
        elapsed = time.monotonic() - started
        sender.join(timeout=5)
        s.close()
    finally:
        rs.stop()
    assert count == n
    assert n / elapsed >= 5000, f"{n / elapsed:.0f} rows/s"
