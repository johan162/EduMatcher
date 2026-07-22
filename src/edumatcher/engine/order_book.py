"""
OrderBook — per-symbol limit order book with matching engine.

Supports: MARKET, LIMIT, STOP, STOP_LIMIT, FOK, ICEBERG, IOC, TRAILING_STOP

Data structures
---------------
  _bids  max-heap: list of (-price, timestamp, order)
  _asks  min-heap: list of ( price, timestamp, order)
  _buy_stops  min-heap of (stop_price, timestamp, order)  — BUY STOP/STOP_LIMIT
  _sell_stops max-heap of (-stop_price, timestamp, order) — SELL STOP/STOP_LIMIT
  _order_index : dict[order_id, Order]  — fast lookup for cancels
  _bid_qty / _ask_qty : dict[price, int]  — price-level qty index for O(1) FOK checks

Heap entries use (±price, timestamp) so that heapq always pops the
best-priced, earliest-submitted order first (price-time priority).
"""

from __future__ import annotations

import heapq
from collections import deque
from typing import Any, Optional

from edumatcher.models.clock import now_ns
from edumatcher.models.price import from_ticks

from edumatcher.models.order import (
    Order,
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
)
from edumatcher.models.trade import Trade

# L9: neutral aggressor flag for auction (uncross) prints, where both orders
# are resting and there is no true aggressor.
_AUCTION_AGGRESSOR = "AUCTION"

# Module-level frozenset avoids allocating a temporary tuple inside _peek()
# on every heap operation (called O(N) times per aggressive order).
_DEAD_STATUSES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)


# __slots__ keeps this hot, high-frequency wrapper small and fast
# (see docs-design/perf-notes.md).
class _HeapEntry:
    """Wrapper so Order objects are never compared directly by heapq."""

    __slots__ = ("key", "order", "valid")

    def __init__(self, key: tuple[Any, ...], order: Order, valid: bool = True) -> None:
        self.key = key
        self.order = order
        self.valid = valid

    def __lt__(self, other: "_HeapEntry") -> bool:
        return self.key < other.key


