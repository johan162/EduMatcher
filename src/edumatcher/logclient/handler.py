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
from typing import TextIO

from edumatcher.logclient.protocol import (
    LalfProtocolError,
    build_hb_frame,
    build_header_line,
    build_hello_frame,
    build_log_frame,
    iso_utc,
    parse_header_line,
    parse_welcome,
    template_id,
)

_RECV_BUFFER_BYTES = 4096
_BACKOFF_INITIAL_SEC = 0.25
_BACKOFF_MAX_SEC = 5.0
_QUEUE_GET_TIMEOUT_SEC = 0.2
_DEFAULT_HBINT_SEC = 5  # used only if a WELCOME is somehow missing HBINT
#: How long ``close()`` keeps sending the backlog on top of
#: ``connect_timeout_sec`` before the rest goes to the fallback file.
_CLOSE_DRAIN_SEC = 2.0
_FALLBACK_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"
#: Floor of the send timeout after the handshake (it is otherwise
#: ``failover_timeout_sec``): a peer that stops reading for longer counts as
#: a disconnect, so failover still starts against a host that vanished
#: without a reset.
_MIN_SEND_TIMEOUT_SEC = 2.0
#: Queued frames are built with ``SEQ=0``; the background thread writes the
#: per-connection number into this prefix as it sends (LALF §SEQ: restart at
#: 1 on every connection). ``build_log_frame`` always puts ``SEQ`` first.
_SEQ0_PREFIX = b"LOG|SEQ=0|"


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

        self._queue_maxsize = queue_maxsize

        #: Each item is the encoded ``LOG`` frame and the fallback-file line
        #: of the same record, both built in ``emit()``, so a backlog can
        #: still go to the file if the server never takes it.
        self._queue: "queue.Queue[tuple[bytes, str]]" = queue.Queue(
            maxsize=queue_maxsize
        )
        #: The item whose ``sendall`` failed, sent again before the queue.
        #: Only the background thread touches it.
        self._held: tuple[bytes, str] | None = None
        #: Last ``SEQ`` sent on the current connection (background thread).
        self._seq = 0
        self.dropped_count = 0
        #: Part of ``dropped_count`` already reported (to the server as a
        #: WARNING row, or as a fallback-file line).
        self._dropped_reported = 0

        self._down_since: float | None = None
        self._failed_over = False
        self._fallback_formatter = logging.Formatter(_FALLBACK_FORMAT)
        self._fallback_file: TextIO | None = None
        self._fallback_lock = threading.Lock()

        self._stop_event = threading.Event()
        self._close_deadline = 0.0
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
                self._write_fallback_lines([self._fallback_formatter.format(record)])
                return

            item = (
                self._build_log_frame(record),
                self._fallback_formatter.format(record),
            )
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self.dropped_count += 1
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        """Send the backlog, then ``EXIT``; file what is left at the deadline.

        ``logging.shutdown()`` calls this at every process exit, so the
        last records a process logs (often the CRITICAL line before it
        stops) are sent rather than left in the queue. The drain is bounded
        by ``connect_timeout_sec`` + ``_CLOSE_DRAIN_SEC`` so a dead server
        never hangs an exit; records still queued then go to the fallback
        file.
        """
        drain_sec = self._connect_timeout_sec + _CLOSE_DRAIN_SEC
        self._close_deadline = time.monotonic() + drain_sec
        self._stop_event.set()
        self._thread.join(timeout=drain_sec + 1.0)
        with self._fallback_lock:
            if self._fallback_file is not None:
                self._fallback_file.close()
                self._fallback_file = None
        super().close()

    # -- frame building --------------------------------------------------------

    def _build_log_frame(self, record: logging.LogRecord, seq: int = 0) -> bytes:
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
            # Only WARNING+ rows are looked up in the log ledger, so the
            # INFO/DEBUG bulk skips the hash.
            tpl=(
                template_id(record.name, str(record.msg))
                if record.levelno >= logging.WARNING
                else None
            ),
        )

    # -- fallback file -----------------------------------------------------------

    def _fallback_path(self) -> Path:
        name = (
            self._client if not self._instance else f"{self._client}-{self._instance}"
        )
        return self._failover_dir / f"{name}.log"

    def _write_fallback_lines_locked(self, lines: list[str]) -> None:
        if self._fallback_file is None:
            path = self._fallback_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fallback_file = open(path, "a", encoding="utf-8")
        for line in lines:
            self._fallback_file.write(line + "\n")
        self._fallback_file.flush()

    def _write_fallback_lines(self, lines: list[str]) -> None:
        with self._fallback_lock:
            self._write_fallback_lines_locked(lines)

    def _note_line(self, message: str) -> str:
        """A WARNING line from the handler itself, in the fallback format."""
        return self._fallback_formatter.format(self._note_record(message))

    @staticmethod
    def _note_record(message: str) -> logging.LogRecord:
        return logging.LogRecord(
            name="edumatcher.logclient",
            level=logging.WARNING,
            pathname=__file__,
            lineno=0,
            msg=message,
            args=(),
            exc_info=None,
        )

    def _unreported_drops_message(self) -> str | None:
        """The drop report owed, once; ``None`` when nothing new was dropped."""
        dropped = self.dropped_count - self._dropped_reported
        if dropped <= 0:
            return None
        self._dropped_reported += dropped
        return (
            f"{dropped} log records dropped: the handler queue was full "
            f"(queue_maxsize={self._queue_maxsize})"
        )

    def _take_backlog_lines(self) -> list[str]:
        """Remove the held item and the queue; return their fallback lines."""
        lines: list[str] = []
        if self._held is not None:
            lines.append(self._held[1])
            self._held = None
        while True:
            try:
                lines.append(self._queue.get_nowait()[1])
            except queue.Empty:
                return lines

    def _take_backlog_and_drop_note(self) -> list[str]:
        lines = self._take_backlog_lines()
        note = self._unreported_drops_message()
        if note is not None:
            lines.append(self._note_line(note))
        return lines

    def _trigger_failover(self) -> None:
        """One-way switch to file logging (§8.6, point 3). Idempotent.

        The backlog queued during the grace window is written to the file
        first, in order, under the same lock ``emit()`` writes with, so
        records logged meanwhile follow it.
        """
        if self._failed_over:
            return
        path = self._fallback_path()
        message = (
            f"pm-log-srv unreachable for {self._failover_timeout_sec:.0f}s, "
            f"falling back to {path}"
        )
        # Marker line written to both stderr and the start of the fallback
        # file, so the failover is visible wherever someone is watching
        # (§8.6).
        print(message, file=sys.stderr)
        with self._fallback_lock:
            self._write_fallback_lines_locked(
                [self._note_line(message), *self._take_backlog_and_drop_note()]
            )
            self._failed_over = True

    # -- background thread ------------------------------------------------------

    def _stopping_done(self) -> bool:
        """After ``close()``: whether the drain is over (idle or out of time)."""
        if not self._stop_event.is_set():
            return False
        idle = self._held is None and self._queue.empty()
        return idle or time.monotonic() >= self._close_deadline

    def _pause(self, seconds: float) -> None:
        if self._stop_event.is_set():
            # Draining for close(): keep retrying, but not past the deadline.
            time.sleep(max(0.0, min(seconds, self._close_deadline - time.monotonic())))
        else:
            self._stop_event.wait(seconds)

    def _numbered(self, frame: bytes) -> bytes:
        """``frame`` with the next ``SEQ`` of this connection."""
        assert frame.startswith(_SEQ0_PREFIX)
        self._seq += 1
        return b"LOG|SEQ=%d|" % self._seq + frame[len(_SEQ0_PREFIX) :]

    def _next_item(self) -> tuple[bytes, str] | None:
        if self._held is not None:
            return self._held
        try:
            return self._queue.get(timeout=_QUEUE_GET_TIMEOUT_SEC)
        except queue.Empty:
            return None

    def _run(self) -> None:
        backoff = _BACKOFF_INITIAL_SEC
        sock: socket.socket | None = None
        hbint = _DEFAULT_HBINT_SEC
        last_activity = 0.0

        while not self._stopping_done():
            if self._failed_over:
                self._drain_queue_to_fallback()
                self._pause(_QUEUE_GET_TIMEOUT_SEC)
                continue

            if sock is None:
                sock, hbint = self._try_connect()
                if sock is None:
                    if self._note_down_and_maybe_failover():
                        continue
                    self._pause(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX_SEC)
                    continue
                # Reconnected (or first connect) — reset backoff/downtime,
                # and SEQ, which numbers the frames of one connection.
                backoff = _BACKOFF_INITIAL_SEC
                self._down_since = None
                self._seq = 0
                last_activity = time.monotonic()

            item = self._next_item()
            if item is None:
                # Queue drained: report drops once (§8.2), then send HB if
                # we're approaching HBINT seconds of silence, so the server
                # never sees this connection as idle (§5.6, §15.3).
                note = self._unreported_drops_message()
                if note is not None:
                    frame = self._build_log_frame(self._note_record(note))
                    self._held = (frame, self._note_line(note))
                    continue
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
                sock.sendall(self._numbered(item[0]))
                self._held = None
                last_activity = time.monotonic()
            except OSError:
                # Kept, not dropped: sent first on the next connection, or
                # filed with the backlog at failover.
                self._held = item
                sock.close()
                sock = None
                if self._note_down_and_maybe_failover():
                    continue

        if sock is not None:
            note = self._unreported_drops_message()
            try:
                if note is not None:
                    frame = self._build_log_frame(self._note_record(note))
                    sock.sendall(self._numbered(frame))
                sock.sendall(build_header_line("EXIT"))
            except OSError:
                pass
            sock.close()
        self._file_leftovers_at_close()

    def _file_leftovers_at_close(self) -> None:
        """Write what ``close()`` could not send to the fallback file."""
        with self._fallback_lock:
            lines = self._take_backlog_lines()
            if lines and not self._failed_over:
                lines.insert(
                    0,
                    self._note_line(
                        f"pm-log-srv did not take {len(lines)} records before "
                        f"the handler closed; writing them to {self._fallback_path()}"
                    ),
                )
            note = self._unreported_drops_message()
            if note is not None:
                lines.append(self._note_line(note))
            if lines:
                self._write_fallback_lines_locked(lines)

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
        # _trigger_failover already filed the grace-window backlog; this
        # catches a record that emit() queued while failover was switching,
        # and drops counted since.
        with self._fallback_lock:
            lines = self._take_backlog_and_drop_note()
            if lines:
                self._write_fallback_lines_locked(lines)

    def _try_connect(self) -> tuple[socket.socket | None, int]:
        """Attempt one connection + handshake. Returns ``(socket, hbint)``.

        On any failure returns ``(None, _DEFAULT_HBINT_SEC)``, with the
        socket closed. After the handshake the socket keeps a send timeout,
        so a peer that stops reading is treated as a disconnect.
        """
        sock: socket.socket | None = None
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
            sock.settimeout(max(self._failover_timeout_sec, _MIN_SEND_TIMEOUT_SEC))
            line = welcome_bytes.decode("utf-8", errors="replace")
            msg_type, fields = parse_header_line(line)
            if msg_type != "WELCOME":
                sock.close()
                return None, _DEFAULT_HBINT_SEC
            welcome = parse_welcome(fields)
            return sock, welcome.hbint
        except OSError, LalfProtocolError, ValueError:
            if sock is not None:
                sock.close()
            return None, _DEFAULT_HBINT_SEC
