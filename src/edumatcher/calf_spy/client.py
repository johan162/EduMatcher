"""TCP client session logic for pm-calf-spy.

Deliberately independent of argparse/console concerns: :class:`CalfSpyClient`
owns the socket, the HELLO/SUB handshake, and the read loop, and hands each
parsed :class:`CalfFrame` to a caller-supplied callback. This keeps the
network code unit-testable without a terminal, and keeps ``cli.py`` a thin
wrapper that only deals with argument parsing and output rendering.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from edumatcher.md_gateway.protocol import (
    CalfFrame,
    CalfProtocolError,
    build_line,
    parse_line,
)

log = logging.getLogger(__name__)

_MAX_LINE_BYTES = 4096
_RECV_CHUNK_BYTES = 4096
_CONNECT_TIMEOUT_SEC = 5.0
_DEFAULT_PING_INTERVAL_SEC = 60.0


class CalfSpyConnectionError(RuntimeError):
    """Raised when the initial connection or handshake fails."""


@dataclass(frozen=True)
class ResumeRequest:
    """A single-stream ``RESUME=1`` request to send on the initial HELLO."""

    channel: str
    symbol: str
    last_seq: int


@dataclass
class CalfSpyOptions:
    """Connection and subscription parameters for one spy session."""

    host: str = "127.0.0.1"
    port: int = 5570
    client_name: str = "calf-spy"
    channels: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=lambda: ["*"])
    resume: ResumeRequest | None = None
    ping_interval_sec: float = _DEFAULT_PING_INTERVAL_SEC


FrameHandler = Callable[[CalfFrame, str, float], None]
"""Callback signature: (parsed_frame, raw_line, recv_time_seconds) -> None."""


class CalfSpyClient:
    """Owns one TCP connection to ``pm-md-gwy`` and drives the CALF handshake."""

    def __init__(self, options: CalfSpyOptions) -> None:
        self._opts = options
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._running = False
        self._send_lock = threading.Lock()
        self._ping_thread: threading.Thread | None = None
        self._ping_stop = threading.Event()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the TCP connection. Raises :class:`CalfSpyConnectionError`."""
        try:
            sock = socket.create_connection(
                (self._opts.host, self._opts.port), timeout=_CONNECT_TIMEOUT_SEC
            )
        except OSError as exc:
            raise CalfSpyConnectionError(
                f"could not connect to {self._opts.host}:{self._opts.port}: {exc}"
            ) from exc
        sock.settimeout(None)
        self._sock = sock
        log.info("connected to %s:%s", self._opts.host, self._opts.port)

    def close(self) -> None:
        self._running = False
        self._stop_ping_thread()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------

    def handshake(self) -> CalfFrame:
        """Send HELLO (with optional RESUME) and return the parsed WELCOME.

        Raises :class:`CalfSpyConnectionError` if the connection closes
        before a WELCOME arrives, or if the gateway sends ERR instead.
        """
        hello_fields = {"CLIENT": self._opts.client_name, "PROTO": "CALF1"}
        resume = self._opts.resume
        if resume is not None:
            hello_fields.update(
                {
                    "RESUME": "1",
                    "CH": resume.channel,
                    "SYM": resume.symbol,
                    "LASTSEQ": str(resume.last_seq),
                }
            )
        self._send_line("HELLO", hello_fields)

        line = self._recv_line()
        if line is None:
            raise CalfSpyConnectionError("connection closed before WELCOME")
        try:
            frame = parse_line(line)
        except CalfProtocolError as exc:
            raise CalfSpyConnectionError(f"malformed reply to HELLO: {exc}") from exc

        if frame.msg_type == "ERR":
            raise CalfSpyConnectionError(
                f"gateway rejected HELLO: {frame.fields.get('CODE', '?')} "
                f"{frame.fields.get('MSG', '')}".rstrip()
            )
        if frame.msg_type != "WELCOME":
            raise CalfSpyConnectionError(f"unexpected reply to HELLO: {frame.msg_type}")
        return frame

    def subscribe(self, channels: list[str], symbols: list[str]) -> None:
        """Send one ``SUB`` for the Cartesian product of channels x symbols."""
        if not channels or not symbols:
            return
        self._send_line("SUB", {"CH": ",".join(channels), "SYM": ",".join(symbols)})

    # ------------------------------------------------------------------
    # Read loop
    # ------------------------------------------------------------------

    def run(self, on_frame: FrameHandler, *, max_frames: int = 0) -> None:
        """Read and dispatch frames until stopped, the peer closes, or
        ``max_frames`` data-carrying frames (anything but HB) have been
        delivered (0 = unlimited).

        A background thread sends a ``PING`` every ``ping_interval_sec``
        seconds for the duration of the read loop, so the gateway's idle
        timeout never fires for a client (like calf-spy) that otherwise
        never sends anything after its initial SUB.
        """
        self._running = True
        self._start_ping_thread()
        try:
            delivered = 0
            while self._running:
                line = self._recv_line()
                if line is None:
                    log.info("gateway closed the connection")
                    return
                recv_time = time.time()
                try:
                    frame = parse_line(line)
                except CalfProtocolError as exc:
                    log.warning("unparseable line from gateway: %r (%s)", line, exc)
                    continue

                on_frame(frame, line, recv_time)

                if frame.msg_type != "HB":
                    delivered += 1
                    if max_frames and delivered >= max_frames:
                        return
        finally:
            self._stop_ping_thread()

    def stop(self) -> None:
        self._running = False
        self._stop_ping_thread()

    # ------------------------------------------------------------------
    # PING heartbeat
    # ------------------------------------------------------------------

    def _start_ping_thread(self) -> None:
        interval = self._opts.ping_interval_sec
        if interval <= 0:
            return
        self._ping_stop.clear()
        thread = threading.Thread(
            target=self._ping_loop, args=(interval,), daemon=True, name="calf-spy-ping"
        )
        self._ping_thread = thread
        thread.start()

    def _stop_ping_thread(self) -> None:
        self._ping_stop.set()
        thread = self._ping_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._ping_thread = None

    def _ping_loop(self, interval: float) -> None:
        while not self._ping_stop.wait(interval):
            if not self._running:
                return
            try:
                self._send_line("PING", {})
            except OSError as exc:
                log.info("ping send failed: %s", exc)
                return
            log.debug("sent PING (interval=%ss)", interval)

    # ------------------------------------------------------------------
    # Low-level IO
    # ------------------------------------------------------------------

    def _send_line(self, msg_type: str, fields: dict[str, str]) -> None:
        assert self._sock is not None, "connect() must be called first"
        with self._send_lock:
            self._sock.sendall(build_line(msg_type, fields))

    def _recv_line(self) -> str | None:
        assert self._sock is not None, "connect() must be called first"
        while b"\n" not in self._buf:
            if len(self._buf) > _MAX_LINE_BYTES:
                raise CalfSpyConnectionError("line from gateway exceeds 4096 bytes")
            try:
                chunk = self._sock.recv(_RECV_CHUNK_BYTES)
            except OSError as exc:
                log.info("socket read error: %s", exc)
                return None
            if not chunk:
                return None
            self._buf.extend(chunk)

        idx = self._buf.find(b"\n")
        raw = bytes(self._buf[:idx])
        del self._buf[: idx + 1]
        return raw.decode("utf-8", errors="replace").strip("\r")
