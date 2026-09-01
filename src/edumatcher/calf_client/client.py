"""A CALF market data client that stays connected and stays correct.

:class:`CalfClient` owns one TCP session to ``pm-md-gwy`` and hides the
things every CALF consumer would otherwise have to rediscover: reconnecting
with backoff, re-subscribing afterwards, keeping the session alive, noticing
sequence gaps, repairing them with ``RESUME``, discarding the duplicates
that repair sends back, and reading per-symbol display precision off the
handshake.

Usage is a blocking loop with callbacks::

    client = CalfClient(CalfClientOptions(
        symbols=["AAPL", "MSFT"],
        channels=["TOP", "TRADE", "STATE"],
    ))
    client.run(on_frame=lambda frame: print(frame.msg_type))

``run()`` returns when :meth:`stop` is called, when the gateway rejects the
session in a way that cannot be retried, or -- if ``reconnect=False`` --
when the connection drops.

Two layers are available and the caller picks. The frame stream is the
lower one: every message, already de-duplicated and gap-checked. The upper
one is :attr:`state`, a :class:`~edumatcher.calf_client.state.MarketState`
maintained only when ``track_state`` is set, which folds those frames into
current top-of-book, depth, session phase and halt status.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from edumatcher.md_gateway.protocol import (
    CalfFrame,
    CalfProtocolError,
    build_line,
    parse_line,
)

from edumatcher.calf_client.recovery import (
    Gap,
    SequenceTracker,
    has_snapshot,
    is_resumable,
)
from edumatcher.calf_client.refdata import ReferenceData
from edumatcher.calf_client.state import MarketState

log = logging.getLogger(__name__)

_MAX_LINE_BYTES = 4096
_RECV_CHUNK_BYTES = 4096

# Errors that mean this session is over. The gateway closes the connection
# on all four, so the only question is whether reconnecting can help.
# PROTO_MISMATCH cannot be fixed by retrying -- the client is speaking the
# wrong protocol version and will do so again. The other three are
# transient with respect to the connection itself.
_FATAL_ERROR_CODES = frozenset({"PROTO_MISMATCH"})
_SESSION_ENDING_ERROR_CODES = frozenset(
    {"PROTO_MISMATCH", "AUTH_REQUIRED", "SLOW_CLIENT", "BAD_MESSAGE"}
)


class CalfError(RuntimeError):
    """Base class for every error this package raises."""


class CalfConnectionError(CalfError):
    """The connection could not be established, or the handshake failed."""


class CalfProtocolMismatch(CalfError):
    """The gateway rejected this client's protocol version.

    Separate from :class:`CalfConnectionError` because retrying cannot help.
    """


FrameHandler = Callable[[CalfFrame], None]
GapHandler = Callable[[Gap], None]
StateHandler = Callable[[str], None]
LineHandler = Callable[[str, float], None]
"""``(raw_line, recv_time_seconds)``, before parsing.

