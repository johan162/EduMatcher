"""Client session state for LALF TCP connections.

Mirrors ``edumatcher.md_gateway.client_session.ClientSession`` in shape —
same non-blocking-socket-plus-buffers pattern — extended with the LALF
handshake fields (§15.5/§15.6) and the per-connection sequence-gap tracking
§15.7's ``SEQ`` field exists to make observable.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field

from edumatcher.logclient.protocol import FrameReader


@dataclass
class LogSession:
    """One connected LALF TCP client and its protocol/session state."""

    sock: socket.socket
    addr: tuple[str, int]
    reader: FrameReader = field(default_factory=FrameReader)
    out_queue: "list[bytes]" = field(default_factory=list)
    out_offset: int = 0
    closing: bool = False

    # Handshake / identity state (§15.5)
    authenticated: bool = False
    client: str = ""
    pid: int = 0
    host: str = ""
    instance: str | None = None
    session_id: str = ""

    # Absolute connection timestamp for handshake-timeout checks.
    connected_at: float = field(default_factory=time.monotonic)

    # Timestamp used for both hello-timeout and idle-timeout checks.
    last_activity: float = field(default_factory=time.monotonic)

    # Highest SEQ seen from this connection so far (0 = none yet) — purely
    # observational bookkeeping; LALF defines no server-side action on a
    # gap (§15.16, item 6: SEQ is per-connection and reset on reconnect),
    # but a gap is still useful to surface via debug logging.
    last_seq: int = 0

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
