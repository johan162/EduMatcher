"""ZMQ SUB client session logic for pm-dc-spy.

Deliberately independent of argparse/console concerns: :class:`DcSpyClient`
owns the ``zmq.SUB`` socket and the receive loop, and hands each decoded
message to a caller-supplied callback. This keeps the network code
unit-testable without a terminal, and keeps ``cli.py`` a thin wrapper that
only deals with argument parsing and output rendering -- the same split used
by ``calf_spy``/``ralf_spy``.

Unlike CALF/RALF, the drop-copy feed is a plain ZeroMQ PUB/SUB stream: there
is no HELLO/WELCOME handshake and no heartbeat protocol to keep alive. A
subscriber simply connects and applies a topic-prefix filter -- see
``edumatcher.engine.drop_copy`` and ``docs/user-guide/200-drop-copy.md``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import zmq

from edumatcher.models.message import decode

log = logging.getLogger(__name__)

_DEFAULT_ADDR = "tcp://127.0.0.1:5557"
_RECV_TIMEOUT_MS = 500  # poll interval so Ctrl-C / max_messages is responsive

# Topic prefixes used by DropCopyPublisher (engine/drop_copy.py).
EVENT_TOPIC_PREFIX = "drop_copy.event."
REPLAY_TOPIC_PREFIX = "drop_copy.replay."


class DcSpyConnectionError(RuntimeError):
    """Raised when the ZMQ socket cannot be created/connected."""


@dataclass
class DcSpyOptions:
    """Connection and subscription parameters for one spy session."""

    host: str = "127.0.0.1"
    port: int = 5557
    gateway: str | None = None  # None/"" => all gateways (subscribe to prefix only)
    replay_of: str | None = None  # recipient_id => also subscribe to its replay topic

    @property
    def addr(self) -> str:
        return f"tcp://{self.host}:{self.port}"

    @property
    def event_topic(self) -> str:
        """Topic filter for live events: all gateways, or one gateway."""
        return EVENT_TOPIC_PREFIX + (self.gateway or "")

    @property
    def replay_topic(self) -> str | None:
        """Topic filter for replay messages addressed to --replay-of, if set."""
        if not self.replay_of:
            return None
        return REPLAY_TOPIC_PREFIX + self.replay_of


MessageHandler = Callable[[str, dict[str, Any], float], None]
"""Callback signature: (topic, payload_dict, recv_time_seconds) -> None."""


class DcSpyClient:
    """Owns one ZMQ SUB connection to the engine's drop-copy PUB socket."""

    def __init__(
        self, options: DcSpyOptions, context: "zmq.Context[Any] | None" = None
    ) -> None:
        self._opts = options
        self._ctx: zmq.Context[Any] = context or zmq.Context.instance()
        self._sock: zmq.Socket[bytes] | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the SUB socket and apply topic filters.

        Raises :class:`DcSpyConnectionError` on failure. Note that ``connect``
        on a ZMQ SUB socket does not itself fail if nothing is listening yet
        (ZMQ transparently reconnects) -- this call establishes the socket
        and subscription, not a live TCP handshake.
        """
        try:
            sock = self._ctx.socket(zmq.SUB)
            sock.setsockopt(zmq.RCVTIMEO, _RECV_TIMEOUT_MS)
            sock.connect(self._opts.addr)
            sock.setsockopt_string(zmq.SUBSCRIBE, self._opts.event_topic)
            replay_topic = self._opts.replay_topic
            if replay_topic is not None:
                sock.setsockopt_string(zmq.SUBSCRIBE, replay_topic)
        except zmq.ZMQError as exc:
            raise DcSpyConnectionError(
                f"could not connect to {self._opts.addr}: {exc}"
            ) from exc
        self._sock = sock
        log.info(
            "connected to %s, subscribed to %r%s",
            self._opts.addr,
            self._opts.event_topic,
            f" and {replay_topic!r}" if replay_topic else "",
        )

    def close(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close(linger=0)
            except zmq.ZMQError:
                pass
            self._sock = None

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------

    def run(self, on_message: MessageHandler, *, max_messages: int = 0) -> None:
        """Read and dispatch messages until stopped or ``max_messages``
        have been delivered (0 = unlimited).

        Uses a receive timeout internally (rather than blocking forever) so
        that Ctrl-C and ``max_messages`` are both responsive even when the
        feed is quiet.
        """
        assert self._sock is not None, "connect() must be called first"
        import time

        self._running = True
        delivered = 0
        try:
            while self._running:
                try:
                    frames = self._sock.recv_multipart()
                except zmq.Again:
                    continue  # recv timeout -- loop so Ctrl-C/stop() are checked
                except zmq.ZMQError as exc:
                    if not self._running:
                        return
                    raise DcSpyConnectionError(f"socket read error: {exc}") from exc

                recv_time = time.time()
                try:
                    topic, payload = decode(frames)
                except (ValueError, UnicodeDecodeError, TypeError) as exc:
                    log.warning("unparseable drop-copy message: %r (%s)", frames, exc)
                    continue

                on_message(topic, payload, recv_time)

                delivered += 1
                if max_messages and delivered >= max_messages:
                    return
        finally:
            pass

    def stop(self) -> None:
        self._running = False


__all__ = [
    "DcSpyClient",
    "DcSpyConnectionError",
    "DcSpyOptions",
    "EVENT_TOPIC_PREFIX",
    "REPLAY_TOPIC_PREFIX",
]
