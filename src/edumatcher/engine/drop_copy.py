"""
engine/drop_copy.py — Sequenced drop copy on a dedicated ZMQ PUB socket.

What is a drop copy?
~~~~~~~~~~~~~~~~~~~~
A *drop copy* is a real-time feed of every order lifecycle event —
fills, cancels, rejects — for one participant, delivered to a *separate*
recipient such as their clearing broker, prime broker, or in-house risk
system.

EduMatcher's drop copy runs on a separate ZMQ PUB socket (port 5557) so
recipients do not need to subscribe to the main market-data feed (port 5556)
and receive everyone's order flow.  Each message is:

  - Scoped to a single gateway (``drop_copy.event.{gateway_id}`` topic)
  - Assigned a monotonically increasing sequence number
  - Timestamped in nanoseconds (``now_ns()`` from ``models/clock.py``)
  - Buffered in memory for replay

Replay
~~~~~~
A participant that reconnects mid-session sends a ``drop_copy.replay_request``
message with ``from_seq=N``.  The engine calls ``replay(recipient_id, N)``
to re-publish every buffered event with ``seq >= N`` on the
``drop_copy.replay.{recipient_id}`` topic.

Buffer
~~~~~~
``DROP_COPY_BUFFER_SIZE = 10_000`` messages are retained in a bounded deque.
Once the deque is full, the oldest messages are automatically dropped.
At ~10 fills/second, 10,000 messages covers roughly 16 minutes.

Relationship to make_dropcopy_fill_msg
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``models/message.py`` contains ``make_dropcopy_fill_msg()`` as an early
placeholder for the drop copy concept.  ``DropCopyPublisher`` supersedes it
for engine-side publishing.  The older helper is kept for backward compat
with any subscribers that consume ``dropcopy.fill.{gateway_id}`` on port 5556.
"""

from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

import zmq

from edumatcher.models.message import dumps

# Per-process monotone counter — starts at 1 so seq=0 means "no events yet"
_seq_counter = itertools.count(1)

DROP_COPY_BUFFER_SIZE = 10_000  # messages retained in memory for replay


@dataclass
class DropCopyMessage:
    """One drop-copy event stored in the replay buffer.

    Attributes
    ----------
    seq        : Monotonically increasing sequence number (process-wide).
    timestamp  : Nanosecond timestamp (``now_ns()``).
    gateway_id : Gateway that owns this event.
    topic      : Event type string, e.g. ``"order.fill"``.
    payload    : Event-specific fields.
    """

    seq: int
    timestamp: int
    gateway_id: str
    topic: str
    payload: dict[str, Any]


class DropCopyPublisher:
    """
    Binds a dedicated ZMQ PUB socket and publishes sequenced order events.

    Instantiate once in ``Engine.run()`` (not in ``__init__``) so that
    unit tests that never call ``run()`` do not attempt to bind the port.

    Parameters
    ----------
    context : A ``zmq.Context`` instance (pass ``zmq.Context.instance()``
              in production).
    addr    : ZMQ bind address.  Defaults to ``DROP_COPY_PUB_ADDR`` from
              ``edumatcher.config`` (``tcp://127.0.0.1:5557``).
    """

    def __init__(self, context: zmq.Context[Any], addr: Optional[str] = None) -> None:
        from edumatcher.config import DROP_COPY_PUB_ADDR

        bind_addr = addr if addr is not None else DROP_COPY_PUB_ADDR
        self._pub: zmq.Socket[bytes] = context.socket(zmq.PUB)
        self._pub.bind(bind_addr)
        # Bounded deque: when full, oldest messages are silently dropped
        self._log: deque[DropCopyMessage] = deque(maxlen=DROP_COPY_BUFFER_SIZE)

    def publish(
        self,
        gateway_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """
        Publish one event on the drop-copy socket.

        Called by the engine on every fill and cancel.  The gateway-scoped
        topic (``drop_copy.event.{gateway_id}``) lets recipients filter
        per-participant without receiving the entire market feed.

        Parameters
        ----------
        gateway_id : The gateway whose order triggered this event.
        event_type : Short string identifying the event, e.g. ``"order.fill"``.
        payload    : Event-specific key-value pairs merged into the published
                     JSON alongside ``seq``, ``timestamp``, ``gateway_id``,
                     and ``event_type``.
        """
        from edumatcher.models.clock import now_ns

        seq = next(_seq_counter)
        now = now_ns()
        msg = DropCopyMessage(
            seq=seq,
            timestamp=now,
            gateway_id=gateway_id,
            topic=event_type,
            payload=payload,
        )
        self._log.append(msg)

        topic_bytes = f"drop_copy.event.{gateway_id}".encode()
        self._pub.send_multipart(
            [
                topic_bytes,
                dumps(
                    {
                        "seq": seq,
                        "timestamp": now,
                        "gateway_id": gateway_id,
                        "event_type": event_type,
                        **payload,
                    }
                ),
            ]
        )

    def replay(self, recipient_id: str, from_seq: int) -> int:
        """
        Re-publish buffered messages with ``seq >= from_seq``.

        Replayed messages are published on topic
        ``drop_copy.replay.{recipient_id}`` so the recipient can distinguish
        replay traffic from live events.

        Parameters
        ----------
        recipient_id : Identifier for the subscriber requesting replay.
                       Used in the replay topic so multiple simultaneous
                       replays do not interleave.
        from_seq     : Lowest sequence number to include.

        Returns
        -------
        Number of messages replayed.
        """
        topic_bytes = f"drop_copy.replay.{recipient_id}".encode()
        replayed = 0
        for msg in self._log:
            if msg.seq >= from_seq:
                self._pub.send_multipart(
                    [
                        topic_bytes,
                        dumps(
                            {
                                "seq": msg.seq,
                                "timestamp": msg.timestamp,
                                "gateway_id": msg.gateway_id,
                                "event_type": msg.topic,
                                **msg.payload,
                            }
                        ),
                    ]
                )
                replayed += 1
        return replayed

    def close(self) -> None:
        """Close the ZMQ socket.  Called from ``Engine._shutdown()``."""
        self._pub.close()
