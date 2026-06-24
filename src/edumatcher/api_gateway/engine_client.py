"""Async-friendly wrapper around the engine ZMQ PUSH/PUB sockets."""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from typing import Any

import zmq

from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.api_gateway.events import envelope, gateway_from_topic
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    make_combo_cancel_msg,
    make_combo_order_msg,
    make_gateway_connect_msg,
    make_gateway_disconnect_msg,
    make_kill_switch_msg,
    make_oco_cancel_msg,
    make_oco_order_msg,
    make_order_amend_msg,
    make_order_cancel_msg,
    make_order_new_msg,
    make_orders_request_msg,
    make_quote_bootstrap_request_msg,
    make_quote_cancel_msg,
    make_quote_legs_request_msg,
    make_quote_new_msg,
    make_session_state_request_msg,
    make_symbols_request_msg,
)
from edumatcher.models.order import Order
from edumatcher.models.price import register_tick_decimals


class EngineClient:
    """Owns engine sockets, event fan-out, futures, and session caches."""

    def __init__(
        self, pull_addr: str, pub_addr: str, loop: asyncio.AbstractEventLoop
    ) -> None:
        self._loop = loop
        self._push = make_pusher(pull_addr)
        # Subscribing to all engine events keeps the gateway implementation easy
        # to reason about; filtering happens before events reach clients.
        self._sub = make_subscriber(pub_addr, "")
        self._running = False
        self._thread: threading.Thread | None = None
        self._authenticated: set[str] = set()
        # Per-gateway locks prevent duplicate gateway_connect messages when
        # concurrent requests authenticate the same gateway simultaneously.
        self._auth_locks: dict[str, asyncio.Lock] = {}
        self._caches: dict[str, SessionCaches] = defaultdict(SessionCaches)
        self._sinks: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._market_data_sinks: set[asyncio.Queue[dict[str, Any]]] = set()
        self._pending: dict[str, list[asyncio.Future[dict[str, Any]]]] = defaultdict(
            list
        )

    def start_listener(self) -> None:
        """Start the daemon thread that receives engine PUB events."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def stop_listener(self) -> None:
        """Stop the receiver thread and close sockets."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._push.close(linger=0)
        self._sub.close(linger=0)

    def active_gateways(self) -> set[str]:
        return set(self._authenticated)

    def send_disconnect(self, gateway_id: str, reason: str) -> None:
        self._push.send_multipart(make_gateway_disconnect_msg(gateway_id, reason))

    async def authenticate(self, gateway_id: str) -> tuple[bool, str]:
        """Perform the engine gateway_connect handshake once per gateway id.

        Uses a per-gateway asyncio.Lock so that concurrent requests for the
        same unauthenticated gateway send exactly one gateway_connect message.
        Subsequent callers queue on the lock and short-circuit when they see
        the gateway already authenticated.
        """
        if gateway_id in self._authenticated:
            return True, ""
        if gateway_id not in self._auth_locks:
            self._auth_locks[gateway_id] = asyncio.Lock()
        async with self._auth_locks[gateway_id]:
            # Re-check after acquiring the lock; a concurrent caller may have
            # already completed authentication while we were waiting.
            if gateway_id in self._authenticated:
                return True, ""
            future = self._register_future(f"system.gateway_auth.{gateway_id}")
            self._push.send_multipart(make_gateway_connect_msg(gateway_id))
            try:
                payload = await asyncio.wait_for(future, timeout=3.0)
            except TimeoutError:
                return False, "Engine authentication timed out"
            accepted = bool(payload.get("accepted", False))
            reason = str(payload.get("reason", ""))
            if accepted:
                self._authenticated.add(gateway_id)
                self._push.send_multipart(make_symbols_request_msg(gateway_id))
            return accepted, reason

    def _register_future(self, key: str) -> asyncio.Future[dict[str, Any]]:
        future: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        self._pending[key].append(future)
        return future

    async def await_topic(self, key: str, timeout: float) -> dict[str, Any]:
        future = self._register_future(key)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            # asyncio.wait_for cancels the inner future on timeout.  Remove it
            # from _pending so cancelled futures do not accumulate if the engine
            # never sends the matching topic.
            pending = self._pending.get(key)
            if pending is not None:
                try:
                    pending.remove(future)
                except ValueError:
                    pass
                if not pending:
                    del self._pending[key]
            raise TimeoutError(f"Timed out waiting for {key}") from exc

    def _resolve_pending(self, topic: str, payload: dict[str, Any]) -> None:
        futures = self._pending.pop(topic, [])
        for future in futures:
            if not future.done():
                future.set_result(payload)

    def _receive_loop(self) -> None:
        poller = zmq.Poller()
        poller.register(self._sub, zmq.POLLIN)
        while self._running:
            try:
                ready = dict(poller.poll(timeout=200))
            except zmq.ZMQError:
                break
            if self._sub not in ready:
                continue
            try:
                topic, payload = decode(self._sub.recv_multipart())
            except Exception:
                continue
            self._loop.call_soon_threadsafe(self._handle_event, topic, payload)

    def _handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        self._resolve_pending(topic, payload)
        gateway_id = gateway_from_topic(topic)
        if gateway_id is not None:
            cache = self._caches[gateway_id]
            cache.apply(topic, payload)
            self._register_tick_metadata(payload)
            event = envelope(topic, payload)
            for queue in list(self._sinks.get(gateway_id, set())):
                self._try_put(queue, event)
        else:
            for cache in self._caches.values():
                cache.apply(topic, payload)
            event = envelope(topic, payload)
            for queue in list(self._market_data_sinks):
                self._try_put(queue, event)

    @staticmethod
    def _try_put(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    @staticmethod
    def _register_tick_metadata(payload: dict[str, Any]) -> None:
        meta = payload.get("symbol_meta")
        if not isinstance(meta, dict):
            return
        for symbol, details in meta.items():
            if isinstance(details, dict) and "tick_decimals" in details:
                register_tick_decimals(str(symbol), int(details["tick_decimals"]))

    def add_sink(self, gateway_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._sinks[gateway_id].add(queue)

    def remove_sink(
        self, gateway_id: str, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        self._sinks[gateway_id].discard(queue)

    def add_market_data_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._market_data_sinks.add(queue)

    def remove_market_data_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._market_data_sinks.discard(queue)

    def get_caches(self, gateway_id: str) -> SessionCaches:
        return self._caches[gateway_id]

    def send_new_order(self, order: Order) -> None:
        self._push.send_multipart(make_order_new_msg(order.to_dict()))

    def send_cancel(self, order_id: str, gateway_id: str) -> None:
        self._push.send_multipart(make_order_cancel_msg(order_id, gateway_id))

    def send_amend(
        self, order_id: str, gateway_id: str, price: float | None, qty: int | None
    ) -> None:
        self._push.send_multipart(
            make_order_amend_msg(order_id, gateway_id, price=price, qty=qty)
        )

    def send_combo(self, payload: dict[str, Any]) -> None:
        self._push.send_multipart(make_combo_order_msg(payload))

    def send_combo_cancel(self, combo_id: str, gateway_id: str) -> None:
        self._push.send_multipart(make_combo_cancel_msg(combo_id, gateway_id))

    def send_oco(self, payload: dict[str, Any]) -> None:
        self._push.send_multipart(make_oco_order_msg(payload))

    def send_oco_cancel(self, oco_id: str, gateway_id: str) -> None:
        self._push.send_multipart(make_oco_cancel_msg(oco_id, gateway_id))

    def send_quote(self, payload: dict[str, Any]) -> None:
        self._push.send_multipart(make_quote_new_msg(payload))

    def send_quote_cancel(self, gateway_id: str, symbol: str) -> None:
        self._push.send_multipart(make_quote_cancel_msg(gateway_id, symbol))

    def send_mass_cancel(self, gateway_id: str, symbol: str = "") -> None:
        self._push.send_multipart(make_kill_switch_msg(gateway_id, symbol))

    def request_orders(self, gateway_id: str) -> None:
        self._push.send_multipart(make_orders_request_msg(gateway_id))

    def request_symbols(self, gateway_id: str) -> None:
        self._push.send_multipart(make_symbols_request_msg(gateway_id))

    def request_session(self, gateway_id: str) -> None:
        self._push.send_multipart(make_session_state_request_msg(gateway_id))

    def request_quote_bootstrap(self, gateway_id: str, symbol: str = "") -> None:
        self._push.send_multipart(make_quote_bootstrap_request_msg(gateway_id, symbol))

    def request_quote_legs(
        self, gateway_id: str, symbol: str = "", show: str = "ALL"
    ) -> None:
        self._push.send_multipart(make_quote_legs_request_msg(gateway_id, symbol, show))
