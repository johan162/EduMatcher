"""
Thin ZeroMQ socket factory functions.

All sockets use a shared module-level Context to avoid per-socket overhead.
Callers are responsible for closing sockets when done.
"""

from __future__ import annotations

from typing import Any

import zmq

_context: zmq.Context[Any] | None = None

# PUSH fail-fast defaults for public gateways: never block the single-threaded
# reactor when engine PULL is unavailable or backpressured.
_PUSH_SEND_TIMEOUT_MS = 0
_PUSH_SEND_HWM = 1000
_PUSH_IMMEDIATE = 1


def get_context() -> zmq.Context[Any]:
    global _context
    if _context is None:
        _context = zmq.Context.instance()
    return _context


# ---------------------------------------------------------------------------
# Engine-side (bind)
# ---------------------------------------------------------------------------


def make_puller(addr: str) -> zmq.Socket[bytes]:
    """PULL socket — engine receives orders."""
    sock = get_context().socket(zmq.PULL)
    sock.bind(addr)
    return sock  # type: ignore[no-any-return]


def make_publisher(addr: str) -> zmq.Socket[bytes]:
    """PUB socket — engine broadcasts events."""
    sock = get_context().socket(zmq.PUB)
    sock.bind(addr)
    return sock  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Client-side (connect)
# ---------------------------------------------------------------------------


def make_pusher(addr: str) -> zmq.Socket[bytes]:
    """PUSH socket — gateway sends orders to engine."""
    sock = get_context().socket(zmq.PUSH)
    sock.setsockopt(zmq.SNDTIMEO, _PUSH_SEND_TIMEOUT_MS)
    sock.setsockopt(zmq.SNDHWM, _PUSH_SEND_HWM)
    sock.setsockopt(zmq.IMMEDIATE, _PUSH_IMMEDIATE)
    sock.connect(addr)
    return sock  # type: ignore[no-any-return]


def make_subscriber(addr: str, *topics: str) -> zmq.Socket[bytes]:
    """
    SUB socket — subscribes to one or more topic prefixes.
    Pass no topics (or empty string) to receive everything.
    """
    sock = get_context().socket(zmq.SUB)
    sock.connect(addr)
    if not topics:
        sock.setsockopt(zmq.SUBSCRIBE, b"")
    else:
        for t in topics:
            sock.setsockopt(zmq.SUBSCRIBE, t.encode())
    return sock  # type: ignore[no-any-return]
