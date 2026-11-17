"""
The bus: ZeroMQ socket factories and the wire contract they apply.

``make_publisher`` and ``make_pusher`` return wrappers that stamp every
message: a published one with its per-topic and socket-wide sequences and a
causal envelope, a pushed one with a root envelope, each in one frame behind
topic and payload (see ``SequencedPublisher``). ``make_pusher`` also sets
the fail-fast options a single-threaded reactor needs.

All sockets use a shared module-level Context to avoid per-socket overhead.
Callers are responsible for closing sockets when done.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

import zmq

from edumatcher.models.envelope import Envelope, envelope_frame, new_ulid


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
    honest contract for the socket operations used by gateway callers.
    """

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> Any: ...

    def get_monitor_socket(self, events: int = zmq.EVENT_ALL) -> zmq.Socket[bytes]: ...

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


_SNDMORE = int(zmq.SNDMORE)


class BusSocket(zmq.Socket[bytes]):
    """A ``zmq.Socket`` whose ``send_multipart`` does its flag arithmetic on
    plain ints.

    pyzmq's own computes ``zmq.SNDMORE | flags`` for every frame but the last,
    and ``SNDMORE`` is an ``IntFlag``: on Python 3.14 that OR goes through
    ``enum.Flag.__or__`` and costs about 1.2 µs, more than the send itself.
    A 3-frame publish measured 3.8 µs with pyzmq's loop and 1.3 µs with this
    one (Engine latency review 2026-11, P1). Create sockets with
    ``context.socket(kind, socket_class=BusSocket)``.

    pyzmq's up-front check that every frame supports the buffer protocol is
    left out: ``send`` raises the same ``TypeError`` on the bad frame.
    """

    def send_multipart(
        self,
        msg_parts: Any,
        flags: int = 0,
        copy: bool = True,
        track: bool = False,
        **kwargs: Any,
    ) -> Any:
        flags = int(flags)
        more = flags | _SNDMORE
        send = self.send
        for part in msg_parts[:-1]:
            send(part, more, copy=copy, track=track)
        return send(msg_parts[-1], flags, copy=copy, track=track)


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
    monotonic counter in the frame behind the payload lets any subscriber
    notice a hole in what it received.

    The counter is **per topic**, not per socket. A SUB socket filters by
    topic prefix, so a subscriber that takes ``trade.executed`` but not
    ``depth.`` would see a socket-wide counter jump on every message it
    filtered out and report continuous phantom gaps. Counting per topic makes
    every subscriber's view contiguous regardless of what it subscribes to.

    Beside it rides a second, socket-wide counter (``eseq``,
    ``decode_publisher_sequence``): the one total order of everything this
    socket published, for a subscriber that takes every topic (pm-audit).

    Sequences start at 1 and reset when the process restarts — a consumer
    should treat a decrease as a restart, not a gap.

    Both counters go in front of the envelope frame ``CausalPublisher``
    attached, in one frame (``models/message.py`` reads it)::

        [topic, payload, b"seq|eseq|msg_id|causation_id|correlation_id"]

    One frame, not one per field: ZeroMQ charges per frame, and three extra
    frames cost more than stamping them (Messaging review 2026-11, P1). The
    trailer rides outside the JSON payload so publishing never decodes and
    re-encodes a message, and ``decode()`` reads only the first two frames.
    Without an envelope the trailer is ``seq|eseq|``.
    """

    __slots__ = ("_sock", "_seq", "_eseq")

    def __init__(self, sock: SendsMultipart) -> None:
        self._sock: Any = sock
        self._seq: dict[bytes, int] = {}
        #: Socket-wide count (``eseq``): on the engine's socket, one total
        #: order over everything it published. A subscriber that takes every
        #: topic (pm-audit) sees it gap-free; one that filters must use
        #: ``seq``.
        self._eseq = 0

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> Any:
        topic = frames[0]
        nxt = self._seq.get(topic, 0) + 1
        self._seq[topic] = nxt
        self._eseq += 1
        envelope = frames[2] if len(frames) > 2 else b""
        return self._sock.send_multipart(
            [
                topic,
                frames[1],
                b"%d|%d|%b" % (nxt, self._eseq, envelope),
                *frames[3:],
            ],
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
        # Everything not declared above passes through, so this is a drop-in
        # replacement for the raw socket.
        return getattr(self._sock, name)


class CausalPublisher:
    """Publisher wrapper that stamps a causal envelope on every message.

    Wraps a ``SequencedPublisher`` (or any socket-like) and hands it one more
    frame, ``msg_id|causation_id|correlation_id`` — see ``models.envelope``;
    ``SequencedPublisher`` puts its counters in front of it. Wrapping rather than editing each publish site is the
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

    __slots__ = ("_inner", "_cause", "_unit")

    def __init__(self, inner: SendsMultipart) -> None:
        self._inner: Any = inner
        #: The cause's ``(msg_id, correlation_id)``: what a child cites and
        #: inherits, kept as strings so a publish builds no ``Envelope``.
        self._cause: tuple[str, str] | None = None
        self._unit = False

    def set_cause(self, envelope: Envelope | None) -> None:
        """Attribute everything published from now until ``clear_cause``."""
        if envelope is None:
            self._cause = None
        else:
            # As ``Envelope.caused``: a cause naming no chain starts one.
            self._cause = (
                envelope.msg_id,
                envelope.correlation_id or envelope.msg_id,
            )

    def clear_cause(self) -> None:
        self._cause = None

    def begin_unit(self) -> None:
        """Group what is published until ``end_unit`` into one chain.

        For work the engine decides by itself that is still one piece (a
        circuit-breaker reopen: its auction result, prints, fills and
        resume). The first message starts the chain; the rest are caused by
        it. Outside a command only: inside one, its cause already does this.
        """
        self._cause = None
        self._unit = True

    def end_unit(self) -> None:
        self._unit = False
        self._cause = None

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> Any:
        msg_id = new_ulid()
        cause = self._cause
        if cause is None:
            frame = envelope_frame(msg_id, "", msg_id)  # a root
            if self._unit:
                self._cause = (msg_id, msg_id)  # the unit's root
        else:
            frame = envelope_frame(msg_id, cause[0], cause[1])
        return self._inner.send_multipart([*frames, frame], *args, **kwargs)

    def send_with_envelope(self, frames: list[bytes], envelope_frame: bytes) -> Any:
        """Publish carrying an envelope minted elsewhere, verbatim.

        For re-publishing a message this process *received* rather than
        originated. ``send_multipart`` would stamp a fresh id caused by the
        message being republished — making it, absurdly, its own child. The
        recorded copy has to keep the sender's ``msg_id``, for two reasons:
        it is the id every effect's ``causation_id`` already names, and it
        was minted at send time, so the copy sorts into the order the sender
        acted rather than the order this process got round to recording it.
        That second property is what lets a recorder re-publish off the
        latency-critical path without misordering the record.

        The frame goes where ``send_multipart`` puts its own, so
        ``SequencedPublisher`` stamps the copy like any other message.
        """
        return self._inner.send_multipart([*frames, envelope_frame])

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

    Wrapping ``make_pusher`` rather than every process that calls it means a
    new client gets this for free, and cannot forget it. The envelope goes in
    a third frame; ``decode()`` reads the first two, so no receiver had to
    change.
    """

    __slots__ = ("_sock",)

    def __init__(self, sock: SendsMultipart) -> None:
        self._sock: Any = sock

    def send_multipart(self, frames: list[bytes], *args: Any, **kwargs: Any) -> Any:
        msg_id = new_ulid()
        return self._sock.send_multipart(
            [*frames, envelope_frame(msg_id, "", msg_id)], *args, **kwargs
        )

    def get_monitor_socket(self, events: int = zmq.EVENT_ALL) -> zmq.Socket[bytes]:
        return cast(zmq.Socket[bytes], self._sock.get_monitor_socket(events=events))

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
    stamps a per-topic sequence, a socket-wide one (``eseq``) *and* a causal
    envelope. A caller that only
    wants to publish needs to know none of it; a caller that attributes what it
    publishes calls ``set_cause``.
    """
    sock = get_context().socket(zmq.PUB, socket_class=BusSocket)
    sock.bind(addr)
    return CausalPublisher(SequencedPublisher(sock))


def make_pusher(addr: str) -> PushSocket:
    """PUSH socket — gateway sends orders to engine, each with an envelope."""
    sock = get_context().socket(zmq.PUSH, socket_class=BusSocket)
    sock.setsockopt(zmq.SNDTIMEO, _PUSH_SEND_TIMEOUT_MS)
    sock.setsockopt(zmq.SNDHWM, _PUSH_SEND_HWM)
    sock.setsockopt(zmq.IMMEDIATE, _PUSH_IMMEDIATE)
    sock.connect(addr)
    return CausalPusher(sock)


def make_replier(addr: str) -> zmq.Socket[bytes]:
    """REP socket — binds and answers simple request/reply pings.

    Deliberately bare (no envelope/sequencing): for a process whose only use
    of this pattern is proving its own event loop is alive and pumping, not
    for carrying modeled wire messages.
    """
    sock = get_context().socket(zmq.REP)
    sock.bind(addr)
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
