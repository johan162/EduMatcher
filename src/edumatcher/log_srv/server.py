"""``pm-log-srv`` LALF TCP server runtime.

Architecture mirrors ``edumatcher.md_gateway.gateway.MarketDataGateway``
exactly: a single-threaded, non-blocking ``select()``-based accept/read/write
loop, not asyncio. (docs-design/EduMatcher-log-srv.md §7.3 describes an
asyncio-per-connection design; this implementation deliberately follows the
pattern actually used elsewhere in this codebase — CALF's own gateway is
select-based, not asyncio — for architectural consistency. See the design
doc correction noted in this module's own docstring history / the
accompanying implementation notes.) The one place this process *does* use a
dedicated background thread is the SQLite writer (§7.4,
``edumatcher.log_srv.writer.WriterThread``), since batching writes on a
timer is a genuinely different concern from the non-blocking network loop
and doing it inline would block that loop on disk I/O.

Design priorities, in the same order ``md_gateway/gateway.py`` states them:
- Correctness first: strict LALF validation (§15) and deterministic behavior
- Maintainability: clear decomposition, heavily documented control flow
- Defensive behavior: bounded queues, explicit disconnect paths
"""

from __future__ import annotations

import logging
import secrets
import select
import signal
import socket
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from edumatcher.log_srv.config import LogServerConfig
from edumatcher.log_srv.schema import (
    DELETE_OLD_LOG_EVENTS,
    INCREMENT_TOTAL_CONNECTIONS,
    INCREMENT_TOTAL_ERRORS_SENT,
    UPDATE_PROCESS_DISCONNECTED,
    UPSERT_PROCESS_CONNECT,
    UPSERT_SERVER_STATS_INIT,
    open_db,
)
from edumatcher.log_srv.session import LogSession
from edumatcher.log_srv.writer import LogEventRow, WriterThread
from edumatcher.logclient.protocol import (
    ERR_BAD_MESSAGE,
    ERR_HELLO_TIMEOUT,
    ERR_INVALID_LEVEL,
    ERR_MISSING_FIELD,
    ERR_PAYLOAD_TOO_LARGE,
    ERR_PROTO_MISMATCH,
    HELLO_TIMEOUT_SEC,
    PROTO_VERSION,
    LalfProtocolError,
    build_header_line,
    iso_utc,
    validate_log_fields,
)

log = logging.getLogger(__name__)

_DEBUG_SUMMARY_INTERVAL_SEC = 5.0
_RETENTION_CHECK_INTERVAL_SEC = 3600  # once per hour, per §6.5/§7.2 step 6


