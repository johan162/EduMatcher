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


class SequencedPublisher:
    """PUB socket that stamps every message with a per-topic sequence number.

    ZeroMQ PUB/SUB drops silently once a subscriber falls behind its
    high-water mark, and nothing in the delivered message reveals it. A
    monotonic counter appended as a third frame lets any subscriber notice a
    hole in what it received.

    The counter is **per topic**, not per socket. A SUB socket filters by
    topic prefix, so a subscriber that takes ``trade.executed`` but not
    ``depth.`` would see a socket-wide counter jump on every message it
    filtered out and report continuous phantom gaps. Counting per topic makes
    every subscriber's view contiguous regardless of what it subscribes to.

    The sequence rides in a third frame rather than inside the JSON payload so
    the hot publish path never has to decode and re-encode a message; adding
    it costs one dict lookup and one int-to-bytes per send. ``decode()`` reads
    only the first two frames, so every existing subscriber is unaffected.

    Sequences start at 1 for each topic and reset when the process restarts —
    a consumer should treat a decrease as a restart, not a gap.
    """

    __slots__ = ("_sock", "_seq")

    def __init__(self, sock: zmq.Socket[bytes]) -> None:
        self._sock = sock
        self._seq: dict[bytes, int] = {}

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> Any:
        topic = frames[0]
        nxt = self._seq.get(topic, 0) + 1
        self._seq[topic] = nxt
        return self._sock.send_multipart(
            [*frames, str(nxt).encode("ascii")], *args, **kwargs
        )

    def __getattr__(self, name: str) -> Any:
        # Everything else (close, closed, setsockopt, ...) passes through, so
        # this is a drop-in replacement for the raw socket.
        return getattr(self._sock, name)


def make_publisher(addr: str) -> SequencedPublisher:
    """PUB socket — engine broadcasts events, each stamped with a sequence."""
    sock = get_context().socket(zmq.PUB)
    sock.bind(addr)
    return SequencedPublisher(sock)


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


def make_subscriber(
    addr: str, *topics: str, rcvhwm: int | None = None
) -> zmq.Socket[bytes]:
    """
    SUB socket — subscribes to one or more topic prefixes.
    Pass no topics (or empty string) to receive everything.

    ``rcvhwm`` raises the receive high-water mark above ZMQ's default of 1000
    messages. Past the mark a SUB socket drops silently, so a recorder that
    must not miss messages wants a deeper buffer to ride out bursts. It is set
    before ``connect()`` because ZMQ only applies the option to connections
    made afterwards.
    """
    sock = get_context().socket(zmq.SUB)
    if rcvhwm is not None:
        sock.setsockopt(zmq.RCVHWM, rcvhwm)
    sock.connect(addr)
    if not topics:
        sock.setsockopt(zmq.SUBSCRIBE, b"")
    else:
        for t in topics:
            sock.setsockopt(zmq.SUBSCRIBE, t.encode())
    return sock  # type: ignore[no-any-return]
