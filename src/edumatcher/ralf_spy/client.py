"""TCP client session logic for pm-ralf-spy.

Deliberately independent of argparse/console concerns: :class:`RalfSpyClient`
owns the socket, the HELLO/SUB handshake, and the read loop, and hands each
parsed :class:`RalfFrame` to a caller-supplied callback. This keeps the
network code unit-testable without a terminal, and keeps ``cli.py`` a thin
wrapper that only deals with argument parsing and output rendering.
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from edumatcher.ralf_gateway.protocol import (
    RalfFrame,
    RalfProtocolError,
    build_line,
    parse_line,
)

log = logging.getLogger(__name__)

_MAX_LINE_BYTES = 4096
_RECV_CHUNK_BYTES = 4096
_CONNECT_TIMEOUT_SEC = 5.0


class RalfSpyConnectionError(RuntimeError):
    """Raised when the initial connection or handshake fails."""


@dataclass
class RalfSpyOptions:
    """Connection and subscription parameters for one spy session."""

    host: str = "127.0.0.1"
    port: int = 5580
    client_name: str = "ralf-spy"
    role: str = "AUDIT"
    channels: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=lambda: ["*"])
    last_seq: int = 0


FrameHandler = Callable[[RalfFrame, str, float], None]
"""Callback signature: (parsed_frame, raw_line, recv_time_seconds) -> None."""


class RalfSpyClient:
    """Owns one TCP connection to ``pm-ralf-gwy`` and drives the RALF handshake."""

    def __init__(self, options: RalfSpyOptions) -> None:
        self._opts = options
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._running = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the TCP connection. Raises :class:`RalfSpyConnectionError`."""
        try:
            sock = socket.create_connection(
                (self._opts.host, self._opts.port), timeout=_CONNECT_TIMEOUT_SEC
            )
        except OSError as exc:
            raise RalfSpyConnectionError(
                f"could not connect to {self._opts.host}:{self._opts.port}: {exc}"
            ) from exc
        sock.settimeout(None)
        self._sock = sock
        log.info("connected to %s:%s", self._opts.host, self._opts.port)

    def close(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------

    def handshake(self) -> RalfFrame:
        """Send HELLO (with role and optional LASTSEQ) and return WELCOME.

        Unlike CALF, RALF has no separate ``RESUME=1`` flag -- a non-zero
        ``LASTSEQ`` directly on ``HELLO`` triggers replay for every channel
        the chosen ``ROLE`` is entitled to (see
        :meth:`RalfSpyOptions.last_seq`).

        Raises :class:`RalfSpyConnectionError` if the connection closes
        before a WELCOME arrives, or if the gateway sends ERR instead.
        """
        hello_fields = {
            "CLIENT": self._opts.client_name,
            "PROTO": "RALF1",
            "ROLE": self._opts.role,
        }
        if self._opts.last_seq > 0:
            hello_fields["LASTSEQ"] = str(self._opts.last_seq)
        self._send_line("HELLO", hello_fields)

        line = self._recv_line()
        if line is None:
            raise RalfSpyConnectionError("connection closed before WELCOME")
        try:
            frame = parse_line(line)
        except RalfProtocolError as exc:
            raise RalfSpyConnectionError(f"malformed reply to HELLO: {exc}") from exc

        if frame.msg_type == "ERR":
            raise RalfSpyConnectionError(
                f"gateway rejected HELLO: {frame.fields.get('CODE', '?')} "
                f"{frame.fields.get('DETAIL', '')}".rstrip()
            )
        if frame.msg_type != "WELCOME":
            raise RalfSpyConnectionError(f"unexpected reply to HELLO: {frame.msg_type}")
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
        """
        self._running = True
        delivered = 0
        while self._running:
            line = self._recv_line()
            if line is None:
                log.info("gateway closed the connection")
                return
            recv_time = time.time()
            try:
                frame = parse_line(line)
            except RalfProtocolError as exc:
                log.warning("unparseable line from gateway: %r (%s)", line, exc)
                continue

            on_frame(frame, line, recv_time)

            if frame.msg_type != "HB":
                delivered += 1
                if max_frames and delivered >= max_frames:
                    return
            if frame.msg_type == "EXIT":
                return

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Low-level IO
    # ------------------------------------------------------------------

    def _send_line(self, msg_type: str, fields: dict[str, str]) -> None:
        assert self._sock is not None, "connect() must be called first"
        self._sock.sendall(build_line(msg_type, fields))

    def _recv_line(self) -> str | None:
        assert self._sock is not None, "connect() must be called first"
        while b"\n" not in self._buf:
            if len(self._buf) > _MAX_LINE_BYTES:
                raise RalfSpyConnectionError("line from gateway exceeds 4096 bytes")
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
