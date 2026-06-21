"""Client session state for CALF TCP connections."""

from __future__ import annotations

import socket
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class ClientSession:
    """One connected TCP client and its protocol/session state."""

    sock: socket.socket
    addr: tuple[str, int]
    in_buffer: bytearray = field(default_factory=bytearray)
    out_queue: deque[bytes] = field(default_factory=deque)
    out_offset: int = 0
    closing: bool = False

    # Authentication/session state
    authenticated: bool = False
    client_id: str = ""

    # Timestamp used for both auth-timeout and idle-timeout checks.
    last_activity: float = field(default_factory=time.monotonic)

    # Per-client subscriptions. Stream key is (channel, symbol)
    subscriptions: set[tuple[str, str]] = field(default_factory=set)

    # Last timestamp at which this session received market data (not heartbeat).
    last_market_data_sent: float = field(default_factory=time.monotonic)

    # Last timestamp at which heartbeat was queued for this client.
    last_heartbeat_sent: float = field(default_factory=time.monotonic)
