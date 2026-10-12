"""One non-blocking ALF TCP session.

``AlfConnection`` never blocks after ``open()``: writes are queued and
flushed as the socket allows, reads return whatever complete lines have
arrived. The owner polls ``fileno()`` (e.g. with a zmq.Poller) and calls
``read()`` / ``flush()``; ``tick()`` keeps the session alive with a PING
well inside the gateway's idle timeout.
"""

from __future__ import annotations

import errno
import socket
from enum import Enum

from edumatcher.alf_client.protocol import AlfMessage, bye, hello, parse_response, ping

PING_INTERVAL = 10.0
MAX_OUTBOUND_BYTES = 4 * 1024 * 1024


class State(str, Enum):
    CLOSED = "CLOSED"
    HELLO_SENT = "HELLO_SENT"
    READY = "READY"


class AlfConnection:
    def __init__(
        self,
        host: str,
        port: int,
        gateway_id: str,
        client: str = "edumatcher",
        feed: str | None = None,
    ) -> None:
        self.host = host
        self.feed = feed
        self.port = port
        self.gateway_id = gateway_id.upper()
        self.client = client
        self.state = State.CLOSED
        self.close_reason = ""
        self._sock: socket.socket | None = None
        self._in = bytearray()
        self._out = bytearray()
        self._last_sent = 0.0

    # --- lifecycle -----------------------------------------------------------
    def open(self, now: float, timeout: float = 3.0) -> None:
        """Connect and send HELLO. Raises OSError if the gateway is unreachable."""
        sock = socket.create_connection((self.host, self.port), timeout=timeout)
        sock.setblocking(False)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._in.clear()
        self._out.clear()
        self.close_reason = ""
        self.state = State.HELLO_SENT
        self.send(hello(self.gateway_id, self.client, self.feed), now)
        self.flush()

    def close(self, reason: str = "client_close", say_bye: bool = True) -> None:
        if self._sock is None:
            return
        if say_bye and self.state == State.READY:
            try:
                self._sock.setblocking(True)
                self._sock.settimeout(0.5)
                self._sock.sendall(bytes(self._out) + bye())
            except OSError:
                pass
        try:
            self._sock.close()
        finally:
            self._sock = None
            self.state = State.CLOSED
            self.close_reason = self.close_reason or reason

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def fileno(self) -> int:
        return self._sock.fileno() if self._sock is not None else -1

    # --- outbound -------------------------------------------------------------
    def send(self, line: bytes, now: float) -> bool:
        """Queue a line; False if the session is closed or hopelessly backed up."""
        if self._sock is None:
            return False
        if len(self._out) + len(line) > MAX_OUTBOUND_BYTES:
            self._fail("outbound buffer overflow")
            return False
        self._out += line
        self._last_sent = now
        return True

    def flush(self) -> None:
        while self._out and self._sock is not None:
            try:
                n = self._sock.send(self._out)
            except BlockingIOError:
                return
            except OSError as exc:
                self._fail(f"send failed: {exc.strerror or exc}")
                return
            del self._out[:n]

    @property
    def wants_write(self) -> bool:
        return bool(self._out)

    def tick(self, now: float) -> None:
        if self.state == State.READY and now - self._last_sent >= PING_INTERVAL:
            self.send(ping(), now)
        self.flush()

    # --- inbound ----------------------------------------------------------------
    def read(self) -> list[AlfMessage]:
        """Every complete line received so far."""
        if self._sock is None:
            return []
        while True:
            try:
                chunk = self._sock.recv(65536)
            except BlockingIOError:
                break
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    break
                self._fail(f"recv failed: {exc.strerror or exc}")
                break
            if not chunk:
                self._fail("closed by gateway")
                break
            self._in += chunk
        out: list[AlfMessage] = []
        while True:
            nl = self._in.find(b"\n")
            if nl < 0:
                break
            raw = bytes(self._in[:nl]).decode("utf-8", errors="replace")
            del self._in[: nl + 1]
            msg = parse_response(raw)
            if msg is None:
                continue
            if msg.msg_type == "WELCOME":
                self.state = State.READY
            out.append(msg)
        return out

    def _fail(self, reason: str) -> None:
        self.close_reason = reason
        self.close(reason, say_bye=False)
