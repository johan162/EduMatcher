"""
ExchangeCommandClient — operator command interface for EduMatcher.

Each public method corresponds to one exchange command:

  Lifecycle:      connect(), disconnect(), close()
  ADMIN risk:     halt_all(), resume_all(), symbol_halt(), symbol_resume(),
                  cancel_symbol(), force_uncross(), kill_switch_gateway(),
                  kill_switch_global(), gateway_kick(), reference_reload()
  Self-service:   kill_switch(), mass_cancel(), quote_cancel() -- the
                  participant's own messages: the engine acts on the gateway
                  they name and does not check who sent them (L044)
  Queries:        book_depth(), order_list(), orders_reply(),
                  price_level_orders(), symbol_list(), tick_decimals(),
                  quote_bootstrap(), position_snapshot(), positions_reply(),
                  gateway_list(), volume()
  Session:        session_advance(), session_status(), session_schedule()
  pm-index:       index_history(), index_corp_action(), index_delist(),
                  index_add_constituent()

Adding a new command
--------------------
1.  Add a make_<cmd>_msg() helper to edumatcher/models/message.py.
2.  Add the handler + dispatch entry to edumatcher/engine/main.py.
3.  If the reply is addressed to the caller's own id, add its topic builder
    to _OWN_ENGINE_TOPICS below; a reply keyed by anything else is
    subscribed by _ask for the one request.
4.  Add a method that calls self._ask(request_frames, reply_topic).
5.  Add tests in tests/test_commands.py.
6.  Document it in docs/books/operator-guide/part-3-run/020-admin-console-and-commands.md.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import Any

import zmq

from edumatcher.messaging.bus import PushSocket, make_pusher
from edumatcher.models.ids import new_command_id
from edumatcher.config import (
    ENGINE_PUB_ADDR,
    ENGINE_PULL_ADDR,
    INDEX_PUB_CONNECT_ADDR,
    INDEX_PULL_CONNECT_ADDR,
)
from edumatcher.models.message import (
    decode,
    make_book_snapshot_request_msg,
    make_cancel_symbol_msg,
    make_circuit_breaker_halt_all_msg,
    make_circuit_breaker_resume_all_msg,
    make_force_uncross_msg,
    make_gateway_connect_msg,
    make_gateway_disconnect_msg,
    make_gateway_kick_msg,
    make_gateways_request_msg,
    make_kill_switch_gateway_msg,
    make_kill_switch_global_msg,
    make_kill_switch_msg,
    make_orders_request_msg,
    make_position_request_msg,
    make_price_level_orders_request_msg,
    make_quote_bootstrap_request_msg,
    make_quote_cancel_msg,
    make_reference_reload_msg,
    make_session_state_request_msg,
    make_session_schedule_request_msg,
    make_session_transition_msg,
    make_symbol_halt_msg,
    make_symbol_resume_msg,
    make_index_constituent_change_msg,
    make_index_corp_action_msg,
    make_index_history_request_msg,
    make_symbols_request_msg,
    make_volume_request_msg,
)
from edumatcher.models.generated.session import topic_session_transition_ack
from edumatcher.models.generated.order import topic_orders, topic_price_level_orders
from edumatcher.models.generated.book import topic_book_snapshot
from edumatcher.models.generated.risk import (
    topic_cancel_symbol_ack,
    topic_circuit_breaker_halt_all_ack,
    topic_circuit_breaker_resume_all_ack,
    topic_force_uncross_ack,
    topic_gateway_kick_ack,
    topic_kill_switch_ack,
    topic_kill_switch_gateway_ack,
    topic_kill_switch_global_ack,
    topic_symbol_halt_ack,
    topic_symbol_resume_ack,
)
from edumatcher.models.generated.index import (
    topic_index_constituent_change_ack,
    topic_index_corp_action_ack,
    topic_index_error,
    topic_index_history,
)
from edumatcher.models.generated.quote import topic_quote_cancel_ack
from edumatcher.models.generated.system import (
    topic_gateway_auth,
    topic_gateways,
    topic_position_snapshot,
    topic_quote_bootstrap,
    topic_reference_reload_ack,
    topic_session_schedule,
    topic_session_status,
    topic_symbols,
    topic_volume,
)

# Replies the engine addresses to this client's own gateway id. They are
# subscribed for the client's whole life, as exact topics: a prefix such as
# ``book.`` delivered every symbol's snapshots, filled an idle client's SUB
# queue and made ZeroMQ drop the next reply (Admin commands review 2026-11,
# H1). A reply keyed by something else (a symbol, a target gateway) is
# subscribed only while its request is outstanding, see ``_ask``.
_OWN_ENGINE_TOPICS: tuple[Callable[[str], str], ...] = (
    topic_gateway_auth,
    topic_circuit_breaker_halt_all_ack,
    topic_circuit_breaker_resume_all_ack,
    topic_symbol_halt_ack,
    topic_symbol_resume_ack,
    topic_cancel_symbol_ack,
    topic_force_uncross_ack,
    topic_gateway_kick_ack,
    topic_kill_switch_ack,
    topic_kill_switch_gateway_ack,
    topic_kill_switch_global_ack,
    topic_quote_cancel_ack,
    topic_reference_reload_ack,
    topic_session_transition_ack,
    topic_symbols,
    topic_price_level_orders,
    topic_session_status,
    topic_session_schedule,
    topic_gateways,
    topic_volume,
)
_OWN_INDEX_TOPICS: tuple[Callable[[str], str], ...] = (
    topic_index_history,
    topic_index_corp_action_ack,
    topic_index_constituent_change_ack,
    topic_index_error,
)

#: Silence after which an idempotent query is sent again. A subscription made
#: just before the request travels on another connection than the request, so
#: the first reply can, rarely, be published before the engine has it.
_RESEND_AFTER_SEC = 0.2
#: Pause after a temporary subscription for a request that must not be sent
#: twice (a self-service cancel naming another gateway).
_SUBSCRIBE_SETTLE_SEC = 0.05


class CommandTimeoutError(Exception):
    """Raised when no matching ack arrives within the configured timeout."""


class CommandError(Exception):
    """
    Raised when the server replies with a generic error on a side-channel
    topic instead of the ack topic the caller is waiting on.

    This is distinct from a normal rejection (``result["accepted"] is
    False`` on the expected ack topic, e.g. an invalid split ratio) — those
    are returned as a payload dict, not raised. ``CommandError`` covers
    replies that arrive on a *different* topic entirely, such as
    ``index.error.<gateway_id>`` for an unrecognized ``index_id`` — a case
    ``_recv()`` would otherwise silently discard while continuing to wait
    for its expected prefix, ultimately raising a misleading
    ``CommandTimeoutError`` instead.

    Parameters
    ----------
    payload:
        The full decoded payload from the error message (typically has
        ``reason`` and ``ts_ns`` keys -- AR-0.3 renamed the index family's
        ``timestamp`` field, this docstring included).
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.reason = str(payload.get("reason", "unknown error"))
        super().__init__(self.reason)


