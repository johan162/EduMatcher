"""
Thin ZeroMQ socket factory functions.

All sockets use a shared module-level Context to avoid per-socket overhead.
Callers are responsible for closing sockets when done.
"""

from __future__ import annotations

from typing import Any, Protocol

import zmq

from edumatcher.models.envelope import Envelope


class SendsMultipart(Protocol):
    """Anything the wrappers below can wrap: it only has to send frames.

    Deliberately narrower than ``zmq.Socket``. The wrappers add frames and
    delegate the rest, so requiring a real socket here would buy no safety and
    would stop a test substituting a recorder.
    """

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> Any: ...


class PushSocket(Protocol):
    """What a caller of :func:`make_pusher` actually uses.

    ``make_pusher`` returns a wrapper, not a ``zmq.Socket``, so annotating a
    caller with the concrete socket type is now wrong. This protocol is the
    honest contract: the four members the call sites in ``alf_console``,
    ``alf_gwy``, ``balf_gwy``, ``mm_bot`` and ``scheduler`` between them use.
    """

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> Any: ...

    def setsockopt(self, option: int, value: Any) -> Any: ...

    def close(self, linger: int | None = None) -> None: ...

    @property
    def closed(self) -> bool: ...


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

    The sequence is *inserted* at index 2 rather than appended, so it keeps
    that position when a caller (see ``CausalPublisher``) has already attached
    frames of its own. ``decode_sequence`` reads ``frames[2]`` and must keep
    working whatever else is on the wire behind it.
    """

    __slots__ = ("_sock", "_seq")

    def __init__(self, sock: SendsMultipart) -> None:
        self._sock: Any = sock
        self._seq: dict[bytes, int] = {}

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> Any:
        topic = frames[0]
        nxt = self._seq.get(topic, 0) + 1
        self._seq[topic] = nxt
        return self._sock.send_multipart(
            [frames[0], frames[1], str(nxt).encode("ascii"), *frames[2:]],
            *args,
            **kwargs,
        )

    # The socket surface callers actually use, declared rather than left to
    # __getattr__. __getattr__ keeps working for everything else, but a
    # *declared* member is what lets these wrappers satisfy `PushSocket`
    # structurally — and what makes a typo here a type error instead of an
    # AttributeError at runtime.

    def setsockopt(self, option: int, value: Any) -> Any:
        return self._sock.setsockopt(option, value)

    def close(self, linger: int | None = None) -> None:
        self._sock.close(linger)

    @property
    def closed(self) -> bool:
        return bool(self._sock.closed)

    def __getattr__(self, name: str) -> Any:
        # Everything else (close, closed, setsockopt, ...) passes through, so
        # this is a drop-in replacement for the raw socket.
        return getattr(self._sock, name)


class CausalPublisher:
    """Publisher wrapper that stamps a causal envelope on every message.

    Wraps a ``SequencedPublisher`` (or any socket-like) and appends one frame
    carrying ``msg_id``/``causation_id``/``correlation_id`` — see
    ``models.envelope``. Wrapping rather than editing each publish site is the
    whole point: the engine publishes from something like a hundred places,
    and an envelope that is only attached at the sites someone remembered is
    worse than none, because its absence would read as "nothing caused this".

    Causation comes from ``set_cause``, which the receive loop calls with the
    inbound message's envelope before dispatching it and clears afterwards.
    While a cause is set, everything published is attributed to it and
    inherits its chain; outside that window — a scheduler tick, a
    circuit-breaker trip, anything the engine decided by itself — messages
    start a new chain with no causation, which is the honest answer.

    Not thread-safe by design, and it does not need to be: the engine's PULL
    loop handles exactly one inbound message at a time, so there is never more
    than one cause in flight. A publisher shared across threads would need a
    context variable instead, and this docstring is the warning to whoever
    tries it.
    """

    __slots__ = ("_inner", "_cause")

    def __init__(self, inner: SendsMultipart) -> None:
        self._inner: Any = inner
        self._cause: Envelope | None = None

    def set_cause(self, envelope: Envelope | None) -> None:
        """Attribute everything published from now until ``clear_cause``."""
        self._cause = envelope

    def clear_cause(self) -> None:
        self._cause = None

    def current_envelope(self) -> Envelope:
        """The envelope the next published message would carry."""
        return self._cause.caused() if self._cause is not None else Envelope.root()

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> Any:
        env = self.current_envelope()
        return self._inner.send_multipart([*frames, env.to_frame()], *args, **kwargs)

    # The socket surface callers actually use, declared rather than left to
    # __getattr__. __getattr__ keeps working for everything else, but a
    # *declared* member is what lets these wrappers satisfy `PushSocket`
    # structurally — and what makes a typo here a type error instead of an
    # AttributeError at runtime.

    def setsockopt(self, option: int, value: Any) -> Any:
        return self._inner.setsockopt(option, value)

    def close(self, linger: int | None = None) -> None:
        self._inner.close(linger)

    @property
    def closed(self) -> bool:
        return bool(self._inner.closed)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# ---------------------------------------------------------------------------
# Client-side (connect)
# ---------------------------------------------------------------------------


class CausalPusher:
    """PUSH wrapper that stamps a root causal envelope on every request.

    A gateway's submission is the *start* of a causal chain: nothing on the bus
    caused it, and everything the engine publishes in response descends from
    it. Stamping it here gives the engine an id to cite (see
    ``CausalPublisher``), which is what turns "this ack answers that
    submission" from an inference into a fact.

    Wrapping ``make_pusher`` rather than each of the thirteen processes that
    call it means a new client gets this for free, and cannot forget it. The
    envelope goes in a third frame; ``decode()`` reads the first two, so no
    receiver had to change.
    """

    __slots__ = ("_sock",)

    def __init__(self, sock: SendsMultipart) -> None:
        self._sock: Any = sock

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> Any:
        return self._sock.send_multipart(
            [*frames, Envelope.root().to_frame()], *args, **kwargs
        )

    # The socket surface callers actually use, declared rather than left to
    # __getattr__. __getattr__ keeps working for everything else, but a
    # *declared* member is what lets these wrappers satisfy `PushSocket`
    # structurally — and what makes a typo here a type error instead of an
    # AttributeError at runtime.

    def setsockopt(self, option: int, value: Any) -> Any:
        return self._sock.setsockopt(option, value)

    def close(self, linger: int | None = None) -> None:
        self._sock.close(linger)

    @property
    def closed(self) -> bool:
        return bool(self._sock.closed)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sock, name)


def make_publisher(addr: str) -> "CausalPublisher":
    """PUB socket — broadcasts events, sequenced and causally stamped.

    Composed here so "a publisher" means one thing everywhere: a socket that
    stamps a per-topic sequence *and* a causal envelope. A caller that only
    wants to publish needs to know none of it; a caller that attributes what it
    publishes calls ``set_cause``.
    """
    sock = get_context().socket(zmq.PUB)
    sock.bind(addr)
    return CausalPublisher(SequencedPublisher(sock))


def make_pusher(addr: str) -> PushSocket:
    """PUSH socket — gateway sends orders to engine, each with an envelope."""
    sock = get_context().socket(zmq.PUSH)
    sock.setsockopt(zmq.SNDTIMEO, _PUSH_SEND_TIMEOUT_MS)
    sock.setsockopt(zmq.SNDHWM, _PUSH_SEND_HWM)
    sock.setsockopt(zmq.IMMEDIATE, _PUSH_IMMEDIATE)
    sock.connect(addr)
    return CausalPusher(sock)


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