# __slots__ speeds up the per-order attribute access on the hot path
# (see docs-design/perf-notes.md).
class OrderBook:
    __slots__ = (
        "symbol",
        "_bids",
        "_asks",
        "_buy_stops",
        "_sell_stops",
        "_trailing_stops",
        "_bid_qty",
        "_ask_qty",
        "_order_index",
        "_entry_index",
        "last_trade_price",
        "last_trade_qty",
        "last_buy_price",
        "last_sell_price",
        "recent_trades",
        "daily_qty",
        "daily_value_ticks",
        "daily_trades",
        "_has_stops",
        "_arrival_seq",
    )

    def __init__(self, symbol: str, recent_trades_maxlen: int = 20) -> None:
        self.symbol = symbol
        self._bids: list[_HeapEntry] = []  # max-heap via negated price
        self._asks: list[_HeapEntry] = []  # min-heap

        # Stop orders split into two heaps for O(log k) trigger checks:
        #   _buy_stops:  min-heap keyed by (stop_price, timestamp)  — fires when price >= stop
        #   _sell_stops: max-heap keyed by (-stop_price, timestamp) — fires when price <= stop
        self._buy_stops: list[_HeapEntry] = []
        self._sell_stops: list[_HeapEntry] = []

        # Trailing stops: simple list, iterated after each trade to update prices.
        # Lazy deletion: orders with CANCELLED/EXPIRED/FILLED status are dropped on next scan.
        self._trailing_stops: list[Order] = []

        # Price-level quantity index: price → total visible resting qty
        self._bid_qty: dict[int, int] = {}
        self._ask_qty: dict[int, int] = {}

        # order_id → _HeapEntry (for bid/ask) or Order (for stops)
        self._order_index: dict[str, Order] = {}
        self._entry_index: dict[str, _HeapEntry] = {}

        self.last_trade_price: Optional[int] = None
        self.last_trade_qty: Optional[int] = None
        self.last_buy_price: Optional[int] = (
            None  # last trade where buyer was aggressor
        )
        self.last_sell_price: Optional[int] = (
            None  # last trade where seller was aggressor
        )
        self.recent_trades: deque[Trade] = deque(maxlen=recent_trades_maxlen)

        # Daily cumulative stats — reset only on engine restart (new OrderBook instance).
        # pm-stats owns EOD aggregation; these counters are session-only.
        # M11: accumulate turnover in INTEGER ticks (price_ticks * qty) and
        # convert to display money once at the boundary — accumulating display
        # floats loses exactness over many fills.
        self.daily_qty: int = 0
        self.daily_value_ticks: int = 0
        self.daily_trades: int = 0

        # True when the book has any resting stop or trailing-stop orders.
        # Guards the stop-check calls in process() to avoid function-call
        # overhead on every fill when no stops are present.
        self._has_stops: bool = False

        # Monotonic arrival sequence for time priority (finding H1).  Assigned
        # by the book when an order is placed on a heap, so queue position is
        # determined by engine arrival order — never by the client-supplied
        # `timestamp`, which a participant could back-date to jump the queue.
        self._arrival_seq: int = 0

    def _next_seq(self) -> int:
        """Return the next monotonic arrival sequence number."""
        self._arrival_seq += 1
        return self._arrival_seq

    @property
    def daily_value(self) -> float:
        """Session turnover in display money (M11).

        Computed once from the exact integer-tick accumulator
        (``daily_value_ticks`` = Σ price_ticks × qty), so no float drift
        accumulates across fills.
        """
        return from_ticks(self.daily_value_ticks, self.symbol)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def process(
        self,
        order: Order,
        *,
        match: bool = True,
        now: int | None = None,
        _cascade_stops: bool = True,
    ) -> tuple[list[Trade], list[Order]]:
        """
        Accept an incoming order and attempt to match it.

        Parameters
        ----------
        match : bool
            When False the order is rested on the book without attempting to
            sweep the opposite side.  Used during auction / no-matching phases
            to collect interest.  MARKET and FOK orders are rejected when
            match=False because they cannot rest.
        now : int | None
            Pre-computed timestamp from the engine's dispatch loop, threaded
            through to Trade.create() and stop conversion so the whole batch
            shares one clock read (see docs-design/perf-notes.md).

        Returns
        -------
        trades  : list of Trade objects produced
        events  : list of Order objects whose status changed (fills, rejects)
                  — caller publishes these as order.fill / order.ack messages
        """
        trades: list[Trade] = []
        events: list[Order] = []

        # Compute the batch timestamp once if the caller did not provide one.
        if now is None:
            now = now_ns()

        # --- No-matching mode: queue-only ---
        if not match:
            if order.order_type in (OrderType.MARKET, OrderType.FOK, OrderType.IOC):
                order.status = OrderStatus.REJECTED
                events.append(order)
                return trades, events
            if order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
                self._add_stop(order, events)
                return trades, events
            # TRAILING_STOP has price=None, so it must go to the trailing-stop
            # list, NOT _rest() (which asserts price is not None).  Without this
            # branch a trailing stop submitted during a halt/auction crashed and
            # a persisted GTC trailing stop bricked engine startup (finding C6).
            if order.order_type == OrderType.TRAILING_STOP:
                self._add_trailing_stop(order, events)
                return trades, events
            # LIMIT / ICEBERG — rest without sweeping
            self._rest(order)
            return trades, events

        if order.order_type == OrderType.MARKET:
            self._match_market(order, trades, events, now)

        elif order.order_type == OrderType.LIMIT:
            self._match_limit(order, trades, events, now)

        elif order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            # M2: if the stop's trigger is already breached by the last trade
            # price, trigger it on entry instead of parking it dormant until
            # some unrelated future trade.
            if self.last_trade_price is not None and self._stop_is_triggered(
                order, self.last_trade_price
            ):
                self._trigger_stop_now(order, trades, events, now)
            else:
                self._add_stop(order, events)

        elif order.order_type == OrderType.FOK:
            self._match_fok(order, trades, events, now)

        elif order.order_type == OrderType.ICEBERG:
            self._match_iceberg(order, trades, events, now)

        elif order.order_type == OrderType.IOC:
            self._match_ioc(order, trades, events, now)

        elif order.order_type == OrderType.TRAILING_STOP:
            self._add_trailing_stop(order, events)

        # After any trade, check if stop orders should trigger.
        # #23: drive the cascade (stop → trade → stop → …) with an explicit work
        # queue instead of recursion, so a long chain cannot exhaust Python's
        # recursion limit.  Triggered orders are matched with _cascade_stops=
        # False; any stops they trigger are picked up by the loop below.
        if trades and self._has_stops and _cascade_stops:
            pending = self._check_stops(now) + self._check_trailing_stops(now)
            while pending:
                t_order = pending.pop(0)
                sub_trades, sub_events = self.process(
                    t_order, now=now, _cascade_stops=False
                )
                trades.extend(sub_trades)
                events.extend(sub_events)
                if sub_trades and self._has_stops:
                    pending.extend(self._check_stops(now))
                    pending.extend(self._check_trailing_stops(now))

        return trades, events

    def get_order(self, order_id: str) -> Optional[Order]:
        """Return the resting Order with *order_id*, or None if not found."""
        return self._order_index.get(order_id)

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """
        Cancel a resting order.  Returns the Order if found and cancellable,
        else None.
        """
        order = self._order_index.get(order_id)
        if order is None:
            return None
        if order.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        ):
            return None

        order.status = OrderStatus.CANCELLED
        entry = self._entry_index.get(order_id)
        if entry:
            entry.valid = False
            # Remove remaining visible qty from price-level index.
            # STOP / STOP_LIMIT orders rest in the stop heaps and never
            # contribute to _bid_qty/_ask_qty; deducting them here would
            # corrupt the qty index of genuine resting orders that share the
            # stop's limit price (STOP_LIMIT carries a non-None price).
            o = entry.order
            if (
                o.order_type not in (OrderType.STOP, OrderType.STOP_LIMIT)
                and o.price is not None
            ):
                qty = (
                    o.displayed_qty or 0
                    if o.order_type == OrderType.ICEBERG
                    else o.remaining_qty
                )
                self._deduct_qty_index(o, qty)
        # H7: purge the cancelled order from both id maps (also invalidates the
        # heap/stop entry for lazy deletion) so terminal orders do not linger.
        self._purge_from_indexes(order)
        return order

    def amend_order(
        self,
        order_id: str,
        new_price: Optional[int] = None,
        new_qty: Optional[int] = None,
        now: Optional[int] = None,
    ) -> tuple[Optional[Order], bool, str]:
        """
        Amend a resting order's price and/or quantity.

        Priority rules (matching real exchange behaviour):
        - Quantity decrease only (same price): priority is PRESERVED
        - Price change or quantity increase: priority is LOST (new timestamp)

        Parameters
        ----------
        order_id  : ID of the order to amend
        new_price : New limit price (None = keep current)
        new_qty   : New total quantity (None = keep current)
        now       : Pre-computed timestamp

        Returns
        -------
        (order, priority_reset, reason)
        - order: the amended Order, or None if not amendable
        - priority_reset: True if the order lost its time priority
        - reason: error description if order is None
        """
        order = self._order_index.get(order_id)
        if order is None:
            return None, False, "Order not found"
        if order.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        ):
            return None, False, f"Cannot amend {order.status.value} order"
        # Only LIMIT and ICEBERG resting orders can be amended
        if order.order_type not in (OrderType.LIMIT, OrderType.ICEBERG):
            return None, False, f"Cannot amend {order.order_type.value} orders"

        if now is None:
            now = now_ns()

        old_price = order.price
        old_qty = order.quantity
        filled_qty = old_qty - order.remaining_qty

        # Resolve new values
        price = new_price if new_price is not None else old_price
        qty = new_qty if new_qty is not None else old_qty
        # Only LIMIT / ICEBERG orders reach here (checked above) and they always
        # carry a price — bind the narrowed int to a local (L7) so the qty-index
        # updates below need no Optional-arithmetic type: ignores.
        assert price is not None, "Amendable order must have a price"

        # Validation
        if qty <= 0:
            return None, False, "Quantity must be positive"
        if qty <= filled_qty:
            return None, False, "New quantity must exceed already-filled quantity"
        if price <= 0:
            return None, False, "Price must be positive"

        # Determine if priority is lost
        price_changed = price != old_price
        qty_increased = qty > old_qty
        priority_reset = price_changed or qty_increased

        # Remove old qty from price-level index
        entry = self._entry_index.get(order_id)
        if entry and old_price is not None:
            old_visible = (
                order.displayed_qty or 0
                if order.order_type == OrderType.ICEBERG
                else order.remaining_qty
            )
            self._deduct_qty_index(order, old_visible)

        # Update order fields
        order.price = price
        order.quantity = qty
        order.remaining_qty = qty - filled_qty
        if order.order_type == OrderType.ICEBERG and order.visible_qty is not None:
            order.displayed_qty = min(order.visible_qty, order.remaining_qty)

        new_visible = (
            order.displayed_qty or 0
            if order.order_type == OrderType.ICEBERG
            else order.remaining_qty
        )
        if priority_reset:
            order.timestamp = now
            # Priority lost: assign a fresh arrival sequence so the order goes
            # to the back of the queue at its (new) price level (finding H1).
            order.arrival_seq = self._next_seq()
            # Invalidate old entry and re-insert with new key
            if entry:
                entry.valid = False
            if order.side == Side.BUY:
                key = (-price, order.arrival_seq)
                heap = self._bids
                self._bid_qty[price] = self._bid_qty.get(price, 0) + new_visible
            else:
                key = (price, order.arrival_seq)
                heap = self._asks
                self._ask_qty[price] = self._ask_qty.get(price, 0) + new_visible
            new_entry = _HeapEntry(key=key, order=order)
            heapq.heappush(heap, new_entry)
            self._entry_index[order.id] = new_entry
        else:
            # Priority preserved — update qty index with new visible amount
            if order.side == Side.BUY:
                self._bid_qty[price] = self._bid_qty.get(price, 0) + new_visible
            else:
                self._ask_qty[price] = self._ask_qty.get(price, 0) + new_visible

        return order, priority_reset, ""

    def resting_orders(self) -> list[Order]:
        """Return all resting (NEW / PARTIAL) orders — used for persistence."""
        return [
            o
            for o in self._order_index.values()
            if o.status in (OrderStatus.NEW, OrderStatus.PARTIAL)
        ]

    def best_bid_ticks(self) -> int | None:
        """Return best bid price in ticks, or None if no active bid exists."""
        return max((px for px, qty in self._bid_qty.items() if qty > 0), default=None)

    def best_ask_ticks(self) -> int | None:
        """Return best ask price in ticks, or None if no active ask exists."""
        return min((px for px, qty in self._ask_qty.items() if qty > 0), default=None)

    def restore_stats(
        self, last_buy_price: Optional[int], last_sell_price: Optional[int]
    ) -> None:
        """Restore persisted side-specific last-trade prices after an engine restart."""
        self.last_buy_price = last_buy_price
        self.last_sell_price = last_sell_price

    def depth_snapshot(self, tolerance_ticks: int) -> "dict[str, Any]":
        """
        Compute book-depth metrics within *tolerance_ticks* of the last trade.

        Uses the ``_bid_qty`` / ``_ask_qty`` price-level index for O(P)
        performance where P = number of distinct price levels — much cheaper
        than iterating heap entries as ``snapshot()`` does.

        Parameters
        ----------
        tolerance_ticks : How many ticks on each side of the last trade to
                          include.  Example: last trade = 15000 ticks,
                          tolerance = 100 → bids in [14900, 15000] and asks
                          in [15000, 15100].

        Returns
        -------
        A dict with keys:
          ``symbol``, ``mid_price_ticks``, ``mid_price``, ``tolerance_ticks``,
          ``bid_depth`` (total qty), ``ask_depth`` (total qty),
          ``imbalance`` (float in [-1, 1]; positive = more bids),
          ``microprice`` (imbalance-weighted midprice as a float price),
          ``cost_to_move`` (display notional to sweep the asks within the
          window — i.e. to move the price up by ``tolerance_ticks``).

        Returns an *empty dict* if no trades have occurred yet (no meaningful
        mid price to anchor the window on).
        """
        if self.last_trade_price is None:
            return {}

        mid = self.last_trade_price
        lower = mid - tolerance_ticks
        upper = mid + tolerance_ticks

        bid_depth = sum(qty for px, qty in self._bid_qty.items() if lower <= px <= mid)
        ask_depth = sum(qty for px, qty in self._ask_qty.items() if mid <= px <= upper)
        total = bid_depth + ask_depth
        imbalance = (bid_depth - ask_depth) / total if total > 0 else 0.0

        # L10: cost to move the market up by `tolerance_ticks` — the notional a
        # buyer must spend to sweep every ask level within the window.  Computed
        # in integer ticks (Σ price_ticks × qty) then converted once to display.
        cost_to_move_ticks = sum(
            px * qty for px, qty in self._ask_qty.items() if mid <= px <= upper
        )
        cost_to_move = from_ticks(cost_to_move_ticks, self.symbol)

        mid_price = from_ticks(mid, self.symbol)

        # Compute microprice from best bid/ask if available; fall back to mid.
        best_bid_ticks = (
            max(px for px, qty in self._bid_qty.items() if qty > 0)
            if any(qty > 0 for qty in self._bid_qty.values())
            else None
        )
        best_ask_ticks = (
            min(px for px, qty in self._ask_qty.items() if qty > 0)
            if any(qty > 0 for qty in self._ask_qty.values())
            else None
        )
        if best_bid_ticks is not None and best_ask_ticks is not None:
            bid_price = from_ticks(best_bid_ticks, self.symbol)
            ask_price = from_ticks(best_ask_ticks, self.symbol)
            spread = ask_price - bid_price
            top_mid = (bid_price + ask_price) / 2
            microprice = top_mid + imbalance * spread / 2
        else:
            microprice = mid_price

        return {
            "symbol": self.symbol,
            "mid_price_ticks": mid,
            "mid_price": mid_price,
            "tolerance_ticks": tolerance_ticks,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "imbalance": imbalance,
            "microprice": microprice,
            "cost_to_move": cost_to_move,
        }

    def snapshot(self) -> dict[str, Any]:
        """
        Build a book snapshot for the viewer.
        Bids and asks are aggregated by price level.
        Iceberg orders contribute only displayed_qty to the visible size.
        """
        bids: dict[int, dict[str, Any]] = {}
        asks: dict[int, dict[str, Any]] = {}

        for entry in self._bids:
            if not entry.valid:
                continue
            o = entry.order
            if o.status in (
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
            ):
                continue
            price = o.price
            assert price is not None  # resting orders always have a price (L7)
            qty = (
                o.displayed_qty or 0
                if o.order_type == OrderType.ICEBERG
                else o.remaining_qty
            )
            lvl = bids.setdefault(price, {"price": price, "qty": 0, "count": 0})
            lvl["qty"] += qty
            lvl["count"] += 1

        for entry in self._asks:
            if not entry.valid:
                continue
            o = entry.order
            if o.status in (
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
            ):
                continue
            price = o.price
            assert price is not None  # resting orders always have a price (L7)
            qty = (
                o.displayed_qty or 0
                if o.order_type == OrderType.ICEBERG
                else o.remaining_qty
            )
            lvl = asks.setdefault(price, {"price": price, "qty": 0, "count": 0})
            lvl["qty"] += qty
            lvl["count"] += 1

        bid_rows = []
        for lvl in bids.values():
            bid_rows.append(
                {
                    "price": from_ticks(lvl["price"], self.symbol),
                    "qty": lvl["qty"],
                    "count": lvl["count"],
                }
            )

        ask_rows = []
        for lvl in asks.values():
            ask_rows.append(
                {
                    "price": from_ticks(lvl["price"], self.symbol),
                    "qty": lvl["qty"],
                    "count": lvl["count"],
                }
            )

        recent_rows: list[dict[str, Any]] = []
        for t in list(self.recent_trades)[-5:]:
            recent_rows.append(
                {
                    "id": t.id,
                    "symbol": t.symbol,
                    "buy_order_id": t.buy_order_id,
                    "sell_order_id": t.sell_order_id,
                    "buy_gateway_id": t.buy_gateway_id,
                    "sell_gateway_id": t.sell_gateway_id,
                    "price": from_ticks(t.price, self.symbol),
                    "quantity": t.quantity,
                    "timestamp": t.timestamp / 1_000_000_000,
                }
            )

        return {
            "symbol": self.symbol,
            "bids": sorted(bid_rows, key=lambda x: -x["price"]),
            "asks": sorted(ask_rows, key=lambda x: x["price"]),
            "last_price": (
                from_ticks(self.last_trade_price, self.symbol)
                if self.last_trade_price is not None
                else None
            ),
            "last_qty": self.last_trade_qty,
            "last_buy_price": (
                from_ticks(self.last_buy_price, self.symbol)
                if self.last_buy_price is not None
                else None
            ),
            "last_sell_price": (
                from_ticks(self.last_sell_price, self.symbol)
                if self.last_sell_price is not None
                else None
            ),
            "recent_trades": recent_rows,
        }

    # ------------------------------------------------------------------
    # Internal matching helpers
    # ------------------------------------------------------------------

    def _match_market(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        opposite = self._asks if order.side == Side.BUY else self._bids
        self._sweep(
            order, opposite, price_limit=None, trades=trades, events=events, now=now
        )
        # Remainder is discarded (no resting market orders).  Emit a terminal
        # event so the owner is notified — without this append a totally
        # unfilled MARKET order got a positive ACK and then silence (#5).
        if order.remaining_qty > 0 and order.status != OrderStatus.FILLED:
            order.status = OrderStatus.CANCELLED  # unsatisfied market → discard
            events.append(order)

    def _match_limit(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        opposite = self._asks if order.side == Side.BUY else self._bids
        self._sweep(
            order,
            opposite,
            price_limit=order.price,
            trades=trades,
            events=events,
            now=now,
        )
        # Guard against resting an order the sweep already killed — e.g. SMP
        # CANCEL_AGGRESSOR / CANCEL_BOTH sets status=CANCELLED but leaves
        # remaining_qty > 0.  Resting it re-registers a dead order and leaks
        # phantom quantity into the level index (finding C3).
        if order.remaining_qty > 0 and order.status not in _DEAD_STATUSES:
            self._rest(order)

    def _match_fok(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        """Check full fillability first; only execute if entire quantity can be filled.

        #15: the pre-check walks the actual resting orders so it (a) counts the
        HIDDEN quantity of resting icebergs — the visible level index alone
        under-counts and spuriously rejects — and (b) excludes same-gateway
        liquidity that SMP would skip/cancel, which would otherwise let the
        sweep run dry and leave the FOK partially filled (a fill-or-kill
        violation).  Rejecting before any fill keeps FOK all-or-nothing.
        """
        opposite = self._asks if order.side == Side.BUY else self._bids
        available = self._fok_available_qty(order, opposite)
        if available < order.quantity:
            # The FOK cannot fully fill.  Resolve SMP the same way a sweep
            # would, then finalise a terminal status WITHOUT any partial fill.
            # smp_action is None only if the engine boundary failed to
            # resolve it (should not happen — see SmpAction's docstring);
            # treat that defensively as "no SMP" rather than raising.
            smp = order.smp_action or SmpAction.NONE
            price_limit = order.price
            same_gw_conflicts = [
                e.order
                for e in opposite
                if e.valid
                and e.order.status not in _DEAD_STATUSES
                and e.order.gateway_id == order.gateway_id
                and e.order.price is not None
                and (
                    price_limit is None
                    or (
                        e.order.price <= price_limit
                        if order.side == Side.BUY
                        else e.order.price >= price_limit
                    )
                )
            ]
            # CANCEL_RESTING / CANCEL_BOTH removes the conflicting resting orders.
            if smp in (SmpAction.CANCEL_RESTING, SmpAction.CANCEL_BOTH):
                for resting in same_gw_conflicts:
                    self._smp_cancel_resting(resting, events)
            # CANCEL_AGGRESSOR / CANCEL_BOTH cancels the aggressor when it would
            # have self-matched; a genuine liquidity shortfall is a plain reject.
            if (
                smp in (SmpAction.CANCEL_AGGRESSOR, SmpAction.CANCEL_BOTH)
                and same_gw_conflicts
            ):
                order.status = OrderStatus.CANCELLED
            else:
                order.status = OrderStatus.REJECTED
            events.append(order)
            return
        self._sweep(
            order,
            opposite,
            price_limit=order.price,
            trades=trades,
            events=events,
            now=now,
        )
        # Safety net: if the sweep somehow failed to fully fill (e.g. an SMP
        # CANCEL_AGGRESSOR encountered mid-sweep), do not leave a resting or
        # limbo remainder — cancel it and notify.  With the accurate pre-check
        # above this should not fire for genuine liquidity.
        if order.remaining_qty > 0 and order.status not in _DEAD_STATUSES:
            order.status = OrderStatus.CANCELLED
            events.append(order)

    def fillable_quantity(self, side: Side, price_limit: Optional[int]) -> int:
        """Resting quantity an incoming order of *side* could execute against
        at or within *price_limit*, counting hidden iceberg quantity.

        Used by the AON combo pre-check (M5) to decide whether every leg can
        fill before any leg is allowed to execute.
        """
        heap = self._asks if side == Side.BUY else self._bids
        total = 0
        for entry in heap:
            if not entry.valid:
                continue
            o = entry.order
            if o.status in _DEAD_STATUSES or o.price is None:
                continue
            if price_limit is not None:
                if side == Side.BUY and o.price > price_limit:
                    continue
                if side == Side.SELL and o.price < price_limit:
                    continue
            total += o.remaining_qty
        return total

    def _fok_available_qty(self, order: Order, heap: list[_HeapEntry]) -> int:
        """Liquidity a FOK could actually execute against.

        Walks live resting orders on *heap* up to the FOK's price limit,
        counting each order's full ``remaining_qty`` (so resting iceberg hidden
        quantity is included), and excluding same-gateway orders when SMP is
        active (they are skipped/cancelled and cannot fill the FOK).  See H8.
        """
        price_limit = order.price
        side = order.side
        # See _process_fok's comment: None should never reach here, but treat
        # it as "no SMP" rather than raising if it somehow does.
        smp = order.smp_action or SmpAction.NONE
        gw = order.gateway_id
        total = 0
        for entry in heap:
            if not entry.valid:
                continue
            o = entry.order
            if o.status in _DEAD_STATUSES:
                continue
            if o.price is None:
                continue
            if price_limit is not None:
                if side == Side.BUY and o.price > price_limit:
                    continue
                if side == Side.SELL and o.price < price_limit:
                    continue
            # SMP: same-gateway resting liquidity is skipped/cancelled by the
            # sweep, so it cannot be used to fill this FOK.
            if smp != SmpAction.NONE and o.gateway_id == gw:
                continue
            total += o.remaining_qty
        return total

    def _match_iceberg(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        """
        Iceberg enters the book as a LIMIT order showing only displayed_qty.
        Each time the visible slice is fully consumed, it replenishes from hidden qty.
        """
        opposite = self._asks if order.side == Side.BUY else self._bids
        # Try to fill the current peak against resting orders on the other side
        self._sweep_iceberg(order, opposite, trades, events, now)
        # If still has quantity, rest the displayed slice — but not if the
        # sweep killed the order (e.g. SMP cancel), which would leak phantom
        # quantity into the level index (finding C3).
        if order.remaining_qty > 0 and order.status not in _DEAD_STATUSES:
            self._rest(order)

    def _match_ioc(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        """
        Immediate-Or-Cancel: sweep up to price_limit, then cancel any unfilled remainder.
        Unlike LIMIT, the order never rests on the book.
        """
        opposite = self._asks if order.side == Side.BUY else self._bids
        self._sweep(
            order,
            opposite,
            price_limit=order.price,
            trades=trades,
            events=events,
            now=now,
        )
        if order.remaining_qty > 0 and order.status not in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
        ):
            order.status = OrderStatus.CANCELLED
            events.append(order)

    def _add_trailing_stop(self, order: Order, events: list[Order]) -> None:
        """
        Add a trailing stop to the active trailing-stop list.
        The order must have stop_price (initial stop level) and trail_offset (distance).
        """
        assert (
            order.stop_price is not None
        ), "Trailing stop must have an initial stop_price"
        assert (
            order.trail_offset is not None and order.trail_offset > 0
        ), "Trailing stop must have a positive trail_offset"
        self._trailing_stops.append(order)
        self._order_index[order.id] = order
        self._has_stops = True
        events.append(order)  # ack (status = NEW)

    @staticmethod
    def _stop_is_triggered(order: Order, price: int) -> bool:
        """True when *price* has breached *order*'s stop trigger (M2).

        A BUY stop fires when the market rises to/through its stop price; a
        SELL stop fires when the market falls to/through it.
        """
        if order.stop_price is None:
            return False
        if order.side == Side.BUY:
            return price >= order.stop_price
        return price <= order.stop_price

    def _trigger_stop_now(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        """Convert an already-breached stop to its live type and match it
        immediately on entry (M2), instead of resting it until a future trade."""
        if order.order_type == OrderType.STOP:
            order.order_type = OrderType.MARKET
            order.price = None
            order.timestamp = now
            self._match_market(order, trades, events, now)
        else:  # STOP_LIMIT → LIMIT
            order.order_type = OrderType.LIMIT
            order.timestamp = now
            self._match_limit(order, trades, events, now)

    def _add_stop(self, order: Order, events: list[Order]) -> None:
        assert order.stop_price is not None, "Stop order must have a stop_price"
        # Arrival sequence breaks ties among stops at the same trigger price
        # (finding H1 / M10) instead of the client timestamp.
        order.arrival_seq = self._next_seq()
        if order.side == Side.BUY:
            key = (order.stop_price, order.arrival_seq)
            entry = _HeapEntry(key=key, order=order)
            heapq.heappush(self._buy_stops, entry)
        else:
            key = (-order.stop_price, order.arrival_seq)
            entry = _HeapEntry(key=key, order=order)
            heapq.heappush(self._sell_stops, entry)
        self._order_index[order.id] = order
        self._entry_index[order.id] = entry
        self._has_stops = True
        events.append(order)  # ack (status = NEW)

    # ------------------------------------------------------------------
    # Sweep helpers
    # ------------------------------------------------------------------

    def _smp_cancel_resting(self, order: Order, events: list[Order]) -> None:
        """Mark a resting order as CANCELLED (SMP), remove from index."""
        order.status = OrderStatus.CANCELLED
        entry = self._entry_index.get(order.id)
        if entry:
            entry.valid = False
            if order.price is not None:
                qty = (
                    order.displayed_qty or 0
                    if order.order_type == OrderType.ICEBERG
                    else order.remaining_qty
                )
                self._deduct_qty_index(order, qty)
        self._order_index.pop(order.id, None)
        events.append(order)

    def _sweep(
        self,
        aggressor: Order,
        opposite_heap: list[_HeapEntry],
        price_limit: Optional[int],
        trades: list[Trade],
        events: list[Order],
        now: int,
    ) -> None:
        """Generic price-time sweep for MARKET / LIMIT / FOK."""
        # Cache immutable aggressor attributes / bound methods as locals for the
        # tight sweep loop (see docs-design/perf-notes.md).
        _side = aggressor.side
        # None should never reach here (see SmpAction's docstring) but treat
        # it as "no SMP" defensively rather than raising.
        _smp_action = aggressor.smp_action or SmpAction.NONE
        _gw_id = aggressor.gateway_id
        _peek = self._peek  # method lookup once
        _apply_fill = self._apply_fill

        while aggressor.remaining_qty > 0 and opposite_heap:
            best = _peek(opposite_heap)
            if best is None:
                break
            # Resting bid/ask orders always carry a price (L7: local narrowing).
            best_price = best.price
            assert best_price is not None
            # Price check
            if price_limit is not None:
                if _side == Side.BUY and best_price > price_limit:
                    break
                if _side == Side.SELL and best_price < price_limit:
                    break

            # Self-match prevention
            if _smp_action != SmpAction.NONE and _gw_id == best.gateway_id:
                if _smp_action == SmpAction.CANCEL_AGGRESSOR:
                    aggressor.status = OrderStatus.CANCELLED
                    events.append(aggressor)
                    return
                elif _smp_action == SmpAction.CANCEL_RESTING:
                    self._smp_cancel_resting(best, events)
                    continue  # skip this resting order; try next
                elif _smp_action == SmpAction.CANCEL_BOTH:
                    self._smp_cancel_resting(best, events)
                    aggressor.status = OrderStatus.CANCELLED
                    events.append(aggressor)
                    return

            # Cap the fill against a PASSIVE iceberg at its displayed slice, not
            # its hidden remaining_qty (finding #17).  Filling the full hidden qty
            # in one shot jumps the queue past same-price orders with better time
            # priority and over-deducts the level index (which only ever held the
            # displayed slice).  _apply_fill replenishes and re-queues the fresh
            # peak to the back, so the loop naturally returns to this level in
            # correct price-time order.
            _passive_avail = (
                best.displayed_qty
                if best.order_type == OrderType.ICEBERG
                and best.displayed_qty is not None
                else best.remaining_qty
            )
            fill_qty = min(aggressor.remaining_qty, _passive_avail)

            _apply_fill(aggressor, best, fill_qty, best_price, trades, events, now)

    def _sweep_iceberg(
        self,
        iceberg: Order,
        opposite_heap: list[_HeapEntry],
        trades: list[Trade],
        events: list[Order],
        now: int,
    ) -> None:
        """
        Sweep visible slice of iceberg; replenish peak if exhausted and hidden qty remains.
        """
        # None should never reach here (see SmpAction's docstring) but treat
        # it as "no SMP" defensively rather than raising.
        _smp_action = iceberg.smp_action or SmpAction.NONE
        while iceberg.remaining_qty > 0 and opposite_heap:
            best = self._peek(opposite_heap)
            if best is None:
                break
            # Both the iceberg and the resting order always carry a price
            # (L7: local narrowing removes the Optional-comparison ignores).
            best_price = best.price
            assert best_price is not None and iceberg.price is not None
            if iceberg.side == Side.BUY and best_price > iceberg.price:
                break
            if iceberg.side == Side.SELL and best_price < iceberg.price:
                break

            # Self-match prevention
            if _smp_action != SmpAction.NONE and iceberg.gateway_id == best.gateway_id:
                if _smp_action == SmpAction.CANCEL_AGGRESSOR:
                    iceberg.status = OrderStatus.CANCELLED
                    events.append(iceberg)
                    return
                elif _smp_action == SmpAction.CANCEL_RESTING:
                    self._smp_cancel_resting(best, events)
                    continue
                elif _smp_action == SmpAction.CANCEL_BOTH:
                    self._smp_cancel_resting(best, events)
                    iceberg.status = OrderStatus.CANCELLED
                    events.append(iceberg)
                    return

            # Iceberg fills up to its current displayed slice; and when the
            # passive resting order is itself an iceberg, cap against its
            # displayed slice too (finding #17) rather than its hidden qty.
            visible = iceberg.displayed_qty or 0
            _passive_avail = (
                best.displayed_qty
                if best.order_type == OrderType.ICEBERG
                and best.displayed_qty is not None
                else best.remaining_qty
            )
            fill_qty = min(visible, _passive_avail)

            self._apply_fill(iceberg, best, fill_qty, best_price, trades, events, now)

            # After filling, replenish iceberg peak if needed and still resting
            if iceberg.remaining_qty > 0 and iceberg.displayed_qty == 0:
                new_peak = min(iceberg.visible_qty or 0, iceberg.remaining_qty)
                iceberg.displayed_qty = new_peak
                # Reuse the cached batch timestamp for the replenished slice
                # that re-queues to the back at the same price level.
                iceberg.timestamp = now

    def _available_qty(
        self,
        heap: list[_HeapEntry],
        price_limit: Optional[int],
        side: Side,
    ) -> int:
        """
        Total available quantity at/within price_limit for FOK pre-check.
        Uses the price-level qty index for O(p) where p = number of price levels,
        rather than O(n) over every heap entry.
        """
        qty_index = self._ask_qty if side == Side.BUY else self._bid_qty
        total = 0
        for price, qty in qty_index.items():
            if price_limit is not None:
                if side == Side.BUY and price > price_limit:
                    continue
                if side == Side.SELL and price < price_limit:
                    continue
            total += qty
        return total

    def _apply_fill(
        self,
        aggressor: Order,
        passive: Order,
        fill_qty: int,
        fill_price: int,
        trades: list[Trade],
        events: list[Order],
        now: int,
        both_resting: bool = False,
    ) -> None:
        """Record fill, update quantities/statuses, build Trade object.

        In continuous matching the aggressor is *not* resting, so only the
        passive side is counted in the price-level qty index and only that
        side is deducted.  In an auction uncross (``both_resting=True``) both
        orders are resting and both must be deducted from the index — omitting
        the aggressor side leaves phantom bid quantity (finding #3).
        """
        # Determine buy/sell sides
        if aggressor.side == Side.BUY:
            buy_order, sell_order = aggressor, passive
        else:
            buy_order, sell_order = passive, aggressor

        # L9: in an auction uncross both orders are resting, so there is no
        # true aggressor — the print carries a neutral flag ("AUCTION") rather
        # than always labelling the buyer as aggressor.
        aggressor_side = _AUCTION_AGGRESSOR if both_resting else aggressor.side.value

        # Pass the cached batch timestamp to Trade.create() so it does not
        # read the clock again (see docs-design/perf-notes.md).
        trade = Trade.create(
            symbol=self.symbol,
            buy_order_id=buy_order.id,
            sell_order_id=sell_order.id,
            buy_gateway_id=buy_order.gateway_id,
            sell_gateway_id=sell_order.gateway_id,
            price=fill_price,
            quantity=fill_qty,
            aggressor_side=aggressor_side,
            now=now,
        )
        trades.append(trade)
        self.last_trade_price = fill_price
        self.last_trade_qty = fill_qty
        # Accumulate daily volume stats
        self.daily_qty += fill_qty
        self.daily_value_ticks += fill_price * fill_qty
        self.daily_trades += 1
        # Track side-specific last price (aggressor side determines the label).
        # L9: auction prints are neutral, so they update neither buy nor sell
        # side label (only last_trade_price, above).
        if not both_resting:
            if aggressor.side == Side.BUY:
                self.last_buy_price = fill_price
            else:
                self.last_sell_price = fill_price
        self.recent_trades.append(
            trade
        )  # deque(maxlen=20) handles eviction automatically

        # Update aggressor
        aggressor.remaining_qty -= fill_qty
        if aggressor.order_type == OrderType.ICEBERG:
            aggressor.displayed_qty = max(0, (aggressor.displayed_qty or 0) - fill_qty)
            if both_resting:
                if aggressor.remaining_qty > 0 and aggressor.displayed_qty == 0:
                    new_peak = min(aggressor.visible_qty or 0, aggressor.remaining_qty)
                    aggressor.displayed_qty = new_peak
                    aggressor.timestamp = now
                    self._deduct_qty_index(aggressor, fill_qty)
                    self._reinsert_iceberg(aggressor)
                else:
                    self._deduct_qty_index(aggressor, fill_qty)
        elif both_resting:
            self._deduct_qty_index(aggressor, fill_qty)
        aggressor.status = (
            OrderStatus.FILLED if aggressor.remaining_qty == 0 else OrderStatus.PARTIAL
        )
        if aggressor.status == OrderStatus.FILLED:
            # H7: purge terminal orders from the indexes so they do not grow
            # without bound and resting_orders() stays O(resting).
            self._purge_from_indexes(aggressor)
        events.append(aggressor)

        # Update passive order
        passive.remaining_qty -= fill_qty
        if passive.order_type == OrderType.ICEBERG:
            passive.displayed_qty = max(0, (passive.displayed_qty or 0) - fill_qty)
            if passive.remaining_qty > 0 and passive.displayed_qty == 0:
                new_peak = min(passive.visible_qty or 0, passive.remaining_qty)
                passive.displayed_qty = new_peak
                # Reuse the cached batch timestamp for iceberg replenishment.
                passive.timestamp = now
                # Deduct the consumed peak from the qty index BEFORE reinserting
                # the fresh peak.  Without this call the index over-counts by
                # fill_qty, corrupting FOK pre-checks and depth snapshots.
                self._deduct_qty_index(passive, fill_qty)
                self._reinsert_iceberg(passive)
            else:
                self._deduct_qty_index(passive, fill_qty)
        else:
            self._deduct_qty_index(passive, fill_qty)
        passive.status = (
            OrderStatus.FILLED if passive.remaining_qty == 0 else OrderStatus.PARTIAL
        )
        if passive.status == OrderStatus.FILLED:
            # H7: purge terminal orders from the indexes (also invalidates the
            # heap entry for lazy deletion).
            self._purge_from_indexes(passive)
        events.append(passive)

    def _purge_from_indexes(self, order: Order) -> None:
        """Remove a terminal order from the id→order and id→entry maps and
        invalidate its heap entry so _peek drops it lazily (finding H7).

        Safe to call for a pure taker that was never rested — the pops are
        no-ops.  Idempotent.
        """
        entry = self._entry_index.pop(order.id, None)
        if entry is not None:
            entry.valid = False
        self._order_index.pop(order.id, None)

    # ------------------------------------------------------------------
    # Heap management
    # ------------------------------------------------------------------

    def _deduct_qty_index(self, order: Order, qty: int) -> None:
        """Subtract qty from the price-level index for the given resting order."""
        if order.price is None or qty <= 0:
            return
        if order.side == Side.BUY:
            idx = self._bid_qty
        else:
            idx = self._ask_qty
        current = idx.get(order.price, 0)
        updated = current - qty
        if updated <= 0:
            idx.pop(order.price, None)
        else:
            idx[order.price] = updated

    def _rest(self, order: Order) -> None:
        """Place a resting order on the appropriate heap and update the qty index."""
        assert order.price is not None, "Resting order must have a price"
        # L7: bind the narrowed price to a local so mypy keeps the non-None
        # narrowing across the following calls (attribute narrowing is dropped
        # after a method call) — removes the Optional-arithmetic type: ignores.
        price = order.price
        qty = (
            order.displayed_qty or 0
            if order.order_type == OrderType.ICEBERG
            else order.remaining_qty
        )
        # Engine-assigned arrival sequence drives time priority (finding H1).
        order.arrival_seq = self._next_seq()
        if order.side == Side.BUY:
            key = (-price, order.arrival_seq)
            heap = self._bids
            self._bid_qty[price] = self._bid_qty.get(price, 0) + qty
        else:
            key = (price, order.arrival_seq)
            heap = self._asks
            self._ask_qty[price] = self._ask_qty.get(price, 0) + qty
        entry = _HeapEntry(key=key, order=order)
        heapq.heappush(heap, entry)
        self._order_index[order.id] = order
        self._entry_index[order.id] = entry

    def _reinsert_iceberg(self, order: Order) -> None:
        """Invalidate old heap entry and push fresh one after peak replenishment."""
        assert order.price is not None, "Iceberg must have a price"
        price = order.price
        old_entry = self._entry_index.get(order.id)
        if old_entry:
            old_entry.valid = False
        # Fresh arrival sequence sends the replenished peak to the back of the
        # queue at this price level (finding H1 — priority is seq-based).
        order.arrival_seq = self._next_seq()
        new_peak = order.displayed_qty or 0
        if order.side == Side.BUY:
            key = (-price, order.arrival_seq)
            heap = self._bids
            self._bid_qty[price] = self._bid_qty.get(price, 0) + new_peak
        else:
            key = (price, order.arrival_seq)
            heap = self._asks
            self._ask_qty[price] = self._ask_qty.get(price, 0) + new_peak
        entry = _HeapEntry(key=key, order=order)
        heapq.heappush(heap, entry)
        self._entry_index[order.id] = entry

    def _peek(self, heap: list[_HeapEntry]) -> Optional[Order]:
        """
        Return the best order on the heap, skipping stale (invalid/filled/cancelled) entries.
        Performs lazy deletion.
        """
        while heap:
            entry = heap[0]
            if not entry.valid:
                heapq.heappop(heap)
                continue
            o = entry.order
            if o.status in _DEAD_STATUSES:
                heapq.heappop(heap)
                entry.valid = False
                continue
            return o
        return None

    # ------------------------------------------------------------------
    # Stop order trigger
    # ------------------------------------------------------------------

    def _check_stops(self, now: int) -> list[Order]:
        """
        Check pending stop orders against last_trade_price using two heaps:
          _buy_stops  min-heap by stop_price — fire when last_price >= stop_price
          _sell_stops max-heap by -stop_price — fire when last_price <= stop_price
        O(k log k) where k = number of triggered stops (usually 0).
        """
        if self.last_trade_price is None:
            return []

        triggered: list[Order] = []

        # BUY stops: fire when price rises to/above stop_price
        while self._buy_stops:
            entry = self._buy_stops[0]
            if not entry.valid or entry.order.status in (
                OrderStatus.CANCELLED,
                OrderStatus.EXPIRED,
            ):
                heapq.heappop(self._buy_stops)
                continue
            stop_price, _ = entry.key
            if self.last_trade_price < stop_price:
                break  # remaining stops need a higher price
            heapq.heappop(self._buy_stops)
            stop_order = entry.order
            if stop_order.order_type == OrderType.STOP:
                stop_order.order_type = OrderType.MARKET
                stop_order.price = None
            else:
                stop_order.order_type = OrderType.LIMIT
            # Reuse the cached batch timestamp.
            stop_order.timestamp = now
            self._order_index.pop(stop_order.id, None)
            # Remove from _entry_index; if the triggered order converts to MARKET
            # (never rests) the entry would otherwise leak indefinitely.
            # STOP_LIMIT→LIMIT orders overwrite this entry in _rest(), so popping
            # first is safe for both cases.
            self._entry_index.pop(stop_order.id, None)
            triggered.append(stop_order)

        # SELL stops: fire when price falls to/below stop_price
        while self._sell_stops:
            entry = self._sell_stops[0]
            if not entry.valid or entry.order.status in (
                OrderStatus.CANCELLED,
                OrderStatus.EXPIRED,
            ):
                heapq.heappop(self._sell_stops)
                continue
            neg_stop_price, _ = entry.key
            stop_price = -neg_stop_price
            if self.last_trade_price > stop_price:
                break  # remaining stops need a lower price
            heapq.heappop(self._sell_stops)
            stop_order = entry.order
            if stop_order.order_type == OrderType.STOP:
                stop_order.order_type = OrderType.MARKET
                stop_order.price = None
            else:
                stop_order.order_type = OrderType.LIMIT
            # Reuse the cached batch timestamp.
            stop_order.timestamp = now
            self._order_index.pop(stop_order.id, None)
            self._entry_index.pop(stop_order.id, None)
            triggered.append(stop_order)

        if not self._buy_stops and not self._sell_stops and not self._trailing_stops:
            self._has_stops = False

        return triggered

    def _check_trailing_stops(self, now: int) -> list[Order]:
        """
        Update trailing stop prices based on the latest trade and return any triggered orders.

        Ratchet logic (only tightens the stop, never loosens it):
          SELL trailing stop — stop_price rises as market rises
            new_stop = trade_price - trail_offset; if new_stop > stop_price: update
            triggered when: trade_price <= stop_price
          BUY trailing stop — stop_price falls as market falls
            new_stop = trade_price + trail_offset; if new_stop < stop_price: update
            triggered when: trade_price >= stop_price

        O(t) where t = number of active trailing stops (typically small).
        """
        if self.last_trade_price is None:
            return []

        trade_price = self.last_trade_price
        triggered: list[Order] = []
        still_active: list[Order] = []

        for order in self._trailing_stops:
            if order.status in (
                OrderStatus.CANCELLED,
                OrderStatus.EXPIRED,
                OrderStatus.FILLED,
            ):
                # Lazy-delete terminal orders; do NOT re-add to still_active
                continue

            offset = order.trail_offset
            stop_price = order.stop_price
            if offset is None or stop_price is None:
                still_active.append(order)
                continue

            if order.side == Side.SELL:
                # Ratchet the stop up if the market has risen
                candidate = trade_price - offset
                if candidate > stop_price:
                    order.stop_price = candidate
                    stop_price = candidate
                # Trigger when price falls to/below the current stop
                if trade_price <= stop_price:
                    order.order_type = OrderType.MARKET
                    order.trail_offset = None
                    # Reuse the cached batch timestamp.
                    order.timestamp = now
                    self._order_index.pop(order.id, None)
                    triggered.append(order)
                    continue
            else:  # BUY trailing stop
                # Ratchet the stop down if the market has fallen
                candidate = trade_price + offset
                if candidate < stop_price:
                    order.stop_price = candidate
                    stop_price = candidate
                # Trigger when price rises to/at the current stop
                if trade_price >= stop_price:
                    order.order_type = OrderType.MARKET
                    order.trail_offset = None
                    # Reuse the cached batch timestamp.
                    order.timestamp = now
                    self._order_index.pop(order.id, None)
                    triggered.append(order)
                    continue

            still_active.append(order)

        self._trailing_stops = still_active
        if not self._trailing_stops and not self._buy_stops and not self._sell_stops:
            self._has_stops = False
        return triggered

    def trigger_stops(self, now: int) -> list[Order]:
        """Return all stop and trailing-stop orders triggered at the current
        ``last_trade_price``.  Returns an empty list if no stops are registered.

        Public wrapper around the private ``_check_stops`` /
        ``_check_trailing_stops`` pair so callers outside the class (e.g.
        ``Engine._run_uncross``) can trigger stops without pyright
        ``reportPrivateUsage`` violations.
        """
        if not self._has_stops:
            return []
        return self._check_stops(now) + self._check_trailing_stops(now)
