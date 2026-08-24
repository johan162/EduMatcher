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
The engine calls ``replay(recipient_id, N)`` to re-publish every buffered
event with ``seq >= N`` on the ``drop_copy.replay.{recipient_id}`` topic.

This is **in-process only**. There is no request message: this docstring
described a ``drop_copy.replay_request`` for a long time, and no producer,
subscriber or spec has ever carried one — ``dc_gateway`` says as much in its
own header. Specifying the family in phase 6.1d is what surfaced it; see
design section 27.3.

Buffer
~~~~~~
``DROP_COPY_BUFFER_SIZE = 10_000`` messages are retained in a bounded deque.
Once the deque is full, the oldest messages are automatically dropped.
At ~10 fills/second, 10,000 messages covers roughly 16 minutes.
"""

from __future__ import annotations

import itertools
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Optional

import zmq

from edumatcher.models.clock import now_ns
from edumatcher.models.generated.drop_copy import (
    DropCopyEventEventType,
    DropCopyEventLiquidityFlag,
    make_drop_copy_event,
    make_drop_copy_replay,
)

# Per-process monotone counter — starts at 1 so seq=0 means "no events yet"
_seq_counter = itertools.count(1)

DROP_COPY_BUFFER_SIZE = 10_000  # messages retained in memory for replay

#: The only event type the engine emits. Declared as a constant rather than
#: written at the call site so that the spec's enum and this agree by
#: construction.
EVENT_ORDER_FILL: DropCopyEventEventType = "order.fill"


@dataclass
class DropCopyMessage:
    """One drop-copy event stored in the replay buffer.

    Named fields rather than the ``topic``/``payload: dict`` pair this used to
    hold. The dict was a map in all but name — one caller, one event type, the
    same five keys every time — and it could not survive adoption: a generated
    builder reads declared keys only, so an undeclared key splatted into it
    would be dropped with no error at all. Design section 27.2.
    """

    seq: int
    timestamp: int
    gateway_id: str
    event_type: DropCopyEventEventType
    order_id: str
    symbol: str
    fill_qty: int
    fill_price: float
    liquidity_flag: DropCopyEventLiquidityFlag


class DropCopyPublisher:
    """
    Binds a dedicated ZMQ PUB socket and publishes sequenced order events.

    Instantiate once in ``Engine.run()`` (not in ``__init__``) so that
    unit tests that never call ``run()`` do not attempt to bind the port.

    Parameters
    ----------
    context : A ``zmq.Context`` instance (pass ``zmq.Context.instance()``
              in production).
    addr    : ZMQ bind address.  Defaults to ``DROP_COPY_PUB_BIND_ADDR`` from
              ``edumatcher.config`` (``tcp://127.0.0.1:5557``).
    """

    def __init__(
        self,
        context: zmq.Context[Any],
        addr: Optional[str] = None,
        buffer_size: int = DROP_COPY_BUFFER_SIZE,
    ) -> None:
        from edumatcher.config import DROP_COPY_PUB_BIND_ADDR

        bind_addr = addr if addr is not None else DROP_COPY_PUB_BIND_ADDR
        self._pub: zmq.Socket[bytes] = context.socket(zmq.PUB)
        self._pub.bind(bind_addr)
        # Bounded deque: when full, oldest messages are silently dropped
        self._log: deque[DropCopyMessage] = deque(maxlen=buffer_size)

    def publish_fill(
        self,
        gateway_id: str,
        *,
        order_id: str,
        symbol: str,
        fill_qty: int,
        fill_price: float,
        liquidity_flag: DropCopyEventLiquidityFlag,
    ) -> None:
        """
        Publish one execution on the drop-copy socket.

        Called by the engine's single trade-publication path, twice per trade
        — once per counterparty.  The gateway-scoped topic
        (``drop_copy.event.{gateway_id}``) lets recipients filter
        per-participant without receiving the entire market feed.

        Named arguments rather than the ``event_type`` + ``payload: dict``
        pair this replaced.  That signature was generic in form and singular
        in use, and generality is not what made it wrong: routed through a
        generated builder, an undeclared key would have been **silently
        dropped**, which is the failure the generator exists to remove.  A
        second event type is a spec change and a sibling method here.

        Parameters
        ----------
        gateway_id     : The participant whose order executed.
        order_id       : The order this execution belongs to.
        symbol         : Instrument ticker.
        fill_qty       : Executed quantity.
        fill_price     : Display money, not ticks.
        liquidity_flag : ``TAKER`` for the aggressor, ``MAKER`` for the
                         resting side.
        """
        msg = DropCopyMessage(
            seq=next(_seq_counter),
            timestamp=now_ns(),
            gateway_id=gateway_id,
            event_type=EVENT_ORDER_FILL,
            order_id=order_id,
            symbol=symbol,
            fill_qty=fill_qty,
            fill_price=fill_price,
            liquidity_flag=liquidity_flag,
        )
        self._log.append(msg)
        self._pub.send_multipart(make_drop_copy_event(**asdict(msg)))

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
        replayed = 0
        for msg in self._log:
            if msg.seq >= from_seq:
                self._pub.send_multipart(
                    make_drop_copy_replay(recipient_id=recipient_id, **asdict(msg))
                )
                replayed += 1
        return replayed

    def close(self) -> None:
        """Close the ZMQ socket.  Called from ``Engine._shutdown()``."""
        self._pub.close()
