"""pm-market-sim's feed: true values for ADMIN eyes, headlines for everyone.

pm-market-sim publishes the true values and the news on its own PUB socket.
This client keeps the latest ``sim.state`` and ``sim.value`` and forwards both
to the ADMIN streams only (the routes check the role). Headlines
(``news.event``) are public: the last :data:`NEWS_KEPT` are kept for
``GET /news`` and each new one goes to every market-data socket.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import threading
from collections import deque
from typing import Any

import zmq

from edumatcher.messaging.bus import make_subscriber
from edumatcher.api_gateway.events import now_iso
from edumatcher.models.generated.news import TOPIC_NEWS_EVENT
from edumatcher.models.generated.sim import TOPIC_SIM_STATE, TOPIC_SIM_VALUE
from edumatcher.models.message import decode

log = logging.getLogger(__name__)

#: Headlines kept for ``GET /news``; a trading day has a few dozen.
NEWS_KEPT = 200


class SimClient:
    def __init__(
        self,
        pub_addr: str,
        loop: asyncio.AbstractEventLoop,
        sectors: dict[str, frozenset[str]] | None = None,
    ) -> None:
        self._loop = loop
        self._pub_addr = pub_addr
        self._sub = make_subscriber(
            pub_addr, TOPIC_SIM_VALUE, TOPIC_SIM_STATE, TOPIC_NEWS_EVENT
        )
        self._running = False
        self._thread: threading.Thread | None = None
        self.state: dict[str, Any] | None = None
        self.values: dict[str, Any] | None = None
        self._sinks: set[asyncio.Queue[dict[str, Any]]] = set()
        self.news: deque[dict[str, Any]] = deque(maxlen=NEWS_KEPT)
        self._news_sinks: set[asyncio.Queue[dict[str, Any]]] = set()
        #: Sector -> member symbols, so a client can tell which symbols a
        #: SECTOR headline is about.
        self.sectors = sectors or {}

    def start_listener(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def stop_listener(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._sub.close(linger=0)

    def add_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._sinks.add(queue)

    def remove_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._sinks.discard(queue)

    def add_news_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._news_sinks.add(queue)

    def remove_news_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._news_sinks.discard(queue)

    def news_snapshot(self, limit: int) -> dict[str, Any]:
        """The latest *limit* headlines, oldest first, and the sectors."""
        news = list(self.news)[-limit:] if limit > 0 else []
        return {
            "news": news,
            "sectors": {k: sorted(v) for k, v in sorted(self.sectors.items())},
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "available": self.state is not None,
            "state": self.state,
            "values": self.values,
        }

    def _receive_loop(self) -> None:
        poller = zmq.Poller()
        poller.register(self._sub, zmq.POLLIN)
        try:
            while self._running:
                try:
                    ready = dict(poller.poll(timeout=200))
                except zmq.ZMQError as exc:
                    if exc.errno != errno.EINTR:
                        raise
                    break
                if self._sub not in ready:
                    continue
                try:
                    topic, payload = decode(self._sub.recv_multipart())
                except Exception as exc:
                    log.warning("Dropping malformed sim PUB message: %s", exc)
                    continue
                self._loop.call_soon_threadsafe(self.handle_event, topic, payload)
        finally:
            self._running = False

    def handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == TOPIC_NEWS_EVENT:
            self.news.append(payload)
            _offer(
                self._news_sinks,
                {"type": "news", "topic": topic, "ts": now_iso(), "data": payload},
            )
            return
        if topic == TOPIC_SIM_STATE:
            self.state = payload
        elif topic == TOPIC_SIM_VALUE:
            self.values = payload
        else:
            return
        # A slow viewer misses a step; the next one supersedes it.
        _offer(self._sinks, {"type": topic, "data": payload})


def _offer(sinks: set[asyncio.Queue[dict[str, Any]]], event: dict[str, Any]) -> None:
    for queue in list(sinks):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass
