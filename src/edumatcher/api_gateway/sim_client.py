"""pm-market-sim's feed: true values for ADMIN eyes, headlines for everyone.

pm-market-sim publishes the true values and the news on its own PUB socket.
This client keeps the latest ``sim.state`` and ``sim.value`` and forwards both
to the ADMIN streams only (the routes check the role). Headlines
(``news.event``) are public: each new one goes to every market-data socket.
``GET /news`` reads pm-market-sim's news history instead, so it survives a
restart of this gateway.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import threading
from typing import Any, Callable

import zmq

from edumatcher.messaging.bus import make_subscriber
from edumatcher.api_gateway.events import now_iso
from edumatcher.models.generated.news import TOPIC_NEWS_EVENT
from edumatcher.models.generated.sim import TOPIC_SIM_STATE, TOPIC_SIM_VALUE
from edumatcher.models.message import decode

log = logging.getLogger(__name__)


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
        #: Called on the event loop when the receive thread dies; pm-api-gwy
        #: then stops with exit status 1, as for the engine listener.
        self.on_listener_failure: Callable[[], None] | None = None
        self.state: dict[str, Any] | None = None
        self.values: dict[str, Any] | None = None
        self._sinks: set[asyncio.Queue[dict[str, Any]]] = set()
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

    def is_running(self) -> bool:
        return self._running

    def add_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._sinks.add(queue)

    def remove_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._sinks.discard(queue)

    def add_news_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._news_sinks.add(queue)

    def remove_news_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._news_sinks.discard(queue)

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
                    continue
                if self._sub not in ready:
                    continue
                try:
                    topic, payload = decode(self._sub.recv_multipart())
                except Exception as exc:
                    log.warning("Dropping malformed sim PUB message: %s", exc)
                    continue
                self._loop.call_soon_threadsafe(self.handle_event, topic, payload)
        except Exception:
            # Still meant to run, so not a stop_listener() closing the
            # sockets under it: as the engine listener (L033).
            if self._running:
                log.exception("sim listener died; stopping pm-api-gwy")
                # Before the callback, not only in ``finally``: whoever it
                # wakes must already see is_running() False.
                self._running = False
                if self.on_listener_failure is not None:
                    self._loop.call_soon_threadsafe(self.on_listener_failure)
        finally:
            self._running = False

    def handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == TOPIC_NEWS_EVENT:
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
