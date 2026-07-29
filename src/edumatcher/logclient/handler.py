"""``TcpLogHandler`` — ships ``LogRecord``s to ``pm-log-srv`` over LALF.

Design: docs-design/EduMatcher-log-srv.md §8.2 (client design), §8.6
(failover behaviour), §15 (normative LALF wire format).

A background thread owns the socket and a bounded queue, so ``emit()``
itself never blocks the calling thread (mirrors the standard library's
``QueueHandler``/``QueueListener`` split, §8.2). While the connection to
the server is healthy, records are encoded as LALF ``LOG`` frames and sent
over TCP, and an ``HB`` frame is sent whenever the connection has been
otherwise idle for the server-assigned ``HBINT`` seconds (§5.6, §15.3's
"a server MUST treat a connection as dead ... if no message of any kind
arrives within 2 x HBINT seconds"). If the connection drops, the
background thread reconnects with capped exponential backoff; if it
cannot reconnect within ``failover_timeout_sec`` of the disconnect being
first noticed, the handler makes a one-way switch to a local fallback
file for the rest of the process's life (§8.6) — it never re-probes for
the server afterwards.
"""

from __future__ import annotations

import logging
import os
import queue
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

from edumatcher.logclient.protocol import (
    LalfProtocolError,
    build_hb_frame,
    build_header_line,
    build_hello_frame,
    build_log_frame,
    iso_utc,
    parse_header_line,
    parse_welcome,
)

_RECV_BUFFER_BYTES = 4096
_BACKOFF_INITIAL_SEC = 0.25
_BACKOFF_MAX_SEC = 5.0
_QUEUE_GET_TIMEOUT_SEC = 0.2
_DEFAULT_HBINT_SEC = 5  # used only if a WELCOME is somehow missing HBINT


class TcpLogHandler(logging.Handler):
    """Formats and ships ``LogRecord``s to ``pm-log-srv`` over LALF (§8.2).

    Falls back to a per-process log file (§8.6) if the server cannot be
    reached again within ``failover_timeout_sec`` of first noticing the
    connection is down.
    """

    def __init__(
        self,
        host: str,
        port: int,
        client: str,
        instance: str | None = None,
        *,
        queue_maxsize: int = 2000,
        connect_timeout_sec: float = 0.5,
        failover_timeout_sec: float = 30.0,
        failover_dir: Path | str = "logs",
    ) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._client = client
        self._instance = instance
        self._connect_timeout_sec = connect_timeout_sec
        self._failover_timeout_sec = failover_timeout_sec
        self._failover_dir = Path(failover_dir)

        self._queue: "queue.Queue[bytes]" = queue.Queue(maxsize=queue_maxsize)
        self._seq = 0
        self._seq_lock = threading.Lock()
        self.dropped_count = 0

        self._down_since: float | None = None
        self._failed_over = False
        self._fallback_handler: logging.FileHandler | None = None
        self._fallback_lock = threading.Lock()

        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="TcpLogHandler", daemon=True
        )
        self._thread.start()

    # -- logging.Handler interface --------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        """Format ``record`` and queue it for delivery; never raises or blocks.

        If this handler has already failed over to file logging (§8.6),
        writes straight through to the fallback ``FileHandler`` instead of
        queuing — the background thread is no longer attempting LALF
        delivery at that point.
        """
        try:
            if self._failed_over:
                self._emit_to_fallback(record)
                return

            frame = self._build_log_frame(record)
            try:
                self._queue.put_nowait(frame)
            except queue.Full:
                self.dropped_count += 1
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        with self._fallback_lock:
            if self._fallback_handler is not None:
                self._fallback_handler.close()
        super().close()

    # -- frame building --------------------------------------------------------

    def _build_log_frame(self, record: logging.LogRecord) -> bytes:
        with self._seq_lock:
            self._seq += 1
            seq = self._seq

        message = record.getMessage()
        has_exception = record.exc_info is not None
        if record.exc_info is not None:
            formatted = "".join(traceback.format_exception(*record.exc_info))
            if formatted:
                message = f"{message}\n{formatted}"

        return build_log_frame(
            seq=seq,
            ts=iso_utc(record.created),
            level=record.levelname,
            logger=record.name,
            message=message,
            module=record.module,
            line=record.lineno,
            has_exception=has_exception,
        )

    # -- fallback file -----------------------------------------------------------

    def _fallback_path(self) -> Path:
        name = (
            self._client if not self._instance else f"{self._client}-{self._instance}"
        )
        return self._failover_dir / f"{name}.log"

    def _ensure_fallback_handler(self) -> logging.FileHandler:
        with self._fallback_lock:
            if self._fallback_handler is None:
                path = self._fallback_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                handler = logging.FileHandler(path, encoding="utf-8")
                handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s %(levelname)s %(name)s - %(message)s"
                    )
                )
                self._fallback_handler = handler
            return self._fallback_handler

    def _emit_to_fallback(self, record: logging.LogRecord) -> None:
        self._ensure_fallback_handler().emit(record)

    def _trigger_failover(self) -> None:
        """One-way switch to file logging (§8.6, point 3). Idempotent."""
        if self._failed_over:
            return
        self._failed_over = True
        path = self._fallback_path()
        message = (
            f"pm-log-srv unreachable for {self._failover_timeout_sec:.0f}s, "
            f"falling back to {path}"
        )
        handler = self._ensure_fallback_handler()
        # Marker line written to both stderr and the start of the fallback
        # file, so the failover is visible wherever someone is watching
        # (§8.6).
        print(message, file=sys.stderr)
        marker = logging.LogRecord(
            name="edumatcher.logclient",
            level=logging.WARNING,
            pathname=__file__,
            lineno=0,
            msg=message,
            args=(),
            exc_info=None,
        )
        handler.emit(marker)

    # -- background thread ------------------------------------------------------

    def _run(self) -> None:
        backoff = _BACKOFF_INITIAL_SEC
        sock: socket.socket | None = None
        hbint = _DEFAULT_HBINT_SEC
        last_activity = 0.0

        while not self._stop_event.is_set():
            if self._failed_over:
                self._drain_queue_to_fallback()
                self._stop_event.wait(_QUEUE_GET_TIMEOUT_SEC)
                continue

            if sock is None:
                sock, hbint = self._try_connect()
                if sock is None:
                    if self._note_down_and_maybe_failover():
                        continue
                    self._stop_event.wait(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX_SEC)
                    continue
                # Reconnected (or first connect) — reset backoff/downtime.
                backoff = _BACKOFF_INITIAL_SEC
                self._down_since = None
                last_activity = time.monotonic()

            try:
                frame = self._queue.get(timeout=_QUEUE_GET_TIMEOUT_SEC)
            except queue.Empty:
                # Nothing to send — send HB if we're approaching HBINT
                # seconds of silence, so the server never sees this
                # connection as idle (§5.6, §15.3).
                if time.monotonic() - last_activity >= hbint:
                    try:
                        sock.sendall(build_hb_frame(iso_utc(time.time())))
                        last_activity = time.monotonic()
                    except OSError:
                        sock.close()
                        sock = None
                        self._note_down_and_maybe_failover()
                continue

            try:
                sock.sendall(frame)
                last_activity = time.monotonic()
            except OSError:
                sock.close()
                sock = None
                if self._note_down_and_maybe_failover():
                    continue

        if sock is not None:
            try:
                sock.sendall(build_header_line("EXIT"))
            except OSError:
                pass
            sock.close()

    def _note_down_and_maybe_failover(self) -> bool:
        """Record the moment the connection was first noticed down.

        Returns ``True`` if this call triggered failover (caller should
        loop back to the top rather than sleep/backoff).
        """
        now = time.monotonic()
        if self._down_since is None:
            self._down_since = now
        if now - self._down_since >= self._failover_timeout_sec:
            self._trigger_failover()
            return True
        return False

    def _drain_queue_to_fallback(self) -> None:
        # Frames queued right before failover triggered are already-encoded
        # LALF bytes, not LogRecords, so they cannot be handed to the
        # fallback FileHandler's formatter; new records go straight to file
        # via emit() once _failed_over is set (§8.6), so this only discards
        # the small in-flight backlog from the moment failover triggered.
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _try_connect(self) -> tuple[socket.socket | None, int]:
        """Attempt one connection + handshake. Returns ``(socket, hbint)``.

        On any failure returns ``(None, _DEFAULT_HBINT_SEC)``.
        """
        try:
            sock = socket.create_connection(
                (self._host, self._port), timeout=self._connect_timeout_sec
            )
            sock.sendall(
                build_hello_frame(
                    client=self._client,
                    pid=os.getpid(),
                    host=socket.gethostname(),
                    instance=self._instance,
                )
            )
            sock.settimeout(self._connect_timeout_sec)
            welcome_bytes = sock.recv(_RECV_BUFFER_BYTES)
            sock.settimeout(None)
            line = welcome_bytes.decode("utf-8", errors="replace")
            msg_type, fields = parse_header_line(line)
            if msg_type != "WELCOME":
                sock.close()
                return None, _DEFAULT_HBINT_SEC
            welcome = parse_welcome(fields)
            return sock, welcome.hbint
        except (OSError, LalfProtocolError, ValueError):
            return None, _DEFAULT_HBINT_SEC