class LogServer:
    """``pm-log-srv`` TCP server: accepts LALF connections, persists LOG rows."""

    def __init__(self, config: LogServerConfig) -> None:
        self.config = config

        self._running = False
        self._server: socket.socket | None = None
        self._clients: dict[int, LogSession] = {}

        self._conn = open_db(Path(config.db_path))
        self._conn.execute(UPSERT_SERVER_STATS_INIT, (iso_utc(time.time()),))
        self._conn.commit()

        self._writer = WriterThread(
            self._conn,
            batch_size=config.write_batch_size,
            batch_interval_ms=config.write_batch_interval_ms,
        )

        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()
        self._last_retention_check = 0.0

        # A dedicated connection is used for the (rare, background) DELETE
        # pruning statement rather than sharing the writer thread's
        # connection, since it runs from the main loop thread — SQLite
        # connections are not meant to be shared across threads without
        # check_same_thread=False plus external serialization, and the
        # writer thread already owns exclusive use of its connection for
        # inserts. A second connection avoids adding cross-thread locking
        # to the (much hotter) insert path just to support hourly pruning.
        self._prune_conn = open_db(Path(config.db_path))

    # ------------------------------------------------------------------
    # Debug summary
    # ------------------------------------------------------------------

    def _dbg_count(self, key: str, amount: int = 1) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        self._debug_counts[key] += amount
        self._flush_debug_summary()

    def _flush_debug_summary(self, force: bool = False) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        now = time.monotonic()
        if not force and now - self._debug_last_summary < _DEBUG_SUMMARY_INTERVAL_SEC:
            return
        if not self._debug_counts:
            self._debug_last_summary = now
            return
        summary = ", ".join(
            f"{key}={value}" for key, value in sorted(self._debug_counts.items())
        )
        log.debug("log_srv flow summary: %s", summary)
        self._debug_counts.clear()
        self._debug_last_summary = now

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start TCP listener, writer thread, and process loop until stopped."""
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.config.bind_address, self.config.port))
        self._server.listen(128)
        self._server.setblocking(False)

        self._running = True
        self._writer.start()

        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, lambda *_: self.stop())
            signal.signal(signal.SIGTERM, lambda *_: self.stop())

        log.info(
            "pm-log-srv %r listening on %s:%s db=%s retention_days=%s",
            self.config.name,
            self.config.bind_address,
            self.config.port,
            self.config.db_path,
            self.config.retention_days,
        )

        try:
            while self._running:
                self._accept_new_clients()
                self._read_client_data()
                self._send_heartbeats_if_due()
                self._flush_client_writes()
                self._drop_idle_clients()
                self._run_retention_if_due()
                time.sleep(0.01)
        finally:
            self.close()

    def stop(self) -> None:
        log.info("stop requested")
        self._running = False

    def close(self) -> None:
        self._flush_debug_summary(force=True)
        log.info("closing pm-log-srv")
        for session in list(self._clients.values()):
            try:
                session.sock.close()
            except OSError:
                pass
        self._clients.clear()

        if self._server is not None:
            self._server.close()
            self._server = None

        self._writer.stop()
        if hasattr(self, "_conn"):
            self._conn.close()
        if hasattr(self, "_prune_conn"):
            self._prune_conn.close()

    # ------------------------------------------------------------------
    # Network IO
    # ------------------------------------------------------------------

    def _accept_new_clients(self) -> None:
        if self._server is None:
            return

        while True:
            try:
                conn, addr = self._server.accept()
            except BlockingIOError:
                break
            except OSError as exc:
                log.warning("accept failed: %s", exc)
                break

            conn.setblocking(False)
            session = LogSession(sock=conn, addr=addr)
            self._clients[conn.fileno()] = session
            log.info(
                "client connected addr=%s:%s fd=%d", addr[0], addr[1], conn.fileno()
            )

    def _read_client_data(self) -> None:
        if not self._clients:
            return

        readable = [session.sock for session in self._clients.values()]
        try:
            ready, _, _ = select.select(readable, [], [], 0)
        except (OSError, ValueError) as exc:
            log.warning("read select failed: %s", exc)
            return

        for sock_obj in ready:
            self._dbg_count("readable_sockets")
            session = self._clients.get(sock_obj.fileno())
            if session is None:
                continue

            # Backpressure (§5.8/§15.13): stop reading from this socket's
            # buffer while its outbound queue is over the limit, so slow
            # writer-thread drainage or a genuinely overloaded downstream
            # naturally throttles the client via TCP flow control rather
            # than the server buffering an unbounded number of LOG rows.
            if len(session.out_queue) > self.config.max_client_queue:
                continue

            try:
                chunk = session.sock.recv(4096)
            except (BlockingIOError, OSError):
                continue

            if not chunk:
                self._disconnect(session, reason="peer_closed")
                continue

            session.reader.feed(chunk)
            session.last_activity = time.monotonic()
            self._drain_frames(session)

    def _drain_frames(self, session: LogSession) -> None:
        while True:
            try:
                frame = session.reader.next_frame()
            except LalfProtocolError as exc:
                log.warning(
                    "dropping client fd=%d due to protocol error: %s",
                    session.sock.fileno(),
                    exc,
                )
                self._queue_line(
                    session, "ERR", {"CODE": ERR_BAD_MESSAGE, "MSG": str(exc)}
                )
                self._close_after_flush(session)
                return
            if frame is None:
                return
            self._handle_frame(session, frame)

    def _flush_client_writes(self) -> None:
        """Flush queued outbound bytes to all clients (mirrors md_gateway)."""
        for session in list(self._clients.values()):
            while session.out_queue:
                payload = session.out_queue[0]
                unsent = payload[session.out_offset :]
                try:
                    sent = session.sock.send(unsent)
                except (BlockingIOError, OSError):
                    break

                if sent <= 0:
                    break

                session.out_offset += sent

                if session.out_offset >= len(payload):
                    session.out_queue.pop(0)
                    session.out_offset = 0

            if session.closing and not session.out_queue:
                self._disconnect(session, reason="close_after_flush")

    # ------------------------------------------------------------------
    # Protocol handling
    # ------------------------------------------------------------------

    def _handle_frame(self, session: LogSession, frame: Any) -> None:
        msg_type = frame.msg_type
        fields = frame.fields

        if not session.authenticated:
            if msg_type != "HELLO":
                self._queue_line(
                    session,
                    "ERR",
                    {"CODE": "AUTH_REQUIRED", "MSG": "send HELLO first"},
                )
                self._close_after_flush(session)
                return
            self._handle_hello(session, fields)
            return

        if msg_type == "HELLO":
            # §15.5/§15.9: a second HELLO on an already-established
            # connection is a protocol violation.
            self._queue_line(
                session,
                "ERR",
                {"CODE": ERR_PROTO_MISMATCH, "MSG": "HELLO already completed"},
            )
            self._close_after_flush(session)
            return

        if msg_type == "LOG":
            self._handle_log(session, fields, frame.payload or b"")
        elif msg_type == "HB":
            session.last_activity = time.monotonic()
        elif msg_type == "PING":
            self._queue_line(session, "PONG", {})
        elif msg_type == "EXIT":
            self._close_after_flush(session)
        else:
            self._queue_line(
                session,
                "ERR",
                {"CODE": ERR_BAD_MESSAGE, "MSG": f"unsupported {msg_type}"},
            )

    def _handle_hello(self, session: LogSession, fields: dict[str, str]) -> None:
        client = fields.get("CLIENT", "")
        pid_raw = fields.get("PID", "")
        host = fields.get("HOST", "")
        proto = fields.get("PROTO", "")
        instance = fields.get("INSTANCE")

        missing = [k for k in ("CLIENT", "PID", "HOST", "PROTO") if not fields.get(k)]
        if missing:
            self._queue_line(
                session,
                "ERR",
                {"CODE": ERR_MISSING_FIELD, "MSG": f"missing: {','.join(missing)}"},
            )
            self._close_after_flush(session)
            return

        if proto != PROTO_VERSION:
            self._queue_line(
                session,
                "ERR",
                {"CODE": ERR_PROTO_MISMATCH, "MSG": f"expected PROTO={PROTO_VERSION}"},
            )
            self._close_after_flush(session)
            return

        try:
            pid = int(pid_raw)
        except (TypeError, ValueError):
            self._queue_line(
                session,
                "ERR",
                {"CODE": ERR_MISSING_FIELD, "MSG": "PID must be an integer"},
            )
            self._close_after_flush(session)
            return

        session.client = client
        session.pid = pid
        session.host = host
        session.instance = instance
        session.authenticated = True
        session.session_id = secrets.token_hex(4)
        session.last_activity = time.monotonic()

        now_iso = iso_utc(time.time())
        with self._conn:
            self._conn.execute(
                UPSERT_PROCESS_CONNECT,
                (
                    session.session_id,
                    client,
                    instance,
                    pid,
                    host,
                    now_iso,
                    now_iso,
                ),
            )
            self._conn.execute(INCREMENT_TOTAL_CONNECTIONS)

        welcome_fields = {
            "PROTO": PROTO_VERSION,
            "SRV": self.config.name,
            "HBINT": str(self.config.heartbeat_interval_sec),
            "SESSION": session.session_id,
        }
        self._queue_line(session, "WELCOME", welcome_fields)
        log.info(
            "client authenticated fd=%d client=%s pid=%d host=%s session=%s",
            session.sock.fileno(),
            client,
            pid,
            host,
            session.session_id,
        )

    def _handle_log(
        self, session: LogSession, fields: dict[str, str], payload: bytes
    ) -> None:
        err_code = validate_log_fields(fields)
        if err_code == ERR_MISSING_FIELD:
            self._queue_line(
                session,
                "ERR",
                {"CODE": ERR_MISSING_FIELD, "MSG": "LOG missing a required field"},
            )
            self._dbg_count("log_rejected_missing_field")
            return
        if err_code == ERR_INVALID_LEVEL:
            self._queue_line(
                session,
                "ERR",
                {
                    "CODE": ERR_INVALID_LEVEL,
                    "MSG": f"unknown LEVEL value: {fields.get('LEVEL')}",
                },
            )
            self._dbg_count("log_rejected_invalid_level")
            return

        try:
            seq = int(fields["SEQ"])
        except (TypeError, ValueError):
            seq = 0
        if seq and session.last_seq and seq != session.last_seq + 1:
            log.debug(
                "SEQ gap on fd=%d client=%s: expected %d got %d",
                session.sock.fileno(),
                session.client,
                session.last_seq + 1,
                seq,
            )
        if seq:
            session.last_seq = seq

        truncated = False
        message = payload.decode("utf-8", errors="replace")
        max_bytes = self.config.max_message_bytes
        if len(payload) > max_bytes:
            # Truncate, store anyway, advisory ERR — never drop (§15.7/§15.9).
            truncated = True
            cut = payload[:max_bytes]
            while cut:
                try:
                    message = cut.decode("utf-8")
                    break
                except UnicodeDecodeError:
                    cut = cut[:-1]
            else:
                message = ""
            self._queue_line(
                session,
                "ERR",
                {
                    "CODE": ERR_PAYLOAD_TOO_LARGE,
                    "MSG": f"message exceeds max_message_bytes={max_bytes}, truncated",
                },
            )
            with self._conn:
                self._conn.execute(INCREMENT_TOTAL_ERRORS_SENT)

        line_raw = fields.get("LINE")
        line_no: int | None = None
        if line_raw is not None:
            try:
                line_no = int(line_raw)
            except (TypeError, ValueError):
                line_no = None

        row = LogEventRow(
            client_ts=fields.get("TS", iso_utc(time.time())),
            server_ts=iso_utc(time.time()),
            process=session.client,
            instance=session.instance,
            pid=session.pid,
            host=session.host,
            session=session.session_id,
            level=fields["LEVEL"],
            logger=fields.get("LOGGER", ""),
            module=fields.get("MODULE"),
            line=line_no,
            has_exception=fields.get("EXC") == "1",
            truncated=truncated,
            message=message,
        )
        self._writer.enqueue(row)
        self._dbg_count("log_events_enqueued")

    # ------------------------------------------------------------------
    # Heartbeat / idle / retention
    # ------------------------------------------------------------------

    def _send_heartbeats_if_due(self) -> None:
        # §15.10: HB is client -> server only; the server does not itself
        # send HB. Nothing to do here — kept as an explicit no-op method
        # (rather than omitted) so the run() loop's shape stays identical
        # to md_gateway's, which does send server -> client HB for its own
        # different protocol. See _drop_idle_clients for the receive-side
        # half of LALF's liveness contract.
        return

    def _drop_idle_clients(self) -> None:
        now = time.monotonic()
        for session in list(self._clients.values()):
            if (
                not session.authenticated
                and now - session.connected_at > HELLO_TIMEOUT_SEC
            ):
                self._queue_line(
                    session,
                    "ERR",
                    {"CODE": ERR_HELLO_TIMEOUT, "MSG": "no HELLO received"},
                )
                self._disconnect(session, reason="hello_timeout")
                continue
            if session.authenticated:
                idle = now - session.last_activity
                max_idle = 2 * self.config.heartbeat_interval_sec
                if idle > max_idle:
                    self._disconnect(session, reason="idle_timeout")

    def _run_retention_if_due(self) -> None:
        if self.config.retention_days is None:
            return
        now = time.monotonic()
        if now - self._last_retention_check < _RETENTION_CHECK_INTERVAL_SEC:
            return
        self._last_retention_check = now
        self._prune_older_than(self.config.retention_days)

    def _prune_older_than(self, days: int) -> int:
        cutoff = iso_utc(time.time() - days * 86400)
        with self._prune_conn:
            cur = self._prune_conn.execute(DELETE_OLD_LOG_EVENTS, (cutoff,))
            deleted = max(cur.rowcount, 0)
        if deleted:
            log.info(
                "retention: pruned %d log_events rows older than %s", deleted, cutoff
            )
        return deleted

    # ------------------------------------------------------------------
    # Queue/disconnect helpers
    # ------------------------------------------------------------------

    def _queue_line(
        self, session: LogSession, msg_type: str, fields: dict[str, str]
    ) -> None:
        self._queue_raw(session, build_header_line(msg_type, fields))
        if msg_type == "ERR":
            with self._conn:
                self._conn.execute(INCREMENT_TOTAL_ERRORS_SENT)

    def _queue_raw(self, session: LogSession, payload: bytes) -> None:
        session.out_queue.append(payload)

    def _disconnect(self, session: LogSession, reason: str = "unspecified") -> None:
        fd = session.sock.fileno()
        client = session.client or "-"
        try:
            session.sock.close()
        except OSError:
            pass
        self._clients.pop(fd, None)
        if session.authenticated:
            with self._conn:
                self._conn.execute(
                    UPDATE_PROCESS_DISCONNECTED,
                    (iso_utc(time.time()), session.session_id),
                )
        log.info("client disconnected fd=%d client=%s reason=%s", fd, client, reason)

    def _close_after_flush(self, session: LogSession) -> None:
        session.closing = True
        log.debug("session fd=%d marked closing-after-flush", session.sock.fileno())
