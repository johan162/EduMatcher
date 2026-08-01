"""TCP client session logic for pm-calf-spy.

A thin adapter over :mod:`edumatcher.calf_client`, which owns the socket,
the handshake, line framing and the keepalive. This module exists to keep
``cli.py``'s vocabulary -- spy options, a resume request, a frame callback
that also gets the raw line -- while there is only one implementation of
the protocol behind it.

**The spy runs the library passively** (``auto_recover=False``). A
diagnostic tool has to show the wire exactly as it is: it must not send a
``RESUME`` the operator did not ask for, and must not hide a duplicate the
gateway actually sent. Both would misrepresent the feed it exists to
reveal. Sequence gaps are still *detected* -- see ``on_gap`` -- they are
simply reported rather than repaired.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from edumatcher.calf_client import (
    CalfClient,
    CalfClientOptions,
    CalfConnectionError,
)
from edumatcher.md_gateway.protocol import CalfFrame

log = logging.getLogger(__name__)

_DEFAULT_PING_INTERVAL_SEC = 60.0

#: Kept as its own name so ``cli.py`` and the tests need not know that the
#: transport moved. Every failure the spy can report is one of these.
CalfSpyConnectionError = CalfConnectionError


@dataclass(frozen=True)
class ResumeRequest:
    """A single-stream ``RESUME`` request to send just after the handshake."""

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
        self._client = CalfClient(
            CalfClientOptions(
                host=options.host,
                port=options.port,
                client_name=options.client_name,
                # The spy subscribes explicitly after inspecting WELCOME's
                # CH_SUPPORTED, so it takes nothing on connect.
                channels=(),
                symbols=(),
                ping_interval_sec=options.ping_interval_sec,
                # One connection, one session: an operator watching a feed
                # wants to see it drop, not have it silently re-established
                # underneath them.
                reconnect=False,
                auto_recover=False,
                track_state=False,
                # Nothing on the wire the operator did not ask for, for the
                # same reason as auto_recover above: an unrequested SYMBOLS
                # would appear in the very capture the spy exists to take.
                request_symbols=False,
            )
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the TCP connection. Raises :class:`CalfSpyConnectionError`."""
        self._client.connect()

    def close(self) -> None:
        self._client.stop()
        self._client.disconnect()

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------

    def handshake(self) -> CalfFrame:
        """Send HELLO, then any RESUME request, and return the parsed WELCOME.

        RESUME is its own command sent after the handshake rather than a flag
        on HELLO, so replay is no longer limited to one stream per connection.

        Raises :class:`CalfSpyConnectionError` if the connection closes
        before a WELCOME arrives, or if the gateway sends ERR instead.
        """
        welcome = self._client.handshake()

        resume = self._opts.resume
        if resume is not None:
            self._client.resume(resume.channel, resume.symbol, resume.last_seq)
        return welcome

    def subscribe(self, channels: list[str], symbols: list[str]) -> None:
        """Send one ``SUB`` for the Cartesian product of channels x symbols."""
        self._client.subscribe(channels, symbols)

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
        # The raw line and its arrival time are what the renderer formats,
        # so they are paired back up with the parsed frame here. `on_line`
        # fires immediately before the parse and dispatch of that same
        # line, on the same thread, so holding only the latest is both
        # sufficient and immune to the drift a queue would accumulate the
        # first time a line failed to parse and never reached `deliver`.
        latest: list[tuple[str, float]] = [("", 0.0)]

        def on_line(line: str, recv_time: float) -> None:
            latest[0] = (line, recv_time)

        def deliver(frame: CalfFrame) -> None:
            raw, recv_time = latest[0]
            on_frame(frame, raw, recv_time)

        self._client.run(deliver, on_line=on_line, max_frames=max_frames)

    def stop(self) -> None:
        self._client.stop()
