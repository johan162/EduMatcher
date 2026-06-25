"""
ExchangeCommandClient — operator command interface for EduMatcher.

Each public method corresponds to one exchange command:

  Lifecycle:      connect(), disconnect(), close()
  ADMIN risk:     halt_all(), resume_all()
  Risk (any GW):  kill_switch(), mass_cancel(), quote_cancel(), gateway_kick()
  Queries:        book_depth(), order_list(), symbol_list()
  Session:        session_advance()

Adding a new command
--------------------
1.  Add a make_<cmd>_msg() helper to edumatcher/models/message.py.
2.  Add the handler + dispatch entry to edumatcher/engine/main.py.
3.  Add the ack topic prefix to _ACK_SUB_PREFIXES below.
4.  Add a method that calls self._send() and self._recv().
5.  Add tests in tests/test_commands.py.
6.  Add a row + detail section to docs/commands.md.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import zmq

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
    make_gateway_connect_msg,
    make_gateway_disconnect_msg,
    make_gateways_request_msg,
    make_kill_switch_msg,
    make_orders_request_msg,
    make_quote_bootstrap_request_msg,
    make_quote_cancel_msg,
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

# Topics this client ever needs to receive from the engine PUB socket.
# Extend this list when adding new commands that carry acks.
_ACK_SUB_PREFIXES: tuple[str, ...] = (
    "system.gateway_auth.",
    "risk.circuit_breaker_halt_all_ack.",
    "risk.circuit_breaker_resume_all_ack.",
    "risk.symbol_halt_ack.",
    "risk.symbol_resume_ack.",
    "risk.cancel_symbol_ack.",
    "risk.kill_switch_ack.",
    "quote.ack.",
    "book.",
    "session.state",
    "system.symbols.",
    "order.orders.",
    "system.quote_bootstrap.",
    "system.session_status.",
    "system.session_schedule.",
    "system.gateways.",
    "system.volume.",
    "index.history.",
    "index.corp_action_ack.",
    "index.constituent_change_ack.",
    "index.error.",
)


class CommandTimeoutError(Exception):
    """Raised when no matching ack arrives within the configured timeout."""


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

        if _push_sock is not None:
            # Injection mode (tests) — use provided sockets as-is.
            self._push = _push_sock
            self._index_push = _push_sock
            self._sub = _sub_sock
            self._index_sub = _sub_sock
            return

        ctx = zmq.Context.instance()

        self._push = ctx.socket(zmq.PUSH)
        self._push.connect(push_addr)

        self._index_push = ctx.socket(zmq.PUSH)
        self._index_push.connect(index_pull_addr)

        self._sub = ctx.socket(zmq.SUB)
        self._sub.connect(pub_addr)

        self._index_sub = ctx.socket(zmq.SUB)
        self._index_sub.connect(index_pub_addr)
        for prefix in _ACK_SUB_PREFIXES:
            self._sub.setsockopt_string(zmq.SUBSCRIBE, prefix)
            self._index_sub.setsockopt_string(zmq.SUBSCRIBE, prefix)

    # ------------------------------------------------------------------
    # Low-level send / recv
    # ------------------------------------------------------------------

    def _send(self, frames: list[bytes]) -> None:
        """Send a two-frame ZMQ multipart message over the PUSH socket."""
        self._push.send_multipart(frames)

    def _recv(self, expected_prefix: str) -> dict[str, Any]:
        """
        Return the payload of the first inbound message whose topic starts
        with *expected_prefix*.

        In test mode (``_recv_queue`` supplied) the queue is drained directly
        without ZMQ polling.  In production mode, ``zmq.Poller`` is used so
        the timeout is correctly enforced.

        Raises
        ------
        CommandTimeoutError
            If no matching message arrives within ``timeout_ms``.
        """
        if self._recv_queue is not None:
            # Test / injection mode — no polling needed.
            while self._recv_queue:
                frames = self._recv_queue.popleft()
                topic, payload = decode(frames)
                if topic.startswith(expected_prefix):
                    return payload
            raise CommandTimeoutError(
                f"Test queue exhausted before finding prefix '{expected_prefix}'"
            )

        # Production mode — use ZMQ poller with timeout.
        poller = zmq.Poller()
        poller.register(self._sub, zmq.POLLIN)
        if self._index_sub is not None:
            poller.register(self._index_sub, zmq.POLLIN)
        deadline = time.monotonic() + self._timeout_ms / 1000.0
        while True:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(remaining_ms))
            if not socks:
                raise CommandTimeoutError(
                    f"No ack with prefix '{expected_prefix}' "
                    f"within {self._timeout_ms} ms"
                )
            for sock in (self._sub, self._index_sub):
                if sock is None:
                    continue
                if sock not in socks:
                    continue
                frames = sock.recv_multipart()
                topic, payload = decode(frames)
                if topic.startswith(expected_prefix):
                    return payload
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
        self._send(make_gateway_connect_msg(self._gw_id))
        return self._recv(f"system.gateway_auth.{self._gw_id}")

    def disconnect(self) -> None:
        """Send a graceful disconnect notice.  No ack is published."""
        self._send(make_gateway_disconnect_msg(self._gw_id))

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

        Halts every known symbol with ``resumption_mode = MANUAL`` and
        cancels all outstanding MM quote legs.  Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``reason``, ``halted_symbols``,
        ``cancelled_quotes``.
        """
        self._send(make_circuit_breaker_halt_all_msg(self._gw_id))
        return self._recv(f"risk.circuit_breaker_halt_all_ack.{self._gw_id}")

    def resume_all(self) -> dict[str, Any]:
        """
        Resume all symbols halted by :meth:`halt_all`.

        Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``reason``, ``resumed_symbols``.
        """
        self._send(make_circuit_breaker_resume_all_msg(self._gw_id))
        return self._recv(f"risk.circuit_breaker_resume_all_ack.{self._gw_id}")

    # ------------------------------------------------------------------
    # Risk controls — any connected gateway
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
        self._send(make_kill_switch_msg(target_gw.upper(), symbol.upper()))
        return self._recv(f"risk.kill_switch_ack.{target_gw.upper()}")

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
        self._send(make_quote_cancel_msg(target_gw.upper(), symbol.upper()))
        return self._recv(f"quote.ack.{target_gw.upper()}")

    def gateway_kick(self, target_gw: str, reason: str = "") -> None:
        """
        Forcefully disconnect *target_gw*.

        The engine applies the gateway's configured ``disconnect_behaviour``
        (``LEAVE_ALL``, ``CANCEL_QUOTES_ONLY``, or ``CANCEL_ALL``).
        No ack is published.  Verify the effect with :meth:`order_list`.
        """
        self._send(make_gateway_disconnect_msg(target_gw.upper(), reason))

    # ------------------------------------------------------------------
    # Data queries
    # ------------------------------------------------------------------

    def book_depth(self, symbol: str) -> dict[str, Any]:
        """
        Request the current L1/L2 order-book snapshot for *symbol*.

        Returns
        -------
        dict with keys: ``symbol``, ``bids``, ``asks``, ``last_price``,
        ``last_qty``, ``recent_trades``.
        """
        self._send(make_book_snapshot_request_msg(symbol.upper()))
        return self._recv(f"book.{symbol.upper()}")

    def order_list(self, target_gw: str) -> list[dict[str, Any]]:
        """
        Return all resting (unfilled, non-cancelled) orders for *target_gw*
        across all symbols.
        """
        self._send(make_orders_request_msg(target_gw.upper()))
        result = self._recv(f"order.orders.{target_gw.upper()}")
        return list(result.get("orders", []))

    def symbol_list(self) -> list[str]:
        """Return the list of all symbols configured in the engine."""
        self._send(make_symbols_request_msg(self._gw_id))
        result = self._recv(f"system.symbols.{self._gw_id}")
        return list(result.get("symbols", []))

    def index_history(
        self,
        index_id: str,
        from_ts: float,
        to_ts: float,
        types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Query historical index records for one index id."""
        self._index_push.send_multipart(
            make_index_history_request_msg(
                gateway_id=self._gw_id,
                index_id=index_id.upper(),
                from_ts=from_ts,
                to_ts=to_ts,
                types=types,
            )
        )
        return self._recv(f"index.history.{self._gw_id}")

    def index_corp_action(
        self,
        index_id: str,
        action: str,
        symbol: str,
        **params: Any,
    ) -> dict[str, Any]:
        """Apply a corporate action on an index constituent."""
        self._index_push.send_multipart(
            make_index_corp_action_msg(
                action=action.upper(),
                index_id=index_id.upper(),
                symbol=symbol.upper(),
                gateway_id=self._gw_id,
                params=params,
            )
        )
        return self._recv(f"index.corp_action_ack.{self._gw_id}")

    def index_delist(self, index_id: str, symbol: str) -> dict[str, Any]:
        """Delist a symbol from an index."""
        self._index_push.send_multipart(
            make_index_constituent_change_msg(
                change_type="DELIST",
                index_id=index_id.upper(),
                symbol=symbol.upper(),
                gateway_id=self._gw_id,
            )
        )
        return self._recv(f"index.constituent_change_ack.{self._gw_id}")

    def index_add_constituent(
        self,
        index_id: str,
        symbol: str,
        shares_outstanding: int,
        initial_price: float,
    ) -> dict[str, Any]:
        """Add a constituent to an index."""
        self._index_push.send_multipart(
            make_index_constituent_change_msg(
                change_type="ADD",
                index_id=index_id.upper(),
                symbol=symbol.upper(),
                gateway_id=self._gw_id,
                shares_outstanding=shares_outstanding,
                initial_price=initial_price,
            )
        )
        return self._recv(f"index.constituent_change_ack.{self._gw_id}")

    def quote_bootstrap(self, target_gw: str, symbol: str = "") -> list[dict[str, Any]]:
        """
        Return active quote bootstrap state for *target_gw*.

        Optional *symbol* narrows the result to one instrument.
        """
        self._send(make_quote_bootstrap_request_msg(target_gw.upper(), symbol.upper()))
        result = self._recv(f"system.quote_bootstrap.{target_gw.upper()}")
        return list(result.get("quotes", []))

    # ------------------------------------------------------------------
    # Session control
    # ------------------------------------------------------------------

    def session_advance(self, to_state: str) -> dict[str, Any]:
        """
        Request a session-phase transition.

        Valid states: ``PRE_OPEN``, ``OPENING_AUCTION``, ``CONTINUOUS``,
        ``CLOSING_AUCTION``, ``CLOSED``.

        Returns the ``session.state`` broadcast confirming the transition.
        Check ``result["state"]`` to verify the transition was accepted.
        """
        self._send(make_session_transition_msg(to_state.upper()))
        return self._recv("session.state")

    def session_status(self) -> dict[str, Any]:
        """
        Return the current session state without advancing it.

        Returns
        -------
        dict with keys: ``state`` (str), ``sessions_enabled`` (bool).
        """
        self._send(make_session_state_request_msg(self._gw_id))
        return self._recv(f"system.session_status.{self._gw_id}")

    def session_schedule(self) -> dict[str, Any]:
        """
        Return the session schedule configuration from the engine config.

        Returns
        -------
        dict with keys: ``sessions_enabled`` (bool), ``schedule`` (dict of
        phase → ``HH:MM`` time strings, or empty dict if scheduling is off).
        """
        self._send(make_session_schedule_request_msg(self._gw_id))
        return self._recv(f"system.session_schedule.{self._gw_id}")

    def gateway_list(self) -> list[dict[str, Any]]:
        """
        Return all gateways configured in the engine with their connection status.

        Returns
        -------
        List of dicts with keys: ``id``, ``role``, ``description``, ``connected``.
        """
        self._send(make_gateways_request_msg(self._gw_id))
        result = self._recv(f"system.gateways.{self._gw_id}")
        return list(result.get("gateways", []))

    def volume(self) -> dict[str, Any]:
        """
        Return daily traded volume for each symbol and exchange-wide totals.

        Returns
        -------
        dict with keys:

        - ``symbols``: dict of symbol → ``{qty, value, trades}``
        - ``total_qty``: int
        - ``total_value``: float
        - ``total_trades``: int
        """
        self._send(make_volume_request_msg(self._gw_id))
        return self._recv(f"system.volume.{self._gw_id}")

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
        self._send(make_symbol_halt_msg(self._gw_id, symbol.upper()))
        return self._recv(f"risk.symbol_halt_ack.{self._gw_id}")

    def symbol_resume(self, symbol: str) -> dict[str, Any]:
        """
        Resume trading on a single *symbol* previously halted by
        :meth:`symbol_halt` or by an automatic circuit-breaker trigger.

        Requires ``role: ADMIN``.

        Returns
        -------
        dict with keys: ``accepted``, ``symbol``, ``reason``.
        """
        self._send(make_symbol_resume_msg(self._gw_id, symbol.upper()))
        return self._recv(f"risk.symbol_resume_ack.{self._gw_id}")

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
        self._send(make_cancel_symbol_msg(self._gw_id, symbol.upper()))
        return self._recv(f"risk.cancel_symbol_ack.{self._gw_id}")