For tools that render or record the wire text itself. It fires for every
line received, including ones the frame stream drops as duplicates -- a
recorder wants what arrived, not what was acted on.
"""


@dataclass
class CalfClientOptions:
    """Everything one client session needs to know."""

    host: str = "127.0.0.1"
    port: int = 5570
    client_name: str = "calf-client"

    #: Channels to subscribe on connect, and again after every reconnect.
    channels: Sequence[str] = ("TOP", "TRADE", "STATE")
    #: Symbols for those channels. ``["*"]`` is accepted by the gateway only
    #: for ``STATE``/``TOP``/``TRADE``/``AUCTION``; ``INDEX``, ``DEPTH`` and
    #: ``CB`` always need explicit ids and are best given their own client
    #: or their own :meth:`subscribe` call.
    symbols: Sequence[str] = ("*",)
    #: Index ids for a separate ``SUB|CH=INDEX``, which never accepts ``*``.
    index_ids: Sequence[str] = ()

    #: Reconnect with exponential backoff when the connection drops.
    reconnect: bool = True
    reconnect_min_sec: float = 0.5
    reconnect_max_sec: float = 30.0
    connect_timeout_sec: float = 5.0

    #: Keepalive interval. The gateway drops an idle client, and a
    #: subscriber that only listens sends nothing after its initial SUB.
    #: Zero disables the keepalive thread entirely.
    ping_interval_sec: float = 30.0

    #: Maintain a :class:`MarketState` from the frame stream.
    track_state: bool = True

    #: Ask for the instrument universe with ``SYMBOLS`` after the handshake.
    #:
    #: On by default because ``WELCOME|SYMBOLS=`` is optional -- absent
    #: whenever the gateway could not read an engine config -- so the reply
    #: is the reliable route to the universe, and it carries ``REF=`` too.
    #: Set ``False`` for an observer that must put nothing on the wire it
    #: was not asked to.
    request_symbols: bool = True

    #: Repair gaps with ``RESUME`` and suppress the duplicates that repair
    #: sends back.
    #:
    #: Set ``False`` for a passive observer -- a spy, a tap, a recorder --
    #: which must show the wire exactly as it is. Gaps are still detected
    #: and reported through ``on_gap``; the difference is that nothing is
    #: sent upstream and nothing is withheld from the caller. A diagnostic
    #: tool that hid a duplicate, or that injected a ``RESUME`` of its own,
    #: would be misrepresenting the feed it exists to show.
    auto_recover: bool = True

    #: Extra subscriptions held for the life of the client, as
    #: ``(channel, symbol)`` pairs -- for the per-symbol channels that
    #: cannot ride the wildcard SUB above.
    extra_subscriptions: Sequence[tuple[str, str]] = field(default_factory=tuple)


class CalfClient:
    """One managed CALF session. Drive it with :meth:`run`.

    Not thread-safe beyond what it needs: :meth:`stop` and :meth:`subscribe`
    may be called from another thread, everything else belongs to the thread
    running the loop.
    """

    def __init__(self, options: CalfClientOptions | None = None) -> None:
        self._opts = options or CalfClientOptions()
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._send_lock = threading.Lock()
        self._running = False
        self._stopped = threading.Event()

        self._sequence = SequenceTracker()
        self._reference = ReferenceData()
        self._state = MarketState() if self._opts.track_state else None
        self._seen_trade_ids: set[str] = set()

        self._welcome: CalfFrame | None = None
        self._supported: set[str] = set()
        self._held: list[tuple[str, str]] = list(self._opts.extra_subscriptions)

        self._ping_thread: threading.Thread | None = None
        self._ping_stop = threading.Event()

    # -- public accessors -----------------------------------------------

    @property
    def reference(self) -> ReferenceData:
        """Per-symbol display precision learned from the handshake."""
        return self._reference

    @property
    def state(self) -> MarketState | None:
        """Cached market state, or ``None`` when ``track_state`` is off."""
        return self._state

    @property
    def welcome(self) -> CalfFrame | None:
        """The most recent ``WELCOME``, or ``None`` before the first one."""
        return self._welcome

    def supports(self, channel: str) -> bool:
        """Whether the gateway advertised a channel.

        A gateway predating ``CH_SUPPORTED`` sends no such field at all;
        an empty set is read as "supports everything", which keeps this
        client working against one rather than refusing to subscribe.
        """
        return not self._supported or channel in self._supported

    # -- lifecycle ------------------------------------------------------

    def connect(self) -> None:
        """Open the connection without handshaking.

        Only needed for the manual sequence -- connect, read ``WELCOME``,
        decide what to subscribe to, then :meth:`run`. :meth:`run` does all
        of this itself when called on an unconnected client, which is what
        most callers want.
        """
        self._connect()

    def handshake(self) -> CalfFrame:
        """Perform the ``HELLO``/``WELCOME`` exchange and return the reply.

        Useful before subscribing, since ``CH_SUPPORTED`` on the reply says
        which channels this gateway actually has.
        """
        return self._handshake()

    def disconnect(self) -> None:
        """Close the socket without stopping a running loop."""
        self._close_socket()

    def run(
        self,
        on_frame: FrameHandler | None = None,
        *,
        on_gap: GapHandler | None = None,
        on_connection_change: StateHandler | None = None,
        on_line: LineHandler | None = None,
        max_frames: int = 0,
    ) -> None:
        """Connect, subscribe, and dispatch frames until stopped.

        ``on_frame`` sees every message that survives de-duplication, after
        :attr:`state` has been updated, so a handler can read the merged
        book rather than the raw delta it just received.

        ``on_gap`` sees holes that could not be repaired -- a ``RESUME``
        that came back ``REPLAY_MISS``, or a channel with no replay path.
        A successful repair backfills the messages themselves and reports
        nothing, because nothing was lost.

        ``on_connection_change`` receives ``"connected"``,
        ``"disconnected"`` and ``"reconnecting"``, for a status indicator.

        ``on_line`` sees the raw text of every line as it arrives, before
        parsing and before de-duplication.

        ``max_frames`` stops after that many non-heartbeat frames, which is
        mostly useful in tests. Zero means unlimited.
        """
        self._running = True
        self._stopped.clear()
        delivered = 0
        backoff = self._opts.reconnect_min_sec

        try:
            while self._running:
                try:
                    # Skipped when the caller already connected and
                    # handshook by hand; every reconnect goes through here.
                    if self._sock is None:
                        self._connect()
                        self._handshake()
                        self._subscribe_all()
                except CalfProtocolMismatch:
                    raise
                except (CalfConnectionError, OSError) as exc:
                    if not self._opts.reconnect:
                        raise CalfConnectionError(str(exc)) from exc
                    log.warning("connect failed: %s; retrying in %.1fs", exc, backoff)
                    if on_connection_change:
                        on_connection_change("reconnecting")
                    if self._stopped.wait(backoff):
                        return
                    backoff = min(backoff * 2, self._opts.reconnect_max_sec)
                    continue

                backoff = self._opts.reconnect_min_sec
                if on_connection_change:
                    on_connection_change("connected")
                self._start_ping_thread()

                try:
                    delivered = self._read_loop(
                        on_frame, on_gap, on_line, delivered, max_frames
                    )
                    if max_frames and delivered >= max_frames:
                        return
                finally:
                    self._stop_ping_thread()
                    self._close_socket()

                if not self._running:
                    return
                if on_connection_change:
                    on_connection_change("disconnected")
                if not self._opts.reconnect:
                    return
                log.info("connection lost; reconnecting in %.1fs", backoff)
                if on_connection_change:
                    on_connection_change("reconnecting")
                if self._stopped.wait(backoff):
                    return
                backoff = min(backoff * 2, self._opts.reconnect_max_sec)
        finally:
            self._running = False
            self._stop_ping_thread()
            self._close_socket()

    def stop(self) -> None:
        """Ask :meth:`run` to return. Safe to call from any thread."""
        self._running = False
        self._stopped.set()
        self._ping_stop.set()

    def subscribe(self, channels: Sequence[str], symbols: Sequence[str]) -> None:
        """Add subscriptions, now and after every future reconnect.

        The gateway keeps no subscription state across connections, so
        anything asked for here is recorded and re-issued on reconnect --
        a caller should not have to notice that a drop happened.
        """
        wanted = [ch for ch in channels if self.supports(ch)]
        if not wanted or not symbols:
            return
        for channel in wanted:
            for symbol in symbols:
                if (channel, symbol) not in self._held:
                    self._held.append((channel, symbol))
        if self._sock is not None:
            self._send("SUB", {"CH": ",".join(wanted), "SYM": ",".join(symbols)})

    def resume(self, channel: str, symbol: str, last_seq: int) -> None:
        """Send an explicit ``RESUME`` for one stream.

        Rarely needed: :meth:`run` already resumes any gap it detects. This
        exists for a client resuming from a position it persisted across a
        process restart, which nothing else can know about.
        """
        self._send("RESUME", {"CH": channel, "SYM": symbol, "LASTSEQ": str(last_seq)})

    # -- connection -----------------------------------------------------

    def _connect(self) -> None:
        try:
            sock = socket.create_connection(
                (self._opts.host, self._opts.port),
                timeout=self._opts.connect_timeout_sec,
            )
        except OSError as exc:
            raise CalfConnectionError(
                f"could not connect to {self._opts.host}:{self._opts.port}: {exc}"
            ) from exc
        sock.settimeout(None)
        self._sock = sock
        self._buf.clear()
        # A new connection may be a new gateway process, and so a new
        # numbering for every stream. Positions are kept -- that is what
        # makes a gap across the drop visible at all -- but the generation
        # moves, which is what lets a restart be told from a replay.
        self._sequence.new_connection()
        log.info("connected to %s:%s", self._opts.host, self._opts.port)

    def _close_socket(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _handshake(self) -> CalfFrame:
        """``HELLO``/``WELCOME``, then ask for the symbol universe.

        ``HELLO`` carries identification only. Replay is the standalone
        ``RESUME`` command -- as a flag here it could only ever run once
        per connection, which is no use to a client following several
        streams.
        """
        self._send("HELLO", {"CLIENT": self._opts.client_name, "PROTO": "CALF1"})

        line = self._recv_line()
        if line is None:
            raise CalfConnectionError("connection closed before WELCOME")
        try:
            frame = parse_line(line)
        except CalfProtocolError as exc:
            raise CalfConnectionError(f"malformed reply to HELLO: {exc}") from exc

        if frame.msg_type == "ERR":
            code = frame.fields.get("CODE", "?")
            detail = f"{code} {frame.fields.get('MSG', '')}".rstrip()
            if code in _FATAL_ERROR_CODES:
                raise CalfProtocolMismatch(f"gateway rejected HELLO: {detail}")
            raise CalfConnectionError(f"gateway rejected HELLO: {detail}")
        if frame.msg_type != "WELCOME":
            raise CalfConnectionError(f"unexpected reply to HELLO: {frame.msg_type}")

        self._welcome = frame
        raw_supported = frame.fields.get("CH_SUPPORTED")
        self._supported = set(raw_supported.split(",")) if raw_supported else set()
        self._reference.learn(frame.fields.get("REF"))

        # Ask rather than rely on WELCOME|SYMBOLS=, which is optional and
        # absent whenever the gateway could not read an engine config. The
        # reply carries REF= too, so this doubles as the reliable route to
        # display precision.
        if self._opts.request_symbols:
            self._send("SYMBOLS", {})
        return frame

    def _subscribe_all(self) -> None:
        """Issue every subscription this client should hold, from scratch."""
        channels = [ch for ch in self._opts.channels if self.supports(ch)]
        if channels and self._opts.symbols:
            self._send(
                "SUB",
                {"CH": ",".join(channels), "SYM": ",".join(self._opts.symbols)},
            )
        if self._opts.index_ids and self.supports("INDEX"):
            self._send("SUB", {"CH": "INDEX", "SYM": ",".join(self._opts.index_ids)})
        for channel, symbol in self._held:
            if self.supports(channel):
                self._send("SUB", {"CH": channel, "SYM": symbol})

    # -- read loop ------------------------------------------------------

    def _read_loop(
        self,
        on_frame: FrameHandler | None,
        on_gap: GapHandler | None,
        on_line: LineHandler | None,
        delivered: int,
        max_frames: int,
    ) -> int:
        while self._running:
            line = self._recv_line()
            if line is None:
                log.info("gateway closed the connection")
                return delivered
            if on_line is not None:
                on_line(line, time.time())
            try:
                frame = parse_line(line)
            except CalfProtocolError as exc:
                log.warning("unparseable line from gateway: %r (%s)", line, exc)
                continue

            if not self._dispatch(frame, on_gap):
                continue
            if on_frame is not None:
                on_frame(frame)

            if frame.msg_type != "HB":
                delivered += 1
                if max_frames and delivered >= max_frames:
                    return delivered
        return delivered

    def _dispatch(self, frame: CalfFrame, on_gap: GapHandler | None) -> bool:
        """Apply protocol housekeeping. Returns whether to hand the frame on."""
        if frame.msg_type in ("HB", "PONG"):
            return True

        if frame.msg_type == "SYMBOLS":
            self._reference.learn(frame.fields.get("REF"))
            return True

        if frame.msg_type == "ERR":
            self._handle_error(frame, on_gap)
            return True

        channel = frame.fields.get("CH", "")
        symbol = frame.fields.get("SYM", "")
        if not channel:
            return True

        try:
            seq = int(frame.fields.get("SEQ", "0"))
        except ValueError:
            seq = 0

        process, gap = self._sequence.observe(frame.msg_type, channel, symbol, seq)

        if not self._opts.auto_recover:
            # A passive observer reports what it sees and changes nothing:
            # no RESUME on the wire, no message withheld. A diagnostic tool
            # that quietly hid a duplicate, or that injected traffic of its
            # own, would be lying about the feed it exists to show.
            if gap is not None and on_gap is not None:
                on_gap(
                    Gap(
                        gap.channel,
                        gap.symbol,
                        gap.first_seq,
                        gap.last_seq,
                        frame.fields.get("TS", ""),
                    )
                )
            if self._state is not None:
                self._state.apply(frame)
            return True

        if not process:
            # A duplicate the gateway replayed and this client already
            # handled. Dropped here so it can never be applied twice.
            return False

        if frame.msg_type == "TRADE":
            trade_id = frame.fields["TRADE_ID"]
            if trade_id in self._seen_trade_ids:
                return False
            self._seen_trade_ids.add(trade_id)

        if gap is not None:
            self._on_gap_detected(gap, frame.fields.get("TS", ""), on_gap)

        # A SNAP on a channel that has none carries an envelope and no
        # payload; an older gateway sends one after REPLAY_MISS. Decoded by
        # CH like any other line it reads as an event that never happened,
        # so it is accounted for above (it re-baselines) and dropped here.
        if frame.msg_type == "SNAP" and not has_snapshot(channel):
            return False

        if self._state is not None:
            self._state.apply(frame)
        return True

    def _on_gap_detected(self, gap: Gap, ts: str, on_gap: GapHandler | None) -> None:
        if is_resumable(gap.channel):
            log.info(
                "gap on (%s,%s): %d..%d missing; resuming",
                gap.channel,
                gap.symbol,
                gap.first_seq,
                gap.last_seq,
            )
            self.resume(gap.channel, gap.symbol, gap.first_seq - 1)
            return

        # A gap on a snapshot-baselined channel closes itself: the SUB that
        # follows every reconnect triggers a fresh SNAP, so whatever was
        # missed is superseded before anyone could act on knowing about it.
        if has_snapshot(gap.channel):
            return

        if on_gap is not None:
            on_gap(Gap(gap.channel, gap.symbol, gap.first_seq, gap.last_seq, ts))

    def _handle_error(self, frame: CalfFrame, on_gap: GapHandler | None) -> None:
        code = frame.fields.get("CODE", "?")
        channel = frame.fields.get("CH", "")
        symbol = frame.fields.get("SYM", "")
        log.warning("gateway ERR %s: %s", code, frame.fields.get("MSG", ""))

        if code == "REPLAY_MISS" and channel:
            # The one RESUME failure that makes a gap permanent: the buffer
            # aged out before this client asked. Nothing will fill the hole,
            # so the range must not stay open to mislabel a later
            # redelivery as backfill.
            position = self._sequence.position(channel, symbol)
            self._sequence.abandon_holes(channel, symbol)
            if on_gap is not None and not has_snapshot(channel):
                on_gap(
                    Gap(
                        channel=channel,
                        symbol=symbol,
                        first_seq=0,
                        last_seq=position or 0,
                        ts=frame.fields.get("TS", ""),
                    )
                )

        if code in _SESSION_ENDING_ERROR_CODES:
            # The gateway closes the connection on these; the read loop
            # will see EOF next. Reconnect handles the retryable ones.
            log.info("session-ending error %s; connection will drop", code)

    # -- keepalive ------------------------------------------------------

    def _start_ping_thread(self) -> None:
        interval = self._opts.ping_interval_sec
        if interval <= 0:
            return
        self._ping_stop.clear()
        thread = threading.Thread(
            target=self._ping_loop,
            args=(interval,),
            daemon=True,
            name="calf-client-ping",
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
                self._send("PING", {})
            except (OSError, CalfError) as exc:
                log.info("ping send failed: %s", exc)
                return

    # -- low-level IO ---------------------------------------------------

    def _send(self, msg_type: str, fields: dict[str, str]) -> None:
        sock = self._sock
        if sock is None:
            raise CalfConnectionError("not connected")
        with self._send_lock:
            try:
                sock.sendall(build_line(msg_type, fields))
            except OSError as exc:
                raise CalfConnectionError(f"send failed: {exc}") from exc

    def _recv_line(self) -> str | None:
        sock = self._sock
        if sock is None:
            return None
        while b"\n" not in self._buf:
            if len(self._buf) > _MAX_LINE_BYTES:
                raise CalfConnectionError("line from gateway exceeds 4096 bytes")
            try:
                chunk = sock.recv(_RECV_CHUNK_BYTES)
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
