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
from fastapi import HTTPException, status

from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.api_gateway.events import (
    ADMIN_ACTION_PREFIX,
    envelope,
    gateway_from_topic,
    new_command_id,
)
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
    make_kill_switch_gateway_msg,
    make_kill_switch_global_msg,
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
    make_reference_reload_msg,
    make_reference_request_msg,
    make_risk_state_request_msg,
    make_session_schedule_request_msg,
    make_session_state_request_msg,
    make_session_transition_msg,
    make_symbol_halt_msg,
    make_symbol_resume_msg,
    make_symbols_request_msg,
)
from edumatcher.models.order import Order
from edumatcher.models.price import register_tick_decimals
from edumatcher.models.generated.risk import topic_kill_switch_ack
from edumatcher.models.generated.session import (
    topic_session_transition_ack,
)
from edumatcher.models.generated.system import (
    topic_gateway_auth,
    topic_gateways,
    topic_reference_reload_ack,
)

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
        # There is deliberately no kill-switch lock here any more. One existed
        # because risk.kill_switch_ack carried no per-call identifier, so two
        # concurrent mass cancels for one gateway could consume each other's
        # ack; serialising them was the only safe option. The ack now echoes
        # command_id, so `match=` disambiguates them the way it always did for
        # the symbol-scoped acks, and the serialisation is unnecessary.
        self._caches: dict[str, SessionCaches] = defaultdict(SessionCaches)
        self._sinks: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._market_data_sinks: set[asyncio.Queue[dict[str, Any]]] = set()
        # ADMIN monitor sinks receive every event across all gateways.
        self._admin_sinks: set[asyncio.Queue[dict[str, Any]]] = set()
        # Cache of resolved gateway roles (keyed by upper-cased gateway id).
        self._role_cache: dict[str, str] = {}
        self._pending: dict[str, list[_PendingWait]] = defaultdict(list)
        # Per-topic outbound sequence numbers — see _next_seq for why per topic.
        self._topic_seq: defaultdict[str, int] = defaultdict(int)
        # Per-gateway private-stream sequence — see _next_stream_seq.
        self._gateway_stream_seq: defaultdict[str, int] = defaultdict(int)
        # Plain counters, not _dbg_count: these must be readable in a normal
        # run, because they are the only server-side evidence of dropped events.
        self._dropped_events: defaultdict[str, int] = defaultdict(int)
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

    def _send(self, frames: list[bytes], *, require_engine: bool = True) -> None:
        """Forward *frames* to the engine, turning backpressure into a 503.

        ``make_pusher`` sets ``SNDTIMEO=0`` and ``IMMEDIATE=1``, so
        ``send_multipart`` raises ``zmq.Again`` when the engine is down, not
        yet connected, or slower than we are. Left unguarded that surfaced as
        a bare 500, which tells a client nothing: "the engine is busy, retry"
        and "the gateway has a bug" call for opposite responses. 503 with
        ``ENGINE_UNAVAILABLE`` mirrors what ALF already returns for the same
        condition.

        ``require_engine=False`` is for best-effort notifications — currently
        shutdown disconnects — where no engine to receive the message is the
        expected case, not an error.
        """
        if self._push.closed:
            return
        try:
            self._push.send_multipart(frames)
        except zmq.Again:
            pass
        except zmq.ZMQError as exc:
            # zmq.Again is a ZMQError subclass, but not every EAGAIN arrives
            # as one; ALF guards both and so must this.
            if exc.errno != errno.EAGAIN:
                raise
        else:
            return
        if not require_engine:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "ENGINE_UNAVAILABLE",
                    "message": "Engine unavailable: command not forwarded; retry shortly",
                }
            },
        )

    def send_disconnect(
        self, gateway_id: str, reason: str, *, require_engine: bool = True
    ) -> None:
        self._send(
            make_gateway_disconnect_msg(gateway_id, reason),
            require_engine=require_engine,
        )

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
            auth_key = topic_gateway_auth(gateway_id)
            future = self._register_future(auth_key)
            try:
                self._send(make_gateway_connect_msg(gateway_id))
            except HTTPException:
                # The waiter is registered before the send because the SUB
                # reader runs in its own thread and could otherwise resolve
                # the reply before we were listening. Nothing will resolve
                # this one now, so drop it — otherwise clients retrying
                # against a down engine accumulate waiters indefinitely.
                self._drop_pending(auth_key, future)
                raise
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
                # Best-effort: the engine accepted the handshake, so the
                # gateway *is* authenticated. Seeding the symbol cache is a
                # convenience the client can obtain later via request_symbols,
                # and failing the whole authentication over it would be wrong.
                self._send(make_symbols_request_msg(gateway_id), require_engine=False)
                self._dbg_count("symbols_request_sent")
            return accepted, reason

    def _register_future(
        self, key: str, match: dict[str, str] | None = None
    ) -> asyncio.Future[dict[str, Any]]:
        future: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        self._pending[key].append(_PendingWait(future=future, match=match))
        self._dbg_count("futures_registered")
        return future

    def _drop_pending(self, key: str, future: asyncio.Future[dict[str, Any]]) -> None:
        """Remove a waiter that will never be resolved."""
        pending = self._pending.get(key)
        if pending is None:
            return
        self._pending[key] = [w for w in pending if w.future is not future]
        if not self._pending[key]:
            del self._pending[key]

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
            self._drop_pending(key, future)
            raise TimeoutError(f"Timed out waiting for {key}") from exc

    def _resolve_pending(self, topic: str, payload: dict[str, Any]) -> None:
        """Resolve waiters on *topic* with *payload*.

        Waiters with an explicit ``match`` only ever consume events whose
        payload satisfies that filter, so distinct match values (e.g.
        different ``order_id``s) are already correctly disambiguated and can
        all resolve off the same incoming event.

        Waiters with ``match=None`` accept *any* payload on the topic. A
        single event must not resolve more than one such waiter — two
        concurrent callers awaiting the same unfiltered topic (e.g. two
        admin calls whose ack carries no per-call identifier) are logically
        separate requests, and handing both of them the same reply would
        silently answer the second caller with the first caller's result.
        Instead, at most the oldest still-pending match=None waiter consumes
        this event (FIFO); any others keep waiting for a subsequent event on
        the same topic.
        """
        waiters = self._pending.get(topic)
        if not waiters:
            return
        remaining: list[_PendingWait] = []
        resolved_unmatched = False
        for waiter in waiters:
            if waiter.future.done():
                continue
            if waiter.match is not None:
                if all(str(payload.get(k, "")) == v for k, v in waiter.match.items()):
                    waiter.future.set_result(payload)
                else:
                    remaining.append(waiter)
            elif not resolved_unmatched:
                waiter.future.set_result(payload)
                resolved_unmatched = True
            else:
                remaining.append(waiter)
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

    def _next_seq(self, topic: str) -> int:
        """Monotonic sequence number for *topic*, starting at 1.

        Per **topic**, not per connection or per stream, and that choice is
        forced by how clients subscribe. A market-data client filters down to
        the symbols and channels it cares about, so a connection-wide counter
        would arrive with holes wherever an event was filtered out — every
        subscriber would see permanent phantom gaps and no subscriber could
        distinguish those from real loss. Per-topic numbering is contiguous
        for anyone receiving that topic at all, which is the only property
        that makes gap detection usable. (Same reasoning as the per-topic
        sequence on the engine's own PUB socket.)
        """
        seq = self._topic_seq[topic] + 1
        self._topic_seq[topic] = seq
        return seq

    def _next_stream_seq(self, gateway_id: str) -> int:
        """Monotonic sequence across *all* of one gateway's private events.

        Market data cannot have this: subscribers filter, so a stream-wide
        counter would show phantom gaps. ``/api/v1/events`` applies no
        filtering at all — a client receives every topic for its gateway — so
        a single counter is contiguous there, and one counter is markedly
        easier to check than one per topic.

        Both numbers are emitted. ``seq`` stays per-topic so the two sockets
        share one meaning for that field; ``stream_seq`` is the private
        stream's own.
        """
        seq = self._gateway_stream_seq[gateway_id] + 1
        self._gateway_stream_seq[gateway_id] = seq
        return seq

    def stream_seq(self, gateway_id: str) -> int:
        """The last private-stream sequence issued for *gateway_id*."""
        return self._gateway_stream_seq[gateway_id]

    def _record_drop(self, sink: str, event: dict[str, Any]) -> None:
        """Account for an event that could not be queued.

        The sink queues are bounded and written with ``put_nowait``, so a
        consumer slower than the feed loses events. That is the correct
        trade-off — one slow browser must not stall the gateway — but it was
        previously counted only through ``_dbg_count``, which is gated on
        DEBUG being enabled. In a normal run the loss was therefore invisible
        from both ends: the client had no sequence to check and the operator
        had no counter to read. Both halves of that are now fixed.
        """
        self._dropped_events[sink] += 1
        total = self._dropped_events[sink]
        # Log the first drop per sink immediately, then back off geometrically:
        # a saturated consumer would otherwise produce one line per event.
        if total == 1 or total % 100 == 0:
            log.warning(
                "%s sink full — dropped event (topic=%s, %d dropped on this sink). "
                "A client is slower than the feed; it can detect this from the "
                "per-topic seq gap.",
                sink,
                event.get("topic", "?"),
                total,
            )

    def _handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        self._dbg_count("events_handled")
        self._resolve_pending(topic, payload)
        if topic.startswith(ADMIN_ACTION_PREFIX):
            # Admin-monitor-only: must reach neither the initiating gateway's
            # own private stream nor market data, so it bypasses both branches
            # below rather than relying on gateway_from_topic() returning None
            # (which would otherwise fall into the market-data branch and leak
            # to every subscriber).
            event = envelope(topic, payload, seq=self._next_seq(topic))
            for queue in list(self._admin_sinks):
                if self._try_put(queue, event):
                    self._dbg_count("admin_sink_events")
                else:
                    self._dbg_count("admin_sink_drops")
                    self._record_drop("admin", event)
            return
        gateway_id = gateway_from_topic(topic)
        # Sequenced once per event, so every sink that receives it agrees on
        # the number. Assigned before fan-out and regardless of whether any
        # sink accepts it — a dropped event still consumes its sequence
        # number, which is precisely what makes the gap detectable.
        seq = self._next_seq(topic)
        if gateway_id is not None:
            self._dbg_count("gateway_scoped_events")
            cache = self._caches[gateway_id]
            cache.apply(topic, payload)
            self._register_tick_metadata(payload)
            event = envelope(
                topic, payload, seq=seq, stream_seq=self._next_stream_seq(gateway_id)
            )
            for queue in list(self._sinks.get(gateway_id, set())):
                if self._try_put(queue, event):
                    self._dbg_count("gateway_sink_events")
                else:
                    self._dbg_count("gateway_sink_drops")
                    self._record_drop("private", event)
        else:
            self._dbg_count("market_data_events")
            for cache in self._caches.values():
                cache.apply(topic, payload)
            event = envelope(topic, payload, seq=seq)
            for queue in list(self._market_data_sinks):
                if self._try_put(queue, event):
                    self._dbg_count("market_data_sink_events")
                else:
                    self._dbg_count("market_data_sink_drops")
                    self._record_drop("market_data", event)
        # The ADMIN monitor feed sees every event regardless of routing branch.
        for queue in list(self._admin_sinks):
            if self._try_put(queue, event):
                self._dbg_count("admin_sink_events")
            else:
                self._dbg_count("admin_sink_drops")
                self._record_drop("admin", event)

    @staticmethod
    def _try_put(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> bool:
        try:
            queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            return False

    @staticmethod
    def _register_tick_metadata(payload: dict[str, Any]) -> None:
        # This read `symbol_meta[sym]["tick_decimals"]`, and no producer has
        # ever sent that key — the engine sent `tick_size` under a separate
        # `symbol_meta` map, so the registration below has never fired. The
        # field exists now and this is the first time it does anything.
        entries = payload.get("symbols")
        if not isinstance(entries, list):
            return
        for entry in entries:
            if isinstance(entry, dict) and "tick_decimals" in entry:
                register_tick_decimals(
                    str(entry.get("symbol", "")), int(entry["tick_decimals"])
                )

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

    @property
    def dropped_events(self) -> dict[str, int]:
        """Events discarded per sink because a consumer could not keep up."""
        return dict(self._dropped_events)

    def get_caches(self, gateway_id: str) -> SessionCaches:
        return self._caches[gateway_id]

    def evict_terminal_orders(self, retention_sec: int) -> int:
        """Sweep every gateway's cache. Returns the number of orders dropped."""
        return sum(
            cache.evict_terminal_orders(retention_sec)
            for cache in list(self._caches.values())
        )

    def all_orders(self) -> list[dict[str, Any]]:
        """Every cached order across every gateway, tagged with its owner.

        `_caches` accumulates an entry for each gateway whose events pass
        through, so the cross-gateway view an admin needs is already here —
        it just was not reachable. `gateway_id` is added on the way out
        because the order payloads themselves do not carry it; it is the
        dictionary key.
        """
        out: list[dict[str, Any]] = []
        for gateway_id, cache in self._caches.items():
            for order in cache.orders.values():
                out.append({**order, "gateway_id": gateway_id})
        return out

    def send_new_order(self, order: Order) -> None:
        self._send(make_order_new_msg(order.to_dict()))

    def send_cancel(self, order_id: str, gateway_id: str) -> None:
        self._send(make_order_cancel_msg(order_id, gateway_id))

    def send_amend(
        self, order_id: str, gateway_id: str, price: float | None, qty: int | None
    ) -> None:
        self._send(make_order_amend_msg(order_id, gateway_id, price=price, qty=qty))

    def send_combo(self, payload: dict[str, Any]) -> None:
        self._send(make_combo_order_msg(payload))

    def send_combo_cancel(self, combo_id: str, gateway_id: str) -> None:
        self._send(make_combo_cancel_msg(combo_id, gateway_id))

    def send_oco(self, payload: dict[str, Any]) -> None:
        self._send(make_oco_order_msg(payload))

    def send_oco_cancel(self, oco_id: str, gateway_id: str) -> None:
        self._send(make_oco_cancel_msg(oco_id, gateway_id))

    def send_quote(self, payload: dict[str, Any]) -> None:
        self._send(make_quote_new_msg(payload))

    def send_quote_cancel(self, gateway_id: str, symbol: str) -> None:
        self._send(make_quote_cancel_msg(gateway_id, symbol))

    def send_mass_cancel(
        self, gateway_id: str, symbol: str = "", command_id: str = ""
    ) -> None:
        self._send(make_kill_switch_msg(gateway_id, symbol, command_id=command_id))

    async def send_and_await_kill_switch(
        self, gateway_id: str, symbol: str, timeout: float
    ) -> dict[str, Any]:
        """Send a mass-cancel/kill-switch request and await its own ack.

        The ack now echoes ``command_id``, so concurrent mass cancels for one
        gateway are told apart by ``match=`` exactly as the symbol-scoped
        halt/resume/cancel acks already were. That replaced a per-gateway
        ``asyncio.Lock`` whose only purpose was to stop two in-flight requests
        consuming each other's ack — a correctness fix that also removes the
        serialisation it imposed.
        """
        command_id = new_command_id()
        self.send_mass_cancel(gateway_id, symbol, command_id=command_id)
        return await self.await_event(
            topic_kill_switch_ack(gateway_id),
            match={"command_id": command_id},
            timeout=timeout,
        )

    async def send_and_await_session_transition(
        self, gateway_id: str, to_state: str, timeout: float
    ) -> dict[str, Any]:
        """Request a session transition and await the engine's verdict.

        Without this the endpoint was fire-and-forget: the engine discards a
        request outright when sessions are disabled or the state is unknown,
        and the caller saw nothing at all.
        """
        command_id = new_command_id()
        topic = topic_session_transition_ack(gateway_id)
        future = self._register_future(topic, match={"command_id": command_id})
        try:
            self._send(
                make_session_transition_msg(
                    to_state, command_id=command_id, gateway_id=gateway_id
                )
            )
        except HTTPException:
            self._drop_pending(topic, future)
            raise
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            self._drop_pending(topic, future)
            raise TimeoutError(f"Timed out waiting for {topic}") from exc

    async def send_and_await_reference_reload(
        self, gateway_id: str, timeout: float
    ) -> dict[str, Any]:
        """Request a reference-data reload and await the engine's verdict.

        Mirrors send_and_await_session_transition: fire-and-forget would
        leave a rejected reload (e.g. the symbol set changed) indistinguishable
        from a slow one.
        """
        command_id = new_command_id()
        topic = topic_reference_reload_ack(gateway_id)
        future = self._register_future(topic, match={"command_id": command_id})
        try:
            self._send(make_reference_reload_msg(gateway_id, command_id))
        except HTTPException:
            self._drop_pending(topic, future)
            raise
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            self._drop_pending(topic, future)
            raise TimeoutError(f"Timed out waiting for {topic}") from exc

    def request_orders(self, gateway_id: str) -> None:
        self._send(make_orders_request_msg(gateway_id))

    def request_symbols(self, gateway_id: str) -> None:
        self._send(make_symbols_request_msg(gateway_id))

    def request_reference(self, gateway_id: str) -> None:
        self._send(make_reference_request_msg(gateway_id))

    def request_session(self, gateway_id: str) -> None:
        self._send(make_session_state_request_msg(gateway_id))

    def request_quote_bootstrap(self, gateway_id: str, symbol: str = "") -> None:
        self._send(make_quote_bootstrap_request_msg(gateway_id, symbol))

    def request_quote_legs(
        self, gateway_id: str, symbol: str = "", show: str = "ALL"
    ) -> None:
        self._send(make_quote_legs_request_msg(gateway_id, symbol, show))

    # ------------------------------------------------------------------
    # ADMIN-persona commands (all map to existing engine topics)
    # ------------------------------------------------------------------

    def send_session_transition(self, to_state: str) -> None:
        self._send(make_session_transition_msg(to_state))

    def send_symbol_halt(
        self,
        gateway_id: str,
        symbol: str,
        level: str | None = None,
        note: str = "",
        command_id: str = "",
    ) -> None:
        self._send(
            make_symbol_halt_msg(
                gateway_id, symbol, level=level, note=note, command_id=command_id
            )
        )

    def send_symbol_resume(
        self, gateway_id: str, symbol: str, note: str = "", command_id: str = ""
    ) -> None:
        self._send(
            make_symbol_resume_msg(gateway_id, symbol, note=note, command_id=command_id)
        )

    def send_cancel_symbol(
        self, gateway_id: str, symbol: str, note: str = "", command_id: str = ""
    ) -> None:
        self._send(
            make_cancel_symbol_msg(gateway_id, symbol, note=note, command_id=command_id)
        )

    def send_kill_switch_gateway(
        self,
        gateway_id: str,
        target_gateway_id: str,
        note: str = "",
        command_id: str = "",
    ) -> None:
        self._send(
            make_kill_switch_gateway_msg(
                gateway_id, target_gateway_id, note=note, command_id=command_id
            )
        )

    def send_kill_switch_global(
        self, gateway_id: str, note: str = "", command_id: str = ""
    ) -> None:
        self._send(
            make_kill_switch_global_msg(gateway_id, note=note, command_id=command_id)
        )

    def send_gateway_disconnect(self, gateway_id: str, reason: str = "") -> None:
        self.send_disconnect(gateway_id, reason)

    def request_gateways(self, gateway_id: str) -> None:
        self._send(make_gateways_request_msg(gateway_id))

    def request_session_schedule(self, gateway_id: str) -> None:
        self._send(make_session_schedule_request_msg(gateway_id))

    def request_halt_status(self, gateway_id: str) -> None:
        self._send(make_halt_status_request_msg(gateway_id))

    def request_risk_state(self, gateway_id: str) -> None:
        self._send(make_risk_state_request_msg(gateway_id))

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
            reply = await self.await_topic(topic_gateways(gid), timeout)
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
