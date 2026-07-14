"""Async-friendly wrapper around the engine ZMQ PUSH/PUB sockets."""

from __future__ import annotations

import asyncio
import errno
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import zmq

from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.api_gateway.events import envelope, gateway_from_topic
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    make_cancel_symbol_msg,
    make_combo_cancel_msg,
    make_combo_order_msg,
    make_gateway_connect_msg,
    make_gateway_disconnect_msg,
    make_gateways_request_msg,
    make_halt_status_request_msg,
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
    make_session_schedule_request_msg,
    make_session_state_request_msg,
    make_session_transition_msg,
    make_symbol_halt_msg,
    make_symbol_resume_msg,
    make_symbols_request_msg,
)
from edumatcher.models.order import Order
from edumatcher.models.price import register_tick_decimals

log = logging.getLogger(__name__)
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0


@dataclass
class _PendingWait:
    """A future waiting for a specific topic, optionally filtered by payload."""

    future: asyncio.Future[dict[str, Any]]
    match: dict[str, str] | None = field(default=None)


class EngineClient:
    """Owns engine sockets, event fan-out, futures, and session caches."""

    def __init__(
        self, pull_addr: str, pub_addr: str, loop: asyncio.AbstractEventLoop
    ) -> None:
        self._loop = loop
        self._pull_addr = pull_addr
        self._pub_addr = pub_addr
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
        # ADMIN monitor sinks receive every event across all gateways.
        self._admin_sinks: set[asyncio.Queue[dict[str, Any]]] = set()
        # Cache of resolved gateway roles (keyed by upper-cased gateway id).
        self._role_cache: dict[str, str] = {}
        self._pending: dict[str, list[_PendingWait]] = defaultdict(list)
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = 0.0

    def _dbg_count(self, key: str, amount: int = 1) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        self._debug_counts[key] += amount
        self._flush_debug_summary()

    def _flush_debug_summary(self, force: bool = False) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        now = self._loop.time()
        if not force and now - self._debug_last_summary < _DEBUG_SUMMARY_INTERVAL_SEC:
            return
        if not self._debug_counts:
            self._debug_last_summary = now
            return
        summary = ", ".join(
            f"{key}={value}" for key, value in sorted(self._debug_counts.items())
        )
        log.debug("api_gateway engine flow summary: %s", summary)
        self._debug_counts.clear()
        self._debug_last_summary = now

    def start_listener(self) -> None:
        """Start the daemon thread that receives engine PUB events."""
        if self._running:
            return
        self._running = True
        self._debug_last_summary = self._loop.time()
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        log.info(
            "engine listener started (pull=%s pub=%s)",
            self._pull_addr,
            self._pub_addr,
        )

    def stop_listener(self) -> None:
        """Stop the receiver thread and close sockets."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._flush_debug_summary(force=True)
        self._push.close(linger=0)
        self._sub.close(linger=0)
        log.info("engine listener stopped")

    def active_gateways(self) -> set[str]:
        return set(self._authenticated)

    def is_running(self) -> bool:
        """Return True if the SUB reader thread is active."""
        return self._running

    def send_disconnect(self, gateway_id: str, reason: str) -> None:
        self._push.send_multipart(make_gateway_disconnect_msg(gateway_id, reason))

    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
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
            log.info(
                "auth handshake started gateway_id=%s timeout=%.2fs",
                gateway_id,
                timeout,
            )
            future = self._register_future(f"system.gateway_auth.{gateway_id}")
            self._push.send_multipart(make_gateway_connect_msg(gateway_id))
            self._dbg_count("gateway_connect_sent")
            try:
                payload = await asyncio.wait_for(future, timeout=timeout)
            except TimeoutError:
                log.warning("auth handshake timed out gateway_id=%s", gateway_id)
                return False, "Engine authentication timed out"
            accepted = bool(payload.get("accepted", False))
            reason = str(payload.get("reason", ""))
            log.info(
                "auth handshake completed gateway_id=%s accepted=%s reason=%s",
                gateway_id,
                accepted,
                reason or "-",
            )
            if accepted:
                self._authenticated.add(gateway_id)
                self._push.send_multipart(make_symbols_request_msg(gateway_id))
                self._dbg_count("symbols_request_sent")
            return accepted, reason

    def _register_future(
        self, key: str, match: dict[str, str] | None = None
    ) -> asyncio.Future[dict[str, Any]]:
        future: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        self._pending[key].append(_PendingWait(future=future, match=match))
        self._dbg_count("futures_registered")
        return future

    async def await_topic(self, key: str, timeout: float) -> dict[str, Any]:
        """Wait for the next event on *key* (any payload)."""
        return await self.await_event(key, match=None, timeout=timeout)

    async def await_event(
        self, key: str, match: dict[str, str] | None, timeout: float
    ) -> dict[str, Any]:
        """Wait for an event on *key* whose payload matches *match* fields."""
        future = self._register_future(key, match=match)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            # asyncio.wait_for cancels the inner future on timeout.  Remove it
            # from _pending so cancelled futures do not accumulate if the engine
            # never sends the matching topic.
            pending = self._pending.get(key)
            if pending is not None:
                self._pending[key] = [w for w in pending if w.future is not future]
                if not self._pending[key]:
                    del self._pending[key]
            raise TimeoutError(f"Timed out waiting for {key}") from exc

    def _resolve_pending(self, topic: str, payload: dict[str, Any]) -> None:
        waiters = self._pending.get(topic)
        if not waiters:
            return
        remaining: list[_PendingWait] = []
        for waiter in waiters:
            if waiter.future.done():
                continue
            if waiter.match is not None and not all(
                str(payload.get(k, "")) == v for k, v in waiter.match.items()
            ):
                remaining.append(waiter)
            else:
                waiter.future.set_result(payload)
        if remaining:
            self._pending[topic] = remaining
        else:
            del self._pending[topic]

    def _receive_loop(self) -> None:
        poller = zmq.Poller()
        poller.register(self._sub, zmq.POLLIN)
        try:
            while self._running:
                try:
                    ready = dict(poller.poll(timeout=200))
                    self._dbg_count("poll_cycles")
                except zmq.ZMQError as exc:
                    if exc.errno != errno.EINTR:
                        raise
                    break
                if self._sub not in ready:
                    continue
                try:
                    topic, payload = decode(self._sub.recv_multipart())
                except Exception as exc:
                    self._dbg_count("decode_errors")
                    log.warning("Dropping malformed engine PUB message: %s", exc)
                    continue
                self._dbg_count("pub_messages")
                self._loop.call_soon_threadsafe(self._handle_event, topic, payload)
        finally:
            self._flush_debug_summary(force=True)
            # Ensure is_running()/`/healthz` reflect reality even if this thread
            # exits on EINTR or an unrecoverable ZMQError instead of a clean stop.
            self._running = False

    def _handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        self._dbg_count("events_handled")
        self._resolve_pending(topic, payload)
        gateway_id = gateway_from_topic(topic)
        if gateway_id is not None:
            self._dbg_count("gateway_scoped_events")
            cache = self._caches[gateway_id]
            cache.apply(topic, payload)
            self._register_tick_metadata(payload)
            event = envelope(topic, payload)
            for queue in list(self._sinks.get(gateway_id, set())):
                if self._try_put(queue, event):
                    self._dbg_count("gateway_sink_events")
                else:
                    self._dbg_count("gateway_sink_drops")
        else:
            self._dbg_count("market_data_events")
            for cache in self._caches.values():
                cache.apply(topic, payload)
            event = envelope(topic, payload)
            for queue in list(self._market_data_sinks):
                if self._try_put(queue, event):
                    self._dbg_count("market_data_sink_events")
                else:
                    self._dbg_count("market_data_sink_drops")
        # The ADMIN monitor feed sees every event regardless of routing branch.
        for queue in list(self._admin_sinks):
            if self._try_put(queue, event):
                self._dbg_count("admin_sink_events")
            else:
                self._dbg_count("admin_sink_drops")

    @staticmethod
    def _try_put(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> bool:
        try:
            queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            return False

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

    def add_admin_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._admin_sinks.add(queue)

    def remove_admin_sink(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._admin_sinks.discard(queue)

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

    # ------------------------------------------------------------------
    # ADMIN-persona commands (all map to existing engine topics)
    # ------------------------------------------------------------------

    def send_session_transition(self, to_state: str) -> None:
        self._push.send_multipart(make_session_transition_msg(to_state))

    def send_symbol_halt(self, gateway_id: str, symbol: str) -> None:
        self._push.send_multipart(make_symbol_halt_msg(gateway_id, symbol))

    def send_symbol_resume(self, gateway_id: str, symbol: str) -> None:
        self._push.send_multipart(make_symbol_resume_msg(gateway_id, symbol))

    def send_cancel_symbol(self, gateway_id: str, symbol: str) -> None:
        self._push.send_multipart(make_cancel_symbol_msg(gateway_id, symbol))

    def send_gateway_disconnect(self, gateway_id: str, reason: str = "") -> None:
        self.send_disconnect(gateway_id, reason)

    def request_gateways(self, gateway_id: str) -> None:
        self._push.send_multipart(make_gateways_request_msg(gateway_id))

    def request_session_schedule(self, gateway_id: str) -> None:
        self._push.send_multipart(make_session_schedule_request_msg(gateway_id))

    def request_halt_status(self, gateway_id: str) -> None:
        self._push.send_multipart(make_halt_status_request_msg(gateway_id))

    async def resolve_role(self, gateway_id: str, timeout: float) -> str:
        """Resolve a gateway's ParticipantRole from the engine gateways reply.

        The API credential store does not carry role, so it is resolved from
        the engine and cached. On timeout the safe (non-admin) default
        ``"TRADER"`` is returned so admin gating fails closed.
        """
        gid = gateway_id.upper()
        cached = self._role_cache.get(gid)
        if cached is not None:
            return cached
        self.request_gateways(gid)
        try:
            reply = await self.await_topic(f"system.gateways.{gid}", timeout)
        except TimeoutError:
            return "TRADER"
        role = "TRADER"
        gateways = reply.get("gateways", [])
        if isinstance(gateways, list):
            for entry in gateways:
                if isinstance(entry, dict) and str(entry.get("id", "")).upper() == gid:
                    role = str(entry.get("role", "TRADER"))
                    break
        self._role_cache[gid] = role
        return role