def _known(reply: dict[str, Any]) -> dict[str, Any]:
    """*reply*, unless the engine says its gateway is no participant."""
    if reply.get("status") == "UNKNOWN_GATEWAY":
        raise CommandError(
            {"reason": f"Gateway not configured: {reply.get('gateway_id', '')}"}
        )
    return reply


class ExchangeCommandClient:
    """
    Operator command client for an EduMatcher gateway.

    Instantiate once per process, call ``connect()``, then use the command
    methods.  Each command sends the appropriate ZMQ frame(s) over the PUSH
    socket and blocks for the matching ack on the SUB socket.

    Parameters
    ----------
    gw_id:
        Gateway ID to authenticate as (must match a gateway configured in
        ``engine_config.yaml``).
    push_addr:
        Address of the engine's PULL socket (default: ``ENGINE_PULL_ADDR``).
    pub_addr:
        Address of the engine's PUB socket (default: ``ENGINE_PUB_ADDR``).
    timeout_ms:
        Milliseconds to wait for an ack before raising ``CommandTimeoutError``.
    _push_sock / _sub_sock:
        Pre-built socket objects injected for testing.  When both are
        supplied, no real ZMQ sockets are created.
    _recv_queue:
        If supplied (a ``deque[list[bytes]]``), ``_recv()`` drains this queue
        instead of polling the real socket.  Used in tests to provide preset
        engine responses without a live ZMQ connection.
    """

    def __init__(
        self,
        gw_id: str,
        push_addr: str = ENGINE_PULL_ADDR,
        pub_addr: str = ENGINE_PUB_ADDR,
        index_pull_addr: str = INDEX_PULL_CONNECT_ADDR,
        index_pub_addr: str = INDEX_PUB_CONNECT_ADDR,
        timeout_ms: int = 3000,
        *,
        _push_sock: Any = None,
        _sub_sock: Any = None,
        _recv_queue: deque[list[bytes]] | None = None,
    ) -> None:
        self._gw_id = gw_id.upper()
        self._timeout_ms = timeout_ms
        self._recv_queue = _recv_queue
        self._owns_sockets = _push_sock is None
        # symbol -> display decimals, from the last symbols reply.
        self._decimals: dict[str, int] | None = None
        self._push: PushSocket

        if _push_sock is not None:
            # Injection mode (tests) — use provided sockets as-is.
            self._push = _push_sock
            self._index_push = _push_sock
            self._sub = _sub_sock
            self._index_sub = _sub_sock
            return

        ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()

        # make_pusher, not a bare zmq.PUSH. This built its own sockets, and so
        # missed both things that wrapper exists for: the causal envelope, so
        # every admin command arrived at the engine anonymous and each of its
        # effects -- kill-switch cancellations, session transitions, symbol
        # halts -- started an orphan chain naming no cause; and SNDTIMEO /
        # IMMEDIATE, without which a send to an engine that is not there blocks
        # indefinitely instead of failing fast.
        self._push = make_pusher(push_addr)
        self._index_push = make_pusher(index_pull_addr)

        self._sub = ctx.socket(zmq.SUB)
        self._sub.connect(pub_addr)

        self._index_sub = ctx.socket(zmq.SUB)
        self._index_sub.connect(index_pub_addr)
        for own in _OWN_ENGINE_TOPICS:
            self._sub.setsockopt_string(zmq.SUBSCRIBE, own(self._gw_id))
        for own in _OWN_INDEX_TOPICS:
            self._index_sub.setsockopt_string(zmq.SUBSCRIBE, own(self._gw_id))

    @property
    def gateway_id(self) -> str:
        """The gateway id this client acts as."""
        return self._gw_id

    # ------------------------------------------------------------------
    # Low-level send / recv
    # ------------------------------------------------------------------

    def _send(self, frames: list[bytes]) -> None:
        """Send a two-frame ZMQ multipart message over the PUSH socket,
        after dropping whatever queued up since the last request."""
        self._discard_pending()
        self._push.send_multipart(frames)

    def _discard_pending(self) -> None:
        """Drop every message already queued on the SUB sockets.

        Called before every request. Only replies to this client's own id
        are subscribed between requests, so what waits here is a reply
        nobody wants any more (a late ack of a command that timed out); left
        there it would answer the next request of its kind. Commands run one
        at a time, so nothing queued before a request is still wanted.
        """
        if self._recv_queue is not None:
            return  # test mode: the injected queue is the whole conversation
        for sock in (self._sub, self._index_sub):
            while sock is not None and sock.poll(0):
                sock.recv_multipart()

    def _send_index(self, frames: list[bytes]) -> None:
        """Send to ``pm-index``, waiting for the PUSH connection to come up.

        ``pm-index`` has no connect handshake, unlike the engine socket, so
        nothing gives the connection time to establish before the first send.
        The pusher is created with ``IMMEDIATE``, so a send before the peer is
        connected fails at once with ``zmq.Again`` instead of queueing; retry
        for up to the command timeout.
        """
        self._discard_pending()
        deadline = time.monotonic() + self._timeout_ms / 1000
        while True:
            try:
                self._index_push.send_multipart(frames)
                return
            except zmq.Again:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def _ask(
        self,
        frames: list[bytes],
        reply_topic: str,
        *,
        error_topic: str | None = None,
        idempotent: bool = False,
        index: bool = False,
    ) -> dict[str, Any]:
        """Send one request and return the payload of its reply.

        A reply topic outside this client's own (``_OWN_ENGINE_TOPICS``,
        ``_OWN_INDEX_TOPICS``) is subscribed for this request only. An
        *idempotent* query is sent again after ``_RESEND_AFTER_SEC`` of
        silence, which also covers a reply published before the new
        subscription reached the engine; any other request waits
        ``_SUBSCRIBE_SETTLE_SEC`` after subscribing instead.
        """
        sub = self._index_sub if index else self._sub
        own = _OWN_INDEX_TOPICS if index else _OWN_ENGINE_TOPICS
        temporary = self._recv_queue is None and reply_topic not in {
            t(self._gw_id) for t in own
        }
        if temporary:
            sub.setsockopt_string(zmq.SUBSCRIBE, reply_topic)
            if not idempotent:
                time.sleep(_SUBSCRIBE_SETTLE_SEC)
        send = self._send_index if index else self._send
        try:
            send(frames)
            return self._recv(
                reply_topic,
                error_topic,
                resend=(lambda: send(frames)) if idempotent else None,
            )
        finally:
            if temporary:
                sub.setsockopt_string(zmq.UNSUBSCRIBE, reply_topic)

    def _recv(
        self,
        expected_topic: str,
        error_topic: str | None = None,
        *,
        resend: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """
        Return the payload of the first inbound message on *expected_topic*.

        Topics are compared exactly: a subscription is a byte prefix, so the
        socket also delivers ``system.volume.GW_ADMIN2`` to ``GW_ADMIN``.

        In test mode (``_recv_queue`` supplied) the queue is drained directly
        without ZMQ polling.  In production mode, ``zmq.Poller`` is used so
        the timeout is correctly enforced.

        Parameters
        ----------
        expected_topic:
            Topic of the normal ack this call is waiting for.
        error_topic:
            Optional topic of a generic side-channel error reply
            (e.g. ``index.error.<gateway_id>``). If it arrives before the
            expected message, ``CommandError`` is raised immediately instead
            of waiting out the full timeout for an ack that will never come.
            Pass ``None`` (the default) for commands with no such side-channel.
        resend:
            Called after ``_RESEND_AFTER_SEC`` without the reply, again and
            again until the timeout; ``None`` waits for the one request.

        Raises
        ------
        CommandError
            If the *error_topic* message arrives before the expected one.
        CommandTimeoutError
            If no matching message arrives within ``timeout_ms``.
        """
        if self._recv_queue is not None:
            # Test / injection mode — no polling needed.
            while self._recv_queue:
                frames = self._recv_queue.popleft()
                topic, payload = decode(frames)
                if topic == expected_topic:
                    return payload
                if error_topic is not None and topic == error_topic:
                    raise CommandError(payload)
            raise CommandTimeoutError(
                f"Test queue exhausted before finding topic '{expected_topic}'"
            )

        # Production mode — use ZMQ poller with timeout.
        poller = zmq.Poller()
        poller.register(self._sub, zmq.POLLIN)
        if self._index_sub is not None:
            poller.register(self._index_sub, zmq.POLLIN)
        deadline = time.monotonic() + self._timeout_ms / 1000.0
        next_resend = time.monotonic() + _RESEND_AFTER_SEC
        while True:
            now = time.monotonic()
            if now >= deadline:
                raise CommandTimeoutError(
                    f"No ack on '{expected_topic}' within {self._timeout_ms} ms"
                )
            if resend is not None and now >= next_resend:
                resend()
                next_resend = now + _RESEND_AFTER_SEC
            wait_until = min(deadline, next_resend) if resend else deadline
            socks = dict(poller.poll(max(0, int((wait_until - now) * 1000))))
            for sock in (self._sub, self._index_sub):
                if sock is None or sock not in socks:
                    continue
                frames = sock.recv_multipart()
                topic, payload = decode(frames)
                if topic == expected_topic:
                    return payload
                if error_topic is not None and topic == error_topic:
                    raise CommandError(payload)
            # Discard unrelated messages and keep waiting.

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> dict[str, Any]:
        """
        Authenticate this gateway with the engine.

        Returns the ``system.gateway_auth`` payload.  Check
        ``result["accepted"]`` before sending any other commands.
        """
        deadline = time.monotonic() + self._timeout_ms / 1000.0
        if self._recv_queue is None:
            self._await_reply_path(deadline)
        # The PUSH socket fails fast (SNDTIMEO 0, IMMEDIATE) and its TCP
        # connection to the engine completes asynchronously, so the very
        # first send can find no peer yet. Retry it within the ack timeout.
        frames = make_gateway_connect_msg(self._gw_id)
        while True:
            try:
                self._send(frames)
                break
            except zmq.Again:
                if time.monotonic() >= deadline:
                    raise CommandTimeoutError(
                        f"Engine not reachable within {self._timeout_ms} ms"
                    ) from None
                time.sleep(0.05)
        return self._recv(topic_gateway_auth(self._gw_id))

    def _await_reply_path(self, deadline: float) -> None:
        """Return once a reply published for this client reaches it.

        The SUB socket connects, and sends its subscriptions, independently
        of the PUSH socket. A connect the engine answers before then loses
        its reply while the engine holds the ID as connected; nothing beats
        for that session, so every later connect is refused until the engine
        times it out (three minutes). ``system.session_state_request`` is
        answered to anyone and changes nothing, so it is sent every 100 ms
        until its reply arrives on this client's own status topic.
        """
        probe = make_session_state_request_msg(self._gw_id)
        status_topic = topic_session_status(self._gw_id)
        while time.monotonic() < deadline:
            try:
                self._send(probe)
            except zmq.Again:
                pass  # the PUSH connection is not up yet
            round_end = min(deadline, time.monotonic() + 0.1)
            while (left := round_end - time.monotonic()) > 0:
                if not self._sub.poll(int(left * 1000) + 1):
                    break
                topic, _ = decode(self._sub.recv_multipart())
                if topic == status_topic:
                    return
        raise CommandTimeoutError(f"Engine not reachable within {self._timeout_ms} ms")

    def disconnect(self) -> None:
        """Send a graceful disconnect notice.  No ack is published."""
        self._send(make_gateway_disconnect_msg(self._gw_id))

    def engine_disconnect_monitor(self) -> zmq.Socket[bytes]:
        """Monitor the engine transport for a disconnect after authentication."""
        return self._push.get_monitor_socket(events=zmq.EVENT_DISCONNECTED)

    def close_engine_disconnect_monitor(self, monitor: zmq.Socket[bytes]) -> None:
        """Detach and close a monitor from :meth:`engine_disconnect_monitor`.

        Closing only the monitor socket is not enough: libzmq's I/O thread
        sends monitor events with a blocking send, so a later disconnect on
        the PUSH socket would block that thread -- and every socket sharing
        the context -- forever on a pipe nobody reads.
        """
        try:
            self._push.disable_monitor()
        except zmq.ZMQError:
            pass  # PUSH socket already closed
        monitor.close(linger=0)

    def close(self) -> None:
        """Close ZMQ sockets (only when they were created by this instance)."""
        if self._owns_sockets:
            self._push.close()
            self._index_push.close()
            self._sub.close()
            self._index_sub.close()

    def __enter__(self) -> "ExchangeCommandClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Risk controls — ADMIN role required
    # ------------------------------------------------------------------

    def halt_all(self) -> dict[str, Any]:
        """
        Exchange-wide circuit-breaker halt.

        Halts every known symbol with ``halt_source = ADMIN`` and
        cancels all outstanding MM quote legs.  Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``reason``, ``halted_symbols``,
        ``cancelled_quotes``.
        """
        return self._ask(
            make_circuit_breaker_halt_all_msg(self._gw_id),
            topic_circuit_breaker_halt_all_ack(self._gw_id),
        )

    def resume_all(self) -> dict[str, Any]:
        """
        Resume all symbols halted by :meth:`halt_all`.

        Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``reason``, ``resumed_symbols``.
        """
        return self._ask(
            make_circuit_breaker_resume_all_msg(self._gw_id),
            topic_circuit_breaker_resume_all_ack(self._gw_id),
        )

    def kill_switch_gateway(
        self,
        target_gw: str,
        note: str = "",
        *,
        symbol: str = "",
        quotes_only: bool = False,
    ) -> dict[str, Any]:
        """
        Cancel every resting order and quote of another gateway.

        Unlike :meth:`kill_switch`, the caller and the target may differ, and
        the target need not be connected. *symbol* scopes it to one
        instrument; *quotes_only* leaves the target's non-quote orders.
        Requires ``role: ADMIN``; the audit trail names the caller.

        Returns
        -------
        dict with keys: ``accepted``, ``reason``, ``target_gateway_id``,
        ``cancelled_orders``, ``cancelled_quotes``.
        """
        return self._ask(
            make_kill_switch_gateway_msg(
                self._gw_id,
                target_gw,
                note=note,
                command_id=new_command_id(),
                symbol=symbol,
                quotes_only=quotes_only,
            ),
            topic_kill_switch_gateway_ack(self._gw_id),
        )

    def kill_switch_global(self, note: str = "") -> dict[str, Any]:
        """
        Cancel every resting order and quote of every gateway.

        Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``reason``, ``cancelled_orders``,
        ``cancelled_quotes``, ``affected_gateways``.
        """
        return self._ask(
            make_kill_switch_global_msg(
                self._gw_id, note=note, command_id=new_command_id()
            ),
            topic_kill_switch_global_ack(self._gw_id),
        )

    def reference_reload(self) -> dict[str, Any]:
        """
        Re-read static reference data from the engine's config file.

        Refused when the engine started from a compiled artifact.
        Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``reason``, ``config_version``.
        """
        return self._ask(
            make_reference_reload_msg(self._gw_id, new_command_id()),
            topic_reference_reload_ack(self._gw_id),
        )

    # ------------------------------------------------------------------
    # Self-service risk controls -- the named gateway's own messages
    # ------------------------------------------------------------------

    def kill_switch(self, target_gw: str, symbol: str = "") -> dict[str, Any]:
        """
        Cancel all resting orders and quotes for *target_gw*.

        Pass *symbol* to scope the cancellation to one instrument.  The
        gateway is NOT halted — it can submit fresh orders immediately after
        the ack is received.

        Returns
        -------
        dict with keys: ``accepted``, ``reason``, ``cancelled_orders``,
        ``cancelled_quotes``.
        """
        return self._ask(
            make_kill_switch_msg(target_gw.upper(), symbol.upper()),
            topic_kill_switch_ack(target_gw.upper()),
        )

    def mass_cancel(self, target_gw: str, symbol: str) -> dict[str, Any]:
        """
        Cancel all resting orders and the active quote for *target_gw* on
        *symbol*.  Convenience alias for :meth:`kill_switch` with a symbol.
        """
        return self.kill_switch(target_gw, symbol=symbol)

    def quote_cancel(self, target_gw: str, symbol: str) -> dict[str, Any]:
        """
        Cancel the active two-sided quote for *target_gw* on *symbol*.

        Resting limit orders submitted outside the quote mechanism are
        unaffected.  Use :meth:`mass_cancel` to also remove those.

        Returns
        -------
        dict with keys: ``accepted``, ``reason``, ``quote_id``.
        """
        return self._ask(
            make_quote_cancel_msg(target_gw.upper(), symbol.upper()),
            topic_quote_cancel_ack(target_gw.upper()),
        )

    def gateway_kick(self, target_gw: str, reason: str = "") -> dict[str, Any]:
        """
        Forcefully disconnect *target_gw*.

        Sends the ADMIN message ``risk.gateway_kick``: the engine applies the
        target's configured ``disconnect_behaviour`` (``LEAVE_ALL``,
        ``CANCEL_QUOTES_ONLY`` or ``CANCEL_ALL``), names this caller in the
        bye's reason and on the admin monitor, and refuses an unknown, a
        disconnected or this client's own id. Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``reason``, ``target_gateway_id``.
        """
        return self._ask(
            make_gateway_kick_msg(
                self._gw_id, target_gw, note=reason, command_id=new_command_id()
            ),
            topic_gateway_kick_ack(self._gw_id),
        )

    # ------------------------------------------------------------------
    # Data queries
    # ------------------------------------------------------------------

    def book_depth(self, symbol: str) -> dict[str, Any]:
        """
        Request the current L1/L2 order-book snapshot for *symbol*.

        Returns
        -------
        dict with keys: ``symbol``, ``tick_decimals``, ``ts_ns``, ``bids``,
        ``asks``, ``recent_trades``, ``last_price``, ``last_qty``,
        ``last_buy_price``, ``last_sell_price``. The four ``last_*`` fields
        are ``None`` on a book that has not traded.
        """
        return self._ask(
            make_book_snapshot_request_msg(symbol.upper()),
            topic_book_snapshot(symbol.upper()),
            idempotent=True,
        )

    def order_list(self, target_gw: str) -> list[dict[str, Any]]:
        """
        Return all resting (unfilled, non-cancelled) orders for *target_gw*
        across all symbols, connected or not.

        Raises
        ------
        CommandError
            If *target_gw* is not a configured participant.
        """
        return list(_known(self.orders_reply(target_gw)).get("orders", []))

    def orders_reply(self, target_gw: str) -> dict[str, Any]:
        """
        Return the engine's whole ``order.orders`` reply for *target_gw*:
        ``gateway_id`` (the one asked about; the reply names it only in its
        topic), ``orders`` and ``status`` -- ``OK``,
        ``NOT_CONNECTED`` (the orders of a logged-off participant) or
        ``UNKNOWN_GATEWAY`` (no such participant; ``orders`` is empty).
        """
        target = target_gw.upper()
        reply = self._ask(
            make_orders_request_msg(target), topic_orders(target), idempotent=True
        )
        return {"gateway_id": target, **reply}

    def price_level_orders(
        self, symbol: str, price: float | None = None
    ) -> dict[str, Any]:
        """
        Return every resting order for *symbol* across every gateway,
        optionally narrowed to a single *price* level — the per-order
        composition ``book_depth`` only ever aggregates to ``{price, qty,
        count}``. ADMIN role required; the engine rejects (``rejected:
        True``, ``orders: []``) for any other caller.

        Returns
        -------
        dict with keys: ``symbol``, ``price`` (echoed back only when a
        filter was supplied), ``rejected``, ``reason`` (set only when
        rejected), ``orders`` — a list of per-order dicts each carrying
        ``gateway_id`` plus the same fields as an ``order_list()`` entry,
        ordered by price then by arrival sequence within a price level.
        """
        return self._ask(
            make_price_level_orders_request_msg(self._gw_id, symbol.upper(), price),
            topic_price_level_orders(self._gw_id),
        )

    def symbol_list(self) -> list[str]:
        """Return the list of all symbols configured in the engine.

        The reply carries one record per instrument since 6.1e; this helper
        still answers with names, and keeps each one's ``tick_decimals`` for
        :meth:`tick_decimals`.
        """
        result = self._ask(
            make_symbols_request_msg(self._gw_id), topic_symbols(self._gw_id)
        )
        entries = result.get("symbols", [])
        self._decimals = {
            str(e.get("symbol", "")): int(e.get("tick_decimals", 2)) for e in entries
        }
        return [str(e.get("symbol", "")) for e in entries]

    def tick_decimals(self, symbol: str) -> int | None:
        """The display decimals of *symbol* (2 for 189.50, 3 for 12.500), or
        ``None`` for a symbol the engine does not list. Asks the engine for
        its symbol list once, unless :meth:`symbol_list` already did."""
        if self._decimals is None:
            self.symbol_list()
        assert self._decimals is not None
        return self._decimals.get(symbol.upper())

    def index_history(
        self,
        index_id: str,
        from_ts: float,
        to_ts: float,
        types: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Query historical index records for one index id.

        Raises
        ------
        CommandError
            If *index_id* is not configured in ``pm-index`` — it replies on
            ``index.error.<gateway_id>`` rather than the history topic.
        """
        # AR-0.3: this method's own from_ts/to_ts stay seconds (its public
        # SDK-level contract); converted to the wire message's
        # from_ts_ns/to_ts_ns only at this boundary.
        return self._ask(
            make_index_history_request_msg(
                gateway_id=self._gw_id,
                index_id=index_id.upper(),
                from_ts_ns=int(from_ts * 1_000_000_000),
                to_ts_ns=int(to_ts * 1_000_000_000),
                types=types,
            ),
            topic_index_history(self._gw_id),
            error_topic=topic_index_error(self._gw_id),
            index=True,
        )

    def index_corp_action(
        self,
        index_id: str,
        action: str,
        symbol: str,
        **params: Any,
    ) -> dict[str, Any]:
        """
        Apply a corporate action on an index constituent.

        Raises
        ------
        CommandError
            If *index_id* is not configured in ``pm-index``. An unknown
            *symbol* or invalid action-specific parameters are instead
            returned as a normal rejection (``result["accepted"] is
            False``) on the corp-action ack topic, since ``pm-index``
            knows the index at that point and can reply on the expected
            topic.
        """
        return self._ask(
            make_index_corp_action_msg(
                action=action.upper(),
                index_id=index_id.upper(),
                symbol=symbol.upper(),
                gateway_id=self._gw_id,
                params=params,
                command_id=new_command_id(),
            ),
            topic_index_corp_action_ack(self._gw_id),
            error_topic=topic_index_error(self._gw_id),
            index=True,
        )

    def index_delist(self, index_id: str, symbol: str) -> dict[str, Any]:
        """
        Delist a symbol from an index.

        Raises
        ------
        CommandError
            If *index_id* is not configured in ``pm-index``.
        """
        return self._ask(
            make_index_constituent_change_msg(
                change_type="DELIST",
                index_id=index_id.upper(),
                symbol=symbol.upper(),
                gateway_id=self._gw_id,
                command_id=new_command_id(),
            ),
            topic_index_constituent_change_ack(self._gw_id),
            error_topic=topic_index_error(self._gw_id),
            index=True,
        )

    def index_add_constituent(
        self,
        index_id: str,
        symbol: str,
        shares_outstanding: int,
        initial_price: float,
    ) -> dict[str, Any]:
        """
        Add a constituent to an index.

        Raises
        ------
        CommandError
            If *index_id* is not configured in ``pm-index``.
        """
        return self._ask(
            make_index_constituent_change_msg(
                change_type="ADD",
                index_id=index_id.upper(),
                symbol=symbol.upper(),
                gateway_id=self._gw_id,
                shares_outstanding=shares_outstanding,
                initial_price=initial_price,
                command_id=new_command_id(),
            ),
            topic_index_constituent_change_ack(self._gw_id),
            error_topic=topic_index_error(self._gw_id),
            index=True,
        )

    def quote_bootstrap(self, target_gw: str, symbol: str = "") -> list[dict[str, Any]]:
        """
        Return active quote bootstrap state for *target_gw*.

        Optional *symbol* narrows the result to one instrument.
        """
        result = self._ask(
            make_quote_bootstrap_request_msg(target_gw.upper(), symbol.upper()),
            topic_quote_bootstrap(target_gw.upper()),
            idempotent=True,
        )
        return list(result.get("quotes", []))

    def position_snapshot(self, target_gw: str) -> list[dict[str, Any]]:
        """
        Return *target_gw*'s signed net position and volume-weighted average
        cost per symbol, from the engine's own per-gateway ledger
        (``_gateway_positions``/``_gateway_avg_cost`` in ``engine/main.py``).

        Works for any gateway, not just a market maker -- this is the same
        ``system.position_request``/``system.position_snapshot.<gateway_id>``
        pair ``pm-alf-console``'s and ``pm-alf-gwy``'s ``POS|GW=`` and the
        REST ``GET /api/v1/admin/gateways/{gateway_id}/positions`` endpoint already use, so all
        four surfaces always agree.

        Raises
        ------
        CommandError
            If *target_gw* is not a configured participant.
        """
        positions = _known(self.positions_reply(target_gw)).get("positions", [])
        return positions if isinstance(positions, list) else []

    def positions_reply(self, target_gw: str) -> dict[str, Any]:
        """
        Return the engine's whole ``system.position_snapshot`` reply for
        *target_gw*: ``gateway_id``, ``positions`` and ``status`` (as for
        :meth:`orders_reply`).
        """
        target = target_gw.upper()
        reply = self._ask(
            make_position_request_msg(target),
            topic_position_snapshot(target),
            idempotent=True,
        )
        return {"gateway_id": target, **reply}

    # ------------------------------------------------------------------
    # Session control
    # ------------------------------------------------------------------

    def session_advance(self, to_state: str) -> dict[str, Any]:
        """
        Request a session-phase transition.

        Valid states: ``PRE_OPEN``, ``OPENING_AUCTION``, ``CONTINUOUS``,
        ``CLOSING_AUCTION``, ``CLOSED``.

        Returns the engine's ``session.transition_ack``: ``accepted``,
        ``to_state`` and, for a refused transition, the engine's ``reason``
        (an illegal one is answered at once, not left to time out, L009).
        """
        return self._ask(
            make_session_transition_msg(
                to_state.upper(), command_id=new_command_id(), gateway_id=self._gw_id
            ),
            topic_session_transition_ack(self._gw_id),
        )

    def session_status(self) -> dict[str, Any]:
        """
        Return the current session state without advancing it.

        Returns
        -------
        dict with keys: ``state`` (str), ``sessions_enabled`` (bool).
        """
        return self._ask(
            make_session_state_request_msg(self._gw_id),
            topic_session_status(self._gw_id),
        )

    def session_schedule(self) -> dict[str, Any]:
        """
        Return the session schedule configuration from the engine config.

        Returns
        -------
        dict with keys: ``sessions_enabled`` (bool), ``schedule`` (the
        resolved weekly table -- ``mon``..``sun`` and ``holidays``, each a
        dict of phase -> ``HH:MM`` or ``None`` for CLOSED -- or ``None`` if
        no ``schedule:`` block is configured).
        """
        return self._ask(
            make_session_schedule_request_msg(self._gw_id),
            topic_session_schedule(self._gw_id),
        )

    def gateway_list(self) -> list[dict[str, Any]]:
        """
        Return all gateways configured in the engine with their connection status.

        Returns
        -------
        List of dicts with keys: ``id``, ``role``, ``description``, ``connected``.
        """
        result = self._ask(
            make_gateways_request_msg(self._gw_id), topic_gateways(self._gw_id)
        )
        return list(result.get("gateways", []))

    def volume(self) -> dict[str, Any]:
        """
        Return daily traded volume for each symbol and exchange-wide totals.

        Returns
        -------
        dict with keys:

        - ``symbols``: list of ``{symbol, qty, value, trades}``
        - ``total_qty``: int
        - ``total_value``: float
        - ``total_trades``: int
        """
        return self._ask(
            make_volume_request_msg(self._gw_id), topic_volume(self._gw_id)
        )

    # ------------------------------------------------------------------
    # Per-symbol controls — ADMIN role required
    # ------------------------------------------------------------------

    def symbol_halt(self, symbol: str) -> dict[str, Any]:
        """
        Halt trading on a single *symbol*.

        Cancels all outstanding MM quote legs for that symbol and prevents
        new orders from matching until :meth:`symbol_resume` is called.
        Unlike :meth:`halt_all`, all other symbols continue trading normally.
        Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``symbol``, ``reason``,
        ``cancelled_quotes``.
        """
        return self._ask(
            make_symbol_halt_msg(self._gw_id, symbol.upper()),
            topic_symbol_halt_ack(self._gw_id),
        )

    def symbol_resume(self, symbol: str) -> dict[str, Any]:
        """
        Resume trading on a single *symbol* previously halted by
        :meth:`symbol_halt` or by an automatic circuit-breaker trigger.

        Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``symbol``, ``reason``.
        """
        return self._ask(
            make_symbol_resume_msg(self._gw_id, symbol.upper()),
            topic_symbol_resume_ack(self._gw_id),
        )

    def cancel_symbol(self, symbol: str) -> dict[str, Any]:
        """
        Cancel **all** resting orders and the active quote for *symbol*
        across every connected gateway.

        Unlike :meth:`kill_switch`, which targets a single gateway, this
        command clears the entire order book for one symbol regardless of
        which participant placed the orders.  Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``symbol``, ``reason``,
        ``cancelled_orders``, ``cancelled_quotes``.
        """
        return self._ask(
            make_cancel_symbol_msg(self._gw_id, symbol.upper()),
            topic_cancel_symbol_ack(self._gw_id),
        )

    def force_uncross(
        self,
        symbol: str,
        price: float | None = None,
        *,
        dry_run: bool = False,
        note: str = "",
    ) -> dict[str, Any]:
        """
        Force *symbol* to uncross now and clear any halt in one step.

        ``price`` is ``None`` to open at the naturally computed equilibrium,
        or a value to assert an operator opening price when a failed auction
        left no natural equilibrium.  ``dry_run=True`` peeks the indicative
        print without changing any state.  Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``symbol``, ``reason``, ``dry_run``,
        ``indicative_price`` (nullable), ``indicative_qty``, ``surplus``,
        ``imbalance_side``, ``printed_price`` (nullable), ``traded_qty``.
        """
        return self._ask(
            make_force_uncross_msg(
                self._gw_id,
                symbol.upper(),
                price=price,
                dry_run=dry_run,
                note=note,
            ),
            topic_force_uncross_ack(self._gw_id),
        )
