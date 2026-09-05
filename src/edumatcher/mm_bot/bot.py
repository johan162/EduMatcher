"""MMBot — state machine and event loop for the market-maker bot.

Supports quoting one symbol (today's default shape) or several symbols at
once from a single process behind a single gateway ID. See
docs-design/EduMatcher-MM-Bot-review.md §5a for the design rationale: the
engine has no per-gateway symbol limit (QuoteIndex keys quotes by
``(gateway_id, symbol)``), so multi-symbol support is purely a matter of
this bot tracking one ``_SymbolState`` per symbol instead of holding scalar
per-symbol attributes on ``self``.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import logging
import random
import signal
import time
from enum import Enum
from typing import Any

import zmq

from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.price import register_tick_decimals, to_ticks
from edumatcher.models.message import (
    decode,
    make_gateway_connect_msg,
    make_quote_bootstrap_request_msg,
    make_quote_cancel_msg,
    make_quote_legs_request_msg,
    make_quote_new_msg,
    make_symbols_request_msg,
)
from edumatcher.mm_bot.pricer import PricingStrategy, create_strategy
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.generated.session import TOPIC_SESSION_STATE
from edumatcher.models.generated.circuit_breaker import (
    topic_circuit_breaker_halt,
    topic_circuit_breaker_resume,
)
from edumatcher.models.generated.book import (
    PREFIX_BOOK_SNAPSHOT,
    topic_book_snapshot,
)
from edumatcher.models.generated.order import (
    topic_order_cancelled,
    topic_order_fill,
)
from edumatcher.models.generated.quote import (
    topic_quote_ack,
    topic_quote_status,
)
from edumatcher.models.generated.system import (
    topic_gateway_auth,
    topic_quote_bootstrap,
    topic_quote_legs,
    topic_symbols,
)

log = logging.getLogger(__name__)


class BotState(str, Enum):
    CONNECTING = "CONNECTING"
    AUTHENTICATING = "AUTHENTICATING"
    WAITING_FOR_SESSION = "WAITING_FOR_SESSION"
    QUOTING = "QUOTING"
    REPRICING = "REPRICING"
    REISSUING = "REISSUING"
    PAUSED = "PAUSED"


# Session states where quoting is allowed
_QUOTING_SESSIONS = {"CONTINUOUS"}
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0


@dataclass
class _SymbolState:
    """Everything MMBot tracks that is scoped to one symbol.

    One instance per symbol the bot quotes. A single-symbol bot (today's
    default shape) holds exactly one of these; a multi-symbol bot holds one
    per ``--symbols`` entry, each progressing through the same state machine
    independently — a fill, cancel, drift, or QLEGS divergence on one symbol
    never touches another symbol's entry.
    """

    tick_size: float = 0.01
    mm_max_spread_ticks: int | None = None
    gap: float = 0.0
    gap_was_explicit: bool = False
    pricer: PricingStrategy | None = None
    state: BotState = BotState.CONNECTING
    quote_id: str | None = None
    bid_order_id: str | None = None
    ask_order_id: str | None = None
    quoted_at_mid: float | None = None
    reissue_at: float | None = None
    last_quote_sent_at: float = 0.0
    last_qlegs_reconcile: float = 0.0
    awaiting_cancel_for_reissue: bool = False
    pending_fills: list[dict[str, Any]] = field(default_factory=list)
    # Set once the symbol has failed a startup check (§5a.4 per-symbol
    # failure isolation) so the rest of the bot can skip it without
    # crashing the whole process. None while startup is still in progress
    # or has succeeded.
    startup_failed_reason: str | None = None


class MMBot:
    """Autonomous market-maker bot for one or more symbols.

    A single ``--symbol AAPL`` invocation (or the ``symbol=`` constructor
    kwarg) behaves exactly as before this class supported multiple symbols.
    Passing ``symbols=["AAPL", "MSFT", ...]`` instead quotes all of them
    from one process behind one gateway ID — see
    docs-design/EduMatcher-MM-Bot-review.md §5a.
    """

    def __init__(
        self,
        *,
        gateway_id: str,
        symbol: str | None = None,
        symbols: list[str] | None = None,
        strategy: str,
        gap: float,
        gap_was_explicit: bool,
        qty: int,
        drift_ticks: int,
        reissue_delay_ms: int,
        tif: str,
        heartbeat_interval_sec: float,
        startup_session_timeout_sec: float,
        bootstrap_timeout_sec: float,
        cancel_timeout_sec: float,
        shutdown_timeout_sec: float,
        qlegs_reconcile_interval_sec: float,
        initial_min: float | None,
        initial_max: float | None,
        engine_pull: str,
        engine_pub: str,
        verbose: bool,
    ) -> None:
        resolved_symbols = _resolve_symbols_arg(symbol=symbol, symbols=symbols)

        self.gateway_id = gateway_id
        self.symbols = resolved_symbols
        self.strategy = strategy
        self.qty = qty
        self.drift_ticks = drift_ticks
        self.tif = tif
        self.verbose = verbose

        self._reissue_delay_sec = reissue_delay_ms / 1000.0
        self._heartbeat_interval_sec = heartbeat_interval_sec
        self._startup_session_timeout_sec = startup_session_timeout_sec
        self._bootstrap_timeout_sec = bootstrap_timeout_sec
        self._cancel_timeout_sec = cancel_timeout_sec
        self._shutdown_timeout_sec = shutdown_timeout_sec
        self._qlegs_reconcile_interval_sec = qlegs_reconcile_interval_sec
        self._initial_min = initial_min
        self._initial_max = initial_max
        self._engine_pull = engine_pull
        self._engine_pub = engine_pub

        # Runtime state
        self._running = False
        self._session_state: str | None = None
        self._last_heartbeat = time.monotonic()

        # Per-symbol state, one _SymbolState per entry in self.symbols, each
        # starting with this bot's shared gap/gap_was_explicit — a symbol's
        # own MM-obligation-derived gap (resolved during startup, see
        # _run_loop) can then diverge per symbol without affecting others.
        self._symbols_state: dict[str, _SymbolState] = {
            sym: _SymbolState(gap=gap, gap_was_explicit=gap_was_explicit)
            for sym in resolved_symbols
        }

        # Reverse lookup populated once a quote is *acked* for a symbol and
        # consulted on the matching quote.status — that topic is
        # per-gateway, not per-symbol, and its payload carries quote_id but
        # not symbol, so this is one piece of local bookkeeping a
        # single-symbol bot never needed.
        self._quote_id_to_symbol: dict[str, str] = {}

        # quote.ack is also per-gateway with no symbol in its payload — it
        # is engine's direct reply to a quote.new we just sent, before any
        # quote_id exists to key off of. The only correlation available is
        # send order: the engine acks quote.new requests on one gateway
        # connection in the order it received them, so a FIFO of "symbols
        # with a quote.new outstanding" pairs each arriving ack with the
        # right symbol. Appended in _send_quote, popped in
        # _handle_quote_ack.
        self._pending_ack_symbols: deque[str] = deque()

        self._pending_fills: list[dict[str, Any]] = []
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()

        # Sockets (created in run())
        self._push_sock: zmq.Socket[bytes] | None = None
        self._sub_sock: zmq.Socket[bytes] | None = None

    # ------------------------------------------------------------------
    # Backward-compatible single-symbol accessors
    #
    # These proxy to self._symbols_state[self._primary_symbol] — the first
    # symbol in self.symbols. Every pre-multi-symbol test, and any external
    # code, that touches bot.symbol / bot._quote_id / bot._pricer / etc.
    # directly keeps working unchanged for a bot constructed with exactly
    # one symbol, since there is only ever one entry to proxy to. Do not
    # use these from new multi-symbol-aware code — index
    # self._symbols_state[symbol] explicitly instead.
    # ------------------------------------------------------------------

    @property
    def _primary_symbol(self) -> str:
        return self.symbols[0]

    @property
    def symbol(self) -> str:
        return self._primary_symbol

    @property
    def _primary(self) -> _SymbolState:
        return self._symbols_state[self._primary_symbol]

    @property
    def gap(self) -> float:
        return self._primary.gap

    @gap.setter
    def gap(self, value: float) -> None:
        self._primary.gap = value

    @property
    def _tick_size(self) -> float:
        return self._primary.tick_size

    @_tick_size.setter
    def _tick_size(self, value: float) -> None:
        self._primary.tick_size = value

    @property
    def _mm_max_spread_ticks(self) -> int | None:
        return self._primary.mm_max_spread_ticks

    @_mm_max_spread_ticks.setter
    def _mm_max_spread_ticks(self, value: int | None) -> None:
        self._primary.mm_max_spread_ticks = value

    @property
    def _pricer(self) -> PricingStrategy | None:
        return self._primary.pricer

    @_pricer.setter
    def _pricer(self, value: PricingStrategy | None) -> None:
        self._primary.pricer = value

    @property
    def _state(self) -> BotState:
        return self._primary.state

    @_state.setter
    def _state(self, value: BotState) -> None:
        self._primary.state = value

    @property
    def _quote_id(self) -> str | None:
        return self._primary.quote_id

    @_quote_id.setter
    def _quote_id(self, value: str | None) -> None:
        self._primary.quote_id = value

    @property
    def _bid_order_id(self) -> str | None:
        return self._primary.bid_order_id

    @_bid_order_id.setter
    def _bid_order_id(self, value: str | None) -> None:
        self._primary.bid_order_id = value

    @property
    def _ask_order_id(self) -> str | None:
        return self._primary.ask_order_id

    @_ask_order_id.setter
    def _ask_order_id(self, value: str | None) -> None:
        self._primary.ask_order_id = value

    @property
    def _quoted_at_mid(self) -> float | None:
        return self._primary.quoted_at_mid

    @_quoted_at_mid.setter
    def _quoted_at_mid(self, value: float | None) -> None:
        self._primary.quoted_at_mid = value

    @property
    def _reissue_at(self) -> float | None:
        return self._primary.reissue_at

    @_reissue_at.setter
    def _reissue_at(self, value: float | None) -> None:
        self._primary.reissue_at = value

    @property
    def _last_quote_sent_at(self) -> float:
        return self._primary.last_quote_sent_at

    @_last_quote_sent_at.setter
    def _last_quote_sent_at(self, value: float) -> None:
        self._primary.last_quote_sent_at = value

    @property
    def _last_qlegs_reconcile(self) -> float:
        return self._primary.last_qlegs_reconcile

    @_last_qlegs_reconcile.setter
    def _last_qlegs_reconcile(self, value: float) -> None:
        self._primary.last_qlegs_reconcile = value

    @property
    def _awaiting_cancel_for_reissue(self) -> bool:
        return self._primary.awaiting_cancel_for_reissue

    @_awaiting_cancel_for_reissue.setter
    def _awaiting_cancel_for_reissue(self, value: bool) -> None:
        self._primary.awaiting_cancel_for_reissue = value

    # Kept as a real instance attribute (not proxied) intentionally: the
    # pre-ack fill buffer historically held fills for the *one* symbol
    # before its first quote.ack, buffered before the bot even knows which
    # _SymbolState a fill belongs to (that mapping only exists once a quote
    # has been sent — see _handle_order_fill). A multi-symbol bot buffers
    # here the same way; _process_pending_fills re-dispatches each one
    # through the normal, now symbol-aware, order_fill handling.
    @property
    def _pending_fills_compat(self) -> list[dict[str, Any]]:
        return self._pending_fills

    def _log(self, text: str) -> None:
        log.info("[%s] %s", self.gateway_id, text)

    def _debug(self, text: str) -> None:
        # verbose (-v/-vv) previously gated this via a private print() channel;
        # kept at INFO (rather than DEBUG) so -v alone still shows these, same
        # as before the print()-to-logger conversion.
        if self.verbose:
            self._log(text)

    def _dbg_count(self, key: str, amount: int = 1) -> None:
        if not self.verbose:
            return
        self._debug_counts[key] += amount
        self._flush_debug_summary()

    def _flush_debug_summary(self, force: bool = False) -> None:
        if not self.verbose:
            return
        now = time.monotonic()
        if not force and now - self._debug_last_summary < _DEBUG_SUMMARY_INTERVAL_SEC:
            return
        if not self._debug_counts:
            self._debug_last_summary = now
            return
        summary = ", ".join(
            f"{key}={value}" for key, value in sorted(self._debug_counts.items())
        )
        self._debug(f"flow summary: {summary}")
        self._debug_counts.clear()
        self._debug_last_summary = now

    def _set_state(self, symbol: str, new_state: "BotState") -> None:
        st = self._symbols_state[symbol]
        if new_state is st.state:
            return
        self._debug(f"[{symbol}] state: {st.state.value} -> {new_state.value}")
        st.state = new_state

    @staticmethod
    def _topic_family(topic: str) -> str:
        if topic.startswith(PREFIX_BOOK_SNAPSHOT):
            return "book"
        if topic.startswith("trade."):
            return "trade"
        if topic.startswith("quote."):
            return "quote"
        if topic.startswith("order."):
            return "order"
        if topic.startswith("session."):
            return "session"
        if topic.startswith("system."):
            return "system"
        if topic.startswith("circuit_breaker."):
            return "circuit_breaker"
        return "other"

    def _active_symbols(self) -> list[str]:
        """Symbols still in play — excludes any that failed startup (§5a.4)."""
        return [
            sym
            for sym, st in self._symbols_state.items()
            if st.startup_failed_reason is None
        ]

    def _setup_sockets(self) -> None:
        self._push_sock = make_pusher(self._engine_pull)
        per_symbol_topics: list[str] = []
        for sym in self.symbols:
            per_symbol_topics.append(topic_book_snapshot(sym))
            per_symbol_topics.append(topic_circuit_breaker_halt(sym))
            per_symbol_topics.append(topic_circuit_breaker_resume(sym))
        self._sub_sock = make_subscriber(
            self._engine_pub,
            topic_gateway_auth(self.gateway_id),
            topic_symbols(self.gateway_id),
            topic_quote_bootstrap(self.gateway_id),
            topic_quote_legs(self.gateway_id),
            TOPIC_TRADE_EXECUTED,
            topic_order_fill(self.gateway_id),
            topic_order_cancelled(self.gateway_id),
            topic_quote_ack(self.gateway_id),
            topic_quote_status(self.gateway_id),
            TOPIC_SESSION_STATE,
            *per_symbol_topics,
        )

    def _close_sockets(self) -> None:
        if self._push_sock:
            self._push_sock.close()
            self._push_sock = None
        if self._sub_sock:
            self._sub_sock.close()
            self._sub_sock = None

    def _send(self, frames: list[bytes]) -> None:
        if self._push_sock:
            self._push_sock.send_multipart(frames)
            self._dbg_count("outgoing_total")
            if frames:
                topic = frames[0].decode("utf-8", errors="replace")
                self._dbg_count(f"outgoing_topic_{self._topic_family(topic)}")

    def _authenticate(self, timeout_sec: float = 3.0) -> bool:
        """Send gateway_connect and wait for auth ACK."""
        assert self._sub_sock is not None
        time.sleep(0.05)
        self._send(make_gateway_connect_msg(self.gateway_id))
        for sym in self.symbols:
            self._set_state(sym, BotState.AUTHENTICATING)

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 200)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == topic_gateway_auth(self.gateway_id):
                accepted = bool(payload.get("accepted", False))
                if accepted:
                    self._log("authenticated")
                else:
                    reason = str(payload.get("reason", "unknown"))
                    self._log(f"auth rejected: {reason}")
                return accepted
            # Also capture session.state that arrives during auth
            if topic == TOPIC_SESSION_STATE:
                self._session_state = str(payload.get("state", "")).upper()
                self._debug(f"session state (during auth): {self._session_state}")

        self._log("authentication timed out")
        return False

    def _request_symbols(self, timeout_sec: float = 3.0) -> list[str]:
        """Request symbol list and register tick/MM-obligation metadata.

        Registers metadata for every symbol this bot quotes that appears in
        the reply. A symbol that never appears is left for the startup
        sequence to fail closed on (single-symbol: whole-process failure,
        same as before; multi-symbol: that one symbol excluded — see
        _run_loop and §5a.4).
        """
        assert self._sub_sock is not None
        self._send(make_symbols_request_msg(self.gateway_id))

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 200)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == topic_symbols(self.gateway_id):
                entries = payload.get("symbols", [])
                symbols = [str(e.get("symbol", "")).upper() for e in entries]
                self._debug(f"symbols received: {symbols}")
                for meta in entries:
                    meta_symbol = str(meta.get("symbol", "")).upper()
                    st = self._symbols_state.get(meta_symbol)
                    if st is None:
                        continue
                    if "tick_decimals" in meta:
                        tick_decimals = int(meta["tick_decimals"])
                        st.tick_size = 10**-tick_decimals
                        register_tick_decimals(meta_symbol, tick_decimals)
                    if "mm_max_spread_ticks" in meta:
                        try:
                            st.mm_max_spread_ticks = int(meta["mm_max_spread_ticks"])
                        except (TypeError, ValueError):
                            st.mm_max_spread_ticks = None
                return symbols
            if topic == TOPIC_SESSION_STATE:
                self._session_state = str(payload.get("state", "")).upper()

        self._log("symbols request timed out")
        return []

    def _request_bootstrap(self, symbol: str | None = None) -> dict[str, Any] | None:
        """Request QBOOT for one symbol and wait for reply within timeout."""
        symbol = symbol if symbol is not None else self._primary_symbol
        assert self._sub_sock is not None
        self._send(make_quote_bootstrap_request_msg(self.gateway_id, symbol))

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + self._bootstrap_timeout_sec

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 100)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == topic_quote_bootstrap(self.gateway_id):
                return payload
            # Capture other events during wait
            self._buffer_event(topic, payload)

        self._debug(f"[{symbol}] QBOOT request timed out — continuing with fallback")
        return None

    def _request_qlegs(self, symbol: str | None = None) -> dict[str, Any] | None:
        """Request QLEGS snapshot for one symbol and wait for reply."""
        symbol = symbol if symbol is not None else self._primary_symbol
        assert self._sub_sock is not None
        self._send(make_quote_legs_request_msg(self.gateway_id, symbol, "ALL"))

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + self._bootstrap_timeout_sec

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 100)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == topic_quote_legs(self.gateway_id):
                return payload
            self._buffer_event(topic, payload)

        self._debug(f"[{symbol}] QLEGS request timed out")
        return None

    def _buffer_event(self, topic: str, payload: dict[str, Any]) -> None:
        """Buffer events received during startup waits."""
        if topic == TOPIC_SESSION_STATE:
            self._session_state = str(payload.get("state", "")).upper()
            return
        for sym in self.symbols:
            if topic == topic_book_snapshot(sym):
                self._handle_book(payload, symbol=sym)
                return
        if topic == TOPIC_TRADE_EXECUTED:
            self._handle_trade(payload)

    def _try_adopt_from_bootstrap(
        self, symbol: str, boot_payload: dict[str, Any] | None
    ) -> bool:
        """Try to adopt an active quote from QBOOT. Returns True if adopted."""
        if not boot_payload:
            return False
        st = self._symbols_state[symbol]
        assert st.pricer is not None

        quotes = boot_payload.get("quotes", [])
        for q in quotes:
            if (
                str(q.get("symbol", "")).upper() == symbol
                and str(q.get("state", "")).upper() == "ACTIVE"
            ):
                st.quote_id = str(q.get("quote_id", ""))
                st.bid_order_id = str(q.get("bid_order_id", ""))
                st.ask_order_id = str(q.get("ask_order_id", ""))
                if st.quote_id:
                    self._quote_id_to_symbol[st.quote_id] = symbol
                bid_price = q.get("bid_price")
                ask_price = q.get("ask_price")
                if bid_price is not None and ask_price is not None:
                    mid = (float(bid_price) + float(ask_price)) / 2.0
                    st.pricer.set_mid(mid)
                    st.quoted_at_mid = mid
                    self._log(
                        f"[{symbol}] adopted existing quote {st.quote_id} "
                        f"bid={bid_price} ask={ask_price}"
                    )
                    return True
        return False

    def _resolve_bootstrap_reference(
        self, boot_payload: dict[str, Any] | None, symbol: str | None = None
    ) -> bool:
        """Resolve initial reference price (non-adopt). Returns True if resolved."""
        symbol = symbol if symbol is not None else self._primary_symbol
        st = self._symbols_state[symbol]
        assert st.pricer is not None

        # 1. Book- or trade-derived mid. Book updates and trade.executed events
        #    received during startup waits already set the mid via the handlers,
        #    so any existing mid covers both the book and last-trade fallbacks.
        if st.pricer.mid_price is not None:
            self._debug(f"[{symbol}] reference from book/trade: {st.pricer.mid_price}")
            return True

        # 2. QBOOT inactive quote prices as reference
        if boot_payload:
            quotes = boot_payload.get("quotes", [])
            for q in quotes:
                if str(q.get("symbol", "")).upper() == symbol:
                    bid_price = q.get("bid_price")
                    ask_price = q.get("ask_price")
                    if bid_price is not None and ask_price is not None:
                        mid = (float(bid_price) + float(ask_price)) / 2.0
                        st.pricer.set_mid(mid)
                        self._debug(f"[{symbol}] reference from bootstrap quote: {mid}")
                        return True

        # 3. Random bootstrap range
        if self._initial_min is not None and self._initial_max is not None:
            price = random.uniform(self._initial_min, self._initial_max)
            # Round to nearest tick
            price = round(
                round(price / st.tick_size) * st.tick_size,
                st.pricer.price_decimals,
            )
            st.pricer.set_mid(price)
            self._log(f"[{symbol}] bootstrap from random range: {price}")
            return True

        return False

    def _wait_for_session(self, timeout_sec: float) -> bool:
        """Wait for first session.state event. Returns True if received."""
        if self._session_state is not None:
            return True

        assert self._sub_sock is not None
        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 200)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == TOPIC_SESSION_STATE:
                self._session_state = str(payload.get("state", "")).upper()
                return True
            self._buffer_event(topic, payload)

        return False

    def _send_quote(self, symbol: str | None = None) -> None:
        """Compute prices and send a fresh quote for one symbol."""
        symbol = symbol if symbol is not None else self._primary_symbol
        st = self._symbols_state[symbol]
        assert st.pricer is not None
        if st.pricer.mid_price is None:
            self._debug(f"[{symbol}] cannot send quote — no mid price")
            return

        bid, ask = st.pricer.compute_prices()
        quote_payload: dict[str, Any] = {
            "gateway_id": self.gateway_id,
            "symbol": symbol,
            # The pricer works in display money; the wire carries ticks
            # (design section 15.2, quotes joined in 6.1b).
            "bid_price": to_ticks(bid, symbol),
            "ask_price": to_ticks(ask, symbol),
            "bid_qty": self.qty,
            "ask_qty": self.qty,
            "tif": self.tif,
        }
        self._send(make_quote_new_msg(quote_payload))
        st.quoted_at_mid = st.pricer.mid_price
        st.last_quote_sent_at = time.monotonic()
        self._set_state(symbol, BotState.REISSUING)
        self._pending_ack_symbols.append(symbol)
        self._debug(f"[{symbol}] QUOTE sent bid={bid} ask={ask}")

    def _cancel_quote(self, symbol: str) -> None:
        """Send quote.cancel for one symbol."""
        self._send(make_quote_cancel_msg(self.gateway_id, symbol))
        self._debug(f"[{symbol}] CANCEL sent")

    def _clear_quote_state(self, symbol: str) -> None:
        """Forget the locally tracked quote and its leg identifiers."""
        st = self._symbols_state[symbol]
        if st.quote_id is not None:
            self._quote_id_to_symbol.pop(st.quote_id, None)
        st.quote_id = None
        st.bid_order_id = None
        st.ask_order_id = None

    def _cancel_and_reissue(self, symbol: str | None = None) -> None:
        """Replace one symbol's active quote with a fresh one at current mid."""
        symbol = symbol if symbol is not None else self._primary_symbol
        st = self._symbols_state[symbol]
        if st.quote_id is not None:
            if st.awaiting_cancel_for_reissue:
                return
            self._cancel_quote(symbol)
            st.awaiting_cancel_for_reissue = True
            st.reissue_at = time.monotonic() + self._cancel_timeout_sec
            self._set_state(symbol, BotState.REPRICING)
            return
        self._send_quote(symbol)

    # ------------------------------------------------------------------
    # Event handlers
    #
    # Handlers for per-symbol topics (book, circuit breaker) take an
    # explicit `symbol` — the caller (usually _dispatch) already knows it
    # from the topic string. Handlers for per-gateway topics (quote/order
    # events) resolve which symbol they're about from the payload
    # (order_fill/order_cancelled carry `symbol` directly; quote_ack/status
    # only carry `quote_id`, resolved via _quote_id_to_symbol).
    # ------------------------------------------------------------------

    def _handle_book(self, payload: dict[str, Any], symbol: str | None = None) -> None:
        """Handle book.SYMBOL event."""
        symbol = symbol if symbol is not None else self._primary_symbol
        st = self._symbols_state.get(symbol)
        if st is None or st.pricer is None:
            return
        bids = payload.get("bids", [])
        asks = payload.get("asks", [])
        best_bid_raw = bids[0].get("price") if bids else None
        best_ask_raw = asks[0].get("price") if asks else None
        best_bid = float(best_bid_raw) if best_bid_raw is not None else None
        best_ask = float(best_ask_raw) if best_ask_raw is not None else None
        st.pricer.update_mid(best_bid, best_ask)
        self._debug(f"[{symbol}] book mid={st.pricer.mid_price}")

    def _handle_trade(self, payload: dict[str, Any]) -> None:
        """Handle trade.executed — update mid if no book data."""
        symbol = str(payload.get("symbol", "")).upper()
        st = self._symbols_state.get(symbol)
        if st is None or st.pricer is None:
            return
        price = payload.get("price")
        if price is not None and st.pricer.mid_price is None:
            st.pricer.set_mid(float(price))
            self._debug(f"[{symbol}] mid from trade: {price}")

    def _handle_quote_ack(self, payload: dict[str, Any]) -> None:
        """Handle quote.ack — record IDs or handle rejection.

        quote.ack carries no `symbol` (only quote_id/accepted/reason/
        bid_order_id/ask_order_id) and, being the *first* reply to a fresh
        quote.new, arrives before any quote_id is known to key off of. It
        is matched to a symbol via the send-order FIFO populated in
        _send_quote — see _pending_ack_symbols.
        """
        symbol = (
            self._pending_ack_symbols.popleft()
            if self._pending_ack_symbols
            else self._primary_symbol
        )
        st = self._symbols_state.get(symbol)
        if st is None:
            return
        accepted = bool(payload.get("accepted", False))
        if accepted:
            st.quote_id = str(payload.get("quote_id", ""))
            st.bid_order_id = str(payload.get("bid_order_id", ""))
            st.ask_order_id = str(payload.get("ask_order_id", ""))
            if st.quote_id:
                self._quote_id_to_symbol[st.quote_id] = symbol
            self._set_state(symbol, BotState.QUOTING)
            self._debug(f"[{symbol}] quote ACK id={st.quote_id}")
            # Process buffered fills
            self._process_pending_fills()
        else:
            reason = str(payload.get("reason", "unknown"))
            self._log(f"[{symbol}] quote REJECTED: {reason}")
            # Retry after delay
            st.reissue_at = time.monotonic() + self._reissue_delay_sec

    def _handle_quote_status(self, payload: dict[str, Any]) -> None:
        """Handle quote.status — detect INACTIVE/CANCELLED.

        Resolved via quote_id (the payload carries no `symbol`), falling
        back to the primary symbol if the quote_id is unknown — this
        mirrors the single-symbol bot's original behavior when a test
        drives this handler directly without going through quote.ack first
        (see the backward-compatible accessors above).
        """
        quote_id = str(payload.get("quote_id", ""))
        symbol = self._quote_id_to_symbol.get(quote_id, self._primary_symbol)
        st = self._symbols_state.get(symbol)
        if st is None:
            return

        status = str(payload.get("status", "")).upper()
        self._debug(f"[{symbol}] quote.status: {status}")

        if st.state in (BotState.PAUSED, BotState.WAITING_FOR_SESSION):
            return

        if status in ("INACTIVE_BID_FILLED", "INACTIVE_ASK_FILLED"):
            # Engine inactivated the quote; schedule fresh reissue.
            st.reissue_at = time.monotonic() + self._reissue_delay_sec
            self._clear_quote_state(symbol)
            if st.awaiting_cancel_for_reissue:
                self._debug(
                    f"[{symbol}] awaiting_cancel_for_reissue: True -> False "
                    "(inactivated)"
                )
            st.awaiting_cancel_for_reissue = False

        elif status == "CANCELLED":
            # Only reissue for CANCELLED if we still track a quote or are
            # awaiting cancel confirmation.  A stale CANCELLED that arrives
            # after an INACTIVE we already handled must be ignored to prevent
            # a duplicate reissue.
            if st.quote_id is not None or st.awaiting_cancel_for_reissue:
                st.reissue_at = time.monotonic()  # immediate
                self._clear_quote_state(symbol)
                if st.awaiting_cancel_for_reissue:
                    self._debug(
                        f"[{symbol}] awaiting_cancel_for_reissue: True -> False "
                        "(cancelled)"
                    )
                st.awaiting_cancel_for_reissue = False

    def _handle_order_fill(self, payload: dict[str, Any]) -> None:
        """Handle order.fill — check if it belongs to one of our quotes."""
        order_id = str(payload.get("order_id", ""))

        symbol = self._symbol_for_order_id(order_id)
        if symbol is None:
            # If nothing has acked yet anywhere, buffer the fill the same
            # way the single-symbol bot always did — we don't yet know
            # which symbol's leg this is.
            if not any(
                st.bid_order_id is not None or st.ask_order_id is not None
                for st in self._symbols_state.values()
            ):
                self._pending_fills.append(payload)
            return  # not a leg we recognise (or not yet)

        st = self._symbols_state[symbol]
        side = "BID" if order_id == st.bid_order_id else "ASK"
        fill_qty = payload.get("fill_qty", 0)
        self._debug(
            f"[{symbol}] fill: {side} {fill_qty}@{payload.get('fill_price', '?')}"
        )

        # Reset or start the reissue timer — but only when no cancel is already
        # in flight.  Overwriting the cancel-confirmation timeout with a shorter
        # fill-delay would lose the timeout if the cancel ACK never arrives,
        # leaving the bot stuck in REPRICING with no recovery timer.
        if not st.awaiting_cancel_for_reissue:
            st.reissue_at = time.monotonic() + self._reissue_delay_sec

    def _symbol_for_order_id(self, order_id: str) -> str | None:
        for sym, st in self._symbols_state.items():
            if order_id in (st.bid_order_id, st.ask_order_id):
                return sym
        return None

    def _handle_order_cancelled(self, payload: dict[str, Any]) -> None:
        """Handle order.cancelled — track leg cleanup."""
        order_id = str(payload.get("order_id", ""))
        symbol = self._symbol_for_order_id(order_id)
        if symbol is not None:
            self._debug(f"[{symbol}] leg cancelled: {order_id}")

    def _handle_session_state(self, payload: dict[str, Any]) -> None:
        """Handle session.state transitions — applies to every symbol."""
        new_state = str(payload.get("state", "")).upper()
        old_state = self._session_state
        self._session_state = new_state
        self._debug(f"session: {old_state} -> {new_state}")

        for symbol in self._active_symbols():
            st = self._symbols_state[symbol]
            if new_state in _QUOTING_SESSIONS:
                if st.state == BotState.PAUSED:
                    self._set_state(symbol, BotState.WAITING_FOR_SESSION)
                    # Trigger reissue if we have reference
                    if st.pricer and st.pricer.mid_price is not None:
                        st.reissue_at = time.monotonic()
            else:
                # Non-trading phase — cancel and pause
                if st.state in (BotState.QUOTING, BotState.REPRICING):
                    self._cancel_quote(symbol)
                    self._clear_quote_state(symbol)
                self._set_state(symbol, BotState.PAUSED)
                st.reissue_at = None

    def _handle_circuit_breaker_halt(self, symbol: str | None = None) -> None:
        """Handle circuit_breaker.halt.SYMBOL for one symbol."""
        symbol = symbol if symbol is not None else self._primary_symbol
        self._log(f"[{symbol}] circuit breaker HALT")
        st = self._symbols_state.get(symbol)
        if st is None:
            return
        if st.state in (BotState.QUOTING, BotState.REPRICING, BotState.REISSUING):
            self._cancel_quote(symbol)
            self._clear_quote_state(symbol)
        self._set_state(symbol, BotState.PAUSED)
        st.reissue_at = None

    def _handle_circuit_breaker_resume(self, symbol: str | None = None) -> None:
        """Handle circuit_breaker.resume.SYMBOL for one symbol."""
        symbol = symbol if symbol is not None else self._primary_symbol
        self._log(f"[{symbol}] circuit breaker RESUME")
        if symbol in self._symbols_state:
            self._set_state(symbol, BotState.WAITING_FOR_SESSION)

    def _process_pending_fills(self) -> None:
        """Process fills that arrived before any quote.ack."""
        pending, self._pending_fills = self._pending_fills, []
        for fill in pending:
            self._handle_order_fill(fill)

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------

    def _dispatch(self, topic: str, payload: dict[str, Any]) -> None:
        """Route an incoming message to the appropriate handler."""
        self._dbg_count("incoming_total")
        self._dbg_count(f"incoming_topic_{self._topic_family(topic)}")

        book_symbol = self._symbol_for_book_topic(topic)
        if book_symbol is not None:
            self._handle_book(payload, symbol=book_symbol)
            st = self._symbols_state[book_symbol]
            # Check drift while quoting
            if (
                st.state == BotState.QUOTING
                and st.pricer
                and st.quoted_at_mid is not None
                and st.pricer.has_drifted(st.quoted_at_mid)
            ):
                self._debug(f"[{book_symbol}] drift detected — repricing")
                self._set_state(book_symbol, BotState.REPRICING)
                self._cancel_and_reissue(book_symbol)
            return

        halt_symbol = self._symbol_for_topic(topic, topic_circuit_breaker_halt)
        if halt_symbol is not None:
            self._handle_circuit_breaker_halt(halt_symbol)
            return

        resume_symbol = self._symbol_for_topic(topic, topic_circuit_breaker_resume)
        if resume_symbol is not None:
            self._handle_circuit_breaker_resume(resume_symbol)
            return

        if topic == TOPIC_TRADE_EXECUTED:
            self._handle_trade(payload)
        elif topic == topic_quote_ack(self.gateway_id):
            self._handle_quote_ack(payload)
        elif topic == topic_quote_status(self.gateway_id):
            self._handle_quote_status(payload)
        elif topic == topic_order_fill(self.gateway_id):
            self._handle_order_fill(payload)
        elif topic == topic_order_cancelled(self.gateway_id):
            self._handle_order_cancelled(payload)
        elif topic == TOPIC_SESSION_STATE:
            self._handle_session_state(payload)
        elif topic == topic_quote_legs(self.gateway_id):
            self._reconcile_qlegs(payload)
        else:
            self._dbg_count("incoming_unhandled")

    def _symbol_for_book_topic(self, topic: str) -> str | None:
        for sym in self.symbols:
            if topic == topic_book_snapshot(sym):
                return sym
        return None

    def _symbol_for_topic(self, topic: str, topic_fn: Any) -> str | None:
        for sym in self.symbols:
            if topic == topic_fn(sym):
                return sym
        return None

    def _tick(self) -> None:
        """Periodic housekeeping — reissue timer, heartbeat, QLEGS. Runs
        independently for every symbol still active (§5a.4)."""
        now = time.monotonic()
        self._dbg_count("tick_calls")

        for symbol in self._active_symbols():
            self._tick_symbol(symbol, now)

    def _tick_symbol(self, symbol: str, now: float) -> None:
        st = self._symbols_state[symbol]

        # Reissue timer
        if st.reissue_at is not None and now >= st.reissue_at:
            st.reissue_at = None
            if st.state in (
                BotState.QUOTING,
                BotState.REPRICING,
                BotState.REISSUING,
                BotState.WAITING_FOR_SESSION,
            ):
                if (
                    self._session_state in _QUOTING_SESSIONS
                    and st.pricer
                    and st.pricer.mid_price is not None
                ):
                    if st.state == BotState.REPRICING and st.quote_id is not None:
                        self._log(
                            f"[{symbol}] cancel confirmation timeout — forcing "
                            "quote replacement"
                        )
                        self._clear_quote_state(symbol)
                        st.awaiting_cancel_for_reissue = False
                    self._cancel_and_reissue(symbol)
                elif st.state == BotState.WAITING_FOR_SESSION:
                    pass  # wait for session
                else:
                    self._set_state(symbol, BotState.WAITING_FOR_SESSION)

        # Heartbeat guard — recover if we are in an active state but hold no
        # live quote and have no reissue already scheduled. This covers a
        # dropped quote.ack that would otherwise strand the bot in REISSUING.
        # Require a full heartbeat interval since the last quote send so we do
        # not pre-empt an ack that is legitimately still in flight.
        #
        # The heartbeat clock itself stays gateway-wide (a single
        # `_last_heartbeat`), matching the original single-symbol cadence;
        # only the "is there a live quote" check below is per symbol.
        if now - self._last_heartbeat >= self._heartbeat_interval_sec:
            if (
                st.state in (BotState.QUOTING, BotState.REISSUING, BotState.REPRICING)
                and st.quote_id is None
                and st.reissue_at is None
                and now - st.last_quote_sent_at >= self._heartbeat_interval_sec
                and self._session_state in _QUOTING_SESSIONS
                and st.pricer
                and st.pricer.mid_price is not None
            ):
                self._log(f"[{symbol}] heartbeat: no active quote — reissuing")
                self._dbg_count("heartbeat_reissues")
                self._cancel_and_reissue(symbol)

        # Periodic QLEGS reconciliation — request only (non-blocking). The
        # reply is handled in _dispatch so steady-state fills/status events
        # are never dropped while waiting for the snapshot.
        if now - st.last_qlegs_reconcile >= self._qlegs_reconcile_interval_sec:
            st.last_qlegs_reconcile = now
            if st.state == BotState.QUOTING and st.quote_id is not None:
                self._send(make_quote_legs_request_msg(self.gateway_id, symbol, "ALL"))
                self._dbg_count("qlegs_reconcile_requests")

        if symbol == self._primary_symbol and (
            now - self._last_heartbeat >= self._heartbeat_interval_sec
        ):
            self._last_heartbeat = now

    def _reconcile_qlegs(self, payload: dict[str, Any]) -> None:
        """Reconcile a QLEGS snapshot against local quote state.

        QLEGS replies carry `symbol` on each leg but the request itself was
        for one symbol, so every leg in a reply belongs to the same symbol
        — resolved from the first leg present, falling back to the primary
        symbol for a reply with no legs (mirrors the single-symbol bot's
        original "no legs but we think we have a quote" mismatch check,
        which otherwise has nothing to resolve a symbol from).

        Only acts while actively quoting a tracked quote for that symbol; a
        divergence clears local state and schedules an immediate reissue.
        Reconciles against ``legs`` (the currently-active set) only —
        ``recent`` (the engine's bounded inactivation history, present when
        ``show=ALL``) is informational and not used for reconciliation.
        """
        legs = payload.get("legs", [])
        if legs:
            symbol = str(legs[0].get("symbol", "")).upper() or self._primary_symbol
        else:
            symbol = self._primary_symbol
        st = self._symbols_state.get(symbol)
        if st is None or st.state != BotState.QUOTING or st.quote_id is None:
            return

        if not payload.get("complete", True):
            self._debug(f"[{symbol}] QLEGS reply marked incomplete by engine")

        if not legs:
            # Engine says no legs but we think we have a quote
            self._log(
                f"[{symbol}] QLEGS mismatch: no legs but local quote exists — "
                "reissuing"
            )
            self._clear_quote_state(symbol)
            st.reissue_at = time.monotonic()
            return

        # Check if our IDs match
        seen_order_ids: set[str] = set()
        for leg in legs:
            leg_qid = str(leg.get("quote_id", ""))
            leg_order_id = str(leg.get("order_id", ""))
            if leg_qid and st.quote_id and leg_qid != st.quote_id:
                self._log(f"[{symbol}] QLEGS mismatch: quote_id divergence — reissuing")
                self._clear_quote_state(symbol)
                st.reissue_at = time.monotonic()
                return
            if leg_order_id:
                seen_order_ids.add(leg_order_id)

        expected_order_ids = {oid for oid in (st.bid_order_id, st.ask_order_id) if oid}
        if (
            expected_order_ids
            and seen_order_ids
            and expected_order_ids != seen_order_ids
        ):
            self._log(f"[{symbol}] QLEGS mismatch: leg order_id divergence — reissuing")
            self._clear_quote_state(symbol)
            st.reissue_at = time.monotonic()
            return

    def run(self) -> int:
        """Run the bot event loop. Returns exit code."""
        self._log(
            f"starting: symbols={','.join(self.symbols)} strategy={self.strategy} "
            f"gap={self.gap} qty={self.qty} "
            f"tif={self.tif} drift_ticks={self.drift_ticks}"
        )
        self._setup_sockets()
        self._running = True

        # Install signal handlers
        def _sig_handler(signum: int, frame: Any) -> None:
            self._running = False

        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)

        try:
            return self._run_loop()
        finally:
            self._close_sockets()

    def _run_loop(self) -> int:
        """Internal event loop."""
        # Step 1: Authenticate (gateway-wide — one auth covers every symbol)
        if not self._authenticate():
            self._log("startup failed: authentication")
            return 1

        # Step 2: Request symbols (registers tick/MM-obligation metadata for
        # every symbol found in the reply)
        symbols_seen = self._request_symbols()

        # Steps 3-5, per symbol: gap validation, pricer creation, QBOOT/QLEGS.
        # A symbol that fails any of these is excluded from the rest of the
        # run (§5a.4 per-symbol failure isolation) rather than failing the
        # whole process — unless it is the *only* symbol, in which case
        # failing it is exactly the original single-symbol failure behavior.
        for symbol in list(self.symbols):
            self._startup_one_symbol(symbol, symbols_seen)

        active = self._active_symbols()
        if not active:
            self._log("startup failed: no symbol survived startup checks")
            return 1
        for symbol in self.symbols:
            if symbol not in active:
                st = self._symbols_state[symbol]
                self._log(
                    f"[{symbol}] excluded from quoting: {st.startup_failed_reason}"
                )

        # Step 6: Wait for session state (gateway-wide)
        if not self._wait_for_session(self._startup_session_timeout_sec):
            self._log("startup failed: no session.state received within timeout")
            return 1

        # Step 7: Determine initial state, per active symbol. This can
        # exclude a symbol too (no reference price available anywhere) —
        # recompute the active set afterwards and, same as after steps 3-5,
        # fail the whole process if nothing survived.
        for symbol in active:
            self._resolve_initial_state(symbol)

        active = self._active_symbols()
        if not active:
            self._log("startup failed: no symbol survived startup checks")
            return 1

        self._log(f"running symbols={active} session={self._session_state}")
        self._last_heartbeat = time.monotonic()
        for symbol in active:
            self._symbols_state[symbol].last_qlegs_reconcile = time.monotonic()

        # Main event loop
        assert self._sub_sock is not None
        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        # Poll at half the shortest timing interval so the reissue/heartbeat
        # timers fire promptly, with a 50 ms floor to avoid a busy loop.
        shortest_interval_sec = min(
            self._heartbeat_interval_sec, self._reissue_delay_sec
        )
        poll_timeout_ms = max(50, int(shortest_interval_sec * 1000 / 2))

        while self._running:
            socks = dict(poller.poll(timeout=poll_timeout_ms))
            if self._sub_sock in socks:
                topic, payload = decode(self._sub_sock.recv_multipart())
                self._dispatch(topic, payload)
            self._tick()

        # Shutdown
        self._flush_debug_summary(force=True)
        self._do_shutdown()
        return 0

    def _startup_one_symbol(self, symbol: str, symbols_seen: list[str]) -> None:
        st = self._symbols_state[symbol]

        if symbols_seen and symbol not in symbols_seen:
            st.startup_failed_reason = f"{symbol} not in symbol list"
            self._log(f"[{symbol}] startup failed: not in symbol list")
            return

        # Derive or validate gap against symbol MM spread obligation when
        # available.
        if st.mm_max_spread_ticks is not None:
            if not st.gap_was_explicit:
                st.gap = (st.mm_max_spread_ticks / 2.0) * st.tick_size
                self._log(
                    f"[{symbol}] gap defaulted from MM obligation: {st.gap:.6f} "
                    f"(max_spread_ticks={st.mm_max_spread_ticks})"
                )
            if st.gap > st.mm_max_spread_ticks * st.tick_size:
                st.startup_failed_reason = (
                    f"--gap exceeds mm_max_spread_ticks obligation "
                    f"({st.gap:.6f} > {st.mm_max_spread_ticks} * {st.tick_size:.6f})"
                )
                self._log(f"[{symbol}] startup failed: {st.startup_failed_reason}")
                return

        # Initialize pricing strategy
        try:
            st.pricer = create_strategy(
                self.strategy,
                tick_size=st.tick_size,
                gap=st.gap,
                drift_ticks=self.drift_ticks,
            )
        except ValueError as exc:
            st.startup_failed_reason = f"invalid strategy/gap/tick configuration: {exc}"
            self._log(f"[{symbol}] startup failed: {st.startup_failed_reason}")
            return

        # QBOOT — try adoption
        boot_payload = self._request_bootstrap(symbol)
        self._try_adopt_from_bootstrap(symbol, boot_payload)

        # QLEGS reconciliation
        qlegs_payload = self._request_qlegs(symbol)
        if qlegs_payload and st.quote_id:
            legs = qlegs_payload.get("legs", [])
            if legs:
                for leg in legs:
                    if str(leg.get("quote_id", "")) != st.quote_id:
                        self._log(
                            f"[{symbol}] startup QLEGS mismatch — clearing "
                            "adopted state"
                        )
                        self._clear_quote_state(symbol)
                        break

        # Stash the resolved boot_payload for the initial-state step so we
        # don't have to re-request QBOOT — resolved lazily via a private
        # attribute since dataclass fields are typed narrowly above.
        self._boot_payloads = getattr(self, "_boot_payloads", {})
        self._boot_payloads[symbol] = boot_payload

    def _resolve_initial_state(self, symbol: str) -> None:
        st = self._symbols_state[symbol]
        boot_payload = getattr(self, "_boot_payloads", {}).get(symbol)
        has_adopted = st.quote_id is not None
        if has_adopted:
            if self._session_state in _QUOTING_SESSIONS:
                st.state = BotState.QUOTING
            else:
                st.state = BotState.PAUSED
        else:
            resolved = self._resolve_bootstrap_reference(boot_payload, symbol=symbol)
            if not resolved:
                st.startup_failed_reason = (
                    "no reference price available "
                    "(no book, no trade, no bootstrap, no random range)"
                )
                self._log(f"[{symbol}] startup failed: {st.startup_failed_reason}")
                return
            if self._session_state in _QUOTING_SESSIONS:
                st.state = BotState.WAITING_FOR_SESSION
                self._send_quote(symbol)
            else:
                st.state = BotState.PAUSED

    def _do_shutdown(self) -> None:
        """Send cancel for every symbol still quoting and wait for
        confirmation (bounded by one shared shutdown timeout, same as the
        original single-symbol behavior)."""
        active = self._active_symbols()
        quoting = [
            sym
            for sym in active
            if self._symbols_state[sym].state
            in (BotState.QUOTING, BotState.REPRICING, BotState.REISSUING)
        ]
        for sym in quoting:
            self._cancel_quote(sym)

        if quoting and self._sub_sock:
            pending = set(quoting)
            poller = zmq.Poller()
            poller.register(self._sub_sock, zmq.POLLIN)
            deadline = time.monotonic() + self._shutdown_timeout_sec
            while time.monotonic() < deadline and pending:
                remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                socks = dict(poller.poll(timeout=min(remaining_ms, 100)))
                if self._sub_sock in socks:
                    topic, payload = decode(self._sub_sock.recv_multipart())
                    if topic == topic_quote_status(self.gateway_id):
                        quote_id = str(payload.get("quote_id", ""))
                        confirmed_sym = self._quote_id_to_symbol.get(quote_id)
                        if confirmed_sym is not None and confirmed_sym in pending:
                            pending.discard(confirmed_sym)
                            self._debug(f"[{confirmed_sym}] shutdown: cancel confirmed")
                self._flush_debug_summary(force=True)
        self._log("shutdown complete")

    def shutdown(self) -> None:
        """External shutdown trigger."""
        self._running = False


def _resolve_symbols_arg(*, symbol: str | None, symbols: list[str] | None) -> list[str]:
    """Normalize the symbol/symbols constructor kwargs to one clean list.

    Exactly one of ``symbol`` (legacy singular) or ``symbols`` (plural) is
    expected to carry real content; both may not be given non-empty values
    at once, and at least one must be.
    """
    if symbols:
        seen: dict[str, None] = {}
        for s in symbols:
            s = s.strip().upper()
            if s:
                seen[s] = None
        resolved = list(seen)
        if not resolved:
            raise ValueError("symbols must contain at least one non-empty entry")
        if symbol and symbol.strip().upper() not in resolved:
            raise ValueError(
                f"symbol={symbol!r} was also given but is not in symbols={symbols!r}"
            )
        return resolved
    if symbol and symbol.strip():
        return [symbol.strip().upper()]
    raise ValueError("MMBot requires either symbol= or a non-empty symbols=")
