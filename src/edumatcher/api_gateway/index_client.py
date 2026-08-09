"""Async-friendly wrapper around pm-index's ZMQ PUSH/PUB request-reply pair.

pm-index is a separate process from pm-engine, reachable over its own
PULL socket (requests) and PUB socket (replies), mirroring the pattern
``EngineClient`` uses for pm-engine. This class is deliberately scoped to
one request/reply exchange — history queries for structural/audit index
records (INIT, CORP_ACTION, ADD_CONSTITUENT, DELIST) — rather than the
full event fan-out ``EngineClient`` provides, since the gateway has no
other reason to talk to pm-index today.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import threading
from collections import defaultdict
from typing import Any

import zmq

from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.generated.index import (
    topic_index_error,
    topic_index_history,
    topic_index_rebalance_ack,
)
from edumatcher.models.message import (
    decode,
    make_index_history_request_msg,
    make_index_rebalance_msg,
)

log = logging.getLogger(__name__)


class IndexHistoryError(RuntimeError):
    """Raised when pm-index replies with ``index.error.<gateway_id>``."""


class IndexClient:
    """Owns the gateway's sockets to pm-index and bridges replies to asyncio."""

    def __init__(
        self, pull_addr: str, pub_addr: str, loop: asyncio.AbstractEventLoop
    ) -> None:
        self._loop = loop
        self._pull_addr = pull_addr
        self._pub_addr = pub_addr
        self._push = make_pusher(pull_addr)
        # Only history/error replies are relevant here, but pm-index's PUB
        # carries other topics too (index.update, ack topics); subscribing to
        # everything and filtering on receipt keeps this symmetric with
        # EngineClient rather than relying on prefix-subscribe semantics.
        self._sub = make_subscriber(pub_addr, "")
        self._running = False
        self._thread: threading.Thread | None = None
        # A list per topic, not a single future: every caller here already
        # addresses its own reply topic with a unique id (request_id /
        # command_id), so two calls should never collide in practice — but a
        # single-future-per-key map would silently drop an earlier waiter's
        # registration if one ever did (e.g. a retried request reusing an
        # id), rather than resolving both. Mirrors EngineClient._pending.
        self._pending: dict[str, list[asyncio.Future[dict[str, Any]]]] = defaultdict(
            list
        )

    def start_listener(self) -> None:
        """Start the daemon thread that receives pm-index PUB events."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        log.info(
            "index listener started (pull=%s pub=%s)", self._pull_addr, self._pub_addr
        )

    def stop_listener(self) -> None:
        """Stop the receiver thread and close sockets."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._push.close(linger=0)
        self._sub.close(linger=0)
        log.info("index listener stopped")

    def is_running(self) -> bool:
        return self._running

    async def request_history(
        self,
        *,
        request_id: str,
        index_id: str,
        from_ts: float,
        to_ts: float,
        types: list[str] | None,
        max_records: int,
        timeout: float,
    ) -> dict[str, Any]:
        """Round-trip a structural/audit history request to pm-index.

        *request_id* is used purely to address the reply topic
        (``index.history.<request_id>`` / ``index.error.<request_id>``); it
        need not be a real, engine-authenticated gateway id — pm-index just
        echoes it back, so a read-only API session's own key (or any other
        caller-unique string) works fine here.
        """
        history_future = self._register_future(topic_index_history(request_id))
        error_future = self._register_future(topic_index_error(request_id))
        self._push.send_multipart(
            make_index_history_request_msg(
                request_id,
                index_id,
                from_ts,
                to_ts,
                types=types,
                max_records=max_records,
            )
        )
        try:
            done, pending = await asyncio.wait(
                {history_future, error_future},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            # Always drop both waiters once one resolves (or on timeout) so
            # a slow/duplicate reply never resolves a future we've already
            # abandoned or lands in _pending indefinitely.
            self._drop_pending(topic_index_history(request_id), history_future)
            self._drop_pending(topic_index_error(request_id), error_future)
        for future in pending:
            future.cancel()
        if not done:
            raise TimeoutError(
                f"Timed out waiting for index history reply ({index_id})"
            )
        result = done.pop().result()
        if error_future.done() and not error_future.cancelled():
            if history_future not in done:
                reason = str(result.get("reason", "pm-index rejected the request"))
                raise IndexHistoryError(reason)
        return result

    async def send_and_await_rebalance(
        self,
        *,
        gateway_id: str,
        index_id: str,
        updates: list[dict[str, Any]],
        command_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        """Round-trip a batch rebalance request to pm-index.

        Unlike ``request_history``, rebalance has one reply topic
        (``index.rebalance_ack.<gateway_id>``) carrying both the accept and
        reject cases in its own ``accepted`` field — mirroring the existing
        corp-action/constituent-change acks — so there is no separate error
        future to race against.
        """
        topic = topic_index_rebalance_ack(gateway_id)
        future = self._register_future(topic)
        self._push.send_multipart(
            make_index_rebalance_msg(index_id, gateway_id, updates, command_id)
        )
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            raise TimeoutError(f"Timed out waiting for {topic}") from exc
        finally:
            self._drop_pending(topic, future)

    def _register_future(self, key: str) -> asyncio.Future[dict[str, Any]]:
        future: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        self._pending[key].append(future)
        return future

    def _drop_pending(self, key: str, future: asyncio.Future[dict[str, Any]]) -> None:
        """Remove one waiter that will never be resolved (timeout/cleanup)."""
        pending = self._pending.get(key)
        if pending is None:
            return
        self._pending[key] = [w for w in pending if w is not future]
        if not self._pending[key]:
            del self._pending[key]

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
                    log.warning("Dropping malformed index PUB message: %s", exc)
                    continue
                self._loop.call_soon_threadsafe(self._handle_event, topic, payload)
        finally:
            self._running = False

    def _handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        pending = self._pending.get(topic)
        if not pending:
            return
        # Resolve the oldest waiter first (FIFO) — reply order should match
        # request order for one topic, and this keeps a topic with more than
        # one waiter from resolving them out of order.
        for future in pending:
            if not future.done():
                future.set_result(payload)
                break
