"""
Matching Engine — main process.

Startup:
  poetry run pm-engine [-v|-vv] [--config engine_config.yaml] [--log-level LEVEL] [-q]

ZMQ sockets:
  PULL :5555  — receives order.new / order.amend / order.cancel from gateways
  PUB  :5556  — broadcasts order.ack, order.fill, order.amended, order.cancelled,
                order.expired, trade.executed, book.{SYMBOL}

Shutdown (SIGINT / Ctrl-C):
  1. Save resting GTC orders to data/gtc_orders.json
  2. Publish order.expired for all resting DAY orders
  3. Clean ZMQ teardown
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any, Optional

import zmq

from edumatcher.config import (
    ENGINE_PULL_ADDR,
    ENGINE_PUB_ADDR,
    GTC_ORDERS_FILE,
    GTC_COMBOS_FILE,
    BOOK_STATS_FILE,
    ENGINE_CONFIG_FILE,
    DATA_DIR,
)
from edumatcher.engine.auction import (
    compute_equilibrium,
    execute_uncross,
)
from edumatcher.cli_version import add_version_argument
from edumatcher.engine.circuit_breaker import CircuitBreakerState
from edumatcher.engine.collar import CollarConfig, validate_collar
from edumatcher.engine.config_loader import EngineConfig, load_engine_config
from edumatcher.engine.drop_copy import DropCopyPublisher
from edumatcher.engine.order_book import OrderBook
from edumatcher.engine.persistence import (
    load_gtc_orders,
    save_gtc_orders,
    load_book_stats,
    save_book_stats,
    load_gtc_combos,
    save_gtc_combos,
)
from edumatcher.messaging.bus import make_puller, make_publisher
from edumatcher.models.combo import ComboOrder, ComboStatus, ComboType
from edumatcher.models.clock import now_ns
from edumatcher.models.message import (
    dumps,
    decode,
    encode,
    make_ack_msg,
    make_amended_msg,
    make_book_msg,
    make_cancelled_msg,
    make_combo_ack_msg,
    make_combo_status_msg,
    make_eod_msg,
    make_expired_msg,
    make_fill_msg,
    make_gateway_auth_msg,
    make_gateway_bye_msg,
    make_circuit_breaker_halt_all_ack_msg,
    make_circuit_breaker_resume_all_ack_msg,
    make_symbol_halt_ack_msg,
    make_symbol_resume_ack_msg,
    make_cancel_symbol_ack_msg,
    make_kill_switch_ack_msg,
    make_orders_msg,
    make_quote_ack_msg,
    make_quote_bootstrap_msg,
    make_quote_legs_msg,
    make_quote_status_msg,
    make_symbols_msg,
    make_session_state_msg,
    make_auction_result_msg,
    make_oco_ack_msg,
    make_oco_cancelled_msg,
    make_session_status_msg,
    make_session_schedule_msg,
    make_gateways_msg,
    make_volume_msg,
    make_halt_status_msg,
    make_position_snapshot_msg,
)
from edumatcher.models.participant import (
    DisconnectBehaviour,
    ParticipantRole,
    ParticipantSession,
)
from edumatcher.models.order import (
    Order,
    OrderOrigin,
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
    TIF,
)
from edumatcher.models.price import from_ticks, to_ticks
from edumatcher.models.price import get_tick_decimals, register_tick_decimals
from edumatcher.models.quote import (
    QuoteEntry,
    QuoteIndex,
    QuoteLegSnapshot,
    QuoteRefreshPolicy,
    QuoteState,
)
from edumatcher.models.session import (
    SessionState,
    VALID_TRANSITIONS,
    accepts_orders,
    is_matching_enabled,
)
from edumatcher.models.trade import Trade

# Kept for backward compatibility (e.g. tests that reference it).  The hot path
# uses the monotonic now_ns() for event timestamps (M9), not this raw source.
_time_ns = time.time_ns

# L2: operational logging goes through the logging module (not print()).  The
# process entry point (main()) configures the handler/level; the library itself
# installs no handlers.
log = logging.getLogger(__name__)

# Pre-encoded static trade topic and a pre-built fill-status set — small hot-path
# allocations avoided (see docs-design/perf-notes.md).
_TRADE_TOPIC = b"trade.executed"

_FILL_STATUSES = frozenset({OrderStatus.PARTIAL, OrderStatus.FILLED})
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0


def order_to_display_dict(order: Order) -> dict[str, Any]:
    """Serialize an order for an outbound snapshot in *display* units (L3).

    Single source of truth built on ``Order.to_dict()`` (so fields never drift
    from the model), with tick prices converted to display floats and the
    timestamp expressed in seconds.
    """
    d = order.to_dict()
    sym = order.symbol
    d["price"] = from_ticks(order.price, sym) if order.price is not None else None
    d["stop_price"] = (
        from_ticks(order.stop_price, sym) if order.stop_price is not None else None
    )
    d["trail_offset"] = (
        from_ticks(order.trail_offset, sym) if order.trail_offset is not None else None
    )
    d["timestamp"] = order.timestamp / 1_000_000_000
    return d


class Engine:
    # Minimum interval between book snapshot publishes per symbol (seconds)
    SNAPSHOT_INTERVAL = 0.5
    QUOTE_HISTORY_MAXLEN = 30
    DROP_COPY_BUFFER_SIZE = 10_000
    RECENT_TRADES_MAXLEN = 20
    DEPTH_SNAPSHOT_TOLERANCE_TICKS = 100

    def __init__(self, verbose: bool = False, config_path: str | None = None) -> None:
        # Kept for backward compatibility with existing callers/tests. Detail
        # logging is no longer gated by this flag -- it is gated by the
        # standard logging level (see main()'s -v/-vv/--log-level/-q), same
        # as every other process. This attribute currently has no effect.
        self.verbose = verbose
        self.books: dict[str, OrderBook] = {}  # symbol → OrderBook
        self._running = False
        self._error_count = 0
        self._unknown_topic_count = 0
        # If None → no symbol restrictions (backward-compat mode)
        self._allowed_symbols: frozenset[str] | None = None
        self._allowed_fix_gateways: frozenset[str] | None = None
        self._engine_config: EngineConfig | None = None
        self._gateway_descriptions: dict[str, str] = {}
        self._connected_fix_gateways: set[str] = set()
        self._sessions: dict[str, ParticipantSession] = {}
        self.quote_history_maxlen: int = self.QUOTE_HISTORY_MAXLEN
        self.drop_copy_buffer_size: int = self.DROP_COPY_BUFFER_SIZE
        self.recent_trades_maxlen: int = self.RECENT_TRADES_MAXLEN
        self.depth_snapshot_tolerance_ticks: int = self.DEPTH_SNAPSHOT_TOLERANCE_TICKS
        self._quote_index = QuoteIndex(self.quote_history_maxlen)

        # Halt state — keyed by symbol; True means halted (circuit breaker fired)
        self._halted_symbols: dict[str, bool] = {}
        # Persisted book stats — loaded once during _load_config and kept for
        # _handle_symbols_request so prev_close is available without re-reading
        self._book_stats: dict[str, dict[str, Any]] = {}
        # Price collar configs — keyed by symbol; populated in _load_config()
        self._collars: dict[str, CollarConfig] = {}
        # Circuit breaker states — keyed by symbol; populated in _load_config()
        self._circuit_breakers: dict[str, CircuitBreakerState] = {}
        # Drop copy publisher — None until run() is called (avoids binding port 5557 in tests)
        self._drop_copy: Optional[DropCopyPublisher] = None

        # Global order_id → symbol map for O(1) cancel routing
        self._order_symbol: dict[str, str] = {}

        # Per-gateway pre-encoded ZMQ topic bytes, cached on first contact so
        # per-message frames are a dict lookup (see docs-design/perf-notes.md).
        self._topic_cache: dict[str, bytes] = {}

        # Per-symbol timestamp of last snapshot publish (for throttling)
        self._last_snapshot: dict[str, float] = {}
        # Set of symbols whose book changed since last snapshot publish
        self._dirty_symbols: set[str] = set()
        self.snapshot_interval_sec: float = self.SNAPSHOT_INTERVAL

        # Combo-order tracking
        self._combos: dict[str, ComboOrder] = {}  # combo internal id → ComboOrder
        self._order_to_combo: dict[str, str] = {}  # child order_id → combo internal id

        # OCO-order tracking
        self._oco_groups: dict[str, list[str]] = (
            {}
        )  # oco_group_id → [order_id_1, order_id_2]
        self._order_to_oco: dict[str, str] = {}  # order_id → oco_group_id

        # Per-gateway position ledger — updated on every fill; keyed by
        # uppercase gateway_id → symbol → value.  Allows bots to resync
        # inventory state after a restart via system.position_request.
        self._gateway_positions: dict[str, dict[str, int]] = {}
        self._gateway_avg_cost: dict[str, dict[str, float]] = {}

        # Session state (auction / continuous matching)
        self._sessions_enabled: bool = False
        self._session_state: SessionState = SessionState.CONTINUOUS
        self._enforce_collars: bool = True
        self._enforce_circuit_breakers: bool = True
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Load engine config (symbol allowlist + MM orders)
        path = Path(config_path) if config_path else ENGINE_CONFIG_FILE
        if path.exists():
            try:
                self._engine_config = load_engine_config(path)
                self._allowed_symbols = self._engine_config.allowed_symbols
                self._allowed_fix_gateways = self._engine_config.allowed_fix_gateways
                self._sessions_enabled = self._engine_config.sessions_enabled
                self._enforce_collars = self._engine_config.enforce_collars
                self._enforce_circuit_breakers = (
                    self._engine_config.enforce_circuit_breakers
                )
                self.snapshot_interval_sec = self._engine_config.snapshot_interval_sec
                self.quote_history_maxlen = self._engine_config.quote_history_maxlen
                self.drop_copy_buffer_size = self._engine_config.drop_copy_buffer_size
                self.recent_trades_maxlen = self._engine_config.recent_trades_maxlen
                self.depth_snapshot_tolerance_ticks = (
                    self._engine_config.depth_snapshot_tolerance_ticks
                )
                self._quote_index = QuoteIndex(self.quote_history_maxlen)
                self._gateway_descriptions = {
                    gw_id: cfg.description
                    for gw_id, cfg in self._engine_config.fix_gateways.items()
                }
                if self._sessions_enabled:
                    # Start CLOSED and wait for scheduler transitions.
                    self._session_state = SessionState.CLOSED
                log.info(
                    f"Loaded config from {path}  "
                    f"({len(self._allowed_symbols)} symbol(s): "
                    f"{', '.join(sorted(self._allowed_symbols))}; "
                    f"{len(self._allowed_fix_gateways)} gateway id(s))"
                )
                log.info(
                    "Session handling: "
                    + (
                        "enabled (startup state: CLOSED)"
                        if self._sessions_enabled
                        else "disabled"
                    )
                )
                log.info(
                    "Risk enforcement: "
                    f"collars={'on' if self._enforce_collars else 'off'}, "
                    f"circuit_breakers={'on' if self._enforce_circuit_breakers else 'off'}"
                )
            except (FileNotFoundError, PermissionError) as exc:
                log.warning(
                    "Config file %s could not be read — "
                    "running without symbol restrictions. (%s)",
                    path,
                    exc,
                )
            except Exception as exc:
                log.error("FATAL: Invalid config %s: %s", path, exc)
                sys.exit(1)
        else:
            log.info(f"No config file at {path} — running without symbol restrictions.")

        try:
            self.pull_sock = make_puller(ENGINE_PULL_ADDR)
            self.pub_sock = make_publisher(ENGINE_PUB_ADDR)
        except zmq.ZMQError as exc:
            log.error(
                "FATAL: Cannot bind sockets — %s\n"
                "         Is another engine instance already running?",
                exc,
            )
            sys.exit(1)

        # Give PUB socket a moment to bind before any client can connect
        time.sleep(0.05)

    def _dbg_count(self, key: str, amount: int = 1) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        self._debug_counts[key] += amount
        self._flush_debug_summary()

    def _flush_debug_summary(self, force: bool = False) -> None:
        if not log.isEnabledFor(logging.DEBUG):
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
        log.debug("decision summary: %s", summary)
        self._debug_counts.clear()
        self._debug_last_summary = now

    def _gateway_status(self, gateway_id: str) -> tuple[bool, str]:
        """Return (is_allowed_and_connected, reason_if_not)."""
        gw_id = gateway_id.upper()
        if self._allowed_fix_gateways is None:
            return True, ""
        if gw_id not in self._allowed_fix_gateways:
            return False, f"Gateway not configured: {gw_id}"
        session = self._sessions.get(gw_id)
        connected = (session is not None and session.connected) or (
            gw_id in self._connected_fix_gateways
        )
        if not connected:
            return False, f"Gateway not connected: {gw_id}"
        return True, ""

    def _resolve_smp_action(
        self, gateway_id: str, smp_action: SmpAction | None
    ) -> SmpAction:
        """Resolve a possibly-unspecified SMP action to a concrete value.

        ``smp_action=None`` means the client omitted ``SMP=`` (or the JSON
        equivalent) entirely -- distinct from an *explicit* ``SMP=NONE``,
        which is a deliberate request to allow self-trades and must be
        respected as-is. When omitted, fall back to the order's gateway's
        configured ``gateways.alf[].smp_action`` default, or ``SmpAction.NONE``
        if the gateway has none configured (unconfigured/unknown gateway,
        or the engine is running without a loaded config). See SmpAction's
        docstring in models/order.py for the full rationale.
        """
        if smp_action is not None:
            return smp_action
        cfg = (
            self._engine_config.fix_gateways.get(gateway_id.upper())
            if self._engine_config
            else None
        )
        return cfg.smp_action if cfg is not None else SmpAction.NONE

    def _session_for_gateway(self, gateway_id: str) -> ParticipantSession:
        gw_id = gateway_id.upper()
        session = self._sessions.get(gw_id)
        if session is not None:
            return session
        session = ParticipantSession(gateway_id=gw_id)
        self._sessions[gw_id] = session
        return session

    # ------------------------------------------------------------------
    # Book access
    # ------------------------------------------------------------------

    def _book(self, symbol: str) -> OrderBook:
        if symbol not in self.books:
            self.books[symbol] = OrderBook(
                symbol, recent_trades_maxlen=self.recent_trades_maxlen
            )
        return self.books[symbol]

    def _mark_dirty(self, symbol: str) -> None:
        """Flag a symbol as needing a snapshot publish."""
        self._dirty_symbols.add(symbol)

    def _flush_snapshots(self) -> None:
        """
        Publish book snapshots for all dirty symbols whose throttle window
        has elapsed (snapshot_interval_sec seconds since last publish).
        Called once per poll loop tick.
        """
        now = time.monotonic()
        sent: set[str] = set()
        for symbol in self._dirty_symbols:
            last = self._last_snapshot.get(symbol, 0.0)
            if now - last >= self.snapshot_interval_sec:
                book = self.books.get(symbol)
                if book:
                    self.pub_sock.send_multipart(make_book_msg(symbol, book.snapshot()))
                    # Depth metrics — published alongside each book snapshot
                    depth = book.depth_snapshot(
                        tolerance_ticks=self.depth_snapshot_tolerance_ticks
                    )
                    if depth:
                        self.pub_sock.send_multipart(encode(f"depth.{symbol}", depth))
                self._last_snapshot[symbol] = now
                sent.add(symbol)
        self._dirty_symbols -= sent

    # ------------------------------------------------------------------
    # Config: seed stats + inject market-maker quotes
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """Pre-create books, seed stats, inject MM quotes from engine config."""
        if not self._engine_config:
            return

        for sym, sym_cfg in self._engine_config.symbols.items():
            register_tick_decimals(sym, sym_cfg.tick_decimals)

        # Restore persisted stats first so config seeds only fill gaps
        stats = load_book_stats(BOOK_STATS_FILE)
        self._book_stats = stats
        for sym, sym_cfg in self._engine_config.symbols.items():
            book = self._book(sym)
            persisted = stats.get(sym, {})
            lbp_raw = persisted.get("last_buy_price")
            lsp_raw = persisted.get("last_sell_price")

            lbp = (
                to_ticks(float(lbp_raw), sym)
                if lbp_raw is not None
                else (
                    to_ticks(float(sym_cfg.last_buy_price), sym)
                    if sym_cfg.last_buy_price is not None
                    else None
                )
            )
            lsp = (
                to_ticks(float(lsp_raw), sym)
                if lsp_raw is not None
                else (
                    to_ticks(float(sym_cfg.last_sell_price), sym)
                    if sym_cfg.last_sell_price is not None
                    else None
                )
            )
            book.restore_stats(lbp, lsp)
        if stats:
            log.info(f"Restored book statistics for {len(stats)} symbol(s).")

        n_mm_quotes = 0
        for sym, sym_cfg in self._engine_config.symbols.items():
            for idx, quote_seed in enumerate(sym_cfg.market_maker_quotes, start=1):
                # seed_once: skip injection if this symbol already has a book_stats
                # entry, meaning it has been started at least once before.
                if quote_seed.seed_once and sym in stats:
                    log.info(
                        f"Skipping seed quote for {sym} "
                        f"(seed_once=true, symbol has prior history)"
                    )
                    continue

                gateway_id = quote_seed.gateway_id
                quote_id = quote_seed.quote_id or f"SEED-{gateway_id}-{sym}-{idx}"

                previous = self._quote_index.remove(
                    gateway_id, sym, reason="Replaced by startup quote"
                )
                if previous:
                    self._cancel_quote_entry(
                        previous, reason="Replaced by startup quote"
                    )

                bid = Order.create(
                    symbol=sym,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=quote_seed.bid_qty,
                    gateway_id=gateway_id,
                    tif=quote_seed.tif,
                    price=to_ticks(quote_seed.bid_price, sym),
                )
                ask = Order.create(
                    symbol=sym,
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=quote_seed.ask_qty,
                    gateway_id=gateway_id,
                    tif=quote_seed.tif,
                    price=to_ticks(quote_seed.ask_price, sym),
                )
                bid.origin = OrderOrigin.QUOTE
                ask.origin = OrderOrigin.QUOTE
                bid.quote_id = quote_id
                ask.quote_id = quote_id

                self._order_symbol[bid.id] = sym
                self._order_symbol[ask.id] = sym
                self._quote_index.put(
                    QuoteEntry(
                        quote_id=quote_id,
                        gateway_id=gateway_id,
                        symbol=sym,
                        bid_order_id=bid.id,
                        ask_order_id=ask.id,
                    )
                )

                now = now_ns()
                book = self._book(sym)
                # #16: seeded quotes must not cross-match if the engine starts in
                # a non-continuous phase (e.g. CLOSED) — they rest for the open.
                seed_do_match = is_matching_enabled(self._session_state)
                for quote_order in (bid, ask):
                    trades, events = book.process(
                        quote_order, match=seed_do_match, now=now
                    )
                    # H5: dedup fills — a seeded quote sweeping k levels appears
                    # k times in `events` with the final cumulative qty.
                    # H6: report each order's own VWAP execution price.
                    _seed_fill_px = self._order_fill_prices(trades)
                    _seed_fill_ids: set[str] = set()
                    _seed_cancel_ids: set[str] = set()
                    for evt in events:
                        if evt.status in _FILL_STATUSES:
                            if evt.id not in _seed_fill_ids:
                                _seed_fill_ids.add(evt.id)
                                self.pub_sock.send_multipart(
                                    make_fill_msg(
                                        evt.gateway_id,
                                        evt.id,
                                        fill_qty=evt.quantity - evt.remaining_qty,
                                        fill_price=_seed_fill_px.get(
                                            evt.id,
                                            (
                                                from_ticks(
                                                    book.last_trade_price, evt.symbol
                                                )
                                                if book.last_trade_price is not None
                                                else 0.0
                                            ),
                                        ),
                                        remaining_qty=evt.remaining_qty,
                                        status=evt.status.value,
                                        order=evt.to_dict(),
                                    )
                                )
                                if evt.quote_id:
                                    self._on_quote_leg_filled(evt)
                        elif evt.status == OrderStatus.CANCELLED:
                            if evt.id not in _seed_cancel_ids:
                                _seed_cancel_ids.add(evt.id)
                                self.pub_sock.send_multipart(
                                    make_cancelled_msg(evt.gateway_id, evt.id)
                                )
                    for trade in trades:
                        self._publish_trade(trade)

                self._mark_dirty(sym)
                n_mm_quotes += 1
                log.info(
                    f"MM quote {quote_id} {sym} "
                    f"bid={quote_seed.bid_price}x{quote_seed.bid_qty} "
                    f"ask={quote_seed.ask_price}x{quote_seed.ask_qty} "
                    f"gw={gateway_id}"
                )

        n_mm_combos = 0
        for combo_cfg in self._engine_config.market_maker_combos:
            combo = ComboOrder.create(
                combo_id=combo_cfg.combo_id,
                gateway_id="MM",
                combo_type=combo_cfg.combo_type,
                tif=combo_cfg.tif,
                legs=combo_cfg.legs,
            )
            if self._accept_combo(combo, publish_ack=False):
                n_mm_combos += 1

        if n_mm_quotes or n_mm_combos:
            log.info(
                f"Injected {n_mm_quotes} market-maker quote(s) "
                f"and {n_mm_combos} combo(s)."
            )
            # Publish immediately on startup (bypass throttle)
            for sym in self._engine_config.symbols:
                if sym in self.books:
                    self.pub_sock.send_multipart(
                        make_book_msg(sym, self.books[sym].snapshot())
                    )

        # Wire collar and circuit breaker configs now that tick-decimals are set
        for sym, sym_cfg in self._engine_config.symbols.items():
            if sym_cfg.collar is not None:
                # Populate reference_price from the book's resolved last-buy /
                # last-sell ticks (buy side preferred). These were set above by
                # restore_stats() and already prefer persisted book_stats.json
                # over the static config seed, so the collar reference tracks
                # the most recently known price instead of a stale config value.
                book = self._book(sym)
                ref_ticks = (
                    book.last_buy_price
                    if book.last_buy_price is not None
                    else book.last_sell_price
                )
                if ref_ticks is not None:
                    sym_cfg.collar.symbol = sym
                    sym_cfg.collar.reference_price = ref_ticks
                    self._collars[sym] = sym_cfg.collar
            if sym_cfg.circuit_breaker is not None:
                sym_cfg.circuit_breaker.symbol = sym
                cb_state = CircuitBreakerState(
                    symbol=sym, config=sym_cfg.circuit_breaker
                )
                # Seed the breaker's reference from the same resolved last-buy /
                # last-sell price used for the collar, so the breaker is active
                # from the first order on day one (before any fills), consistent
                # with collars being active from their reference immediately.
                book = self._book(sym)
                cb_ref_ticks = (
                    book.last_buy_price
                    if book.last_buy_price is not None
                    else book.last_sell_price
                )
                if cb_ref_ticks is not None:
                    cb_state.seed_reference(cb_ref_ticks, now_ns())
                self._circuit_breakers[sym] = cb_state

    # ------------------------------------------------------------------
    # Startup — restore GTC orders
    # ------------------------------------------------------------------

    def _restore_gtc(self) -> None:
        # M4: register tick decimals BEFORE restoring and publishing snapshots.
        # run() calls _restore_gtc() before _load_config(), so without this the
        # startup snapshots format prices with the default 2 decimals — 100x
        # off for a 4-decimal symbol.  Re-registration in _load_config is a
        # harmless no-op.
        if self._engine_config:
            for sym, sym_cfg in self._engine_config.symbols.items():
                register_tick_decimals(sym, sym_cfg.tick_decimals)

        orders = load_gtc_orders(GTC_ORDERS_FILE)
        for order in orders:
            # Skip GTC orders for symbols no longer in config
            if self._allowed_symbols and order.symbol not in self._allowed_symbols:
                log.info(
                    f"Skipping GTC order {order.id[:8]} for removed symbol {order.symbol}"
                )
                continue
            order.status = OrderStatus.NEW
            book = self._book(order.symbol)
            # match=False: restore resting state only; do not replay execution.
            # Two crossed GTC orders saved from an auction phase would otherwise
            # silently match with no fill events or position updates.
            #
            # Guard each order so one bad record cannot abort engine startup
            # (finding C6): a persisted order that raises during restore is
            # logged and skipped rather than crashing the whole engine.
            try:
                book.process(order, match=False)
            except Exception as exc:
                log.info(
                    f"Skipping GTC order {order.id[:8]} ({order.symbol}) "
                    f"— restore failed: {exc}"
                )
                continue
            self._order_symbol[order.id] = order.symbol
            log.info(f"Restored GTC order {order.id} ({order.symbol})")
        if orders:
            log.info(f"Restored {len(orders)} GTC order(s) from previous session.")
            # M3: restore rests orders without matching, so two crossed GTC
            # orders would leave the book crossed at startup.  Uncross each
            # book at the equilibrium price before continuous trading begins.
            for symbol in list(self.books.keys()):
                self._run_uncross(symbol_filter=symbol)
            # Publish initial book snapshots immediately on startup
            for symbol, book in self.books.items():
                self.pub_sock.send_multipart(make_book_msg(symbol, book.snapshot()))

        # Restore GTC combos and rebuild parent-child links
        combos = load_gtc_combos(GTC_COMBOS_FILE)
        for combo in combos:
            self._combos[combo.id] = combo
            for child_id in combo.child_order_ids:
                self._order_to_combo[child_id] = combo.id
        if combos:
            log.info(f"Restored {len(combos)} GTC combo(s) from previous session.")

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def _validate_new_order(self, order: Order) -> str | None:
        """Boundary validation for an inbound order (M7 / A4).

        Returns a human-readable rejection reason, or None if the order is
        acceptable.  Runs before the positive ACK so malformed orders never
        reach the book.
        """
        # A4: a duplicate order id (gateway retry / replay) would overwrite the
        # routing map and rest a second heap entry, doubling liquidity.
        if order.id in self._order_symbol:
            return f"Duplicate order id {order.id}"
        # M7: quantity must be positive.
        if order.quantity <= 0 or order.remaining_qty <= 0:
            return "Quantity must be positive"
        # M7: order types that rest / price-limit must carry a positive price.
        price_required = order.order_type in (
            OrderType.LIMIT,
            OrderType.FOK,
            OrderType.STOP_LIMIT,
            OrderType.ICEBERG,
        )
        if price_required and (order.price is None or order.price <= 0):
            return f"{order.order_type.value} order requires a positive price"
        # M7: iceberg visible slice must be present and not exceed quantity.
        if order.order_type == OrderType.ICEBERG:
            if order.visible_qty is None or order.visible_qty <= 0:
                return "ICEBERG order requires a positive visible_qty"
            if order.visible_qty > order.quantity:
                return "ICEBERG visible_qty must not exceed quantity"
        return None

    def _handle_new_order(self, payload: dict[str, Any]) -> None:
        order = Order.from_dict(payload)
        self._dbg_count("new_order_requests")

        # Boundary conversion: inbound payload prices are display decimals.
        if order.price is not None and isinstance(order.price, float):
            order.price = to_ticks(order.price, order.symbol)
        if order.stop_price is not None and isinstance(order.stop_price, float):
            order.stop_price = to_ticks(order.stop_price, order.symbol)
        if order.trail_offset is not None and isinstance(order.trail_offset, float):
            order.trail_offset = to_ticks(order.trail_offset, order.symbol)

        # SMP=None means the client omitted it -- fall back to the gateway's
        # configured default (gateways.alf[].smp_action). An explicit value
        # (including SmpAction.NONE) from the client is always respected.
        order.smp_action = self._resolve_smp_action(order.gateway_id, order.smp_action)

        # FIX gateway allowlist + connect/auth check
        # Fast-path: if gateway_id is already in _connected_fix_gateways it is
        # known-good (allowed + connected).  Only invoke _gateway_status() on
        # first contact, disconnected gateways, or backward-compat mode.
        _gw_id_upper = order.gateway_id.upper()
        if _gw_id_upper not in self._connected_fix_gateways:
            ok, reason = self._gateway_status(order.gateway_id)
            if not ok:
                self._dbg_count("new_order_reject_gateway")
                self.pub_sock.send_multipart(
                    make_ack_msg(
                        order.gateway_id, order.id, accepted=False, reason=reason
                    )
                )
                log.info(f"REJECTED {order.id[:8]} — {reason}")
                return

        # Symbol allowlist check
        if self._allowed_symbols and order.symbol not in self._allowed_symbols:
            self._dbg_count("new_order_reject_symbol")
            self.pub_sock.send_multipart(
                make_ack_msg(
                    order.gateway_id,
                    order.id,
                    accepted=False,
                    reason=f"Symbol not configured: {order.symbol}",
                )
            )
            log.info(f"REJECTED {order.id[:8]} — symbol not configured: {order.symbol}")
            return

        # Ensure the (configured) symbol's book exists even if the order is
        # about to be rejected — keeps book state observable and consistent.
        self._book(order.symbol)

        # M7 / A4: validate the payload at the engine boundary BEFORE the
        # positive ACK, so bad values are rejected with a reasoned NACK instead
        # of ACKing accepted=True and then crashing inside the book (swallowed
        # by the blanket handler → order silently lost) or corrupting the index.
        validation_error = self._validate_new_order(order)
        if validation_error is not None:
            self._dbg_count("new_order_reject_validation")
            self.pub_sock.send_multipart(
                make_ack_msg(
                    order.gateway_id, order.id, accepted=False, reason=validation_error
                )
            )
            log.info(f"REJECTED {order.id[:8]} — {validation_error}")
            return

        # Session state gating
        if self._sessions_enabled and not accepts_orders(self._session_state):
            self._dbg_count("new_order_reject_session")
            self.pub_sock.send_multipart(
                make_ack_msg(
                    order.gateway_id,
                    order.id,
                    accepted=False,
                    reason="Market is closed",
                )
            )
            return

        # ATO orders only during opening auction
        if (
            self._sessions_enabled
            and order.tif == TIF.ATO
            and self._session_state != SessionState.OPENING_AUCTION
        ):
            self._dbg_count("new_order_reject_ato_window")
            self.pub_sock.send_multipart(
                make_ack_msg(
                    order.gateway_id,
                    order.id,
                    accepted=False,
                    reason="ATO orders only accepted during opening auction",
                )
            )
            return

        # ATC orders only during closing auction
        if (
            self._sessions_enabled
            and order.tif == TIF.ATC
            and self._session_state != SessionState.CLOSING_AUCTION
        ):
            self._dbg_count("new_order_reject_atc_window")
            self.pub_sock.send_multipart(
                make_ack_msg(
                    order.gateway_id,
                    order.id,
                    accepted=False,
                    reason="ATC orders only accepted during closing auction",
                )
            )
            return

        book = self._book(order.symbol)
        do_match = is_matching_enabled(self._session_state)

        # Halt check — circuit breaker has halted this symbol
        if self._halted_symbols.get(order.symbol):
            if order.order_type in (OrderType.MARKET, OrderType.FOK, OrderType.IOC):
                self._dbg_count("new_order_reject_halt")
                self.pub_sock.send_multipart(
                    make_ack_msg(
                        order.gateway_id,
                        order.id,
                        accepted=False,
                        reason=(
                            f"{order.symbol} is halted — "
                            f"{order.order_type.value} orders rejected during circuit breaker halt"
                        ),
                    )
                )
                return
            # LIMIT / ICEBERG: accept and rest without matching (auction interest)
            do_match = False

        # Price collar check — static and dynamic band protection
        if self._enforce_collars and order.price is not None:
            collar = self._collars.get(order.symbol)
            if collar is not None:
                result = validate_collar(order.price, collar, book.last_trade_price)
                if result.rejected:
                    self._dbg_count("new_order_reject_collar")
                    self.pub_sock.send_multipart(
                        make_ack_msg(
                            order.gateway_id,
                            order.id,
                            accepted=False,
                            reason=result.reason,
                        )
                    )
                    return

        # MARKET / FOK / IOC cannot rest — reject during no-matching phases
        if not do_match and order.order_type in (
            OrderType.MARKET,
            OrderType.FOK,
            OrderType.IOC,
        ):
            self._dbg_count("new_order_reject_no_match_phase")
            self.pub_sock.send_multipart(
                make_ack_msg(
                    order.gateway_id,
                    order.id,
                    accepted=False,
                    reason=f"{order.order_type.value} orders not accepted during {self._session_state.value}",
                )
            )
            return

        log.info(
            f"NEW {order.id[:8]} {order.symbol} {order.side.value} "
            f"{order.order_type.value} qty={order.quantity} price={order.price}"
        )

        # TRAILING_STOP: compute initial stop_price from last trade if not supplied
        if order.order_type == OrderType.TRAILING_STOP:
            book = self._book(order.symbol)
            if order.stop_price is None:
                if book.last_trade_price is None:
                    self.pub_sock.send_multipart(
                        make_ack_msg(
                            order.gateway_id,
                            order.id,
                            accepted=False,
                            reason="Trailing stop requires STOP= or a prior trade price",
                        )
                    )
                    return
                if order.side == Side.SELL:
                    order.stop_price = book.last_trade_price - order.trail_offset  # type: ignore[operator]
                else:
                    order.stop_price = book.last_trade_price + order.trail_offset  # type: ignore[operator]

        # M8: order→symbol registration happens AFTER book.process() succeeds
        # (below), not here — so a failure mid-processing leaves no half-applied
        # routing entry for an order that never reached the book.

        # M9: use the monotonic clock (now_ns) for the matching timestamp, not
        # raw time.time_ns — a wall-clock regression (e.g. an NTP step) must
        # never make event timestamps go backwards.  Since time priority is
        # driven by the engine arrival sequence (H1), this is the correct
        # source of truth for ordering; the small monotonic-guard cost is
        # acceptable on the single-threaded hot path.
        now = now_ns()

        # NOTE: accepted=True is published here, BEFORE book.process() runs.
        # This is the "gateway ACK" — it confirms the engine accepted the order
        # for processing (symbol valid, session open, gateway authenticated).
        # For MARKET, FOK, and IOC orders that the book subsequently rejects
        # (e.g. FOK with insufficient liquidity), a second accepted=False ACK
        # follows in the events loop below.  Clients must treat the second ACK
        # as authoritative for these order types.
        #
        # Hot path: the ACK is built inline (bypassing make_ack_msg) with
        # pre-cached per-gateway topic bytes and hot attributes bound to locals
        # (see docs-design/perf-notes.md).
        _gw = order.gateway_id
        _tc = self._topic_cache
        ack_topic = _tc.get(_gw)
        if ack_topic is None:
            # First order from this gateway — populate the three hot topics
            _tc[_gw] = f"order.ack.{_gw}".encode()
            _tc[f"fill.{_gw}"] = f"order.fill.{_gw}".encode()
            _tc[f"cancel.{_gw}"] = f"order.cancelled.{_gw}".encode()
            ack_topic = _tc[_gw]
        _pub = self.pub_sock
        _fill_topic = _tc[f"fill.{_gw}"]  # guaranteed set by ack-topic setup above
        _ptrade = self._publish_trade
        _side_v: str = payload["side"]
        _ot_v: str = payload["order_type"]
        _tif_v: str = payload["tif"]
        _price_v = payload.get("price")  # None for MARKET orders
        _pub.send_multipart(
            [
                ack_topic,
                dumps(
                    {
                        "order_id": order.id,
                        "accepted": True,
                        "reason": "",
                        "symbol": order.symbol,
                        "side": _side_v,
                        "order_type": _ot_v,
                        "tif": _tif_v,
                        "qty": order.quantity,
                        "price": _price_v,
                        "client_tag": order.client_tag,
                    }
                ),
            ]
        )
        self._dbg_count("new_order_accepted")

        trades, events = book.process(order, match=do_match, now=now)
        self._dbg_count("new_order_events", len(events))
        self._dbg_count("new_order_trades", len(trades))

        # M8: register the routing entry only now that the book has accepted the
        # order.  The fill-publication loop below may prune it again if the
        # order fully filled (H7), so this must precede that loop.
        self._order_symbol[order.id] = order.symbol

        # H6: each order's fill message must carry ITS OWN execution price
        # (per-order VWAP over the trades it participated in), not the sweep's
        # last trade price.  Fall back to last_trade_price only if an order is
        # somehow missing from the trade map.
        _order_fill_px = self._order_fill_prices(trades)
        _fill_px = (
            from_ticks(book.last_trade_price, order.symbol)
            if trades and book.last_trade_price is not None
            else None
        )

        # Publish fills / cancels
        # Guard against duplicate fill events: when an aggressive order sweeps
        # multiple resting price levels, _apply_fill appends the SAME order
        # object to `events` once per fill.  By the time this loop runs the
        # object reflects only the FINAL state, so iterating it N times would
        # emit N identical fill messages (wrong fill_qty and fill_price for the
        # first N-1 occurrences, and N× overcounting in position trackers).
        # Using a seen-set ensures exactly ONE fill message per order per
        # process() call — reporting the correct total fill quantity and final
        # remaining_qty.  Combo/OCO side-effect checks are idempotent so they
        # run unconditionally and are safe to call on every occurrence.
        _published_fill_ids: set[str] = set()
        _published_terminal_ids: set[str] = set()
        for evt in events:
            # ----------------------------------------------------------------
            # Fill notification (finding #5)
            # ----------------------------------------------------------------
            # Publish a fill whenever the order EXECUTED any quantity, keyed off
            # cumulative filled qty — NOT off the order's final status.  `events`
            # holds repeated references to the same live Order, and an
            # IOC/MARKET/SMP-cancelled aggressor fills and is then mutated to
            # CANCELLED on that same object.  Branching on the final status alone
            # (the old `if evt.status in _FILL_STATUSES`) dropped the fill entirely
            # while still emitting a cancel — the owner saw order.cancelled and no
            # order.fill despite a real execution having printed.
            _filled_qty = evt.quantity - evt.remaining_qty
            if _filled_qty > 0 and evt.id not in _published_fill_ids:
                _published_fill_ids.add(evt.id)
                # Hot path: fill payload built inline with pre-cached topic
                # bytes; for the aggressor (evt is order) canonical string values
                # from the payload are reused (see docs-design/perf-notes.md).
                _is_agg = evt is order
                _pub.send_multipart(
                    [
                        (
                            _fill_topic
                            if evt.gateway_id == _gw
                            else (
                                _tc.get(f"fill.{evt.gateway_id}")
                                or f"order.fill.{evt.gateway_id}".encode()
                            )
                        ),
                        dumps(
                            {
                                "order_id": evt.id,
                                "fill_qty": _filled_qty,
                                "fill_price": _order_fill_px.get(evt.id, _fill_px),
                                "remaining_qty": evt.remaining_qty,
                                "status": (
                                    "PARTIAL_FILL" if evt.remaining_qty else "FILLED"
                                ),
                                "symbol": evt.symbol,
                                "side": _side_v if _is_agg else evt.side.value,
                                "order_type": (
                                    _ot_v if _is_agg else evt.order_type.value
                                ),
                                "qty": evt.quantity,
                                "price": (
                                    _price_v
                                    if _is_agg
                                    else (
                                        from_ticks(evt.price, evt.symbol)
                                        if evt.price is not None
                                        else None
                                    )
                                ),
                                "client_tag": evt.client_tag,
                            }
                        ),
                    ]
                )
                # Drop copy is published centrally in _publish_trade (#11,#30 so
                # every flow's fills reach the clearing/risk feed uniformly —
                # no per-flow drop-copy call is needed here.

            # Combo / OCO side-effects on fill (idempotent — safe every occurrence)
            if evt.status in _FILL_STATUSES:
                if evt.combo_parent_id:
                    self._check_combo_after_child_event(evt)
                if evt.status == OrderStatus.FILLED and evt.oco_group_id:
                    self._check_oco_after_event(evt)
                # MM quote leg inactivation: a resting quote leg can be filled
                # here by an independent, later-arriving taker order — not
                # just by the quote's own submission sweeping the book (that
                # path is handled separately in _handle_quote_submit's match
                # loop). Without this call, a quote hit by a later order was
                # never inactivated or had its sibling leg cancelled, and its
                # removal was never recorded in QuoteIndex's RECENT history.
                if evt.quote_id:
                    self._on_quote_leg_filled(evt)
                # H7: a fully filled order is terminal — drop its engine-level
                # order→symbol routing entry (the book already purged its own
                # indexes).  A partially filled order that rests keeps it.
                if evt.status == OrderStatus.FILLED:
                    self._order_symbol.pop(evt.id, None)

            # ----------------------------------------------------------------
            # Terminal status notification (deduped per order id)
            # ----------------------------------------------------------------
            if (
                evt.status == OrderStatus.REJECTED
                and evt.id not in _published_terminal_ids
            ):
                _published_terminal_ids.add(evt.id)
                _pub.send_multipart(
                    make_ack_msg(
                        evt.gateway_id,
                        evt.id,
                        accepted=False,
                        reason="Insufficient liquidity",
                    )
                )
                # REJECTED event carrying an oco_group_id → cancel the other leg
                if evt.oco_group_id:
                    self._check_oco_after_event(evt)
                # H7: rejected order is terminal — drop its routing entry.
                self._order_symbol.pop(evt.id, None)
            elif (
                evt.status == OrderStatus.CANCELLED
                and evt.id not in _published_terminal_ids
            ):
                _published_terminal_ids.add(evt.id)
                # Terminal cancellation (SMP, IOC/MARKET remainder) — notify owner.
                _pub.send_multipart(
                    [
                        _tc.get(f"cancel.{evt.gateway_id}")
                        or f"order.cancelled.{evt.gateway_id}".encode(),
                        dumps({"order_id": evt.id, "client_tag": evt.client_tag}),
                    ]
                )
                if evt.combo_parent_id:
                    self._check_combo_after_child_event(evt)
                if evt.oco_group_id:
                    self._check_oco_after_event(evt)
                # H7: cancelled order is terminal — drop its routing entry.
                self._order_symbol.pop(evt.id, None)
                log.info(f"CANCEL {evt.id[:8]} ({evt.gateway_id})")

        # Publish trades — _publish_trade updates both position ledgers (H3).
        for trade in trades:
            log.info(
                f"TRADE {trade.id[:8]} {trade.symbol} "
                f"qty={trade.quantity} @{trade.price}"
            )
            _ptrade(trade)

        # Mark book dirty; snapshot will be published on next throttle tick
        self._dirty_symbols.add(order.symbol)

    def _handle_symbols_request(self, payload: dict[str, Any]) -> None:
        gateway_id = payload.get("gateway_id", "")
        symbols = sorted(self.books.keys())
        engine_cfg = self._engine_config
        symbol_meta: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            meta: dict[str, Any] = {}
            sym_cfg = engine_cfg.symbols.get(symbol) if engine_cfg else None
            if sym_cfg is not None:
                meta["tick_size"] = 10 ** (-int(sym_cfg.tick_decimals))

                mm_max_spread_ticks: int | None = None
                mm_min_qty: int | None = None
                enforce_mm_obligation: bool | None = None

                gw_cfg = engine_cfg.fix_gateways.get(gateway_id) if engine_cfg else None
                if gw_cfg is not None:
                    enforce_mm_obligation = gw_cfg.enforce_mm_obligation
                    mm_max_spread_ticks = gw_cfg.mm_max_spread_ticks
                    mm_min_qty = gw_cfg.mm_min_qty

                    global_sym_policy = (
                        engine_cfg.global_symbol_mm_obligation_policies.get(symbol)
                        if engine_cfg
                        else None
                    )
                    if global_sym_policy is not None:
                        enforce_mm_obligation = global_sym_policy.enforce_mm_obligation
                        mm_max_spread_ticks = global_sym_policy.mm_max_spread_ticks
                        mm_min_qty = global_sym_policy.mm_min_qty

                    gw_sym_policy = gw_cfg.mm_obligation_policies.get(symbol)
                    if gw_sym_policy is not None:
                        enforce_mm_obligation = gw_sym_policy.enforce_mm_obligation
                        mm_max_spread_ticks = gw_sym_policy.mm_max_spread_ticks
                        mm_min_qty = gw_sym_policy.mm_min_qty

                if enforce_mm_obligation is not None:
                    meta["enforce_mm_obligation"] = enforce_mm_obligation
                if mm_max_spread_ticks is not None:
                    meta["mm_max_spread_ticks"] = mm_max_spread_ticks
                if mm_min_qty is not None:
                    meta["mm_min_qty"] = mm_min_qty

            # Previous-close reference price (float display price)
            prev_close = self._book_stats.get(symbol, {}).get("prev_close")
            if prev_close is not None:
                meta["prev_close"] = prev_close

            symbol_meta[symbol] = meta

        self.pub_sock.send_multipart(
            make_symbols_msg(gateway_id, symbols, symbol_meta=symbol_meta)
        )

    def _handle_session_state_request(self, payload: dict[str, Any]) -> None:
        """Return the current session state without advancing it."""
        gateway_id = str(payload.get("gateway_id", "")).upper()
        self.pub_sock.send_multipart(
            make_session_status_msg(
                gateway_id,
                self._session_state.value,
                self._sessions_enabled,
            )
        )

    def _update_position(
        self,
        gateway_id: str,
        symbol: str,
        side_str: str,
        fill_qty: int,
        fill_price: float,
    ) -> None:
        """Update per-gateway position ledger after a fill.

        Maintains a signed net quantity per symbol and a VWAP average cost
        that resets to the fill price whenever the position crosses zero.
        """
        gw = gateway_id.upper()
        gw_pos = self._gateway_positions.setdefault(gw, {})
        gw_cost = self._gateway_avg_cost.setdefault(gw, {})

        pos = gw_pos.get(symbol, 0)
        cost = gw_cost.get(symbol, 0.0)

        if side_str == "BUY":
            new_pos = pos + fill_qty
            if pos >= 0:
                # Opening or adding to a long position
                new_cost = (cost * pos + fill_price * fill_qty) / new_pos
            elif new_pos < 0:
                # Reducing a short, still net short: avg_cost unchanged
                new_cost = cost
            elif new_pos == 0:
                # Closed the short exactly flat
                new_cost = 0.0
            else:
                # Crossed from short to long: reset cost to fill price
                new_cost = fill_price
        else:  # SELL
            new_pos = pos - fill_qty
            if pos <= 0:
                # Opening or adding to a short position
                abs_new = abs(new_pos)
                new_cost = (cost * abs(pos) + fill_price * fill_qty) / abs_new
            elif new_pos > 0:
                # Reducing a long, still net long: avg_cost unchanged
                new_cost = cost
            elif new_pos == 0:
                # Closed the long exactly flat
                new_cost = 0.0
            else:
                # Crossed from long to short: reset cost to fill price
                new_cost = fill_price

        gw_pos[symbol] = new_pos
        gw_cost[symbol] = new_cost if new_pos != 0 else 0.0

    def _handle_position_request(self, payload: dict[str, Any]) -> None:
        """Reply with a per-symbol position snapshot for the requesting gateway."""
        gateway_id = str(payload.get("gateway_id", "")).upper()
        ok, _ = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(make_position_snapshot_msg(gateway_id, []))
            return
        gw_pos = self._gateway_positions.get(gateway_id, {})
        gw_cost = self._gateway_avg_cost.get(gateway_id, {})
        positions = [
            {
                "symbol": sym,
                "net_qty": qty,
                "avg_cost": gw_cost.get(sym, 0.0),
            }
            for sym, qty in gw_pos.items()
            if qty != 0
        ]
        self.pub_sock.send_multipart(make_position_snapshot_msg(gateway_id, positions))

    def _handle_halt_status_request(self, payload: dict[str, Any]) -> None:
        """Reply with a snapshot of all currently halted symbols."""
        gateway_id = str(payload.get("gateway_id", "")).upper()
        halted: list[dict[str, Any]] = []
        for symbol, is_halted in self._halted_symbols.items():
            if not is_halted:
                continue
            entry: dict[str, Any] = {"symbol": symbol}
            cb = self._circuit_breakers.get(symbol)
            if cb and cb.halted:
                entry["resume_at_ns"] = cb.resume_at_ns
                entry["level"] = cb.triggered_level
                entry["resumption_mode"] = cb.active_resumption_mode
            halted.append(entry)
        self.pub_sock.send_multipart(make_halt_status_msg(gateway_id, halted))

    def _handle_session_schedule_request(self, payload: dict[str, Any]) -> None:
        """Return the session schedule configuration from the loaded engine config."""
        gateway_id = str(payload.get("gateway_id", "")).upper()
        schedule: dict[str, str] | None = None
        if self._engine_config and self._engine_config.schedule:
            s = self._engine_config.schedule
            schedule = {
                "pre_open": s.pre_open,
                "opening_auction_start": s.opening_auction_start,
                "continuous_start": s.continuous_start,
                "closing_auction_start": s.closing_auction_start,
                "closing_auction_end": s.closing_auction_end,
            }
        self.pub_sock.send_multipart(
            make_session_schedule_msg(gateway_id, self._sessions_enabled, schedule)
        )

    def _handle_gateways_request(self, payload: dict[str, Any]) -> None:
        """Return all configured gateways with their role and connection status."""
        gateway_id = str(payload.get("gateway_id", "")).upper()
        gateways: list[dict[str, Any]] = []
        if self._engine_config:
            for gw_id, cfg in sorted(self._engine_config.fix_gateways.items()):
                session = self._sessions.get(gw_id)
                connected = (session is not None and session.connected) or (
                    gw_id in self._connected_fix_gateways
                )
                gateways.append(
                    {
                        "id": gw_id,
                        "role": cfg.role.value,
                        "description": cfg.description,
                        "connected": connected,
                    }
                )
        self.pub_sock.send_multipart(make_gateways_msg(gateway_id, gateways))

    def _handle_volume_request(self, payload: dict[str, Any]) -> None:
        """Return daily traded volume totals per symbol and exchange-wide."""
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbols_vol: dict[str, dict[str, Any]] = {}
        total_qty = 0
        total_value = 0.0
        total_trades = 0
        for sym, book in sorted(self.books.items()):
            symbols_vol[sym] = {
                "qty": book.daily_qty,
                "value": round(book.daily_value, 2),
                "trades": book.daily_trades,
            }
            total_qty += book.daily_qty
            total_value += book.daily_value
            total_trades += book.daily_trades
        self.pub_sock.send_multipart(
            make_volume_msg(
                gateway_id,
                symbols_vol,
                total_qty,
                round(total_value, 2),
                total_trades,
            )
        )

    def _handle_gateway_connect(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        if not gateway_id:
            return

        session = self._session_for_gateway(gateway_id)

        if self._allowed_fix_gateways is None:
            # Backward-compat mode: no gateway restrictions
            self._connected_fix_gateways.add(gateway_id)
            session.connected = True
            self.pub_sock.send_multipart(
                make_gateway_auth_msg(gateway_id, accepted=True)
            )
            return

        if gateway_id not in self._allowed_fix_gateways:
            self.pub_sock.send_multipart(
                make_gateway_auth_msg(
                    gateway_id,
                    accepted=False,
                    reason=f"Gateway not configured: {gateway_id}",
                )
            )
            log.info(f"REFUSED gateway connect: {gateway_id}")
            return

        cfg = (
            self._engine_config.fix_gateways[gateway_id]
            if self._engine_config
            else None
        )
        if cfg:
            session.role = cfg.role
            session.disconnect_behaviour = cfg.disconnect_behaviour

        self._connected_fix_gateways.add(gateway_id)
        session.connected = True
        self.pub_sock.send_multipart(
            make_gateway_auth_msg(
                gateway_id,
                accepted=True,
                description=self._gateway_descriptions.get(gateway_id, ""),
            )
        )
        desc = self._gateway_descriptions.get(gateway_id, "")
        if desc:
            log.info(f"Gateway connected: {gateway_id} — {desc}")
        else:
            log.info(f"Gateway connected: {gateway_id}")

    def _handle_book_snapshot_request(self, payload: dict[str, Any]) -> None:
        symbol = payload.get("symbol", "").upper()
        if symbol in self.books:
            self.pub_sock.send_multipart(
                make_book_msg(symbol, self.books[symbol].snapshot())
            )
        # If symbol unknown (no orders yet), there is nothing to send;
        # the viewer will get its first update when the first order arrives.

    def _handle_orders_request(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        ok, _ = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(make_orders_msg(gateway_id, []))
            return
        orders: list[dict[str, Any]] = []
        for book in self.books.values():
            for order in book.resting_orders():
                if order.gateway_id == gateway_id:
                    orders.append(order_to_display_dict(order))
        self.pub_sock.send_multipart(make_orders_msg(gateway_id, orders))

    def _handle_quote_bootstrap_request(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbol_filter = str(payload.get("symbol", "")).upper()

        ok, _ = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(make_quote_bootstrap_msg(gateway_id, []))
            return

        order_by_id: dict[str, Order] = {}
        for book in self.books.values():
            for order in book.resting_orders():
                order_by_id[order.id] = order

        entries = self._quote_index.entries_for_gateway(gateway_id)
        if symbol_filter:
            entries = [e for e in entries if e.symbol == symbol_filter]

        quotes: list[dict[str, Any]] = []
        for entry in entries:
            bid = order_by_id.get(entry.bid_order_id)
            ask = order_by_id.get(entry.ask_order_id)
            if bid is None and ask is None:
                continue

            quotes.append(
                {
                    "quote_id": entry.quote_id,
                    "gateway_id": entry.gateway_id,
                    "symbol": entry.symbol,
                    "state": entry.state.value,
                    "bid_order_id": entry.bid_order_id,
                    "ask_order_id": entry.ask_order_id,
                    "bid_price": (
                        from_ticks(bid.price, bid.symbol)
                        if bid is not None and bid.price is not None
                        else None
                    ),
                    "ask_price": (
                        from_ticks(ask.price, ask.symbol)
                        if ask is not None and ask.price is not None
                        else None
                    ),
                    "bid_qty": bid.quantity if bid is not None else 0,
                    "ask_qty": ask.quantity if ask is not None else 0,
                    "bid_remaining_qty": bid.remaining_qty if bid is not None else 0,
                    "ask_remaining_qty": ask.remaining_qty if ask is not None else 0,
                    "bid_status": bid.status.value if bid is not None else "MISSING",
                    "ask_status": ask.status.value if ask is not None else "MISSING",
                }
            )

        self.pub_sock.send_multipart(make_quote_bootstrap_msg(gateway_id, quotes))

    def _handle_quote_legs_request(self, payload: dict[str, Any]) -> None:
        """Reply to a QLEGS snapshot request with the gateway's quote legs.

        ``ACTIVE`` legs come straight from ``QuoteIndex`` plus each leg's
        live order state (qty, remaining, status) — unchanged from before.

        ``RECENT``/``ALL`` are now served from ``QuoteIndex``'s bounded
        per-gateway history of recently-removed quotes (see
        ``QuoteIndex.recent_for_gateway``), populated at every point a quote
        is inactivated (fill, cancel, disconnect, kill switch, circuit
        breaker halt, etc.). This history is a *quote-level* summary, not a
        per-leg one: once an order leaves the book its live qty/remaining/
        status are no longer available anywhere in the engine, so recent
        rows report the quote's identity, final state, removal reason, and
        removal time instead of reconstructing per-leg fill detail. The
        history is in-memory only, bounded, and does not survive an engine
        restart — see docs/user-guide/180-persistence.md.

        ``complete`` is ``True`` whenever the reply honestly reflects what
        was asked for: ``ACTIVE`` is always complete, and ``RECENT``/``ALL``
        are now complete too (subject to the history buffer's bound — very
        old inactivations may have been evicted).
        """
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbol_filter = str(payload.get("symbol", "")).upper()
        show = str(payload.get("show", "ACTIVE")).upper() or "ACTIVE"

        ok, _ = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_quote_legs_msg(gateway_id, [], show_requested=show, complete=True)
            )
            return

        legs: list[dict[str, Any]] = []
        if show in ("ACTIVE", "ALL"):
            legs = self._active_quote_legs(gateway_id, symbol_filter)

        recent: list[dict[str, Any]] = []
        if show in ("RECENT", "ALL"):
            recent = self._recent_quote_legs(gateway_id, symbol_filter)

        self.pub_sock.send_multipart(
            make_quote_legs_msg(
                gateway_id,
                legs,
                show_requested=show,
                complete=True,
                recent=recent,
            )
        )

    def _active_quote_legs(
        self, gateway_id: str, symbol_filter: str
    ) -> list[dict[str, Any]]:
        """Build the ACTIVE leg rows for one gateway (unchanged behavior)."""
        order_by_id: dict[str, Order] = {}
        for book in self.books.values():
            for order in book.resting_orders():
                order_by_id[order.id] = order

        entries = self._quote_index.entries_for_gateway(gateway_id)
        if symbol_filter:
            entries = [e for e in entries if e.symbol == symbol_filter]

        legs: list[dict[str, Any]] = []
        for entry in entries:
            for leg_side, order_id in (
                ("BUY", entry.bid_order_id),
                ("SELL", entry.ask_order_id),
            ):
                leg_order = order_by_id.get(order_id)
                if leg_order is None:
                    continue
                legs.append(
                    {
                        "quote_id": entry.quote_id,
                        "order_id": leg_order.id,
                        "symbol": entry.symbol,
                        "leg_side": leg_side,
                        "qty": leg_order.quantity,
                        "remaining": leg_order.remaining_qty,
                        "filled": leg_order.quantity - leg_order.remaining_qty,
                        "status": leg_order.status.value,
                        "quote_status": entry.state.value,
                    }
                )
        return legs

    @staticmethod
    def _leg_snapshot_to_dict(
        leg: Optional[QuoteLegSnapshot],
    ) -> Optional[dict[str, Any]]:
        if leg is None:
            return None
        return {
            "order_id": leg.order_id,
            "qty": leg.qty,
            "remaining": leg.remaining,
            "filled": leg.filled,
            "status": leg.status,
        }

    def _recent_quote_legs(
        self, gateway_id: str, symbol_filter: str
    ) -> list[dict[str, Any]]:
        """Build RECENT rows from QuoteIndex's bounded inactivation history.

        Quote-level summary fields (see `_handle_quote_legs_request`
        docstring), most-recently-removed first, plus per-leg detail
        (`bid_leg`/`ask_leg`) when available.

        `QuoteEntry.state` is never mutated after creation (it is always
        the `ACTIVE` it started as), so it cannot be used to report a
        removed quote's final status. Instead, the final `quote_status` is
        derived from `reason`: fill-driven removals pass one of the
        `INACTIVE_*_FILLED` values as `reason` (see `_on_quote_leg_filled`),
        so that value doubles as the status; every other removal path is a
        cancellation of one kind or another (participant cancel, kill
        switch, disconnect, circuit breaker halt, replaced by a new quote,
        ...), so it is reported as `CANCELLED`.

        `bid_leg`/`ask_leg` carry each leg's final `order_id`/`qty`/
        `remaining`/`filled`/`status` at the moment its quote was removed,
        captured via `QuoteIndex.attach_leg_snapshots` (see
        `Engine._cancel_quote_entry` and `Engine._on_quote_leg_filled`).
        They are `None` on the rare entry recorded before its cancellation
        completed (e.g. process interrupted mid-cancel) — callers should
        treat a `None` leg as "detail unavailable," not "leg had no fill."
        """
        history = self._quote_index.recent_for_gateway(gateway_id, symbol_filter)
        fill_reasons = {
            QuoteState.INACTIVE_BID_FILLED.value,
            QuoteState.INACTIVE_ASK_FILLED.value,
        }
        return [
            {
                "quote_id": h.entry.quote_id,
                "symbol": h.entry.symbol,
                "bid_order_id": h.entry.bid_order_id,
                "ask_order_id": h.entry.ask_order_id,
                "quote_status": (
                    h.reason if h.reason in fill_reasons else QuoteState.CANCELLED.value
                ),
                "reason": h.reason,
                "removed_at_ns": h.removed_at_ns,
                "bid_leg": self._leg_snapshot_to_dict(h.bid_leg),
                "ask_leg": self._leg_snapshot_to_dict(h.ask_leg),
            }
            for h in history
        ]

    def _cancel_order_by_id(self, order_id: str) -> Optional[Order]:
        """Cancel a resting order by id.

        Returns the cancelled `Order` (reflecting its final qty/remaining/
        status at the moment of cancellation) so callers that need that
        detail — e.g. quote-leg history snapshots, see
        `_snapshot_quote_leg` — don't have to re-derive it. Returns `None`
        if the order could not be found or was already terminal; callers
        that only care about success/failure can keep using this as a
        truthy check, same as the previous `bool` return.
        """
        symbol = self._order_symbol.get(order_id)
        book = self.books.get(symbol) if symbol else None
        cancelled = book.cancel_order(order_id) if book else None
        if not cancelled:
            return None
        self._order_symbol.pop(order_id, None)
        self._mark_dirty(cancelled.symbol)
        # L8: echo the order's client_tag on the cancel so subscribers that
        # correlate on it don't miss quote/combo-driven cancels.
        self.pub_sock.send_multipart(
            make_cancelled_msg(
                cancelled.gateway_id, order_id, client_tag=cancelled.client_tag
            )
        )
        return cancelled

    @staticmethod
    def _snapshot_quote_leg(order: Optional[Order]) -> Optional[QuoteLegSnapshot]:
        """Build a `QuoteLegSnapshot` from a (possibly already-terminal)
        `Order`, or `None` if there is nothing to snapshot (e.g. the order
        was already gone before cancellation was attempted).
        """
        if order is None:
            return None
        return QuoteLegSnapshot(
            order_id=order.id,
            qty=order.quantity,
            remaining=order.remaining_qty,
            filled=order.quantity - order.remaining_qty,
            status=order.status.value,
        )

    def _cancel_quote_entry(self, entry: QuoteEntry, reason: str = "") -> int:
        cancelled = 0
        bid_order = self._cancel_order_by_id(entry.bid_order_id)
        if bid_order is not None:
            cancelled += 1
        ask_order = self._cancel_order_by_id(entry.ask_order_id)
        if ask_order is not None:
            cancelled += 1
        # entry has already been popped from the active QuoteIndex and its
        # quote-level history recorded by the caller (remove()/
        # cancel_all_for_*()) before _cancel_quote_entry runs — attach the
        # per-leg detail we just captured to that already-recorded entry.
        # See QuoteIndex.attach_leg_snapshots and
        # docs-design/EduMatcher-QLEGS-RECENT.md §9.3.
        self._quote_index.attach_leg_snapshots(
            entry.gateway_id,
            entry.quote_id,
            self._snapshot_quote_leg(bid_order),
            self._snapshot_quote_leg(ask_order),
        )
        self.pub_sock.send_multipart(
            make_quote_status_msg(entry.gateway_id, entry.quote_id, "CANCELLED", reason)
        )
        return cancelled

    def _publish_trade(self, trade: Any) -> None:
        _pub = self.pub_sock
        tick_decimals = get_tick_decimals(trade.symbol)
        _pub.send_multipart(
            [
                _TRADE_TOPIC,
                dumps(
                    {
                        "id": trade.id,
                        "symbol": trade.symbol,
                        "buy_order_id": trade.buy_order_id,
                        "sell_order_id": trade.sell_order_id,
                        "buy_gateway_id": trade.buy_gateway_id,
                        "sell_gateway_id": trade.sell_gateway_id,
                        "price": from_ticks(trade.price, trade.symbol),
                        "tick_decimals": tick_decimals,
                        "quantity": trade.quantity,
                        "aggressor_side": trade.aggressor_side,
                        "timestamp": trade.timestamp / 1_000_000_000,
                    }
                ),
            ]
        )
        # #10: update BOTH counterparties' position ledgers for every trade,
        # right here in the single trade-publication path — so fills produced
        # by any flow (new order, quote, combo, OCO leg, auction uncross,
        # stop cascade, amend rematch) are reflected in system.position_request.
        # Callers must NOT also call _update_position or positions double-count.
        _trade_px = from_ticks(trade.price, trade.symbol)
        self._update_position(
            trade.buy_gateway_id, trade.symbol, "BUY", trade.quantity, _trade_px
        )
        self._update_position(
            trade.sell_gateway_id, trade.symbol, "SELL", trade.quantity, _trade_px
        )

        # H4: feed the drop-copy (clearing/risk) feed from this single trade
        # path so EVERY fill reaches it — quote, combo, OCO, and auction fills
        # were previously invisible because drop copy was only wired into the
        # new-order loop.  One record per counterparty per execution.
        # M13: derive the liquidity flag from the aggressor side instead of
        # hard-coding MAKER — the taker side is the aggressor.
        if self._drop_copy is not None:
            _agg = trade.aggressor_side
            for _gw, _oid, _sd in (
                (trade.buy_gateway_id, trade.buy_order_id, "BUY"),
                (trade.sell_gateway_id, trade.sell_order_id, "SELL"),
            ):
                self._drop_copy.publish(
                    gateway_id=_gw,
                    event_type="order.fill",
                    payload={
                        "order_id": _oid,
                        "symbol": trade.symbol,
                        "fill_qty": trade.quantity,
                        "fill_price": _trade_px,
                        "liquidity_flag": "TAKER" if _sd == _agg else "MAKER",
                    },
                )

        # Circuit breaker monitor — check if this fill triggered a halt.
        # Inline the null-guard to skip the function-call overhead entirely
        # when no circuit breaker is configured for the symbol.
        if self._enforce_circuit_breakers:
            _cb = self._circuit_breakers.get(trade.symbol)
            if _cb is not None:
                self._check_circuit_breaker(trade.symbol, trade.price, trade.timestamp)

    @staticmethod
    def _order_fill_prices(trades: list[Any]) -> dict[str, float]:
        """Per-order volume-weighted execution price (display) from *trades*.

        H6: a fill message must report the price the order ACTUALLY executed
        at, not ``book.last_trade_price`` (the last level of the whole sweep).
        For an order that fills across multiple levels this is its VWAP; for a
        passive order filled at a single level it is exactly that level's price.
        """
        agg: dict[str, tuple[int, float]] = {}  # order_id -> (qty, notional)
        for t in trades:
            px = from_ticks(t.price, t.symbol)
            for oid in (t.buy_order_id, t.sell_order_id):
                qty, notional = agg.get(oid, (0, 0.0))
                agg[oid] = (qty + t.quantity, notional + px * t.quantity)
        return {oid: (n / q if q else 0.0) for oid, (q, n) in agg.items()}

    def _check_circuit_breaker(self, symbol: str, trade_price: int, now: int) -> None:
        """
        Called after every fill to check whether a circuit breaker halt should fire.

        If the rolling-window average has moved more than ``dynamic_band_pct``
        from the trigger price, the symbol is halted:
          - All resting quotes for the symbol are cancelled.
          - A ``circuit_breaker.halt.{symbol}`` message is broadcast.
          - ``_halted_symbols[symbol]`` is set to True so new orders are blocked.
        """
        if not self._enforce_circuit_breakers:
            return

        cb = self._circuit_breakers.get(symbol)
        if cb is None:
            return
        triggered_level = cb.record_trade(trade_price, now)
        if triggered_level is None:
            return

        cb.activate(now, triggered_level)
        self._halted_symbols[symbol] = True

        # Cancel all resting quotes for the halted symbol.
        # Fast-path: avoid cancellation traversal when no quotes exist.
        if self._quote_index.has_symbol(symbol):
            for entry in self._quote_index.cancel_all_for_symbol(
                symbol, reason="Circuit breaker halt"
            ):
                self._cancel_quote_entry(entry, reason="Circuit breaker halt")

        self.pub_sock.send_multipart(
            encode(
                f"circuit_breaker.halt.{symbol}",
                {
                    "symbol": symbol,
                    "trigger_price": (
                        from_ticks(cb.trigger_price, symbol)
                        if cb.trigger_price is not None
                        else None
                    ),
                    "reference_price": (
                        from_ticks(cb.reference_price, symbol)
                        if cb.reference_price is not None
                        else None
                    ),
                    "resume_at_ns": cb.resume_at_ns,
                    "resumption_mode": cb.active_resumption_mode,
                    "level": cb.triggered_level,
                },
            )
        )
        self._mark_dirty(symbol)
        log.info(
            f"CIRCUIT BREAKER HALT {symbol}: "
            f"level={cb.triggered_level} "
            f"trigger={cb.trigger_price}, ref={cb.reference_price} ticks"
        )

    def _flush_circuit_breakers(self) -> None:
        """
        Called once per poll loop tick.  Checks all halted symbols and resumes
        trading for those whose ``halt_duration_ns`` has elapsed.

        If ``resumption_mode == "AUCTION"``, the accumulated resting orders
        are uncrossed at the equilibrium price before continuous matching resumes.
        """
        now = now_ns()
        for symbol, cb in self._circuit_breakers.items():
            if not cb.should_resume(now):
                continue
            # Capture resumption_mode BEFORE deactivate() clears it.
            _resumption_mode = cb.active_resumption_mode
            cb.deactivate()
            self._halted_symbols[symbol] = False
            # M3: crossed interest accumulates while halted (LIMITs rest
            # unmatched).  Uncross it at the equilibrium price on EVERY resume,
            # not only AUCTION mode, so continuous trading never starts crossed.
            self._run_uncross(symbol_filter=symbol)
            self.pub_sock.send_multipart(
                encode(
                    f"circuit_breaker.resume.{symbol}",
                    {"symbol": symbol, "mode": _resumption_mode},
                )
            )
            self._mark_dirty(symbol)
            log.info(f"CIRCUIT BREAKER RESUME {symbol}")

    def _on_quote_leg_filled(self, order: Order) -> None:
        if not order.quote_id:
            return
        entry = self._quote_index.get(order.gateway_id, order.symbol)
        if not entry or entry.quote_id != order.quote_id:
            return

        cfg = (
            self._engine_config.fix_gateways.get(order.gateway_id)
            if self._engine_config
            else None
        )
        policy = (
            cfg.quote_refresh_policy
            if cfg is not None
            else QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL
        )

        should_inactivate = policy == QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL or (
            policy == QuoteRefreshPolicy.INACTIVATE_ON_FULL_FILL
            and order.status == OrderStatus.FILLED
        )
        if not should_inactivate:
            return

        status = (
            "INACTIVE_BID_FILLED" if order.side == Side.BUY else "INACTIVE_ASK_FILLED"
        )
        self._quote_index.remove(order.gateway_id, order.symbol, reason=status)
        sibling_id = entry.counterpart_order_id(order.side.value)
        sibling_order = self._cancel_order_by_id(sibling_id)

        # `order` is the filled leg — already terminal, its final state is
        # available directly. `sibling_order` is whatever _cancel_order_by_id
        # just returned for the other leg. Attach both to the history entry
        # remove() just recorded, same pattern as _cancel_quote_entry.
        filled_snapshot = self._snapshot_quote_leg(order)
        sibling_snapshot = self._snapshot_quote_leg(sibling_order)
        bid_leg = filled_snapshot if order.side == Side.BUY else sibling_snapshot
        ask_leg = sibling_snapshot if order.side == Side.BUY else filled_snapshot
        self._quote_index.attach_leg_snapshots(
            order.gateway_id, entry.quote_id, bid_leg, ask_leg
        )

        self.pub_sock.send_multipart(
            make_quote_status_msg(order.gateway_id, entry.quote_id, status)
        )

    def _handle_quote_new(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbol = str(payload.get("symbol", "")).upper()
        quote_id = str(payload.get("quote_id", ""))
        self._dbg_count("quote_requests")

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self._dbg_count("quote_reject_gateway")
            self.pub_sock.send_multipart(
                make_quote_ack_msg(gateway_id, quote_id, False, reason)
            )
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.MARKET_MAKER:
            self._dbg_count("quote_reject_role")
            self.pub_sock.send_multipart(
                make_quote_ack_msg(
                    gateway_id,
                    quote_id,
                    False,
                    "Quotes are only allowed for MARKET_MAKER participants",
                )
            )
            return

        if not symbol:
            self._dbg_count("quote_reject_payload")
            self.pub_sock.send_multipart(
                make_quote_ack_msg(gateway_id, quote_id, False, "Missing symbol")
            )
            return
        if self._allowed_symbols and symbol not in self._allowed_symbols:
            self._dbg_count("quote_reject_symbol")
            self.pub_sock.send_multipart(
                make_quote_ack_msg(
                    gateway_id,
                    quote_id,
                    False,
                    f"Symbol not configured: {symbol}",
                )
            )
            return

        # Halt check — circuit breaker has halted this symbol; reject incoming quotes
        if self._halted_symbols.get(symbol):
            self._dbg_count("quote_reject_halt")
            self.pub_sock.send_multipart(
                make_quote_ack_msg(
                    gateway_id,
                    quote_id,
                    False,
                    f"{symbol} is halted — quotes rejected during circuit breaker halt",
                )
            )
            return

        # #16: quotes are subject to the same session gating as ordinary orders.
        # Reject outright when the market is not accepting orders (e.g. CLOSED).
        if self._sessions_enabled and not accepts_orders(self._session_state):
            self._dbg_count("quote_reject_session")
            self.pub_sock.send_multipart(
                make_quote_ack_msg(gateway_id, quote_id, False, "Market is closed")
            )
            return

        try:
            bid_price = to_ticks(float(payload["bid_price"]), symbol)
            ask_price = to_ticks(float(payload["ask_price"]), symbol)
            bid_qty = int(payload["bid_qty"])
            ask_qty = int(payload["ask_qty"])
            tif = TIF(str(payload.get("tif", "DAY")).upper())
        except (KeyError, TypeError, ValueError):
            self._dbg_count("quote_reject_payload")
            self.pub_sock.send_multipart(
                make_quote_ack_msg(gateway_id, quote_id, False, "Invalid quote payload")
            )
            return

        if bid_qty <= 0 or ask_qty <= 0:
            self._dbg_count("quote_reject_payload")
            self.pub_sock.send_multipart(
                make_quote_ack_msg(
                    gateway_id, quote_id, False, "Quote quantities must be positive"
                )
            )
            return
        if bid_price >= ask_price:
            self._dbg_count("quote_reject_payload")
            self.pub_sock.send_multipart(
                make_quote_ack_msg(
                    gateway_id, quote_id, False, "Quote requires bid_price < ask_price"
                )
            )
            return

        cfg = (
            self._engine_config.fix_gateways.get(gateway_id)
            if self._engine_config
            else None
        )
        enforce_mm = False
        mm_max_spread_ticks = 0
        mm_min_qty = 0
        # Quote legs have no per-request SMP concept of their own -- always
        # resolve from the gateway's configured default (or SmpAction.NONE).
        smp_action = self._resolve_smp_action(gateway_id, None)
        if cfg:
            enforce_mm = cfg.enforce_mm_obligation
            mm_max_spread_ticks = cfg.mm_max_spread_ticks
            mm_min_qty = cfg.mm_min_qty

            # Specificity precedence for MM obligation policy:
            # gateway+symbol > global symbol > gateway > global defaults.
            if self._engine_config is not None:
                global_symbol_policy = (
                    self._engine_config.global_symbol_mm_obligation_policies.get(symbol)
                )
                if global_symbol_policy is not None:
                    enforce_mm = global_symbol_policy.enforce_mm_obligation
                    mm_max_spread_ticks = global_symbol_policy.mm_max_spread_ticks
                    mm_min_qty = global_symbol_policy.mm_min_qty

            gateway_symbol_policy = cfg.mm_obligation_policies.get(symbol)
            if gateway_symbol_policy is not None:
                enforce_mm = gateway_symbol_policy.enforce_mm_obligation
                mm_max_spread_ticks = gateway_symbol_policy.mm_max_spread_ticks
                mm_min_qty = gateway_symbol_policy.mm_min_qty

        if cfg and enforce_mm:
            spread_ticks = ask_price - bid_price
            if spread_ticks > mm_max_spread_ticks:
                self._dbg_count("quote_reject_mm_obligation")
                self.pub_sock.send_multipart(
                    make_quote_ack_msg(
                        gateway_id,
                        quote_id,
                        False,
                        (
                            f"Spread {spread_ticks} ticks exceeds max "
                            f"{mm_max_spread_ticks}"
                        ),
                    )
                )
                return
            if bid_qty < mm_min_qty or ask_qty < mm_min_qty:
                self._dbg_count("quote_reject_mm_obligation")
                self.pub_sock.send_multipart(
                    make_quote_ack_msg(
                        gateway_id,
                        quote_id,
                        False,
                        f"Quote size must be >= {mm_min_qty}",
                    )
                )
                return

        previous = self._quote_index.remove(
            gateway_id, symbol, reason="Replaced by new quote"
        )
        if previous:
            self._cancel_quote_entry(previous, reason="Replaced by new quote")

        if not quote_id:
            quote_id = f"{gateway_id}-{symbol}-{now_ns()}"

        bid = Order.create(
            symbol=symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=bid_qty,
            gateway_id=gateway_id,
            tif=tif,
            price=bid_price,
            smp_action=smp_action,
        )
        ask = Order.create(
            symbol=symbol,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=ask_qty,
            gateway_id=gateway_id,
            tif=tif,
            price=ask_price,
            smp_action=smp_action,
        )
        bid.origin = OrderOrigin.QUOTE
        ask.origin = OrderOrigin.QUOTE
        bid.quote_id = quote_id
        ask.quote_id = quote_id

        self._order_symbol[bid.id] = symbol
        self._order_symbol[ask.id] = symbol
        entry = QuoteEntry(
            quote_id=quote_id,
            gateway_id=gateway_id,
            symbol=symbol,
            bid_order_id=bid.id,
            ask_order_id=ask.id,
        )
        self._quote_index.put(entry)

        now = now_ns()
        book = self._book(symbol)
        # #16: only match continuously in CONTINUOUS session state; in auction
        # phases (PRE_OPEN etc.) quote legs rest and cross at the uncross.
        do_match = is_matching_enabled(self._session_state)
        for quote_order in (bid, ask):
            trades, events = book.process(quote_order, match=do_match, now=now)
            # H5: dedup fills — an order sweeping k levels appears k times in
            # `events`, each reflecting the FINAL cumulative qty; publishing all
            # k would overcount for consumers summing fill_qty.
            # H6: report each order's own VWAP execution price.
            _q_fill_px = self._order_fill_prices(trades)
            _pub_fill_ids: set[str] = set()
            _pub_cancel_ids: set[str] = set()
            for evt in events:
                if evt.status in _FILL_STATUSES:
                    if evt.id not in _pub_fill_ids:
                        _pub_fill_ids.add(evt.id)
                        self.pub_sock.send_multipart(
                            make_fill_msg(
                                evt.gateway_id,
                                evt.id,
                                fill_qty=evt.quantity - evt.remaining_qty,
                                fill_price=_q_fill_px.get(
                                    evt.id,
                                    (
                                        from_ticks(book.last_trade_price, evt.symbol)
                                        if book.last_trade_price is not None
                                        else 0.0
                                    ),
                                ),
                                remaining_qty=evt.remaining_qty,
                                status=evt.status.value,
                                order=evt.to_dict(),
                            )
                        )
                        if evt.quote_id:
                            self._on_quote_leg_filled(evt)
                elif evt.status == OrderStatus.CANCELLED:
                    if evt.id not in _pub_cancel_ids:
                        _pub_cancel_ids.add(evt.id)
                        self.pub_sock.send_multipart(
                            make_cancelled_msg(evt.gateway_id, evt.id)
                        )
            for trade in trades:
                self._publish_trade(trade)

        self._mark_dirty(symbol)
        self.pub_sock.send_multipart(
            make_quote_ack_msg(
                gateway_id,
                quote_id,
                True,
                bid_order_id=bid.id,
                ask_order_id=ask.id,
            )
        )
        self._dbg_count("quote_accepted")
        self.pub_sock.send_multipart(
            make_quote_status_msg(gateway_id, quote_id, "ACTIVE")
        )

    def _handle_quote_cancel(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbol = str(payload.get("symbol", "")).upper()

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_quote_ack_msg(gateway_id, "", False, reason)
            )
            return

        entry = self._quote_index.remove(
            gateway_id, symbol, reason="Cancelled by participant"
        )
        if not entry:
            self.pub_sock.send_multipart(
                make_quote_ack_msg(gateway_id, "", False, "No active quote for symbol")
            )
            return

        self._cancel_quote_entry(entry, reason="Cancelled by participant")
        self.pub_sock.send_multipart(
            make_quote_ack_msg(gateway_id, entry.quote_id, True)
        )

    def _handle_gateway_disconnect(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        if not gateway_id:
            return

        session = self._session_for_gateway(gateway_id)
        session.connected = False
        self._connected_fix_gateways.discard(gateway_id)

        # Republish the disconnect on the PUB feed as the lifecycle counterpart
        # to system.gateway_auth.{id}, so PUB-only subscribers (e.g. clearing)
        # can close the matching session.  Emitted before any behaviour-specific
        # early return so it always fires.
        reason = str(payload.get("reason", ""))
        self.pub_sock.send_multipart(make_gateway_bye_msg(gateway_id, reason))

        if session.disconnect_behaviour == DisconnectBehaviour.LEAVE_ALL:
            return

        removed_quotes = self._quote_index.cancel_all_for_gateway(
            gateway_id, reason="Gateway disconnected"
        )
        for entry in removed_quotes:
            self._cancel_quote_entry(entry, reason="Gateway disconnected")

        if session.disconnect_behaviour == DisconnectBehaviour.CANCEL_ALL:
            for book in self.books.values():
                for order in list(book.resting_orders()):
                    if (
                        order.gateway_id == gateway_id
                        and order.origin != OrderOrigin.QUOTE
                    ):
                        self._cancel_order_by_id(order.id)

    def _handle_kill_switch(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbol_filter = str(payload.get("symbol", "")).upper()

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_kill_switch_ack_msg(gateway_id, False, reason)
            )
            return

        cancelled_orders = 0
        cancelled_quotes = 0

        if symbol_filter:
            entry = self._quote_index.get(gateway_id, symbol_filter)
            if entry is not None:
                self._quote_index.remove(
                    gateway_id, symbol_filter, reason="Kill switch"
                )
                cancelled_quotes += self._cancel_quote_entry(
                    entry, reason="Kill switch"
                )
        else:
            entries = self._quote_index.cancel_all_for_gateway(
                gateway_id, reason="Kill switch"
            )
            for entry in entries:
                cancelled_quotes += self._cancel_quote_entry(
                    entry, reason="Kill switch"
                )

        for book in self.books.values():
            if symbol_filter and book.symbol != symbol_filter:
                continue
            for order in list(book.resting_orders()):
                if order.gateway_id == gateway_id and order.origin != OrderOrigin.QUOTE:
                    if self._cancel_order_by_id(order.id):
                        cancelled_orders += 1

        self.pub_sock.send_multipart(
            make_kill_switch_ack_msg(
                gateway_id,
                True,
                cancelled_orders=cancelled_orders,
                cancelled_quotes=cancelled_quotes,
            )
        )

    def _handle_circuit_breaker_halt_all(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_circuit_breaker_halt_all_ack_msg(gateway_id, False, reason)
            )
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            self.pub_sock.send_multipart(
                make_circuit_breaker_halt_all_ack_msg(
                    gateway_id,
                    False,
                    "Global circuit-breaker halt is only allowed for ADMIN participants",
                )
            )
            return

        symbols: set[str] = set(self.books.keys())
        symbols.update(self._circuit_breakers.keys())
        symbols.update(self._halted_symbols.keys())
        if self._allowed_symbols is not None:
            symbols.update(self._allowed_symbols)
        elif self._engine_config is not None:
            symbols.update(self._engine_config.symbols.keys())

        now = now_ns()
        cancelled_quotes = 0
        for symbol in sorted(symbols):
            self._halted_symbols[symbol] = True

            cb = self._circuit_breakers.get(symbol)
            if cb is not None:
                cb.halted = True
                cb.halted_at_ns = now
                cb.resume_at_ns = None
                cb.trigger_price = None
                cb.reference_price = None
                cb.triggered_level = "ADMIN_ALL"
                cb.active_resumption_mode = "MANUAL"

            for entry in self._quote_index.cancel_all_for_symbol(
                symbol, reason="Global circuit breaker halt"
            ):
                cancelled_quotes += self._cancel_quote_entry(
                    entry, reason="Global circuit breaker halt"
                )

            self.pub_sock.send_multipart(
                encode(
                    f"circuit_breaker.halt.{symbol}",
                    {
                        "symbol": symbol,
                        "trigger_price": None,
                        "reference_price": None,
                        "resume_at_ns": None,
                        "resumption_mode": "MANUAL",
                        "level": "ADMIN_ALL",
                    },
                )
            )
            self._mark_dirty(symbol)

        self.pub_sock.send_multipart(
            make_circuit_breaker_halt_all_ack_msg(
                gateway_id,
                True,
                halted_symbols=len(symbols),
                cancelled_quotes=cancelled_quotes,
            )
        )

    def _handle_circuit_breaker_resume_all(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_circuit_breaker_resume_all_ack_msg(gateway_id, False, reason)
            )
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            self.pub_sock.send_multipart(
                make_circuit_breaker_resume_all_ack_msg(
                    gateway_id,
                    False,
                    "Global circuit-breaker resume is only allowed for ADMIN participants",
                )
            )
            return

        # Collect every symbol that is currently halted
        halted_symbols = sorted(
            sym for sym, halted in self._halted_symbols.items() if halted
        )

        for symbol in halted_symbols:
            self._halted_symbols[symbol] = False

            cb = self._circuit_breakers.get(symbol)
            if cb is not None:
                cb.deactivate()

            self.pub_sock.send_multipart(
                encode(
                    f"circuit_breaker.resume.{symbol}",
                    {"symbol": symbol, "mode": "MANUAL"},
                )
            )
            self._mark_dirty(symbol)

        self.pub_sock.send_multipart(
            make_circuit_breaker_resume_all_ack_msg(
                gateway_id,
                True,
                resumed_symbols=len(halted_symbols),
            )
        )
        if halted_symbols:
            log.info(
                f"ADMIN CIRCUIT BREAKER RESUME ALL — "
                f"{len(halted_symbols)} symbol(s): {', '.join(halted_symbols)}"
            )

    def _handle_symbol_halt(self, payload: dict[str, Any]) -> None:
        """Halt trading on a single symbol (ADMIN only)."""
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbol = str(payload.get("symbol", "")).upper()

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_symbol_halt_ack_msg(gateway_id, symbol, False, reason)
            )
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            self.pub_sock.send_multipart(
                make_symbol_halt_ack_msg(
                    gateway_id,
                    symbol,
                    False,
                    "Per-symbol halt is only allowed for ADMIN participants",
                )
            )
            return

        if not symbol:
            self.pub_sock.send_multipart(
                make_symbol_halt_ack_msg(gateway_id, symbol, False, "symbol required")
            )
            return

        if self._allowed_symbols is not None and symbol not in self._allowed_symbols:
            self.pub_sock.send_multipart(
                make_symbol_halt_ack_msg(
                    gateway_id, symbol, False, f"Unknown symbol: {symbol}"
                )
            )
            return

        now = now_ns()
        self._halted_symbols[symbol] = True

        cb = self._circuit_breakers.get(symbol)
        if cb is not None:
            cb.halted = True
            cb.halted_at_ns = now
            cb.resume_at_ns = None
            cb.trigger_price = None
            cb.reference_price = None
            cb.triggered_level = "ADMIN_SYMBOL"
            cb.active_resumption_mode = "MANUAL"

        cancelled_quotes = 0
        for entry in self._quote_index.cancel_all_for_symbol(
            symbol, reason="Per-symbol halt"
        ):
            cancelled_quotes += self._cancel_quote_entry(
                entry, reason="Per-symbol halt"
            )

        self.pub_sock.send_multipart(
            encode(
                f"circuit_breaker.halt.{symbol}",
                {
                    "symbol": symbol,
                    "trigger_price": None,
                    "reference_price": None,
                    "resume_at_ns": None,
                    "resumption_mode": "MANUAL",
                    "level": "ADMIN_SYMBOL",
                },
            )
        )
        self._mark_dirty(symbol)

        self.pub_sock.send_multipart(
            make_symbol_halt_ack_msg(
                gateway_id,
                symbol,
                True,
                cancelled_quotes=cancelled_quotes,
            )
        )
        log.info(f"ADMIN SYMBOL HALT — {symbol} by {gateway_id}")

    def _handle_symbol_resume(self, payload: dict[str, Any]) -> None:
        """Resume a single symbol that was halted by a per-symbol or global halt (ADMIN only)."""
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbol = str(payload.get("symbol", "")).upper()

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_symbol_resume_ack_msg(gateway_id, symbol, False, reason)
            )
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            self.pub_sock.send_multipart(
                make_symbol_resume_ack_msg(
                    gateway_id,
                    symbol,
                    False,
                    "Per-symbol resume is only allowed for ADMIN participants",
                )
            )
            return

        if not symbol:
            self.pub_sock.send_multipart(
                make_symbol_resume_ack_msg(gateway_id, symbol, False, "symbol required")
            )
            return

        if not self._halted_symbols.get(symbol):
            self.pub_sock.send_multipart(
                make_symbol_resume_ack_msg(
                    gateway_id, symbol, False, f"{symbol} is not halted"
                )
            )
            return

        self._halted_symbols[symbol] = False

        cb = self._circuit_breakers.get(symbol)
        if cb is not None:
            cb.deactivate()

        self.pub_sock.send_multipart(
            encode(
                f"circuit_breaker.resume.{symbol}",
                {"symbol": symbol, "mode": "MANUAL"},
            )
        )
        self._mark_dirty(symbol)

        self.pub_sock.send_multipart(
            make_symbol_resume_ack_msg(gateway_id, symbol, True)
        )
        log.info(f"ADMIN SYMBOL RESUME — {symbol} by {gateway_id}")

    def _handle_cancel_symbol(self, payload: dict[str, Any]) -> None:
        """Cancel all resting orders for a symbol across every gateway (ADMIN only)."""
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbol = str(payload.get("symbol", "")).upper()

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_cancel_symbol_ack_msg(gateway_id, symbol, False, reason)
            )
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            self.pub_sock.send_multipart(
                make_cancel_symbol_ack_msg(
                    gateway_id,
                    symbol,
                    False,
                    "Symbol-level mass cancel is only allowed for ADMIN participants",
                )
            )
            return

        if not symbol:
            self.pub_sock.send_multipart(
                make_cancel_symbol_ack_msg(gateway_id, symbol, False, "symbol required")
            )
            return

        book = self.books.get(symbol)
        cancelled_orders = 0
        if book is not None:
            for order in list(book.resting_orders()):
                if order.origin != OrderOrigin.QUOTE:
                    if self._cancel_order_by_id(order.id):
                        cancelled_orders += 1

        cancelled_quotes = 0
        for entry in self._quote_index.cancel_all_for_symbol(
            symbol, reason="Symbol mass cancel"
        ):
            cancelled_quotes += self._cancel_quote_entry(
                entry, reason="Symbol mass cancel"
            )

        self.pub_sock.send_multipart(
            make_cancel_symbol_ack_msg(
                gateway_id,
                symbol,
                True,
                cancelled_orders=cancelled_orders,
                cancelled_quotes=cancelled_quotes,
            )
        )
        log.info(
            f"ADMIN CANCEL SYMBOL — {symbol} by {gateway_id}:"
            f" orders={cancelled_orders} quotes={cancelled_quotes}"
        )

    # ------------------------------------------------------------------
    # Combo-order handlers
    # ------------------------------------------------------------------

    def _validate_combo(self, combo: ComboOrder) -> str:
        """Return an error string if the combo is invalid, else empty string."""
        if len(combo.legs) < 2:
            return "Combo requires at least 2 legs"
        if len(combo.legs) > 10:
            return "Combo supports at most 10 legs"

        symbols_in_combo = [leg.symbol for leg in combo.legs]
        if len(set(symbols_in_combo)) != len(symbols_in_combo):
            return "Duplicate symbols in combo legs"

        for leg in combo.legs:
            if self._allowed_symbols and leg.symbol not in self._allowed_symbols:
                return f"Symbol not configured: {leg.symbol}"

        for i, leg in enumerate(combo.legs):
            if leg.quantity <= 0:
                return f"Leg {i}: invalid quantity {leg.quantity}"
            needs_price = leg.order_type in (
                OrderType.LIMIT,
                OrderType.FOK,
                OrderType.STOP_LIMIT,
                OrderType.ICEBERG,
            )
            if needs_price and leg.price is None:
                return f"Leg {i}: {leg.order_type.value} requires a price"

        return ""

    def _accept_combo(self, combo: ComboOrder, *, publish_ack: bool = True) -> bool:
        """Post combo child orders to books and start tracking the parent combo."""
        reason = self._validate_combo(combo)
        if reason:
            if publish_ack:
                self.pub_sock.send_multipart(
                    make_combo_ack_msg(combo.gateway_id, combo.combo_id, False, reason)
                )
            return False

        log.info(
            f"COMBO {combo.combo_id} accepted "
            f"({len(combo.legs)} legs) from {combo.gateway_id}"
        )

        # M5: all-or-none combos must not execute ANY leg unless EVERY leg can
        # fully fill simultaneously.  Pre-check each leg's fillability; if any
        # leg is short, post all legs without matching (they rest as pending
        # interest) so no partial, non-atomic execution occurs.
        aon_blocked = False
        if combo.combo_type == ComboType.AON:
            aon_blocked = not all(
                self._book(leg.symbol).fillable_quantity(leg.side, leg.price)
                >= leg.quantity
                for leg in combo.legs
            )

        # Create child orders and post to books
        for i, leg in enumerate(combo.legs):
            # SMP=None on a leg means it was omitted (either by the client on
            # a live combo, or by an unset market_maker_combos[].legs[]
            # config seed) -- fall back to the gateway's configured default.
            leg_smp_action = self._resolve_smp_action(combo.gateway_id, leg.smp_action)
            child = Order.create(
                symbol=leg.symbol,
                side=leg.side,
                order_type=leg.order_type,
                quantity=leg.quantity,
                gateway_id=combo.gateway_id,
                tif=combo.tif,
                price=leg.price,
                stop_price=leg.stop_price,
                visible_qty=None,
                smp_action=leg_smp_action,
            )
            child.combo_parent_id = combo.id
            child.leg_index = i

            combo.child_order_ids.append(child.id)
            combo.leg_statuses[i] = OrderStatus.NEW.value
            combo.leg_fill_qty[i] = 0
            self._order_to_combo[child.id] = combo.id
            self._order_symbol[child.id] = leg.symbol

            book = self._book(leg.symbol)
            # H9: combo children respect the session's matching state and the
            # per-symbol halt, exactly like ordinary orders — no continuous
            # matching outside CONTINUOUS or while the leg's symbol is halted.
            # M5: an AON combo with any unfillable leg matches nothing.
            do_match = (
                is_matching_enabled(self._session_state)
                and not self._halted_symbols.get(leg.symbol)
                and not aon_blocked
            )
            trades, events = book.process(child, match=do_match)

            # H5: dedup fills/terminals — a child sweeping k levels appears k
            # times in `events` with the final cumulative qty on every copy.
            # H6: report each order's own VWAP execution price.
            _c_fill_px = self._order_fill_prices(trades)
            _pub_fill_ids: set[str] = set()
            _pub_terminal_ids: set[str] = set()
            for evt in events:
                if evt.status in (OrderStatus.PARTIAL, OrderStatus.FILLED):
                    if evt.id not in _pub_fill_ids:
                        _pub_fill_ids.add(evt.id)
                        self.pub_sock.send_multipart(
                            make_fill_msg(
                                evt.gateway_id,
                                evt.id,
                                fill_qty=evt.quantity - evt.remaining_qty,
                                fill_price=_c_fill_px.get(
                                    evt.id,
                                    (
                                        from_ticks(book.last_trade_price, evt.symbol)
                                        if book.last_trade_price is not None
                                        else 0.0
                                    ),
                                ),
                                remaining_qty=evt.remaining_qty,
                                status=evt.status.value,
                                order=evt.to_dict(),
                            )
                        )
                    if evt.combo_parent_id and evt.id != child.id:
                        self._check_combo_after_child_event(evt)
                elif evt.status == OrderStatus.REJECTED:
                    if evt.id not in _pub_terminal_ids:
                        _pub_terminal_ids.add(evt.id)
                        self.pub_sock.send_multipart(
                            make_ack_msg(
                                evt.gateway_id,
                                evt.id,
                                accepted=False,
                                reason="Insufficient liquidity",
                            )
                        )
                elif evt.status == OrderStatus.CANCELLED:
                    if evt.id not in _pub_terminal_ids:
                        _pub_terminal_ids.add(evt.id)
                        self.pub_sock.send_multipart(
                            make_cancelled_msg(evt.gateway_id, evt.id)
                        )
                    if evt.combo_parent_id and evt.id != child.id:
                        self._check_combo_after_child_event(evt)

            for trade in trades:
                self._publish_trade(trade)

            self._mark_dirty(leg.symbol)
            combo.leg_statuses[i] = child.status.value
            combo.leg_fill_qty[i] = child.quantity - child.remaining_qty

        self._combos[combo.id] = combo

        # Emit ACK after child creation so child_order_ids is populated
        if publish_ack:
            self.pub_sock.send_multipart(
                make_combo_ack_msg(
                    combo.gateway_id, combo.combo_id, True, combo=combo.to_dict()
                )
            )

        self._update_combo_status(combo)
        return True

    def _handle_combo_order(self, payload: dict[str, Any]) -> None:
        """Accept a combo, create child orders on respective books."""
        combo = ComboOrder.from_dict(payload)

        # Boundary conversion: combo legs may arrive in display price units.
        for leg in combo.legs:
            if leg.price is not None and isinstance(leg.price, float):
                leg.price = to_ticks(leg.price, leg.symbol)
            if leg.stop_price is not None and isinstance(leg.stop_price, float):
                leg.stop_price = to_ticks(leg.stop_price, leg.symbol)

        # Gateway auth
        ok, reason = self._gateway_status(combo.gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_combo_ack_msg(combo.gateway_id, combo.combo_id, False, reason)
            )
            return
        if self._sessions_enabled and not accepts_orders(self._session_state):
            self.pub_sock.send_multipart(
                make_combo_ack_msg(
                    combo.gateway_id, combo.combo_id, False, "Market is closed"
                )
            )
            return
        self._accept_combo(combo, publish_ack=True)

    def _handle_combo_cancel(self, payload: dict[str, Any]) -> None:
        """Cancel a combo and all its resting child legs."""
        gateway_id = str(payload.get("gateway_id", "")).upper()
        combo_id = payload.get("combo_id", "")

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_combo_ack_msg(gateway_id, combo_id, False, reason)
            )
            return

        # Find the combo by user-provided combo_id
        combo = None
        for c in self._combos.values():
            if c.combo_id == combo_id and c.gateway_id == gateway_id:
                combo = c
                break
        if not combo:
            self.pub_sock.send_multipart(
                make_combo_ack_msg(gateway_id, combo_id, False, "Combo not found")
            )
            return
        if combo.status in (
            ComboStatus.MATCHED,
            ComboStatus.FAILED,
            ComboStatus.CANCELLED,
            ComboStatus.REJECTED,
        ):
            self.pub_sock.send_multipart(
                make_combo_ack_msg(
                    gateway_id, combo_id, False, f"Combo already {combo.status.value}"
                )
            )
            return

        self._cascade_cancel_combo(combo, ComboStatus.CANCELLED)

    def _check_combo_after_child_event(self, child_order: Order) -> None:
        """Called after any child order fill/cancel/expire to update combo state."""
        combo_id = self._order_to_combo.get(child_order.id)
        if not combo_id:
            return
        combo = self._combos.get(combo_id)
        if not combo:
            return
        if combo.status in (
            ComboStatus.MATCHED,
            ComboStatus.FAILED,
            ComboStatus.CANCELLED,
            ComboStatus.REJECTED,
        ):
            return

        idx = child_order.leg_index
        if idx is None:
            return
        combo.leg_statuses[idx] = child_order.status.value
        combo.leg_fill_qty[idx] = child_order.quantity - child_order.remaining_qty

        if child_order.status in (OrderStatus.CANCELLED, OrderStatus.EXPIRED):
            self._cascade_cancel_combo(
                combo,
                ComboStatus.FAILED,
                reason=f"Leg {idx} ({child_order.symbol}) "
                f"{child_order.status.value}",
            )
            return

        self._update_combo_status(combo)

    def _update_combo_status(self, combo: ComboOrder) -> None:
        """Transition combo status based on current leg states."""
        if combo.is_fully_filled:
            combo.status = ComboStatus.MATCHED
            self.pub_sock.send_multipart(
                make_combo_status_msg(
                    combo.gateway_id, combo.combo_id, ComboStatus.MATCHED.value
                )
            )
            log.info(f"COMBO {combo.combo_id} MATCHED (all legs filled)")
            return

        # Check if at least one leg has partial or full fill
        has_fill = any(
            s in (OrderStatus.PARTIAL.value, OrderStatus.FILLED.value)
            for s in combo.leg_statuses.values()
        )
        if has_fill and combo.status == ComboStatus.PENDING:
            combo.status = ComboStatus.PARTIALLY_MATCHED
            self.pub_sock.send_multipart(
                make_combo_status_msg(
                    combo.gateway_id,
                    combo.combo_id,
                    ComboStatus.PARTIALLY_MATCHED.value,
                )
            )

    def _cascade_cancel_combo(
        self, combo: ComboOrder, terminal_status: ComboStatus, reason: str = ""
    ) -> None:
        """Cancel all resting child legs and mark combo as terminal."""
        combo.status = terminal_status

        for child_id in combo.child_order_ids:
            symbol = self._order_symbol.get(child_id)
            book = self.books.get(symbol) if symbol else None
            if book:
                cancelled = book.cancel_order(child_id)
                if cancelled:
                    self.pub_sock.send_multipart(
                        make_cancelled_msg(combo.gateway_id, child_id)
                    )
                    self._mark_dirty(symbol)  # type: ignore[arg-type]
            self._order_symbol.pop(child_id, None)
            self._order_to_combo.pop(child_id, None)

        self.pub_sock.send_multipart(
            make_combo_status_msg(
                combo.gateway_id,
                combo.combo_id,
                terminal_status.value,
                details={"reason": reason} if reason else None,
            )
        )
        log.info(
            f"COMBO {combo.combo_id} {terminal_status.value}"
            + (f" — {reason}" if reason else "")
        )

    # ------------------------------------------------------------------
    # Session / auction transitions
    # ------------------------------------------------------------------

    def _handle_session_transition(self, payload: dict[str, Any]) -> None:
        """Handle a session.transition message from the scheduler."""
        if not self._sessions_enabled:
            return

        try:
            to_state = SessionState(payload["to_state"])
        except (KeyError, ValueError) as exc:
            log.warning("Invalid session transition: %s", exc)
            return

        from_state = self._session_state

        # Validate transition
        allowed = VALID_TRANSITIONS.get(from_state, set())
        if to_state not in allowed:
            log.warning(
                "Invalid transition %s → %s (allowed: %s)",
                from_state.value,
                to_state.value,
                ", ".join(s.value for s in allowed),
            )
            return

        # --- Uncrossing on exit from auction / no-matching phases ---
        needs_uncross = not is_matching_enabled(from_state) and (
            is_matching_enabled(to_state) or to_state == SessionState.CLOSED
        )
        if needs_uncross:
            self._run_uncross()

        # --- Expire auction-only orders when their window closes ---
        if from_state == SessionState.OPENING_AUCTION:
            self._expire_tif(TIF.ATO)
        if from_state == SessionState.CLOSING_AUCTION:
            self._expire_tif(TIF.ATC)

        # --- Apply the transition ---
        self._session_state = to_state

        if to_state == SessionState.CLOSED:
            # M14: the close is the day boundary — expire all resting DAY orders
            # so they do not silently carry into the next trading day (they were
            # previously only expired at process shutdown).
            self._expire_tif(TIF.DAY)
            # End-of-day reset for any still-halted symbols (e.g. L3 rest-of-day).
            for symbol, cb in self._circuit_breakers.items():
                if cb.halted:
                    cb.deactivate()
                    self._halted_symbols[symbol] = False

        if to_state == SessionState.PRE_OPEN:
            # M14: reset per-symbol 'daily' counters at the start of a new
            # trading day so a multi-day run does not report cumulative volume.
            for book in self.books.values():
                book.daily_qty = 0
                book.daily_value_ticks = 0
                book.daily_trades = 0

        self.pub_sock.send_multipart(
            make_session_state_msg(to_state.value, prev_state=from_state.value)
        )
        log.info(f"Session: {from_state.value} → {to_state.value}")

    def _expire_tif(self, tif: TIF) -> None:
        """Expire all resting orders with the given TIF."""
        for book in self.books.values():
            for order in book.resting_orders():
                if order.tif == tif:
                    cancelled = book.cancel_order(order.id)
                    if cancelled:
                        cancelled.status = OrderStatus.EXPIRED
                        self.pub_sock.send_multipart(
                            make_expired_msg(cancelled.gateway_id, cancelled.id)
                        )
                        self._order_symbol.pop(cancelled.id, None)
                        if cancelled.combo_parent_id:
                            self._check_combo_after_child_event(cancelled)
                        self._mark_dirty(book.symbol)

    def _run_uncross(
        self,
        symbol_filter: str | None = None,
    ) -> None:
        """Run the equilibrium-price uncrossing on every (or one) symbol book.

        Parameters
        ----------
        symbol_filter : When provided, only uncross this specific symbol.
                        Used by ``_flush_circuit_breakers()`` for per-symbol
                        resumption auctions.
        """
        for symbol, book in self.books.items():
            if symbol_filter is not None and symbol != symbol_filter:
                continue
            result = compute_equilibrium(book)
            trades: list[Any] = []
            if result.eq_price is not None and result.eq_qty > 0:
                trades, events = execute_uncross(book, result.eq_price)

                # H5: dedup fills — an order that crosses multiple counterparties
                # in the uncross appears once per fill in `events`, each with the
                # final cumulative qty.
                _pub_fill_ids: set[str] = set()
                for evt in events:
                    if evt.status in (OrderStatus.PARTIAL, OrderStatus.FILLED):
                        if evt.id not in _pub_fill_ids:
                            _pub_fill_ids.add(evt.id)
                            self.pub_sock.send_multipart(
                                make_fill_msg(
                                    evt.gateway_id,
                                    evt.id,
                                    fill_qty=evt.quantity - evt.remaining_qty,
                                    fill_price=from_ticks(result.eq_price, symbol),
                                    remaining_qty=evt.remaining_qty,
                                    status=evt.status.value,
                                    order=evt.to_dict(),
                                )
                            )
                        if evt.combo_parent_id:
                            self._check_combo_after_child_event(evt)

                for trade in trades:
                    self._publish_trade(trade)  # updates positions (H3)

            # Trigger stop and trailing-stop orders whose stop price is now
            # reached by the equilibrium price.  execute_uncross() sets
            # last_trade_price but does not call _check_stops(); without this
            # block, auction-phase stop orders never fire at uncross time.
            if trades:
                now_stop = now_ns()
                triggered = book.trigger_stops(now_stop)
                for stop_order in triggered:
                    sub_trades, sub_events = book.process(stop_order, now=now_stop)
                    published_stop_ids: set[str] = set()
                    for sub_evt in sub_events:
                        if sub_evt.status in (OrderStatus.PARTIAL, OrderStatus.FILLED):
                            if sub_evt.id not in published_stop_ids:
                                published_stop_ids.add(sub_evt.id)
                                self.pub_sock.send_multipart(
                                    make_fill_msg(
                                        sub_evt.gateway_id,
                                        sub_evt.id,
                                        fill_qty=sub_evt.quantity
                                        - sub_evt.remaining_qty,
                                        fill_price=(
                                            from_ticks(book.last_trade_price, symbol)
                                            if book.last_trade_price is not None
                                            else 0.0
                                        ),
                                        remaining_qty=sub_evt.remaining_qty,
                                        status=sub_evt.status.value,
                                        order=sub_evt.to_dict(),
                                    )
                                )
                                if sub_evt.combo_parent_id:
                                    self._check_combo_after_child_event(sub_evt)
                                if (
                                    sub_evt.status == OrderStatus.FILLED
                                    and sub_evt.oco_group_id
                                ):
                                    self._check_oco_after_event(sub_evt)
                    for sub_trade in sub_trades:
                        self._publish_trade(sub_trade)  # updates positions (H3)

                log.info(
                    f"UNCROSS {symbol}: {len(trades)} trade(s) "
                    f"@ {result.eq_price}, qty={result.eq_qty}, "
                    f"surplus={result.surplus} ({result.imbalance_side})"
                )
            else:
                log.info(f"UNCROSS {symbol}: no crossable interest")

            self.pub_sock.send_multipart(
                make_auction_result_msg(
                    symbol=symbol,
                    eq_price=(
                        from_ticks(result.eq_price, symbol)
                        if result.eq_price is not None
                        else None
                    ),
                    eq_qty=result.eq_qty,
                    trades_count=len(trades) if result.eq_price else 0,
                    imbalance_side=result.imbalance_side,
                    imbalance_qty=result.surplus,
                )
            )

    # ------------------------------------------------------------------
    # OCO-order handlers
    # ------------------------------------------------------------------

    def _handle_oco_order(self, payload: dict[str, Any]) -> None:
        """
        Accept an OCO (One-Cancels-Other) pair.

        Payload schema:
          {
            "oco_id":     str,    # user-supplied label
            "gateway_id": str,
            "symbol":     str,    # both legs must be on the same symbol
            "quantity":   int,
            "tif":        str,
            "leg1": {"side": str, "order_type": str, "price": float|null, "stop_price": float|null},
            "leg2": {"side": str, "order_type": str, "price": float|null, "stop_price": float|null},
          }
        """
        gateway_id = str(payload.get("gateway_id", "")).upper()
        oco_id = payload.get("oco_id", "")

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_oco_ack_msg(gateway_id, oco_id, False, reason)
            )
            return

        symbol = str(payload.get("symbol", "")).upper()
        quantity = int(payload.get("quantity", 0))
        tif = TIF(payload.get("tif", "DAY"))

        if self._allowed_symbols and symbol not in self._allowed_symbols:
            self.pub_sock.send_multipart(
                make_oco_ack_msg(
                    gateway_id, oco_id, False, f"Symbol not configured: {symbol}"
                )
            )
            return

        if quantity <= 0:
            self.pub_sock.send_multipart(
                make_oco_ack_msg(gateway_id, oco_id, False, "Quantity must be positive")
            )
            return

        # Parse both legs
        leg1_raw = payload.get("leg1", {})
        leg2_raw = payload.get("leg2", {})

        def _parse_leg(raw: dict[str, Any]) -> Order | None:
            try:
                return Order.create(
                    symbol=symbol,
                    side=Side(raw["side"]),
                    order_type=OrderType(raw["order_type"]),
                    quantity=quantity,
                    gateway_id=gateway_id,
                    tif=tif,
                    price=(
                        to_ticks(float(raw["price"]), symbol)
                        if raw.get("price") is not None
                        else None
                    ),
                    stop_price=(
                        to_ticks(float(raw["stop_price"]), symbol)
                        if raw.get("stop_price") is not None
                        else None
                    ),
                    trail_offset=(
                        to_ticks(float(raw["trail_offset"]), symbol)
                        if raw.get("trail_offset") is not None
                        else None
                    ),
                )
            except (KeyError, ValueError):
                return None

        leg1 = _parse_leg(leg1_raw)
        leg2 = _parse_leg(leg2_raw)

        if leg1 is None or leg2 is None:
            self.pub_sock.send_multipart(
                make_oco_ack_msg(
                    gateway_id,
                    oco_id,
                    False,
                    "Invalid leg definition — check order_type and required price fields",
                )
            )
            return

        # Validate that legs with limit/stop prices have those prices
        for i, leg in enumerate((leg1, leg2), 1):
            if (
                leg.order_type in (OrderType.LIMIT, OrderType.IOC, OrderType.FOK)
                and leg.price is None
            ):
                self.pub_sock.send_multipart(
                    make_oco_ack_msg(
                        gateway_id,
                        oco_id,
                        False,
                        f"Leg {i} ({leg.order_type.value}) requires price",
                    )
                )
                return
            if (
                leg.order_type in (OrderType.STOP, OrderType.STOP_LIMIT)
                and leg.stop_price is None
            ):
                self.pub_sock.send_multipart(
                    make_oco_ack_msg(
                        gateway_id,
                        oco_id,
                        False,
                        f"Leg {i} ({leg.order_type.value}) requires stop_price",
                    )
                )
                return
            if leg.order_type == OrderType.TRAILING_STOP and leg.trail_offset is None:
                self.pub_sock.send_multipart(
                    make_oco_ack_msg(
                        gateway_id,
                        oco_id,
                        False,
                        f"Leg {i} (TRAILING_STOP) requires trail_offset",
                    )
                )
                return

        if self._sessions_enabled and not accepts_orders(self._session_state):
            self.pub_sock.send_multipart(
                make_oco_ack_msg(gateway_id, oco_id, False, "Market is closed")
            )
            return

        # Assign shared OCO group ID to both legs
        leg1.oco_group_id = oco_id
        leg2.oco_group_id = oco_id

        # Register the pair
        self._oco_groups[oco_id] = [leg1.id, leg2.id]
        self._order_to_oco[leg1.id] = oco_id
        self._order_to_oco[leg2.id] = oco_id
        self._order_symbol[leg1.id] = symbol
        self._order_symbol[leg2.id] = symbol

        # Acknowledge first, then post both orders
        self.pub_sock.send_multipart(
            make_oco_ack_msg(
                gateway_id, oco_id, True, order_id_1=leg1.id, order_id_2=leg2.id
            )
        )

        do_match = is_matching_enabled(self._session_state)
        book = self._book(symbol)

        # Defer OCO fill/cancel checks until BOTH legs have been posted.
        # Running _check_oco_after_event mid-loop (when leg 1 fills on entry)
        # unregisters the group and pops leg 2's routing entries *before* leg 2
        # is posted — leg 2 then rests unlinked and uncancellable (finding #6).
        _oco_pending_checks: list[Order] = []

        for leg in (leg1, leg2):
            # Resolve trailing stop initial price if needed
            if leg.order_type == OrderType.TRAILING_STOP and leg.stop_price is None:
                if book.last_trade_price is not None:
                    if leg.side == Side.SELL:
                        leg.stop_price = book.last_trade_price - leg.trail_offset  # type: ignore[operator]
                    else:
                        leg.stop_price = book.last_trade_price + leg.trail_offset  # type: ignore[operator]

            # ACK each leg individually so the gateway can track them
            self.pub_sock.send_multipart(
                make_ack_msg(
                    gateway_id,
                    leg.id,
                    accepted=True,
                    order={
                        "symbol": leg.symbol,
                        "side": leg.side.value,
                        "order_type": leg.order_type.value,
                        "tif": leg.tif.value,
                        "quantity": leg.quantity,
                        "price": (
                            from_ticks(leg.price, leg.symbol)
                            if leg.price is not None
                            else None
                        ),
                    },
                )
            )

            trades, events = book.process(leg, match=do_match)

            # H5: dedup fills/terminals — a leg sweeping k levels appears k
            # times in `events` with the final cumulative qty on every copy.
            # H6: report each order's own VWAP execution price.
            _o_fill_px = self._order_fill_prices(trades)
            _pub_fill_ids: set[str] = set()
            _pub_terminal_ids: set[str] = set()
            for evt in events:
                if evt.status in (OrderStatus.PARTIAL, OrderStatus.FILLED):
                    if evt.id not in _pub_fill_ids:
                        _pub_fill_ids.add(evt.id)
                        self.pub_sock.send_multipart(
                            make_fill_msg(
                                evt.gateway_id,
                                evt.id,
                                fill_qty=evt.quantity - evt.remaining_qty,
                                fill_price=_o_fill_px.get(
                                    evt.id,
                                    (
                                        from_ticks(book.last_trade_price, evt.symbol)
                                        if book.last_trade_price is not None
                                        else 0.0
                                    ),
                                ),
                                remaining_qty=evt.remaining_qty,
                                status=evt.status.value,
                                order=evt.to_dict(),
                            )
                        )
                        if evt.status == OrderStatus.FILLED and evt.oco_group_id:
                            _oco_pending_checks.append(evt)
                elif evt.status == OrderStatus.CANCELLED:
                    if evt.id not in _pub_terminal_ids:
                        _pub_terminal_ids.add(evt.id)
                        self.pub_sock.send_multipart(
                            make_cancelled_msg(evt.gateway_id, evt.id)
                        )
                        if evt.oco_group_id:
                            _oco_pending_checks.append(evt)
                elif evt.status == OrderStatus.REJECTED:
                    if evt.id not in _pub_terminal_ids:
                        _pub_terminal_ids.add(evt.id)
                        self.pub_sock.send_multipart(
                            make_ack_msg(
                                evt.gateway_id,
                                evt.id,
                                accepted=False,
                                reason="Insufficient liquidity",
                            )
                        )

            for trade in trades:
                self._publish_trade(trade)

            self._mark_dirty(symbol)

        # Both legs are now on the book — safe to resolve OCO terminal events.
        # The sibling can be found and cancelled instead of being orphaned.
        for evt in _oco_pending_checks:
            self._check_oco_after_event(evt)

        log.info(f"OCO {oco_id}: legs {leg1.id[:8]} and {leg2.id[:8]} posted")

    def _handle_oco_cancel(self, payload: dict[str, Any]) -> None:
        """Cancel an OCO pair and both its legs."""
        gateway_id = str(payload.get("gateway_id", "")).upper()
        oco_id = payload.get("oco_id", "")

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_oco_ack_msg(gateway_id, oco_id, False, reason)
            )
            return

        order_ids = self._oco_groups.get(oco_id)
        if not order_ids:
            self.pub_sock.send_multipart(
                make_oco_ack_msg(gateway_id, oco_id, False, "OCO not found")
            )
            return

        for order_id in list(order_ids):
            symbol = self._order_symbol.get(order_id)
            book = self.books.get(symbol) if symbol else None
            if book:
                cancelled = book.cancel_order(order_id)
                if cancelled:
                    self.pub_sock.send_multipart(
                        make_cancelled_msg(gateway_id, order_id)
                    )
                    self._mark_dirty(symbol)  # type: ignore[arg-type]
            self._order_symbol.pop(order_id, None)
            self._order_to_oco.pop(order_id, None)

        self._oco_groups.pop(oco_id, None)

        log.info(f"OCO {oco_id} cancelled by {gateway_id}")

    def _check_oco_after_event(self, order: Order) -> None:
        """
        Called when an OCO leg reaches a terminal state.
        Cancels the sibling leg and removes the group from tracking.
        """
        oco_id = order.oco_group_id
        if not oco_id:
            return
        order_ids = self._oco_groups.get(oco_id)
        if not order_ids:
            return

        sibling_ids = [oid for oid in order_ids if oid != order.id]
        for sibling_id in sibling_ids:
            symbol = self._order_symbol.get(sibling_id)
            book = self.books.get(symbol) if symbol else None
            if book:
                cancelled = book.cancel_order(sibling_id)
                if cancelled:
                    self.pub_sock.send_multipart(
                        make_oco_cancelled_msg(
                            order.gateway_id,
                            oco_id,
                            sibling_id,
                            reason=f"OCO sibling {order.id[:8]} reached {order.status.value}",
                        )
                    )
                    self._mark_dirty(symbol)  # type: ignore[arg-type]
            self._order_symbol.pop(sibling_id, None)
            self._order_to_oco.pop(sibling_id, None)

        self._order_to_oco.pop(order.id, None)
        self._oco_groups.pop(oco_id, None)

        log.info(
            f"OCO {oco_id}: sibling cancelled after {order.id[:8]} {order.status.value}"
        )

    def _handle_cancel(self, payload: dict[str, Any]) -> None:
        order_id = payload["order_id"]
        gateway_id = str(payload["gateway_id"]).upper()
        self._dbg_count("cancel_requests")

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self._dbg_count("cancel_reject_gateway")
            self.pub_sock.send_multipart(
                make_ack_msg(gateway_id, order_id, accepted=False, reason=reason)
            )
            return

        # O(1) lookup via global order→symbol map
        symbol = self._order_symbol.get(order_id)
        book = self.books.get(symbol) if symbol else None

        # Ownership check: a gateway may only cancel its own orders.
        if book is not None:
            resting = book.get_order(order_id)
            if resting is not None and resting.gateway_id != gateway_id:
                self._dbg_count("cancel_reject_ownership")
                self.pub_sock.send_multipart(
                    make_ack_msg(
                        gateway_id,
                        order_id,
                        accepted=False,
                        reason="Cannot cancel an order owned by another gateway",
                    )
                )
                return

        cancelled = book.cancel_order(order_id) if book else None

        if cancelled:
            self._dbg_count("cancel_accepted")
            self._order_symbol.pop(order_id, None)
            self.pub_sock.send_multipart(
                make_cancelled_msg(
                    gateway_id, order_id, client_tag=cancelled.client_tag
                )
            )
            self._mark_dirty(cancelled.symbol)
            log.info(f"CANCELLED {order_id[:8]}")
            # If this was a combo child, cascade-cancel the parent combo
            if cancelled.combo_parent_id:
                self._check_combo_after_child_event(cancelled)
            # If this was an OCO leg, cancel the sibling
            if cancelled.oco_group_id:
                self._check_oco_after_event(cancelled)
            return

        # Order not found — send rejection ack
        self.pub_sock.send_multipart(
            make_ack_msg(gateway_id, order_id, accepted=False, reason="Order not found")
        )
        self._dbg_count("cancel_reject_not_found")

    def _handle_amend(self, payload: dict[str, Any]) -> None:
        order_id = payload["order_id"]
        gateway_id = str(payload["gateway_id"]).upper()
        new_price = payload.get("price")
        new_qty = payload.get("qty")
        self._dbg_count("amend_requests")

        # M12: amend quantity arrives raw from JSON.  Coerce it to int (like
        # prices are converted) so a float/string never propagates into
        # quantity/remaining_qty; reject values that are not a valid number.
        if new_qty is not None:
            try:
                new_qty = int(new_qty)
            except (TypeError, ValueError):
                self._dbg_count("amend_reject_payload")
                self.pub_sock.send_multipart(
                    make_ack_msg(
                        gateway_id,
                        order_id,
                        accepted=False,
                        reason="Amend quantity must be an integer",
                    )
                )
                return

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self._dbg_count("amend_reject_gateway")
            self.pub_sock.send_multipart(
                make_ack_msg(gateway_id, order_id, accepted=False, reason=reason)
            )
            return

        if new_price is None and new_qty is None:
            self._dbg_count("amend_reject_payload")
            self.pub_sock.send_multipart(
                make_ack_msg(
                    gateway_id,
                    order_id,
                    accepted=False,
                    reason="Amend requires at least PRICE or QTY",
                )
            )
            return

        # O(1) lookup via global order→symbol map
        symbol = self._order_symbol.get(order_id)
        book = self.books.get(symbol) if symbol else None
        if book is None:
            self._dbg_count("amend_reject_not_found")
            self.pub_sock.send_multipart(
                make_ack_msg(
                    gateway_id, order_id, accepted=False, reason="Order not found"
                )
            )
            return
        assert symbol is not None

        # Ownership check: a gateway may only amend its own orders.
        resting = book.get_order(order_id)
        if resting is not None and resting.gateway_id != gateway_id:
            self._dbg_count("amend_reject_ownership")
            self.pub_sock.send_multipart(
                make_ack_msg(
                    gateway_id,
                    order_id,
                    accepted=False,
                    reason="Cannot amend an order owned by another gateway",
                )
            )
            return

        # #9: apply the same gates a NEW order at this price would face, so
        # fat-finger / session / halt protections cannot be bypassed by amending
        # instead of re-entering.
        new_price_ticks = (
            to_ticks(float(new_price), symbol) if new_price is not None else None
        )

        # Session gating — reject amends while the market does not accept orders.
        if self._sessions_enabled and not accepts_orders(self._session_state):
            self._dbg_count("amend_reject_session")
            self.pub_sock.send_multipart(
                make_ack_msg(
                    gateway_id, order_id, accepted=False, reason="Market is closed"
                )
            )
            return

        # Matching is disabled while the symbol is halted or the session is a
        # non-continuous phase; a marketable amend then rests without crossing.
        do_match = is_matching_enabled(self._session_state)
        if self._halted_symbols.get(symbol):
            do_match = False

        # Price collar check on the amended price (same band as a new order).
        if self._enforce_collars and new_price_ticks is not None:
            collar = self._collars.get(symbol)
            if collar is not None:
                result = validate_collar(new_price_ticks, collar, book.last_trade_price)
                if result.rejected:
                    self._dbg_count("amend_reject_collar")
                    self.pub_sock.send_multipart(
                        make_ack_msg(
                            gateway_id, order_id, accepted=False, reason=result.reason
                        )
                    )
                    return

        now = now_ns()
        amended, priority_reset, err = book.amend_order(
            order_id,
            new_price=new_price_ticks,
            new_qty=new_qty,
            now=now,
        )

        if amended is None:
            self._dbg_count("amend_reject_book")
            self.pub_sock.send_multipart(
                make_ack_msg(gateway_id, order_id, accepted=False, reason=err)
            )
            return

        # Publish amended confirmation
        self.pub_sock.send_multipart(
            make_amended_msg(
                gateway_id,
                order_id,
                price=(
                    from_ticks(amended.price, amended.symbol)
                    if amended.price is not None
                    else None
                ),
                qty=amended.quantity,
                remaining_qty=amended.remaining_qty,
                priority_reset=priority_reset,
            )
        )
        self._dbg_count("amend_accepted")
        self._mark_dirty(amended.symbol)
        prio_str = " (priority reset)" if priority_reset else " (priority kept)"
        log.info(
            f"AMENDED {order_id[:8]} price={amended.price} "
            f"qty={amended.quantity}{prio_str}"
        )

        # H2: a marketable amend must not leave the book crossed.  If the
        # amended order now crosses the opposite best, pull the re-inserted
        # resting copy and run it through matching (cancel/replace semantics).
        if (
            do_match
            and amended.price is not None
            and amended.status
            not in (
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
            )
        ):
            if amended.side == Side.BUY:
                best_ask = book.best_ask_ticks()
                marketable = best_ask is not None and amended.price >= best_ask
            else:
                best_bid = book.best_bid_ticks()
                marketable = best_bid is not None and amended.price <= best_bid

            if marketable:
                # Remove the resting copy (deducts qty index, invalidates entry)
                # then re-process the same order through the matching path.
                book.cancel_order(order_id)
                amended.status = OrderStatus.NEW
                trades, events = book.process(amended, match=True, now=now)
                self._publish_amend_rematch(book, amended, trades, events)

    def _publish_amend_rematch(
        self,
        book: "OrderBook",
        aggressor: Order,
        trades: list[Trade],
        events: list[Order],
    ) -> None:
        """Publish fills / terminal events / trades for an amend cancel-replace.

        Mirrors the new-order publication contract (C4: a fill is published
        whenever an order executed any quantity, regardless of final status)
        and updates both counterparties' positions for every trade (H3).
        """
        # H6: report each order's own VWAP execution price, not the sweep's last.
        order_fill_px = self._order_fill_prices(trades)
        fill_px = (
            from_ticks(book.last_trade_price, aggressor.symbol)
            if book.last_trade_price is not None
            else 0.0
        )
        published_fill_ids: set[str] = set()
        published_terminal_ids: set[str] = set()
        for evt in events:
            filled = evt.quantity - evt.remaining_qty
            if filled > 0 and evt.id not in published_fill_ids:
                published_fill_ids.add(evt.id)
                self.pub_sock.send_multipart(
                    make_fill_msg(
                        evt.gateway_id,
                        evt.id,
                        fill_qty=filled,
                        fill_price=order_fill_px.get(evt.id, fill_px),
                        remaining_qty=evt.remaining_qty,
                        status=("PARTIAL_FILL" if evt.remaining_qty else "FILLED"),
                        order=evt.to_dict(),
                    )
                )
            if (
                evt.status == OrderStatus.CANCELLED
                and evt.id not in published_terminal_ids
            ):
                published_terminal_ids.add(evt.id)
                self.pub_sock.send_multipart(make_cancelled_msg(evt.gateway_id, evt.id))
            elif (
                evt.status == OrderStatus.REJECTED
                and evt.id not in published_terminal_ids
            ):
                published_terminal_ids.add(evt.id)
                self.pub_sock.send_multipart(
                    make_ack_msg(
                        evt.gateway_id,
                        evt.id,
                        accepted=False,
                        reason="Insufficient liquidity",
                    )
                )
        for trade in trades:
            self._publish_trade(trade)  # updates positions (H3)
        self._mark_dirty(aggressor.symbol)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        log.info("Shutting down …")
        self._running = False

        all_resting: list[Order] = []
        for book in self.books.values():
            for order in book.resting_orders():
                if order.tif == TIF.GTC:
                    if order.origin == OrderOrigin.QUOTE:
                        # Quote legs are re-seeded from config on every startup;
                        # do not persist them or they accumulate across restarts.
                        continue
                    all_resting.append(order)
                else:
                    # Expire DAY orders
                    order.status = OrderStatus.EXPIRED
                    self.pub_sock.send_multipart(
                        make_expired_msg(
                            order.gateway_id, order.id, client_tag=order.client_tag
                        )
                    )
                    # If this was a combo child, cascade-cancel sibling legs
                    if order.combo_parent_id:
                        self._check_combo_after_child_event(order)

        save_gtc_orders(all_resting, GTC_ORDERS_FILE)
        log.info(f"Saved {len(all_resting)} GTC order(s) to {GTC_ORDERS_FILE}")

        # Persist resting GTC combos
        save_gtc_combos(list(self._combos.values()), GTC_COMBOS_FILE)
        n_combos = sum(
            1
            for c in self._combos.values()
            if c.tif == TIF.GTC
            and c.status in (ComboStatus.PENDING, ComboStatus.PARTIALLY_MATCHED)
        )
        if n_combos:
            log.info(f"Saved {n_combos} GTC combo(s) to {GTC_COMBOS_FILE}")

        save_book_stats(self.books, BOOK_STATS_FILE)
        log.info(
            f"Saved book statistics for {len(self.books)} symbol(s) to {BOOK_STATS_FILE}"
        )

        # Broadcast EOD — subscribers record closing prices before sockets close
        eod_books = [book.snapshot() for book in self.books.values()]
        self.pub_sock.send_multipart(make_eod_msg(eod_books))

        self.pull_sock.close()
        self.pub_sock.close()
        if self._drop_copy is not None:
            self._drop_copy.close()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _dispatch_pull_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Route one decoded PULL-socket message to its handler.

        Every branch is wrapped in a single try/except so one bad message
        can never take down the receive loop. A topic that matches no
        branch falls into the `else` below rather than being silently
        dropped: it's logged at WARNING (visible by default, no need to
        raise the log level) and counted in `self._unknown_topic_count` so
        the gap is observable instead of invisible. This is a deliberate
        third failure mode, distinct from `self._error_count` (a *known*
        handler raised) — "no handler is registered for this topic at all"
        is a routing/completeness bug, not a runtime exception, and
        operators benefit from being able to tell the two apart.
        """
        try:
            if topic == "order.new":
                self._handle_new_order(payload)
            elif topic == "order.cancel":
                self._handle_cancel(payload)
            elif topic == "order.amend":
                self._handle_amend(payload)
            elif topic == "order.combo":
                self._handle_combo_order(payload)
            elif topic == "order.combo_cancel":
                self._handle_combo_cancel(payload)
            elif topic == "order.oco":
                self._handle_oco_order(payload)
            elif topic == "order.oco_cancel":
                self._handle_oco_cancel(payload)
            elif topic == "quote.new":
                self._handle_quote_new(payload)
            elif topic == "quote.cancel":
                self._handle_quote_cancel(payload)
            elif topic == "system.gateway_connect":
                self._handle_gateway_connect(payload)
            elif topic == "system.gateway_disconnect":
                self._handle_gateway_disconnect(payload)
            elif topic == "system.symbols_request":
                self._handle_symbols_request(payload)
            elif topic == "book.snapshot_request":
                self._handle_book_snapshot_request(payload)
            elif topic == "order.orders_request":
                self._handle_orders_request(payload)
            elif topic == "system.quote_bootstrap_request":
                self._handle_quote_bootstrap_request(payload)
            elif topic == "system.quote_legs_request":
                self._handle_quote_legs_request(payload)
            elif topic == "risk.kill_switch":
                self._handle_kill_switch(payload)
            elif topic == "risk.circuit_breaker_halt_all":
                self._handle_circuit_breaker_halt_all(payload)
            elif topic == "risk.circuit_breaker_resume_all":
                self._handle_circuit_breaker_resume_all(payload)
            elif topic == "risk.symbol_halt":
                self._handle_symbol_halt(payload)
            elif topic == "risk.symbol_resume":
                self._handle_symbol_resume(payload)
            elif topic == "risk.cancel_symbol":
                self._handle_cancel_symbol(payload)
            elif topic == "session.transition":
                self._handle_session_transition(payload)
            elif topic == "system.session_state_request":
                self._handle_session_state_request(payload)
            elif topic == "system.session_schedule_request":
                self._handle_session_schedule_request(payload)
            elif topic == "system.gateways_request":
                self._handle_gateways_request(payload)
            elif topic == "system.volume_request":
                self._handle_volume_request(payload)
            elif topic == "system.halt_status_request":
                self._handle_halt_status_request(payload)
            elif topic == "system.position_request":
                self._handle_position_request(payload)
            else:
                self._unknown_topic_count += 1
                log.warning(
                    "No dispatch handler for topic %s (#%d) — " "message dropped",
                    topic,
                    self._unknown_topic_count,
                )
        except Exception as exc:
            self._dbg_count("handler_errors")
            self._error_count += 1
            log.error(
                "Error processing %s (#%d): %s",
                topic,
                self._error_count,
                exc,
            )

    def run(self) -> None:
        self._restore_gtc()
        self._load_config()  # seed stats + MM orders (after GTC restore)

        # Create drop copy publisher here (not in __init__) so that unit tests
        # that call handlers directly never attempt to bind ZMQ port 5557.
        try:
            self._drop_copy = DropCopyPublisher(
                zmq.Context.instance(),
                buffer_size=self.drop_copy_buffer_size,
            )
            log.info("Drop copy PUB bound on port 5557")
        except zmq.ZMQError as exc:
            log.warning("Drop copy unavailable — %s", exc)

        self._running = True

        poller = zmq.Poller()
        poller.register(self.pull_sock, zmq.POLLIN)

        log.info(f"Listening on PULL={ENGINE_PULL_ADDR}  PUB={ENGINE_PUB_ADDR}")

        # Signal handlers only set the stop flag.  Calling _shutdown() directly
        # from a signal handler is unsafe: the handler can interrupt mid-message
        # (e.g. inside _handle_new_order) and close pub_sock while the handler
        # still holds references, causing unhandled ZMQErrors in _flush_snapshots.
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "_running", False))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_running", False))

        while self._running:
            try:
                socks = dict(poller.poll(timeout=200))  # 200 ms tick
            except zmq.ZMQError:
                break
            if self.pull_sock in socks:
                frames = self.pull_sock.recv_multipart()
                topic, payload = decode(frames)
                self._dbg_count("pull_messages")
                self._dbg_count(f"topic_{topic}")
                self._dispatch_pull_message(topic, payload)
            # Throttled snapshot publish — runs every poll tick (max 200ms)
            self._flush_snapshots()
            # Check circuit breaker timers — resume halted symbols
            self._flush_circuit_breakers()
            self._flush_debug_summary()

        self._flush_debug_summary(force=True)
        self._shutdown()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher matching engine")
    add_version_argument(parser, "pm-engine")
    parser.add_argument(
        "--config",
        "-c",
        metavar="FILE",
        help="Engine config YAML (default: engine_config.yaml)",
    )
    parser.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level override (default: WARNING)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v: INFO, -vv: DEBUG)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce log output to warnings/errors",
    )
    return parser


def _configure_logging(args: argparse.Namespace) -> int:
    log_level = getattr(args, "log_level", None)
    verbose = getattr(args, "verbose", 0)
    quiet = getattr(args, "quiet", False)

    if log_level:
        level_name = str(log_level).upper()
        level = getattr(logging, level_name, logging.WARNING)
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    return int(level)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-engine with log level %s", logging.getLevelName(log_level))
    Engine(config_path=args.config).run()


if __name__ == "__main__":
    main()
