"""
Matching Engine — main process.

Startup:
  poetry run pm-engine [--verbose] [--config engine_config.yaml]

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
import signal
import sys
import time
from pathlib import Path
from typing import Any

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
from edumatcher.engine.config_loader import EngineConfig, load_engine_config
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
from edumatcher.models.combo import ComboOrder, ComboStatus
from edumatcher.models.clock import now_ns
from edumatcher.models.message import (
    _dumps,
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
    make_kill_switch_ack_msg,
    make_orders_msg,
    make_quote_ack_msg,
    make_quote_status_msg,
    make_symbols_msg,
    make_session_state_msg,
    make_auction_result_msg,
    make_oco_ack_msg,
    make_oco_cancelled_msg,
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
    TIF,
)
from edumatcher.models.price import from_ticks, to_ticks
from edumatcher.models.price import register_tick_decimals
from edumatcher.models.quote import QuoteEntry, QuoteIndex, QuoteRefreshPolicy

# PERF B: Module-level pre-encoded topic constant for trade messages.
# Avoids re-encoding the same static string on every trade publication.
_TRADE_TOPIC = b"trade.executed"

# PERF: Pre-built frozenset for fill status check — avoids creating a
# temporary tuple on every iteration of the events loop.
_FILL_STATUSES = frozenset({OrderStatus.PARTIAL, OrderStatus.FILLED})
from edumatcher.models.session import (  # noqa: E402
    SessionState,
    VALID_TRANSITIONS,
    accepts_orders,
    is_matching_enabled,
)


class Engine:
    # Minimum interval between book snapshot publishes per symbol (seconds)
    SNAPSHOT_INTERVAL = 0.5

    def __init__(self, verbose: bool = False, config_path: str | None = None) -> None:
        self.verbose = verbose
        self.books: dict[str, OrderBook] = {}  # symbol → OrderBook
        self._running = False
        # If None → no symbol restrictions (backward-compat mode)
        self._allowed_symbols: frozenset[str] | None = None
        self._allowed_fix_gateways: frozenset[str] | None = None
        self._engine_config: EngineConfig | None = None
        self._gateway_descriptions: dict[str, str] = {}
        self._connected_fix_gateways: set[str] = set()
        self._sessions: dict[str, ParticipantSession] = {}
        self._quote_index = QuoteIndex()

        # Halt state — keyed by symbol; True means halted (circuit breaker fired)
        self._halted_symbols: dict[str, bool] = {}
        # Price collar configs — keyed by symbol; populated in _load_config()
        self._collars: dict[str, Any] = {}  # values: CollarConfig
        # Circuit breaker states — keyed by symbol; populated in _load_config()
        self._circuit_breakers: dict[str, Any] = {}  # values: CircuitBreakerState
        # Drop copy publisher — None until run() is called (avoids binding port 5557 in tests)
        self._drop_copy: Any = None  # DropCopyPublisher created lazily in run()

        # Global order_id → symbol map for O(1) cancel routing
        self._order_symbol: dict[str, str] = {}

        # PERF improvement B: Pre-encoded topic bytes cache.
        #
        # ZMQ topic frames are the same bytes for every message to a given
        # gateway (e.g. b"order.ack.GW01").  Building them with f-string +
        # .encode() costs ~100ns each; with 3-4 messages per order that's
        # ~300-400ns wasted on repeated string formatting.  Caching the
        # encoded bytes reduces this to a single dict lookup (~50ns total).
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

        # Session state (auction / continuous matching)
        self._sessions_enabled: bool = False
        self._session_state: SessionState = SessionState.CONTINUOUS

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Load engine config (symbol allowlist + MM orders)
        path = Path(config_path) if config_path else ENGINE_CONFIG_FILE
        if path.exists():
            try:
                self._engine_config = load_engine_config(path)
                self._allowed_symbols = self._engine_config.allowed_symbols
                self._allowed_fix_gateways = self._engine_config.allowed_fix_gateways
                self._sessions_enabled = self._engine_config.sessions_enabled
                self.snapshot_interval_sec = self._engine_config.snapshot_interval_sec
                self._gateway_descriptions = {
                    gw_id: cfg.description
                    for gw_id, cfg in self._engine_config.fix_gateways.items()
                }
                if self._sessions_enabled:
                    # Start CLOSED and wait for scheduler transitions.
                    self._session_state = SessionState.CLOSED
                print(
                    f"[ENGINE] Loaded config from {path}  "
                    f"({len(self._allowed_symbols)} symbol(s): "
                    f"{', '.join(sorted(self._allowed_symbols))}; "
                    f"{len(self._allowed_fix_gateways)} gateway id(s))"
                )
                print(
                    "[ENGINE] Session handling: "
                    + (
                        "enabled (startup state: CLOSED)"
                        if self._sessions_enabled
                        else "disabled"
                    )
                )
            except (FileNotFoundError, PermissionError) as exc:
                print(
                    f"[ENGINE] WARNING: Config file {path} could not be read — "
                    f"running without symbol restrictions. ({exc})",
                    file=sys.stderr,
                )
            except Exception as exc:
                print(f"[ENGINE] FATAL: Invalid config {path}: {exc}", file=sys.stderr)
                sys.exit(1)
        else:
            print(
                f"[ENGINE] No config file at {path} — running without symbol restrictions."
            )

        try:
            self.pull_sock = make_puller(ENGINE_PULL_ADDR)
            self.pub_sock = make_publisher(ENGINE_PUB_ADDR)
        except zmq.ZMQError as exc:
            print(
                f"[ENGINE] FATAL: Cannot bind sockets — {exc}\n"
                f"         Is another engine instance already running?",
                file=sys.stderr,
            )
            sys.exit(1)

        # Give PUB socket a moment to bind before any client can connect
        time.sleep(0.05)

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
            self.books[symbol] = OrderBook(symbol)
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
                    depth = book.depth_snapshot(tolerance_ticks=100)
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
            print(f"[ENGINE] Restored book statistics for {len(stats)} symbol(s).")

        n_mm_quotes = 0
        for sym, sym_cfg in self._engine_config.symbols.items():
            for idx, quote_seed in enumerate(sym_cfg.market_maker_quotes, start=1):
                gateway_id = quote_seed.gateway_id
                quote_id = quote_seed.quote_id or f"SEED-{gateway_id}-{sym}-{idx}"

                previous = self._quote_index.remove(gateway_id, sym)
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
                for quote_order in (bid, ask):
                    trades, events = book.process(quote_order, match=True, now=now)
                    for evt in events:
                        if evt.status in _FILL_STATUSES:
                            self.pub_sock.send_multipart(
                                make_fill_msg(
                                    evt.gateway_id,
                                    evt.id,
                                    fill_qty=evt.quantity - evt.remaining_qty,
                                    fill_price=(
                                        from_ticks(book.last_trade_price, evt.symbol)
                                        if book.last_trade_price is not None
                                        else 0.0
                                    ),
                                    remaining_qty=evt.remaining_qty,
                                    status=evt.status.value,
                                    order=evt.to_dict(),
                                )
                            )
                            if evt.quote_id:
                                self._on_quote_leg_filled(evt)
                        elif evt.status == OrderStatus.CANCELLED:
                            self.pub_sock.send_multipart(
                                make_cancelled_msg(evt.gateway_id, evt.id)
                            )
                    for trade in trades:
                        self._publish_trade(trade)

                self._mark_dirty(sym)
                n_mm_quotes += 1
                if self.verbose:
                    print(
                        f"[ENGINE] MM quote {quote_id} {sym} "
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
            print(
                f"[ENGINE] Injected {n_mm_quotes} market-maker quote(s) "
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
                # Populate reference_price from last trade (buy side preferred)
                ref_float = sym_cfg.last_buy_price or sym_cfg.last_sell_price
                if ref_float is not None:
                    sym_cfg.collar.symbol = sym
                    sym_cfg.collar.reference_price = to_ticks(float(ref_float), sym)
                    self._collars[sym] = sym_cfg.collar
            if sym_cfg.circuit_breaker is not None:
                sym_cfg.circuit_breaker.symbol = sym
                from edumatcher.engine.circuit_breaker import CircuitBreakerState

                self._circuit_breakers[sym] = CircuitBreakerState(
                    symbol=sym, config=sym_cfg.circuit_breaker
                )

    # ------------------------------------------------------------------
    # Startup — restore GTC orders
    # ------------------------------------------------------------------

    def _restore_gtc(self) -> None:
        orders = load_gtc_orders(GTC_ORDERS_FILE)
        for order in orders:
            # Skip GTC orders for symbols no longer in config
            if self._allowed_symbols and order.symbol not in self._allowed_symbols:
                if self.verbose:
                    print(
                        f"[ENGINE] Skipping GTC order {order.id[:8]} for removed symbol {order.symbol}"
                    )
                continue
            order.status = OrderStatus.NEW
            book = self._book(order.symbol)
            book.process(order)
            self._order_symbol[order.id] = order.symbol
            if self.verbose:
                print(f"[ENGINE] Restored GTC order {order.id} ({order.symbol})")
        if orders:
            print(
                f"[ENGINE] Restored {len(orders)} GTC order(s) from previous session."
            )
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
            print(
                f"[ENGINE] Restored {len(combos)} GTC combo(s) from previous session."
            )

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def _handle_new_order(self, payload: dict[str, Any]) -> None:
        order = Order.from_dict(payload)

        # Boundary conversion: inbound payload prices are display decimals.
        if order.price is not None and isinstance(order.price, float):
            order.price = to_ticks(order.price, order.symbol)
        if order.stop_price is not None and isinstance(order.stop_price, float):
            order.stop_price = to_ticks(order.stop_price, order.symbol)
        if order.trail_offset is not None and isinstance(order.trail_offset, float):
            order.trail_offset = to_ticks(order.trail_offset, order.symbol)

        # FIX gateway allowlist + connect/auth check
        ok, reason = self._gateway_status(order.gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_ack_msg(order.gateway_id, order.id, accepted=False, reason=reason)
            )
            if self.verbose:
                print(f"[ENGINE] REJECTED {order.id[:8]} — {reason}")
            return

        # Symbol allowlist check
        if self._allowed_symbols and order.symbol not in self._allowed_symbols:
            self.pub_sock.send_multipart(
                make_ack_msg(
                    order.gateway_id,
                    order.id,
                    accepted=False,
                    reason=f"Symbol not configured: {order.symbol}",
                )
            )
            if self.verbose:
                print(
                    f"[ENGINE] REJECTED {order.id[:8]} — symbol not configured: {order.symbol}"
                )
            return

        # Session state gating
        if self._sessions_enabled and not accepts_orders(self._session_state):
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
        if order.price is not None:
            collar = self._collars.get(order.symbol)
            if collar is not None:
                from edumatcher.engine.collar import validate_collar

                result = validate_collar(order.price, collar, book.last_trade_price)
                if result.rejected:
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
            self.pub_sock.send_multipart(
                make_ack_msg(
                    order.gateway_id,
                    order.id,
                    accepted=False,
                    reason=f"{order.order_type.value} orders not accepted during {self._session_state.value}",
                )
            )
            return

        if self.verbose:
            print(
                f"[ENGINE] NEW {order.id[:8]} {order.symbol} {order.side.value} "
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

        # Track order → symbol for O(1) cancel routing
        self._order_symbol[order.id] = order.symbol

        # PERF #3: Capture a single high-resolution timestamp at the start of
        # the hot path.  This `now` value is threaded through book.process() →
        # _sweep() → _apply_fill() → Trade.create() and into stop/trailing stop
        # triggers.  Eliminates 2-6 redundant time.time() syscalls per order,
        # saving ~0.5-2µs per order depending on the number of fills and stops.
        now = now_ns()

        # PERF A: Inline ack message — bypass make_ack_msg() entirely.
        #
        # make_ack_msg() allocates a base dict, conditionally merges order
        # fields via .update(), then calls encode() which does f-string +
        # .encode() + orjson.dumps().  Total cost: ~950ns.
        # Inlining with pre-cached topic bytes and a single dict literal:
        # ~450ns.  Saves ~500ns per order on the hot path.
        #
        # PERF B: Use pre-cached topic bytes instead of f-string + .encode().
        # Saves ~60-100ns per message by avoiding repeated string formatting.
        _gw = order.gateway_id
        _tc = self._topic_cache
        ack_topic = _tc.get(_gw)
        if ack_topic is None:
            # First order from this gateway — populate the three hot topics
            _tc[_gw] = f"order.ack.{_gw}".encode()
            _tc[f"fill.{_gw}"] = f"order.fill.{_gw}".encode()
            _tc[f"cancel.{_gw}"] = f"order.cancelled.{_gw}".encode()
            ack_topic = _tc[_gw]
        self.pub_sock.send_multipart(
            [
                ack_topic,
                _dumps(
                    {
                        "order_id": order.id,
                        "accepted": True,
                        "reason": "",
                        "symbol": order.symbol,
                        "side": payload.get("side"),
                        "order_type": payload.get("order_type"),
                        "tif": payload.get("tif"),
                        "qty": order.quantity,
                        "price": (
                            from_ticks(order.price, order.symbol)
                            if order.price is not None
                            else None
                        ),
                    }
                ),
            ]
        )

        trades, events = book.process(order, match=do_match, now=now)

        # Publish fills / cancels
        for evt in events:
            if evt.status in _FILL_STATUSES:
                # PERF #9: Build the full fill payload in one dict literal and
                # call encode() directly, bypassing make_fill_msg().
                #
                # make_fill_msg() builds a base dict, then calls .update() to
                # merge order fields — that's 2 dict allocations + a hash merge.
                # Building one flat dict is ~3x faster (~250ns vs ~750ns) and
                # also eliminates the function call overhead (~50ns).
                # PERF B: Use pre-cached fill topic bytes.
                self.pub_sock.send_multipart(
                    [
                        _tc.get(f"fill.{evt.gateway_id}")
                        or f"order.fill.{evt.gateway_id}".encode(),
                        _dumps(
                            {
                                "order_id": evt.id,
                                "fill_qty": evt.quantity - evt.remaining_qty,
                                "fill_price": (
                                    from_ticks(book.last_trade_price, evt.symbol)
                                    if book.last_trade_price is not None
                                    else None
                                ),
                                "remaining_qty": evt.remaining_qty,
                                "status": evt.status.value,
                                "symbol": evt.symbol,
                                "side": evt.side.value,
                                "order_type": evt.order_type.value,
                                "qty": evt.quantity,
                                "price": (
                                    from_ticks(evt.price, evt.symbol)
                                    if evt.price is not None
                                    else None
                                ),
                            }
                        ),
                    ]
                )
                # If this event is for a combo child, update combo state
                if evt.combo_parent_id:
                    self._check_combo_after_child_event(evt)
                # If this order is an OCO leg, cancel the sibling when fully filled
                if evt.status == OrderStatus.FILLED and evt.oco_group_id:
                    self._check_oco_after_event(evt)
                # Drop copy — forward fill to participant's risk/clearing system
                if self._drop_copy is not None:
                    self._drop_copy.publish(
                        gateway_id=evt.gateway_id,
                        event_type="order.fill",
                        payload={
                            "order_id": evt.id,
                            "symbol": evt.symbol,
                            "fill_qty": evt.quantity - evt.remaining_qty,
                            "fill_price": (
                                from_ticks(book.last_trade_price, evt.symbol)
                                if book.last_trade_price is not None
                                else 0.0
                            ),
                            "remaining_qty": evt.remaining_qty,
                            "liquidity_flag": (
                                "MAKER_QUOTE"
                                if evt.origin == OrderOrigin.QUOTE
                                else "MAKER"
                            ),
                        },
                    )
            elif evt.status == OrderStatus.REJECTED:
                self.pub_sock.send_multipart(
                    make_ack_msg(
                        evt.gateway_id,
                        evt.id,
                        accepted=False,
                        reason="Insufficient liquidity",
                    )
                )
                # IOC partial fill: remainder was cancelled, not rejected — but if a
                # REJECTED event carries an oco_group_id the other leg should be cancelled
                if evt.oco_group_id:
                    self._check_oco_after_event(evt)
            elif evt.status == OrderStatus.CANCELLED:
                # SMP-triggered cancellation — notify the affected gateway
                # PERF B: Use pre-cached cancel topic bytes + inline _dumps.
                self.pub_sock.send_multipart(
                    [
                        _tc.get(f"cancel.{evt.gateway_id}")
                        or f"order.cancelled.{evt.gateway_id}".encode(),
                        _dumps({"order_id": evt.id}),
                    ]
                )
                if evt.combo_parent_id:
                    self._check_combo_after_child_event(evt)
                if evt.oco_group_id:
                    self._check_oco_after_event(evt)
                if self.verbose:
                    print(f"[ENGINE] SMP CANCEL {evt.id[:8]} ({evt.gateway_id})")

        # Publish trades
        for trade in trades:
            if self.verbose:
                print(
                    f"[ENGINE] TRADE {trade.id[:8]} {trade.symbol} "
                    f"qty={trade.quantity} @{trade.price}"
                )
            self._publish_trade(trade)

        # Mark book dirty; snapshot will be published on next throttle tick
        self._mark_dirty(order.symbol)

    def _handle_symbols_request(self, payload: dict[str, Any]) -> None:
        gateway_id = payload.get("gateway_id", "")
        symbols = sorted(self.books.keys())
        self.pub_sock.send_multipart(make_symbols_msg(gateway_id, symbols))

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
            if self.verbose:
                print(f"[ENGINE] REFUSED gateway connect: {gateway_id}")
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
        if self.verbose:
            desc = self._gateway_descriptions.get(gateway_id, "")
            if desc:
                print(f"[ENGINE] Gateway connected: {gateway_id} — {desc}")
            else:
                print(f"[ENGINE] Gateway connected: {gateway_id}")

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
                    orders.append(
                        {
                            "id": order.id,
                            "symbol": order.symbol,
                            "side": order.side.value,
                            "order_type": order.order_type.value,
                            "tif": order.tif.value,
                            "quantity": order.quantity,
                            "remaining_qty": order.remaining_qty,
                            "gateway_id": order.gateway_id,
                            "trail_offset": (
                                from_ticks(order.trail_offset, order.symbol)
                                if order.trail_offset is not None
                                else None
                            ),
                            "oco_group_id": order.oco_group_id,
                            "timestamp": order.timestamp / 1_000_000_000,
                            "status": order.status.value,
                            "price": (
                                from_ticks(order.price, order.symbol)
                                if order.price is not None
                                else None
                            ),
                            "stop_price": (
                                from_ticks(order.stop_price, order.symbol)
                                if order.stop_price is not None
                                else None
                            ),
                            "visible_qty": order.visible_qty,
                            "displayed_qty": order.displayed_qty,
                            "smp_action": order.smp_action.value,
                            "combo_parent_id": order.combo_parent_id,
                            "leg_index": order.leg_index,
                            "origin": order.origin.value,
                            "quote_id": order.quote_id,
                        }
                    )
        self.pub_sock.send_multipart(make_orders_msg(gateway_id, orders))

    def _cancel_order_by_id(self, order_id: str) -> bool:
        symbol = self._order_symbol.get(order_id)
        book = self.books.get(symbol) if symbol else None
        cancelled = book.cancel_order(order_id) if book else None
        if not cancelled:
            return False
        self._order_symbol.pop(order_id, None)
        self._mark_dirty(cancelled.symbol)
        self.pub_sock.send_multipart(make_cancelled_msg(cancelled.gateway_id, order_id))
        return True

    def _cancel_quote_entry(self, entry: QuoteEntry, reason: str = "") -> int:
        cancelled = 0
        for order_id in (entry.bid_order_id, entry.ask_order_id):
            if self._cancel_order_by_id(order_id):
                cancelled += 1
        self.pub_sock.send_multipart(
            make_quote_status_msg(entry.gateway_id, entry.quote_id, "CANCELLED", reason)
        )
        return cancelled

    def _publish_trade(self, trade: Any) -> None:
        self.pub_sock.send_multipart(
            [
                _TRADE_TOPIC,
                _dumps(
                    {
                        "id": trade.id,
                        "symbol": trade.symbol,
                        "buy_order_id": trade.buy_order_id,
                        "sell_order_id": trade.sell_order_id,
                        "buy_gateway_id": trade.buy_gateway_id,
                        "sell_gateway_id": trade.sell_gateway_id,
                        "price": from_ticks(trade.price, trade.symbol),
                        "quantity": trade.quantity,
                        "aggressor_side": trade.aggressor_side,
                        "timestamp": trade.timestamp / 1_000_000_000,
                    }
                ),
            ]
        )
        # Circuit breaker monitor — check if this fill triggered a halt
        self._check_circuit_breaker(trade.symbol, trade.price, trade.timestamp)

    def _check_circuit_breaker(self, symbol: str, trade_price: int, now: int) -> None:
        """
        Called after every fill to check whether a circuit breaker halt should fire.

        If the rolling-window average has moved more than ``dynamic_band_pct``
        from the trigger price, the symbol is halted:
          - All resting quotes for the symbol are cancelled.
          - A ``circuit_breaker.halt.{symbol}`` message is broadcast.
          - ``_halted_symbols[symbol]`` is set to True so new orders are blocked.
        """
        cb = self._circuit_breakers.get(symbol)
        if cb is None:
            return
        triggered_level = cb.record_trade(trade_price, now)
        if triggered_level is None:
            return

        cb.activate(now, triggered_level)
        self._halted_symbols[symbol] = True

        # Cancel all resting quotes for the halted symbol
        for entry in self._quote_index.cancel_all_for_symbol(symbol):
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
        print(
            f"[ENGINE] CIRCUIT BREAKER HALT {symbol}: "
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
            cb.deactivate()
            self._halted_symbols[symbol] = False
            if cb.active_resumption_mode == "AUCTION":
                self._run_uncross(from_state=self._session_state, symbol_filter=symbol)
            self.pub_sock.send_multipart(
                encode(
                    f"circuit_breaker.resume.{symbol}",
                    {"symbol": symbol, "mode": cb.active_resumption_mode},
                )
            )
            self._mark_dirty(symbol)
            print(f"[ENGINE] CIRCUIT BREAKER RESUME {symbol}")

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

        self._quote_index.remove(order.gateway_id, order.symbol)
        sibling_id = entry.counterpart_order_id(order.side.value)
        self._cancel_order_by_id(sibling_id)

        status = (
            "INACTIVE_BID_FILLED" if order.side == Side.BUY else "INACTIVE_ASK_FILLED"
        )
        self.pub_sock.send_multipart(
            make_quote_status_msg(order.gateway_id, entry.quote_id, status)
        )

    def _handle_quote_new(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbol = str(payload.get("symbol", "")).upper()
        quote_id = str(payload.get("quote_id", ""))

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_quote_ack_msg(gateway_id, quote_id, False, reason)
            )
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.MARKET_MAKER:
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
            self.pub_sock.send_multipart(
                make_quote_ack_msg(gateway_id, quote_id, False, "Missing symbol")
            )
            return
        if self._allowed_symbols and symbol not in self._allowed_symbols:
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
            self.pub_sock.send_multipart(
                make_quote_ack_msg(
                    gateway_id,
                    quote_id,
                    False,
                    f"{symbol} is halted — quotes rejected during circuit breaker halt",
                )
            )
            return

        try:
            bid_price = to_ticks(float(payload["bid_price"]), symbol)
            ask_price = to_ticks(float(payload["ask_price"]), symbol)
            bid_qty = int(payload["bid_qty"])
            ask_qty = int(payload["ask_qty"])
            tif = TIF(str(payload.get("tif", "DAY")).upper())
        except (KeyError, TypeError, ValueError):
            self.pub_sock.send_multipart(
                make_quote_ack_msg(gateway_id, quote_id, False, "Invalid quote payload")
            )
            return

        if bid_qty <= 0 or ask_qty <= 0:
            self.pub_sock.send_multipart(
                make_quote_ack_msg(
                    gateway_id, quote_id, False, "Quote quantities must be positive"
                )
            )
            return
        if bid_price >= ask_price:
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
                self.pub_sock.send_multipart(
                    make_quote_ack_msg(
                        gateway_id,
                        quote_id,
                        False,
                        f"Quote size must be >= {mm_min_qty}",
                    )
                )
                return

        previous = self._quote_index.remove(gateway_id, symbol)
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
        )
        ask = Order.create(
            symbol=symbol,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=ask_qty,
            gateway_id=gateway_id,
            tif=tif,
            price=ask_price,
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
        for quote_order in (bid, ask):
            trades, events = book.process(quote_order, match=True, now=now)
            for evt in events:
                if evt.status in _FILL_STATUSES:
                    self.pub_sock.send_multipart(
                        make_fill_msg(
                            evt.gateway_id,
                            evt.id,
                            fill_qty=evt.quantity - evt.remaining_qty,
                            fill_price=(
                                from_ticks(book.last_trade_price, evt.symbol)
                                if book.last_trade_price is not None
                                else 0.0
                            ),
                            remaining_qty=evt.remaining_qty,
                            status=evt.status.value,
                            order=evt.to_dict(),
                        )
                    )
                    if evt.quote_id:
                        self._on_quote_leg_filled(evt)
                elif evt.status == OrderStatus.CANCELLED:
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

        entry = self._quote_index.remove(gateway_id, symbol)
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

        if session.disconnect_behaviour == DisconnectBehaviour.LEAVE_ALL:
            return

        removed_quotes = self._quote_index.cancel_all_for_gateway(gateway_id)
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
                self._quote_index.remove(gateway_id, symbol_filter)
                cancelled_quotes += self._cancel_quote_entry(
                    entry, reason="Kill switch"
                )
        else:
            entries = self._quote_index.cancel_all_for_gateway(gateway_id)
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

        if self.verbose:
            print(
                f"[ENGINE] COMBO {combo.combo_id} accepted "
                f"({len(combo.legs)} legs) from {combo.gateway_id}"
            )

        # Create child orders and post to books
        for i, leg in enumerate(combo.legs):
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
                smp_action=leg.smp_action,
            )
            child.combo_parent_id = combo.id
            child.leg_index = i

            combo.child_order_ids.append(child.id)
            combo.leg_statuses[i] = OrderStatus.NEW.value
            combo.leg_fill_qty[i] = 0
            self._order_to_combo[child.id] = combo.id
            self._order_symbol[child.id] = leg.symbol

            book = self._book(leg.symbol)
            trades, events = book.process(child)

            for evt in events:
                if evt.status in (OrderStatus.PARTIAL, OrderStatus.FILLED):
                    self.pub_sock.send_multipart(
                        make_fill_msg(
                            evt.gateway_id,
                            evt.id,
                            fill_qty=evt.quantity - evt.remaining_qty,
                            fill_price=(
                                from_ticks(book.last_trade_price, evt.symbol)
                                if book.last_trade_price is not None
                                else 0.0
                            ),
                            remaining_qty=evt.remaining_qty,
                            status=evt.status.value,
                            order=evt.to_dict(),
                        )
                    )
                    if evt.combo_parent_id and evt.id != child.id:
                        self._check_combo_after_child_event(evt)
                elif evt.status == OrderStatus.REJECTED:
                    self.pub_sock.send_multipart(
                        make_ack_msg(
                            evt.gateway_id,
                            evt.id,
                            accepted=False,
                            reason="Insufficient liquidity",
                        )
                    )
                elif evt.status == OrderStatus.CANCELLED:
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
            if self.verbose:
                print(f"[ENGINE] COMBO {combo.combo_id} MATCHED (all legs filled)")
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

        for i, child_id in enumerate(combo.child_order_ids):
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
        if self.verbose:
            print(
                f"[ENGINE] COMBO {combo.combo_id} {terminal_status.value}"
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
            print(f"[ENGINE] Invalid session transition: {exc}", file=sys.stderr)
            return

        from_state = self._session_state

        # Validate transition
        allowed = VALID_TRANSITIONS.get(from_state, set())
        if to_state not in allowed:
            print(
                f"[ENGINE] Invalid transition {from_state.value} → {to_state.value} "
                f"(allowed: {', '.join(s.value for s in allowed)})",
                file=sys.stderr,
            )
            return

        # --- Uncrossing on exit from auction / no-matching phases ---
        needs_uncross = not is_matching_enabled(from_state) and (
            is_matching_enabled(to_state) or to_state == SessionState.CLOSED
        )
        if needs_uncross:
            self._run_uncross(from_state)

        # --- Expire auction-only orders when their window closes ---
        if from_state == SessionState.OPENING_AUCTION:
            self._expire_tif(TIF.ATO)
        if from_state == SessionState.CLOSING_AUCTION:
            self._expire_tif(TIF.ATC)

        # --- Apply the transition ---
        self._session_state = to_state

        if to_state == SessionState.CLOSED:
            # End-of-day reset for any still-halted symbols (e.g. L3 rest-of-day).
            for symbol, cb in self._circuit_breakers.items():
                if cb.halted:
                    cb.deactivate()
                    self._halted_symbols[symbol] = False

        self.pub_sock.send_multipart(
            make_session_state_msg(to_state.value, prev_state=from_state.value)
        )
        print(f"[ENGINE] Session: {from_state.value} → {to_state.value}")

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
        from_state: SessionState,
        symbol_filter: str | None = None,
    ) -> None:
        """Run the equilibrium-price uncrossing on every (or one) symbol book.

        Parameters
        ----------
        from_state    : The session state from which the uncross is triggered
                        (currently unused in the body, kept for call-site clarity).
        symbol_filter : When provided, only uncross this specific symbol.
                        Used by ``_flush_circuit_breakers()`` for per-symbol
                        resumption auctions.
        """
        for symbol, book in self.books.items():
            if symbol_filter is not None and symbol != symbol_filter:
                continue
            result = compute_equilibrium(book)
            if result.eq_price is not None and result.eq_qty > 0:
                trades, events = execute_uncross(book, result.eq_price)

                for evt in events:
                    if evt.status in (OrderStatus.PARTIAL, OrderStatus.FILLED):
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
                    self._publish_trade(trade)

                self._mark_dirty(symbol)

                if self.verbose:
                    print(
                        f"[ENGINE] UNCROSS {symbol}: {len(trades)} trade(s) "
                        f"@ {result.eq_price}, qty={result.eq_qty}, "
                        f"surplus={result.surplus} ({result.imbalance_side})"
                    )
            else:
                if self.verbose:
                    print(f"[ENGINE] UNCROSS {symbol}: no crossable interest")

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
        for i, (leg, raw) in enumerate([(leg1, leg1_raw), (leg2, leg2_raw)], 1):
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

            for evt in events:
                if evt.status in (OrderStatus.PARTIAL, OrderStatus.FILLED):
                    self.pub_sock.send_multipart(
                        make_fill_msg(
                            evt.gateway_id,
                            evt.id,
                            fill_qty=evt.quantity - evt.remaining_qty,
                            fill_price=(
                                from_ticks(book.last_trade_price, evt.symbol)
                                if book.last_trade_price is not None
                                else 0.0
                            ),
                            remaining_qty=evt.remaining_qty,
                            status=evt.status.value,
                            order=evt.to_dict(),
                        )
                    )
                    if evt.status == OrderStatus.FILLED and evt.oco_group_id:
                        self._check_oco_after_event(evt)
                elif evt.status == OrderStatus.CANCELLED:
                    self.pub_sock.send_multipart(
                        make_cancelled_msg(evt.gateway_id, evt.id)
                    )
                    if evt.oco_group_id:
                        self._check_oco_after_event(evt)
                elif evt.status == OrderStatus.REJECTED:
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

        if self.verbose:
            print(f"[ENGINE] OCO {oco_id}: legs {leg1.id[:8]} and {leg2.id[:8]} posted")

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

        if self.verbose:
            print(f"[ENGINE] OCO {oco_id} cancelled by {gateway_id}")

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

        if self.verbose:
            print(
                f"[ENGINE] OCO {oco_id}: sibling cancelled after {order.id[:8]} {order.status.value}"
            )

    def _handle_cancel(self, payload: dict[str, Any]) -> None:
        order_id = payload["order_id"]
        gateway_id = str(payload["gateway_id"]).upper()

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_ack_msg(gateway_id, order_id, accepted=False, reason=reason)
            )
            return

        # O(1) lookup via global order→symbol map
        symbol = self._order_symbol.get(order_id)
        book = self.books.get(symbol) if symbol else None
        cancelled = book.cancel_order(order_id) if book else None

        if cancelled:
            self._order_symbol.pop(order_id, None)
            self.pub_sock.send_multipart(make_cancelled_msg(gateway_id, order_id))
            self._mark_dirty(cancelled.symbol)
            if self.verbose:
                print(f"[ENGINE] CANCELLED {order_id[:8]}")
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

    def _handle_amend(self, payload: dict[str, Any]) -> None:
        order_id = payload["order_id"]
        gateway_id = str(payload["gateway_id"]).upper()
        new_price = payload.get("price")
        new_qty = payload.get("qty")

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_ack_msg(gateway_id, order_id, accepted=False, reason=reason)
            )
            return

        if new_price is None and new_qty is None:
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
            self.pub_sock.send_multipart(
                make_ack_msg(
                    gateway_id, order_id, accepted=False, reason="Order not found"
                )
            )
            return
        assert symbol is not None

        now = now_ns()
        amended, priority_reset, err = book.amend_order(
            order_id,
            new_price=(
                to_ticks(float(new_price), symbol) if new_price is not None else None
            ),
            new_qty=new_qty,
            now=now,
        )

        if amended is None:
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
        self._mark_dirty(amended.symbol)
        if self.verbose:
            prio_str = " (priority reset)" if priority_reset else " (priority kept)"
            print(
                f"[ENGINE] AMENDED {order_id[:8]} price={amended.price} "
                f"qty={amended.quantity}{prio_str}"
            )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        print("\n[ENGINE] Shutting down …")
        self._running = False

        all_resting: list[Order] = []
        for book in self.books.values():
            for order in book.resting_orders():
                if order.tif == TIF.GTC:
                    all_resting.append(order)
                else:
                    # Expire DAY orders
                    order.status = OrderStatus.EXPIRED
                    self.pub_sock.send_multipart(
                        make_expired_msg(order.gateway_id, order.id)
                    )
                    # If this was a combo child, cascade-cancel sibling legs
                    if order.combo_parent_id:
                        self._check_combo_after_child_event(order)

        save_gtc_orders(all_resting, GTC_ORDERS_FILE)
        print(f"[ENGINE] Saved {len(all_resting)} GTC order(s) to {GTC_ORDERS_FILE}")

        # Persist resting GTC combos
        save_gtc_combos(list(self._combos.values()), GTC_COMBOS_FILE)
        n_combos = sum(
            1
            for c in self._combos.values()
            if c.tif == TIF.GTC
            and c.status in (ComboStatus.PENDING, ComboStatus.PARTIALLY_MATCHED)
        )
        if n_combos:
            print(f"[ENGINE] Saved {n_combos} GTC combo(s) to {GTC_COMBOS_FILE}")

        save_book_stats(self.books, BOOK_STATS_FILE)
        print(
            f"[ENGINE] Saved book statistics for {len(self.books)} symbol(s) to {BOOK_STATS_FILE}"
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

    def run(self) -> None:
        self._restore_gtc()
        self._load_config()  # seed stats + MM orders (after GTC restore)

        # Create drop copy publisher here (not in __init__) so that unit tests
        # that call handlers directly never attempt to bind ZMQ port 5557.
        try:
            from edumatcher.engine.drop_copy import DropCopyPublisher

            self._drop_copy = DropCopyPublisher(zmq.Context.instance())
            print("[ENGINE] Drop copy PUB bound on port 5557")
        except zmq.ZMQError as exc:
            print(
                f"[ENGINE] WARNING: Drop copy unavailable — {exc}",
                file=sys.stderr,
            )

        self._running = True

        poller = zmq.Poller()
        poller.register(self.pull_sock, zmq.POLLIN)

        print(f"[ENGINE] Listening on PULL={ENGINE_PULL_ADDR}  PUB={ENGINE_PUB_ADDR}")

        signal.signal(signal.SIGINT, lambda *_: self._shutdown())
        signal.signal(signal.SIGTERM, lambda *_: self._shutdown())

        while self._running:
            try:
                socks = dict(poller.poll(timeout=200))  # 200 ms tick
            except zmq.ZMQError:
                break
            if self.pull_sock in socks:
                frames = self.pull_sock.recv_multipart()
                topic, payload = decode(frames)
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
                    elif topic == "risk.kill_switch":
                        self._handle_kill_switch(payload)
                    elif topic == "session.transition":
                        self._handle_session_transition(payload)
                except Exception as exc:
                    print(f"[ENGINE] Error processing {topic}: {exc}", file=sys.stderr)
            # Throttled snapshot publish — runs every poll tick (max 200ms)
            self._flush_snapshots()
            # Check circuit breaker timers — resume halted symbols
            self._flush_circuit_breakers()


def main() -> None:
    parser = argparse.ArgumentParser(description="EduMatcher matching engine")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print each order and trade to stdout",
    )
    parser.add_argument(
        "--config",
        "-c",
        metavar="FILE",
        help="Engine config YAML (default: engine_config.yaml)",
    )
    args = parser.parse_args()
    Engine(verbose=args.verbose, config_path=args.config).run()


if __name__ == "__main__":
    main()
