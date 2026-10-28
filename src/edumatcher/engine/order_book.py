"""
OrderBook — per-symbol limit order book with matching engine.

Supports: MARKET, LIMIT, STOP, STOP_LIMIT, FOK, ICEBERG, IOC, TRAILING_STOP

This file is the heart of the exchange.  If you read only one file to
understand how a trade happens, read this one -- top to bottom, in the order
set out below.

Where this file sits
--------------------
The engine process (``engine/main.py``) owns the network side; this class owns
the *rules of matching* and knows nothing about ZeroMQ::

    gateway --PUSH--> Engine.run()                   (receive + decode)
                      Engine._dispatch_pull_message  (route by topic)
                      Engine._handle_new_order       (validate, ACK, gate on session)
                      OrderBook.process(order)       <== YOU ARE HERE
                          |  returns (trades, events)
                      Engine._publish_dispatch       (order.fill / order.cancelled /
                                                      reject, then trade.executed)
                      --PUB--> gateways, market data, clearing, audit ...

``OrderBook`` is a plain, synchronous, single-threaded Python object.  It
never publishes anything; it *mutates* orders and *returns* what happened, and
the engine turns that into bus messages.  That separation is what makes the
matching rules unit-testable without a network.

The life of one incoming order
------------------------------
``process(order)`` is the single entry point.  For a LIMIT order it goes:

1. ``process``            picks the matcher for the order type (``_match_limit``).
2. ``_match_limit``       calls ``_sweep`` against the OPPOSITE side's heap.
3. ``_sweep``             loops: look at the best opposite order (``_peek``),
                          stop if its price is worse than our limit, apply
                          self-match prevention, then take
                          ``min(our remaining, their available)``.
4. ``_apply_fill``        for each such step: builds a ``Trade``, updates both
                          orders' ``remaining_qty`` / ``status``, updates the
                          price-level index, and appends *both* orders to
                          ``events``.
5. back in ``_match_limit``  whatever is left over RESTS on our own side
                          (``_rest``) -- that is the difference between LIMIT
                          and IOC/MARKET, which discard the remainder.
6. back in ``process``    every trade moved ``last_trade_price``, so resting
                          stops may now trigger (``_check_stops``); each
                          triggered stop is itself processed as a new order.
7. return ``(trades, events)`` to the engine.

The *aggressor* (a.k.a. taker) is the incoming order; the *passive* order (a.k.a.
maker) is the one already resting.  A trade always happens at the PASSIVE
order's price, never the aggressor's: a buy limit at 101 that meets a resting
ask at 100 trades at 100 -- the aggressor gets price improvement.

Data structures
---------------
Per side there is one *heap* of ``_HeapEntry`` objects (not of bare orders --
see ``_HeapEntry``)::

  _bids        max-heap on price:  key = (-price, arrival_seq)
  _asks        min-heap on price:  key = ( price, arrival_seq)
  _buy_stops   min-heap on trigger price: key = ( stop_price, arrival_seq)
  _sell_stops  max-heap on trigger price: key = (-stop_price, arrival_seq)
  _trailing_stops  plain list (their trigger price moves, so a heap is useless)

Python's ``heapq`` is a *min*-heap, so the best bid (the HIGHEST price) is
obtained by storing the price negated: the smallest ``-price`` is the largest
price.  The second key component, ``arrival_seq``, breaks ties between equal
prices: the lower number arrived first and so is served first.  Together this
is exactly *price-time priority*: ``heap[0]`` is always the order that must be
matched next.  ``arrival_seq`` is a monotonic counter this book assigns on
admission (finding H1) -- never the client-supplied ``timestamp``, which a
participant could back-date to jump the queue.

Why a heap and not one sorted list per price level?  Pushing and popping the
best order are both O(log n), and matching only ever needs "the best one".  The
price of that choice is that a heap cannot remove an order from the *middle*
cheaply, which is what the next paragraph is about.

Lazy deletion (the thing that looks strange at first)
-----------------------------------------------------
Cancelling an order that sits deep in a heap would cost O(n).  Instead the
book does not remove it: it sets ``entry.valid = False`` and leaves the dead
entry where it is.  Whoever next looks at the top of the heap (``_peek``)
pops and discards dead entries until it finds a live one.  Two consequences
every reader must keep in mind:

* ``len(self._bids)`` is NOT the number of resting bids; it includes garbage.
* Garbage deep in the heap would otherwise accumulate forever, so
  ``_compact_heaps`` rebuilds the heaps when garbage outnumbers live entries.

Side indexes (kept in lock-step with the heaps)
-----------------------------------------------
  _order_index : order_id -> Order       resting orders, incl. stops (cancel/amend lookup)
  _entry_index : order_id -> _HeapEntry  the live heap entry of a resting order,
                                         so cancel can flip ``valid`` in O(1)
  _orders_by_gateway : gateway_id -> {order_id}   "everything gateway X has here"
  _bid_qty / _ask_qty : price -> visible qty      total shown quantity per level

``_bid_qty`` / ``_ask_qty`` are the aggregate *display* depth per price: they
count an iceberg's shown slice only, not its hidden remainder.  They feed the
best bid/offer and depth statistics, not the matching itself (the sweep walks
the heaps).  Every code path that adds or removes quantity from a heap MUST
make the matching change to these dicts, which is the most common source of
bugs when this file is edited -- see ``_rest``, ``_apply_fill``,
``_deduct_qty_index``.

Order lifecycle (``OrderStatus``)
---------------------------------
  NEW --fill--> PARTIAL --fill--> FILLED          (terminal)
  NEW/PARTIAL --cancel / SMP / unfilled MARKET or IOC remainder--> CANCELLED
  NEW --FOK short of liquidity / cannot rest in this session phase--> REJECTED
  A terminal order is purged from every index (``_purge_from_indexes``).

Corner cases worth knowing before you read the code
---------------------------------------------------
* Iceberg orders: only ``displayed_qty`` is matchable per pass; when the
  slice is used up a fresh slice is created and queued at the BACK of its
  price level (it loses time priority).  See ``_apply_fill`` and
  ``_reinsert_iceberg``.
* Self-match prevention (SMP): an order from gateway G may not trade with a
  resting order from the same G.  Four policies, see ``SmpAction``.
* Stops are not "in the book": they wait in separate heaps and only become
  real MARKET/LIMIT orders when a trade price crosses their trigger.
* The *same* ``Order`` object appears in ``events`` once per fill it took
  part in, always in its final state; the engine de-duplicates.
* Two matching modes: continuous (``match=True``) and call/auction phases
  (``match=False``: orders only queue; ``engine/auction.py`` later crosses the
  book at one price using ``_apply_fill(both_resting=True)``).
"""

from __future__ import annotations

import heapq
import logging
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Optional

from edumatcher.models.clock import now_ns
from edumatcher.models.price import from_ticks, get_tick_decimals

from edumatcher.models.order import (
    Order,
    OrderOrigin,
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
    TIF,
)
from edumatcher.models.trade import Trade

log = logging.getLogger(__name__)

# L9: neutral aggressor flag for auction (uncross) prints, where both orders
# are resting and there is no true aggressor.  It takes the place of "BUY" /
# "SELL" in Trade.aggressor_side, so consumers must expect a third value.
_AUCTION_AGGRESSOR = "AUCTION"

# The "terminal" statuses: an order in one of these is finished and must never
# match again.  _peek() uses it to recognise dead heap entries (see "Lazy
# deletion" in the module docstring) and most other checks use it to ask "is
# this order still alive?".
#
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


@dataclass(frozen=True, slots=True)
class BookStats:
    """Sizes of one book, for the health beacon (operator dashboard §8.3).

    ``resting_orders`` counts every order the book holds -- stops and trailing
    stops included, as ``resting_orders()`` does; ``gtc_orders`` is the subset
    with TIF=GTC, the long orders that survive the close; ``stop_orders`` is the live
    subset of those that are stops. ``heap_entries`` includes entries already
    invalidated but not yet compacted; ``live_entries`` does not.
    """

    resting_orders: int
    gtc_orders: int
    stop_orders: int
    bid_levels: int
    ask_levels: int
    heap_entries: int
    live_entries: int
    recent_trades: int

    @property
    def heap_garbage_pct(self) -> float:
        """Share of heap entries that are dead -- whether compaction keeps up."""
        if self.heap_entries == 0:
            return 0.0
        return 100.0 * (self.heap_entries - self.live_entries) / self.heap_entries


#: Rebuild the heaps once they hold more than this many entries per live order
#: (plus _COMPACT_SLACK) -- see OrderBook._compact_heaps.  The slack keeps a
#: nearly empty book from rebuilding its heaps after every single cancel.
_COMPACT_FACTOR = 2
_COMPACT_SLACK = 64


# __slots__ keeps this hot, high-frequency wrapper small and fast
# (see docs-design/perf-notes.md).
class _HeapEntry:
    """One slot in a price heap: a sort key, the order it stands for, and a
    liveness flag.

    Why not push the ``Order`` itself?  Three reasons:

    * ``heapq`` orders items with ``<``.  Wrapping the order lets us define
      ``<`` as "compare the key" and guarantees two Orders are never compared
      directly (a dataclass Order has no sensible ordering).
    * The key is *frozen at push time*.  A heap is only correct if the key of
      an item never changes while it is inside; an Order's price or
      ``arrival_seq`` can change (amend, iceberg refill), so a changed order is
      pushed again as a NEW entry and the old one is retired.
    * ``valid`` is the lazy-deletion flag.  Setting ``valid = False`` is how
      the book "removes" an order from the middle of a heap in O(1); the dead
      entry is thrown away when it eventually reaches the top (``_peek``) or
      when ``_compact_heaps`` sweeps the garbage.

    ``key`` is ``(+/-price, arrival_seq)`` -- see the module docstring.
    """

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
    """The order book of ONE symbol: its resting orders, its stops, and the
    matching rules.  The engine keeps one instance per symbol in
    ``Engine.books``; they never interact.

    Read the module docstring first.  Public surface, in the order a student
    will meet it: ``process`` (a new order arrives), ``cancel_order``,
    ``amend_order``, ``snapshot`` / ``depth_snapshot`` (read-only views for
    market data), and ``run_stops`` (used by the auction code).
    Everything starting with an underscore is internal machinery.
    """

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
        "_orders_by_gateway",
        "_gtc_count",
        "last_trade_price",
        "last_trade_qty",
        "last_buy_price",
        "last_sell_price",
        "recent_trades",
        "daily_qty",
        "daily_value_ticks",
        "daily_trades",
        "_has_stops",
        "on_quote_leg_fill",
        "on_oco_leg_done",
        "_triggered",
        "_arrival_seq",
        "trace",
        "last_trade_id",
    )

    def __init__(self, symbol: str, recent_trades_maxlen: int = 20) -> None:
        self.symbol = symbol

        # The two sides of the book.  Both are plain lists managed with
        # heapq; heap[0] is always the best entry (see module docstring).
        # Bids store the NEGATED price in the key so that Python's min-heap
        # yields the highest bid first.
        self._bids: list[_HeapEntry] = []  # max-heap via negated price
        self._asks: list[_HeapEntry] = []  # min-heap

        # Stop orders split into two heaps for O(log k) trigger checks:
        #   _buy_stops:  min-heap keyed by (stop_price, arrival_seq)  — fires when price >= stop
        #   _sell_stops: max-heap keyed by (-stop_price, arrival_seq) — fires when price <= stop
        # The heap top is the stop closest to firing, so a trade that moves
        # nothing is answered by looking at heap[0] only.
        self._buy_stops: list[_HeapEntry] = []
        self._sell_stops: list[_HeapEntry] = []

        # Trailing stops: simple list, iterated after each trade to update prices.
        # (Not a heap: every trade can move every trailing stop's trigger price.)
        # Lazy deletion: orders with CANCELLED/EXPIRED/FILLED status are dropped on next scan.
        self._trailing_stops: list[Order] = []

        # Price-level quantity index: price → total visible resting qty
        # (an iceberg contributes only its displayed slice).  Display depth,
        # not the matching source of truth: matching walks the heaps.
        self._bid_qty: dict[int, int] = {}
        self._ask_qty: dict[int, int] = {}

        # order_id → Order for every resting order (stops included): lets a
        # cancel / amend find its order without scanning a heap.
        self._order_index: dict[str, Order] = {}
        # order_id → the order's CURRENT live _HeapEntry (plain/quote orders
        # and stop/stop-limit orders; trailing stops have none).  Cancelling
        # flips entry.valid to False: this is the handle for lazy deletion.
        self._entry_index: dict[str, _HeapEntry] = {}

        # Secondary index over _order_index: gateway_id → set of order_ids
        # that are currently resting in this book, of ANY origin/type
        # (plain orders, quote legs, stop/stop-limit, trailing stop).
        # Answers "which resting orders does this gateway have in this
        # book?" in O(k) (k = that gateway's resting orders here) instead
        # of a full scan of resting_orders() — see
        # Engine._handle_gateway_disconnect, _handle_kill_switch* and
        # _handle_cancel_symbol, and ../../../docs/books/architecture-and-development/part-1-architecture/020-guided-tour.md
        # §10 for the rationale.
        # Maintained by every funnel that can make an order resting or stop
        # it resting — the same funnels that maintain _order_index
        # (_entry_index skips trailing stops, which have no heap entry):
        #   added:   _rest() (plain + quote LIMIT orders), _add_stop()
        #            (STOP/STOP_LIMIT), _add_trailing_stop() (TRAILING_STOP)
        #   removed: _purge_from_indexes() (cancel, full fill, SMP-cancel —
        #            covers plain/quote orders and any resting order routed
        #            through cancel_order()), _check_stops() and
        #            _check_trailing_stops() (a triggered stop is popped
        #            here directly, before it re-enters via _rest() if the
        #            triggered order goes on to rest again — so a single
        #            stop order is discarded and (re-)added at most once
        #            per trigger, never double-counted).
        # An insertion-ordered dict, not a set (X11): batch cancels walk it,
        # and a set of id strings would emit them in the per-process hash
        # order, so two runs of the same input would publish differently.
        self._orders_by_gateway: dict[str, dict[str, None]] = {}
        # How many of those orders are TIF=GTC -- the ones that outlive the
        # day.  Moves with _orders_by_gateway (_track_gateway on the way in,
        # _discard_from_gateway_index on the way out) so book_stats() can
        # report it without walking the book.
        self._gtc_count = 0

        # Prices are always INTEGER TICKS inside the engine (never floats), so
        # arithmetic and dict keys are exact; conversion to display money
        # happens only at the edge (from_ticks).  last_trade_price is what
        # stops compare against and what the engine's price collar anchors on;
        # None until the first trade of the session.
        self.last_trade_price: Optional[int] = None
        #: The trade that set last_trade_price (what a stop triggers on).
        self.last_trade_id: Optional[str] = None
        #: Where the book reports what it did that no trade or order event
        #: shows: an order resting or arming (with its priority), an iceberg
        #: refilling, a trailing stop ratcheting, a stop triggering. The
        #: engine shares one list across its books and publishes it
        #: (engine.trace.<SYM>, order.triggered.<GW>); None reports nothing.
        self.trace: Optional[list[tuple[Any, ...]]] = None
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

        # Called after every continuous fill of a quote leg (an order with a
        # quote_id), while the dispatch is still running, so the engine can
        # pull the quote's sibling leg before anything else matches: a stop
        # the fill triggers must not trade against a leg the engine has just
        # reported cancelled (finding X3). Not called in an uncross, where
        # both sides are resting and the auction walks both heaps.
        self.on_quote_leg_fill: Optional[Callable[[Order], None]] = None

        # Called when an OCO leg (an order with an oco_group_id) ends while
        # the dispatch is still running -- filled, cancelled (SMP, an IOC's
        # rest, a triggered stop leg short of liquidity) or rejected -- so the
        # engine can pull the sibling before a later stop in the cascade
        # trades with it (findings X15, X8d; the OCO twin of X3). Not called
        # for an uncross's own prints, whose follow-ups the engine runs after
        # execute_uncross (X8b).
        self.on_oco_leg_done: Optional[Callable[[Order], None]] = None

        # Stops the running cascade (or an uncross) has triggered and queued
        # to match: out of every index, but still cancellable until their
        # turn, so an OCO sibling cancel reaches them (X15).
        self._triggered: dict[str, Order] = {}

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

        THIS IS THE ENTRY POINT of the matching engine.  By the time an order
        gets here the engine has already authenticated the gateway, checked
        the symbol, validated quantities/prices, applied the price collar and
        the session/halt gates, and sent the positive ACK (all in
        ``Engine._handle_new_order``).  The book only decides *how the order
        trades*.

        Steps, in order:

        1. Sanity guard for icebergs (corrupt orders must fail loudly).
        2. A stop that was triggered earlier and is now being matched leaves
           the ``_triggered`` waiting room (or is dropped if cancelled).
        3. ``match=False`` -> queue only (auction / halted phases), no trading.
        4. ``match=True``  -> dispatch on ``order_type`` to the matcher,
           which fills against the opposite side and rests any remainder.
        5. Tell the engine if an OCO leg just died (``_oco_leg_ended``).
        6. Stop cascade: the trades above moved ``last_trade_price``; stops
           that fire are processed as fresh orders, which may trade, move the
           price again and fire more stops (iteratively, not recursively).

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
        _cascade_stops : bool
            Internal.  False while processing an order that a stop has just
            released, so that the *outer* call's work-queue (step 6), not a
            recursive call, handles any further stops.

        Returns
        -------
        trades  : list of Trade objects produced
        events  : list of Order objects whose status changed (fills, rejects)
                  — caller publishes these as order.fill / order.ack messages.
                  The SAME Order can occur several times (once per fill it
                  took part in, each time in its final state); the engine
                  de-duplicates in ``_publish_dispatch``.  Because the lists
                  are shared with the matchers below (they ``append`` to
                  them), nothing is returned from the ``_match_*`` helpers.
        """
        # An iceberg's displayed slice is what a sweep is allowed to take from
        # it, so a slice larger than what is left over-fills the order to a
        # negative remaining_qty -- after which the slice is zero, every
        # further pass of the sweep fills nothing, neither side moves, and
        # `while aggressor.remaining_qty > 0 and opposite_heap` never ends.
        # The engine hangs rather than mis-fills.
        #
        # The ALF path cannot produce one (engine/main.py's M7 rejects
        # visible_qty > quantity before the order gets here) and no internal
        # path builds an iceberg with a visible slice at all, so this guards
        # the callers that reach a book *without* passing M7: startup restore
        # from a persisted gtc_orders.json, and anything constructing an Order
        # directly. Cheap to state, and the alternative failure is a stopped
        # exchange.
        if (
            order.order_type == OrderType.ICEBERG
            and order.displayed_qty is not None
            and not 0 < order.displayed_qty <= order.remaining_qty
        ):
            raise ValueError(
                f"ICEBERG {order.id} has a displayed slice of "
                f"{order.displayed_qty} against {order.remaining_qty} "
                f"remaining; it must be positive and no larger"
            )

        trades: list[Trade] = []
        events: list[Order] = []

        # A stop that fired during an earlier step of this cascade is parked in
        # self._triggered until its turn comes -- i.e. until now.  Pop it out
        # of that waiting room.  If it was CANCELLED while it waited (its OCO
        # sibling filled first, X15) it must do nothing at all: no trade, no
        # event, so it returns immediately.  For every ordinary new order the
        # dict is empty and this whole test short-circuits on `self._triggered`.
        if (
            self._triggered
            and self._triggered.pop(order.id, None) is not None
            and order.status == OrderStatus.CANCELLED
        ):
            return trades, events

        # Compute the batch timestamp once if the caller did not provide one.
        if now is None:
            now = now_ns()

        # --- No-matching mode: queue-only ---
        # Used while the market is in a call phase (opening/closing auction,
        # reopening) or a symbol is halted.  Orders are collected, not
        # traded; the auction code crosses them later at one price.  Only
        # orders that can sit on a book are allowed: anything that must trade
        # *now* (MARKET, FOK, IOC) has nowhere to wait and is rejected.
        if not match:
            if order.order_type in (OrderType.MARKET, OrderType.FOK, OrderType.IOC):
                order.status = OrderStatus.REJECTED
                events.append(order)
                self._oco_leg_ended(order)
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
            # LIMIT / ICEBERG — rest without sweeping.  The book may now be
            # *crossed* (best bid >= best ask); that is normal during an
            # auction and is resolved by the uncross, not here.
            self._rest(order)
            return trades, events

        # --- Continuous matching: one matcher per order type ---
        # Each _match_* method fills what it can via _sweep() and then decides
        # the fate of the remainder (rest it, cancel it, or reject the lot).
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
            # Same on-entry rule as STOP / STOP_LIMIT above (M2).
            if self.last_trade_price is not None and self._stop_is_triggered(
                order, self.last_trade_price
            ):
                self._trigger_stop_now(order, trades, events, now)
            else:
                self._add_trailing_stop(order, events)

        # The order's own end (an IOC's rest, an SMP or FOK refusal) pulls its
        # OCO sibling before the cascade below can trade with it.
        self._oco_leg_ended(order)

        # After any trade, check if stop orders should trigger.
        # #23: drive the cascade (stop → trade → stop → …) with an explicit work
        # queue instead of recursion, so a long chain cannot exhaust Python's
        # recursion limit.  Triggered orders are matched with _cascade_stops=
        # False; any stops they trigger are picked up by the loop below.
        #
        # Example: a SELL STOP at 99 sits on the book.  A trade prints at 99
        # -> _check_stops releases it as a MARKET sell -> it sweeps the bids
        # and prints at 98 -> that may release a SELL STOP at 98, and so on.
        # `pending` is FIFO (pop(0)): stops run in the order they were
        # released -- buy stops first, then sell stops, each group by trigger
        # price then arrival.
        #
        # The three guards are cheap early-outs: no trades means the price did
        # not move; _has_stops means there is anything to trigger at all.
        # The loop itself is run_stops(), which the uncross uses as well.
        if trades and self._has_stops and _cascade_stops:
            sub_trades, sub_events = self.run_stops(now)
            trades.extend(sub_trades)
            events.extend(sub_events)

        return trades, events

    def _oco_leg_ended(self, order: Order) -> None:
        """Report an OCO leg that is now dead to ``on_oco_leg_done``.

        OCO = "one cancels other": two linked orders, and when one ends the
        other must be cancelled.  The book cannot do that itself (the sibling
        may live in the engine's bookkeeping), so it raises a callback and the
        engine cancels the sibling.  It is done *inside* the dispatch, before
        the stop cascade continues, so a later stop cannot trade against a
        sibling that is already supposed to be gone.
        """
        if (
            order.oco_group_id is not None
            and order.status in _DEAD_STATUSES
            and self.on_oco_leg_done is not None
        ):
            self.on_oco_leg_done(order)

    def get_order(self, order_id: str) -> Optional[Order]:
        """Return the resting Order with *order_id*, or None if not found."""
        return self._order_index.get(order_id)

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """
        Cancel a resting order.  Returns the Order if found and cancellable,
        else None.

        This is lazy deletion in action: the heap entry is not removed, only
        marked ``valid = False`` (and the visible quantity taken out of the
        price-level index); ``_peek`` discards it later.  The cancelled
        order may be a resting limit order, a stop, or a stop that has fired
        and is waiting its turn in ``_triggered``.
        """
        order = self._order_index.get(order_id) or self._triggered.get(order_id)
        if order is None:
            return None
        if order.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        ):
            return None

        log.debug(
            "cancel order_id=%s symbol=%s status_before=%s remaining_qty=%s",
            order.id,
            self.symbol,
            order.status.value,
            order.remaining_qty,
        )
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
                and o.price_ticks is not None
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
        - Price change or quantity increase: priority is LOST (new arrival_seq)

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
            log.debug(
                "amend rejected order_id=%s reason=%s", order_id, "Order not found"
            )
            return None, False, "Order not found"
        if order.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        ):
            reason = f"Cannot amend {order.status.value} order"
            log.debug("amend rejected order_id=%s reason=%s", order_id, reason)
            return None, False, reason
        # Only LIMIT and ICEBERG resting orders can be amended
        if order.order_type not in (OrderType.LIMIT, OrderType.ICEBERG):
            reason = f"Cannot amend {order.order_type.value} orders"
            log.debug("amend rejected order_id=%s reason=%s", order_id, reason)
            return None, False, reason

        if now is None:
            now = now_ns()

        old_price = order.price_ticks
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
            log.debug(
                "amend rejected order_id=%s reason=%s",
                order_id,
                "Quantity must be positive",
            )
            return None, False, "Quantity must be positive"
        if qty <= filled_qty:
            reason = "New quantity must exceed already-filled quantity"
            log.debug("amend rejected order_id=%s reason=%s", order_id, reason)
            return None, False, reason
        if price <= 0:
            log.debug(
                "amend rejected order_id=%s reason=%s",
                order_id,
                "Price must be positive",
            )
            return None, False, "Price must be positive"

        # Determine if priority is lost
        price_changed = price != old_price
        qty_increased = qty > old_qty
        priority_reset = price_changed or qty_increased

        # Bookkeeping order matters here: first take the OLD visible quantity
        # out of the price-level index (at the OLD price, because
        # _deduct_qty_index reads order.price_ticks), then mutate the order,
        # then add the NEW visible quantity at the NEW price.  Swapping these
        # steps would corrupt _bid_qty/_ask_qty.
        entry = self._entry_index.get(order_id)
        if entry and old_price is not None:
            old_visible = (
                order.displayed_qty or 0
                if order.order_type == OrderType.ICEBERG
                else order.remaining_qty
            )
            self._deduct_qty_index(order, old_visible)

        # Update order fields
        order.price_ticks = price
        order.quantity = qty
        order.remaining_qty = qty - filled_qty
        if order.order_type == OrderType.ICEBERG and order.visible_qty is not None:
            # A refilled slice is a new peak and queues at the back, so only an
            # amend that loses priority anyway may refill it. One that keeps
            # priority (a qty decrease) can only shrink a partly used slice —
            # refilling it in place would jump the orders queued behind.
            if priority_reset:
                order.displayed_qty = min(order.visible_qty, order.remaining_qty)
            else:
                order.displayed_qty = min(order.displayed_qty or 0, order.remaining_qty)

        new_visible = (
            order.displayed_qty or 0
            if order.order_type == OrderType.ICEBERG
            else order.remaining_qty
        )
        if priority_reset:
            order.ts_ns = now
            # Priority lost: assign a fresh arrival sequence so the order goes
            # to the back of the queue at its (new) price level (finding H1).
            order.arrival_seq = self._next_seq()
            self._note("RESTED", order.id, order.arrival_seq)
            # A heap key cannot be edited in place, so "move" the order by
            # retiring the old entry (lazy deletion) and pushing a new one.
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
            # Priority preserved (pure quantity decrease at the same price):
            # the existing heap entry and its key stay exactly as they are --
            # that IS what keeping your place in the queue means.  Only the
            # price-level quantity index needs the new visible amount.
            if order.side == Side.BUY:
                self._bid_qty[price] = self._bid_qty.get(price, 0) + new_visible
            else:
                self._ask_qty[price] = self._ask_qty.get(price, 0) + new_visible

        log.debug(
            "amend order_id=%s symbol=%s old_price=%s new_price=%s old_qty=%s new_qty=%s priority_reset=%s",
            order_id,
            self.symbol,
            old_price,
            price,
            old_qty,
            qty,
            priority_reset,
        )
        return order, priority_reset, ""

    def resting_orders(self) -> list[Order]:
        """Return all resting (NEW / PARTIAL) orders — used for persistence."""
        return [
            o
            for o in self._order_index.values()
            if o.status in (OrderStatus.NEW, OrderStatus.PARTIAL)
        ]

    def checkpoint(self) -> dict[str, Any]:
        """The whole book for ``system.book_checkpoint`` (S25): resting
        orders in matching priority, armed stops in trigger order, trailing
        stops in checking order, and the last prices."""

        def live(heap: list[_HeapEntry]) -> list[Order]:
            entries = [
                e for e in heap if e.valid and e.order.status not in _DEAD_STATUSES
            ]
            return [e.order for e in sorted(entries, key=lambda e: e.key)]

        def record(o: Order, seq: bool = True) -> dict[str, Any]:
            return {
                "order_id": o.id,
                "gateway_id": o.gateway_id,
                "side": o.side.value,
                "order_type": o.order_type.value,
                "tif": o.tif.value,
                "quantity": o.quantity,
                "remaining_qty": o.remaining_qty,
                "price_ticks": o.price_ticks,
                "stop_price_ticks": o.stop_price_ticks,
                "trail_offset_ticks": o.trail_offset_ticks,
                "visible_qty": o.visible_qty,
                "displayed_qty": o.displayed_qty,
                "priority_seq": o.arrival_seq if seq else None,
                "smp_action": o.smp_action.value if o.smp_action else None,
                "oco_group_id": o.oco_group_id,
                "quote_id": o.quote_id,
                "combo_parent_id": o.combo_parent_id,
            }

        return {
            "symbol": self.symbol,
            "bids": [record(o) for o in live(self._bids)],
            "asks": [record(o) for o in live(self._asks)],
            "buy_stops": [record(o) for o in live(self._buy_stops)],
            "sell_stops": [record(o) for o in live(self._sell_stops)],
            "trailing_stops": [
                record(o, seq=False)
                for o in self._trailing_stops
                if o.status not in _DEAD_STATUSES
            ],
            "last_trade_price_ticks": self.last_trade_price,
            "last_buy_price_ticks": self.last_buy_price,
            "last_sell_price_ticks": self.last_sell_price,
            "last_trade_id": self.last_trade_id,
        }

    def book_stats(self) -> BookStats:
        """Sizes for the health beacon. O(levels + stops), never O(orders):
        every figure is a container length except the live-stop count, which
        walks the stop heaps only."""
        live_stops = sum(
            1
            for heap in (self._buy_stops, self._sell_stops)
            for e in heap
            if e.valid and e.order.status not in _DEAD_STATUSES
        ) + sum(1 for o in self._trailing_stops if o.status not in _DEAD_STATUSES)
        return BookStats(
            resting_orders=len(self._order_index),
            gtc_orders=self._gtc_count,
            stop_orders=live_stops,
            bid_levels=len(self._bid_qty),
            ask_levels=len(self._ask_qty),
            heap_entries=len(self._bids)
            + len(self._asks)
            + len(self._buy_stops)
            + len(self._sell_stops),
            live_entries=len(self._entry_index),
            recent_trades=len(self.recent_trades),
        )

    def containers(self) -> Iterator[object]:
        """Every container this book owns, for a shallow size estimate."""
        yield from (
            self._bids,
            self._asks,
            self._buy_stops,
            self._sell_stops,
            self._trailing_stops,
            self._bid_qty,
            self._ask_qty,
            self._order_index,
            self._entry_index,
            self._orders_by_gateway,
            self.recent_trades,
        )
        yield from self._orders_by_gateway.values()

    def resting_count_by_gateway(self) -> Iterator[tuple[str, int]]:
        """(gateway_id, resting orders here) for every gateway with any."""
        for gateway_id, order_ids in self._orders_by_gateway.items():
            yield gateway_id, len(order_ids)

    def orders_for_gateway(self, gateway_id: str) -> list[Order]:
        """Return all of this gateway's resting orders in this book, any
        origin or type (plain, quote leg, stop, stop-limit, trailing stop).

        O(k) in the number of matching orders (k), via
        ``_orders_by_gateway`` — never a scan of ``resting_orders()``. Every
        id in the index names a resting order in ``_order_index`` (the two
        are kept in lock-step by every funnel listed on
        ``_orders_by_gateway``'s definition), so no result needs a liveness
        re-check; ``.get(..., ())`` handles a gateway with nothing resting
        here without a KeyError.
        """
        order_ids = self._orders_by_gateway.get(gateway_id, ())
        return [self._order_index[oid] for oid in order_ids]

    def quote_orders_for_gateway(self, gateway_id: str) -> list[Order]:
        """Return this gateway's resting QUOTE-origin orders in this book.

        A filtered view over ``orders_for_gateway`` — see that method for
        the index this relies on.
        """
        return [
            o
            for o in self.orders_for_gateway(gateway_id)
            if o.origin == OrderOrigin.QUOTE
        ]

    def best_bid_ticks(self) -> int | None:
        """Return best bid price in ticks, or None if no active bid exists."""
        return max((px for px, qty in self._bid_qty.items() if qty > 0), default=None)

    def best_ask_ticks(self) -> int | None:
        """Return best ask price in ticks, or None if no active ask exists."""
        return min((px for px, qty in self._ask_qty.items() if qty > 0), default=None)

    def restore_stats(
        self,
        last_buy_price: Optional[int],
        last_sell_price: Optional[int],
        last_trade_price: Optional[int] = None,
    ) -> None:
        """Restore persisted last-trade prices after an engine restart. The
        last trade price is kept if the book has traded since the restart."""
        self.last_buy_price = last_buy_price
        self.last_sell_price = last_sell_price
        if self.last_trade_price is None:
            self.last_trade_price = last_trade_price

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
            # AR-0.4: when this depth snapshot was produced. Monotonic, so a
            # snapshot taken after a given trade always carries ts_ns >= that
            # trade's — see now_ns()'s docstring.
            "ts_ns": now_ns(),
            # The scale for the `_ticks` fields below, so a reader can turn
            # them into money from this message alone.
            "tick_decimals": get_tick_decimals(self.symbol),
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
            price = o.price_ticks
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
            price = o.price_ticks
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
                    "ts_ns": t.ts_ns,
                }
            )

        return {
            "symbol": self.symbol,
            # The tick scale the display prices in this snapshot were produced
            # at. Subscribers that store prices exactly (pm-stats) need it to
            # convert back to integer ticks; without it they must guess, and
            # guessing 2 for a 4-decimal symbol rounds the price away.
            "tick_decimals": get_tick_decimals(self.symbol),
            # AR-0.4: when this snapshot was produced. Monotonic, so a
            # snapshot taken after a given trade always carries ts_ns >= that
            # trade's — see now_ns()'s docstring.
            "ts_ns": now_ns(),
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

    # The _match_* methods below differ only in (a) the price limit they hand
    # to _sweep and (b) what they do with the part that did not trade:
    #
    #   type     price limit   unfilled remainder
    #   -------  ------------  ----------------------------------------------
    #   MARKET   none          cancelled (INSUFFICIENT_LIQUIDITY)
    #   LIMIT    order price   rests on the book
    #   IOC      order price   cancelled (INSUFFICIENT_LIQUIDITY)
    #   FOK      order price   never starts unless it can fill completely
    #   ICEBERG  order price   rests, but only a small slice is displayed
    #
    # `opposite` is the heap the order trades AGAINST: a buyer lifts asks, a
    # seller hits bids.  All of them append to `trades` / `events` in place.

    def _match_market(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        """MARKET: trade at any price until filled or the book is empty."""
        opposite = self._asks if order.side == Side.BUY else self._bids
        self._sweep(
            order, opposite, price_limit=None, trades=trades, events=events, now=now
        )
        # Remainder is discarded (no resting market orders).  Emit a terminal
        # event so the owner is notified — without this append a totally
        # unfilled MARKET order got a positive ACK and then silence (#5).
        if order.remaining_qty > 0 and order.status != OrderStatus.FILLED:
            order.status = OrderStatus.CANCELLED  # unsatisfied market → discard
            # A cancel with no stated cause is indistinguishable from a kill
            # switch or a halt cascade on the wire; say the book ran out.  An
            # SMP cancel encountered mid-sweep has already set its own reason,
            # which is the more specific answer and must not be overwritten.
            if order.cancel_reason is None:
                order.cancel_reason = "INSUFFICIENT_LIQUIDITY"
            log.debug(
                "MARKET order discarded order_id=%s symbol=%s remaining_qty=%s reason=%s",
                order.id,
                self.symbol,
                order.remaining_qty,
                order.cancel_reason,
            )
            events.append(order)

    def _match_limit(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        """LIMIT: trade at the limit price or better, then rest the remainder.

        "Or better" = a buy never pays more than its limit, a sell never
        receives less.  The check is in ``_sweep`` (``price_limit``).
        """
        opposite = self._asks if order.side == Side.BUY else self._bids
        self._sweep(
            order,
            opposite,
            price_limit=order.price_ticks,
            trades=trades,
            events=events,
            now=now,
        )
        # Guard against resting an order the sweep already killed — e.g. SMP
        # CANCEL_AGGRESSOR / CANCEL_BOTH sets status=CANCELLED but leaves
        # remaining_qty > 0.  Resting it re-registers a dead order and leaks
        # phantom quantity into the level index (finding C3).
        # (So "remaining_qty > 0" alone does NOT mean "should rest": a
        # cancelled order keeps its unfilled quantity.  Always test status.)
        if order.remaining_qty > 0 and order.status not in _DEAD_STATUSES:
            log.debug(
                "LIMIT order resting after sweep order_id=%s symbol=%s side=%s price=%s remaining_qty=%s",
                order.id,
                self.symbol,
                order.side.value,
                order.price_ticks,
                order.remaining_qty,
            )
            self._rest(order)

    def _match_fok(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        """FOK (Fill-Or-Kill): all of it now, or none of it.

        Check full fillability first; only execute if entire quantity can be filled.
        This is the only matcher that looks BEFORE it trades -- a partial fill
        cannot be undone, so the decision has to be made up front.

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
            price_limit = order.price_ticks
            same_gw_conflicts = [
                e.order
                for e in opposite
                if e.valid
                and e.order.status not in _DEAD_STATUSES
                and e.order.gateway_id == order.gateway_id
                and e.order.price_ticks is not None
                and (
                    price_limit is None
                    or (
                        e.order.price_ticks <= price_limit
                        if order.side == Side.BUY
                        else e.order.price_ticks >= price_limit
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
                order.cancel_reason = "SELF_MATCH_PREVENTED"
            else:
                order.status = OrderStatus.REJECTED
            log.debug(
                "FOK rejected order_id=%s symbol=%s side=%s price=%s required=%s available=%s status=%s",
                order.id,
                self.symbol,
                order.side.value,
                order.price_ticks,
                order.quantity,
                available,
                order.status.value,
            )
            events.append(order)
            return
        self._sweep(
            order,
            opposite,
            price_limit=order.price_ticks,
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
            # The pre-check above already rejected a genuine shortfall, so
            # reaching here means the sweep hit a same-gateway order the
            # pre-check's exclusion missed.
            if order.cancel_reason is None:
                order.cancel_reason = "SELF_MATCH_PREVENTED"
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
            if o.status in _DEAD_STATUSES or o.price_ticks is None:
                continue
            if price_limit is not None:
                if side == Side.BUY and o.price_ticks > price_limit:
                    continue
                if side == Side.SELL and o.price_ticks < price_limit:
                    continue
            total += o.remaining_qty
        return total

    def _fok_available_qty(self, order: Order, heap: list[_HeapEntry]) -> int:
        """Liquidity a FOK could actually execute against.

        Walks live resting orders on *heap* in priority order up to the FOK's
        price limit, the way the sweep will meet them (H8):

        - Resting iceberg hidden quantity counts, but -- as a replenished peak
          queues at the back of its level -- only behind everything else at
          that price.
        - Same-gateway orders are skipped when SMP is active: the sweep skips
          or cancels them.
        - Under CANCEL_AGGRESSOR / CANCEL_BOTH the sweep *stops* at the first
          same-gateway order it meets, so nothing behind it counts. Summing
          past it let a FOK trade part of its size and then cancel (workplan
          T2, bug C).
        """
        price_limit = order.price_ticks
        side = order.side
        # See _match_fok's comment: None should never reach here, but treat
        # it as "no SMP" rather than raising if it somehow does.
        smp = order.smp_action or SmpAction.NONE
        stops_sweep = smp in (SmpAction.CANCEL_AGGRESSOR, SmpAction.CANCEL_BOTH)
        gw = order.gateway_id
        # A heap list is only partially ordered (heap[0] is best, the rest is
        # not sorted), and popping would destroy the book.  sorted() on a COPY
        # uses _HeapEntry.__lt__ (the key) to give true price-time order
        # without touching the real heap.  O(n log n), acceptable because a
        # FOK is rare compared with the rest of the flow.
        live = sorted(
            e
            for e in heap
            if e.valid
            and e.order.status not in _DEAD_STATUSES
            and e.order.price_ticks is not None
        )
        total = 0
        level_price: Optional[int] = None
        level_hidden = 0  # hidden iceberg qty queued at the back of this level
        oco_seen: set[str] = set()
        for entry in live:
            o = entry.order
            price = o.price_ticks
            assert price is not None
            if price_limit is not None:
                if side == Side.BUY and price > price_limit:
                    break
                if side == Side.SELL and price < price_limit:
                    break
            if price != level_price:
                total += level_hidden
                level_price, level_hidden = price, 0
            # SMP: same-gateway resting liquidity is skipped/cancelled by the
            # sweep, so it cannot be used to fill this FOK.
            if smp != SmpAction.NONE and o.gateway_id == gw:
                if stops_sweep:
                    return total
                continue
            # X15: the first leg of an OCO pair the sweep fills pulls the
            # other, and a FOK that takes only part of it is done before
            # reaching the other: only the first leg met can count.
            if o.oco_group_id is not None:
                if o.oco_group_id in oco_seen:
                    continue
                oco_seen.add(o.oco_group_id)
            shown = (
                o.displayed_qty
                if o.order_type == OrderType.ICEBERG and o.displayed_qty is not None
                else o.remaining_qty
            )
            total += shown
            level_hidden += o.remaining_qty - shown
        return total + level_hidden

    def _match_iceberg(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        """
        An incoming iceberg trades its full quantity like a LIMIT -- one
        execution per resting counterparty, as on real venues; hiding only
        matters for what rests. The remainder rests behind a full peak.

        Iceberg vocabulary: ``quantity`` is the total size, ``visible_qty``
        the fixed "peak" size chosen by the client, and ``displayed_qty`` how
        much of the current peak is still showing on the book.  Example:
        qty=1000, visible_qty=100 shows 100; once those 100 are traded a new
        100 is shown, queued BEHIND everyone else at that price.
        """
        opposite = self._asks if order.side == Side.BUY else self._bids
        self._sweep(
            order,
            opposite,
            price_limit=order.price_ticks,
            trades=trades,
            events=events,
            now=now,
        )
        # Rest the remainder -- but not if the sweep killed the order (e.g. SMP
        # cancel), which would leak phantom quantity into the level index
        # (finding C3).
        if order.remaining_qty > 0 and order.status not in _DEAD_STATUSES:
            if order.visible_qty is not None:
                order.displayed_qty = min(order.visible_qty, order.remaining_qty)
            self._rest(order)

    def _match_ioc(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        """
        Immediate-Or-Cancel: sweep up to price_limit, then cancel any unfilled remainder.
        Unlike LIMIT, the order never rests on the book.  Unlike FOK, a partial
        fill is fine -- it is the remainder that is cancelled.

        The ``events.append`` below is what tells the owner about the cancel:
        a fill alone would look as if the rest were still working.
        """
        opposite = self._asks if order.side == Side.BUY else self._bids
        self._sweep(
            order,
            opposite,
            price_limit=order.price_ticks,
            trades=trades,
            events=events,
            now=now,
        )
        if order.remaining_qty > 0 and order.status not in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
        ):
            order.status = OrderStatus.CANCELLED
            # Same cause as the discarded MARKET remainder: the book ran out
            # before the IOC was filled.
            if order.cancel_reason is None:
                order.cancel_reason = "INSUFFICIENT_LIQUIDITY"
            log.debug(
                "IOC cancelled order_id=%s symbol=%s remaining_qty=%s reason=%s",
                order.id,
                self.symbol,
                order.remaining_qty,
                order.cancel_reason,
            )
            events.append(order)

    def _note(self, kind: str, *fields: Any) -> None:
        """Report *kind* to the engine's trace, if it listens."""
        if self.trace is not None:
            self.trace.append((kind, self.symbol, *fields))

    def _note_trigger(self, order: Order) -> None:
        """Report a stop that fires now, before it is converted: as armed,
        on which trade, and what it becomes."""
        if self.trace is not None:
            becomes = "LIMIT" if order.order_type == OrderType.STOP_LIMIT else "MARKET"
            self.trace.append(
                ("TRIGGERED", self.symbol, order, order.order_type.value,
                 order.stop_price_ticks, self.last_trade_id, self.last_trade_price, becomes)
            )  # fmt: skip

    def _add_trailing_stop(self, order: Order, events: list[Order]) -> None:
        """
        Add a trailing stop to the active trailing-stop list.
        The order must have stop_price (initial stop level) and trail_offset (distance).

        A trailing stop is a stop whose trigger price follows the market at a
        fixed distance (see ``_check_trailing_stops``).  It has no limit price
        and never rests on a bid/ask heap, so it has no ``_entry_index`` entry.
        """
        assert (
            order.stop_price_ticks is not None
        ), "Trailing stop must have an initial stop_price"
        assert (
            order.trail_offset_ticks is not None and order.trail_offset_ticks > 0
        ), "Trailing stop must have a positive trail_offset"
        self._trailing_stops.append(order)
        self._order_index[order.id] = order
        self._track_gateway(order)
        self._has_stops = True
        # Trailing stops are checked in list order, not by a sequence.
        self._note("RESTED", order.id, None)
        # Report the order as NEW.  The engine already sent the ACK before
        # calling process(), and _publish_dispatch publishes nothing for a
        # NEW order without fills, so this is a state notification for
        # callers that inspect `events`, not a second ACK on the wire.
        events.append(order)

    @staticmethod
    def _stop_is_triggered(order: Order, price: int) -> bool:
        """True when *price* has breached *order*'s stop trigger (M2).

        A BUY stop fires when the market rises to/through its stop price; a
        SELL stop fires when the market falls to/through it.
        """
        if order.stop_price_ticks is None:
            return False
        if order.side == Side.BUY:
            return price >= order.stop_price_ticks
        return price <= order.stop_price_ticks

    def _trigger_stop_now(
        self, order: Order, trades: list[Trade], events: list[Order], now: int
    ) -> None:
        """Convert an already-breached stop to its live type and match it
        immediately on entry (M2), instead of resting it until a future trade.

        Stop conversion rules (the same ones ``_check_stops`` applies to a
        stop that fires later):  STOP -> MARKET,  STOP_LIMIT -> LIMIT at the
        order's limit price,  TRAILING_STOP -> MARKET.  ``ts_ns`` is reset to
        "now" because from here on the order behaves like a fresh order.
        """
        self._note_trigger(order)
        if order.order_type in (OrderType.STOP, OrderType.TRAILING_STOP):
            order.order_type = OrderType.MARKET
            order.price_ticks = None
            order.trail_offset_ticks = None
            order.ts_ns = now
            self._match_market(order, trades, events, now)
        else:  # STOP_LIMIT → LIMIT
            order.order_type = OrderType.LIMIT
            order.ts_ns = now
            self._match_limit(order, trades, events, now)

    def _add_stop(self, order: Order, events: list[Order]) -> None:
        """Arm a STOP / STOP_LIMIT: park it in a stop heap until it triggers.

        A dormant stop is not part of the visible book: it is in no price
        level, never matches, and shows in no depth.  It sits in the heap
        keyed by its TRIGGER price, so ``_check_stops`` can find the next
        one to fire by looking at ``heap[0]``.
        """
        assert order.stop_price_ticks is not None, "Stop order must have a stop_price"
        log.debug(
            "stop armed order_id=%s symbol=%s side=%s stop_price=%s order_type=%s",
            order.id,
            self.symbol,
            order.side.value,
            order.stop_price_ticks,
            order.order_type.value,
        )
        # Arrival sequence breaks ties among stops at the same trigger price
        # (finding H1 / M10) instead of the client timestamp.
        order.arrival_seq = self._next_seq()
        self._note("RESTED", order.id, order.arrival_seq)
        if order.side == Side.BUY:
            key = (order.stop_price_ticks, order.arrival_seq)
            entry = _HeapEntry(key=key, order=order)
            heapq.heappush(self._buy_stops, entry)
        else:
            key = (-order.stop_price_ticks, order.arrival_seq)
            entry = _HeapEntry(key=key, order=order)
            heapq.heappush(self._sell_stops, entry)
        self._order_index[order.id] = order
        self._entry_index[order.id] = entry
        self._track_gateway(order)
        self._has_stops = True
        # Report the order as NEW.  The engine already sent the ACK before
        # calling process(), and _publish_dispatch publishes nothing for a
        # NEW order without fills, so this is a state notification for
        # callers that inspect `events`, not a second ACK on the wire.
        events.append(order)

    # ------------------------------------------------------------------
    # Sweep helpers
    # ------------------------------------------------------------------

    def _smp_cancel_resting(self, order: Order, events: list[Order]) -> None:
        """Mark a resting order as CANCELLED (SMP), remove from index."""
        log.debug(
            "SMP cancel resting order_id=%s symbol=%s side=%s price=%s qty=%s gateway=%s",
            order.id,
            self.symbol,
            order.side.value,
            order.price_ticks,
            order.remaining_qty,
            order.gateway_id,
        )
        order.status = OrderStatus.CANCELLED
        order.cancel_reason = "SELF_MATCH_PREVENTED"
        entry = self._entry_index.get(order.id)
        if entry and order.price_ticks is not None:
            qty = (
                order.displayed_qty or 0
                if order.order_type == OrderType.ICEBERG
                else order.remaining_qty
            )
            self._deduct_qty_index(order, qty)
        # H7 / quote-index parity: funnel through the same purge every other
        # removal path uses (cancel_order, _apply_fill) instead of popping
        # _order_index directly. Before this, _smp_cancel_resting left
        # _entry_index's heap entry invalidated-but-not-popped (a harmless
        # leak — lazy deletion still skips it) and, more importantly, never
        # cleared _orders_by_gateway (then quote-only; see its definition):
        # a same-gateway SMP cancel of a resting QUOTE-origin leg left a
        # stale order_id there, which then raised KeyError out of
        # quote_orders_for_gateway on that gateway's next quote reissue.
        # Routing through _purge_from_indexes fixes both.
        self._purge_from_indexes(order)
        events.append(order)
        self._oco_leg_ended(order)

    def _sweep(
        self,
        aggressor: Order,
        opposite_heap: list[_HeapEntry],
        price_limit: Optional[int],
        trades: list[Trade],
        events: list[Order],
        now: int,
    ) -> None:
        """Generic price-time sweep for MARKET / LIMIT / IOC / FOK / ICEBERG.

        THE MATCHING LOOP.  Walk the opposite side from best price to worst
        (and, within a price, oldest first) and trade until one of these stops
        us:

        * the aggressor is completely filled (``remaining_qty == 0``);
        * the opposite side is empty;
        * the best remaining price is worse than ``price_limit``
          (``None`` = MARKET order, no limit);
        * self-match prevention killed the aggressor.

        Each pass of the loop produces exactly ONE trade, between the
        aggressor and the single best resting order, for
        ``min(aggressor remaining, resting available)``.  A big aggressor
        therefore generates a *sequence* of trades, one per resting order it
        consumes.  The trade price is always the RESTING order's price.

        The loop never pops the heap itself: ``_peek`` returns the best live
        order and ``_apply_fill`` (via ``_purge_from_indexes``) retires it once
        it is fully filled, which is why the next ``_peek`` sees the next one.
        """
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
            # (1) Who is the best live counterparty?  `opposite_heap` may be
            # non-empty yet hold only dead entries, so `_peek` can still
            # return None.
            best = _peek(opposite_heap)
            if best is None:
                break
            # Resting bid/ask orders always carry a price (L7: local narrowing).
            best_price = best.price_ticks
            assert best_price is not None

            # (2) Price check.  The heap is sorted best-first, so the first
            # order that is too expensive means ALL the rest are too: stop.
            # A BUY accepts asks at or BELOW its limit; a SELL accepts bids at
            # or ABOVE it.
            if price_limit is not None:
                if _side == Side.BUY and best_price > price_limit:
                    break
                if _side == Side.SELL and best_price < price_limit:
                    break

            # (3) Self-match prevention: the same gateway on both sides would
            # be trading with itself (a "wash trade").  What happens depends
            # on the policy the order (or its gateway) carries.
            if _smp_action != SmpAction.NONE and _gw_id == best.gateway_id:
                if _smp_action == SmpAction.CANCEL_AGGRESSOR:
                    log.debug(
                        "SMP cancel aggressor order_id=%s symbol=%s vs resting_id=%s gateway=%s",
                        aggressor.id,
                        self.symbol,
                        best.id,
                        _gw_id,
                    )
                    # Note: remaining_qty is left > 0 on purpose; the callers
                    # (_match_limit etc.) test `status`, not just quantity,
                    # before resting what is left (finding C3).
                    aggressor.status = OrderStatus.CANCELLED
                    aggressor.cancel_reason = "SELF_MATCH_PREVENTED"
                    events.append(aggressor)
                    return
                elif _smp_action == SmpAction.CANCEL_RESTING:
                    self._smp_cancel_resting(best, events)
                    continue  # skip this resting order; try next
                elif _smp_action == SmpAction.CANCEL_BOTH:
                    log.debug(
                        "SMP cancel both aggressor_id=%s resting_id=%s symbol=%s gateway=%s",
                        aggressor.id,
                        best.id,
                        self.symbol,
                        _gw_id,
                    )
                    self._smp_cancel_resting(best, events)
                    aggressor.status = OrderStatus.CANCELLED
                    aggressor.cancel_reason = "SELF_MATCH_PREVENTED"
                    events.append(aggressor)
                    return

            # (4) How much can we trade with this one order?
            #
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

            log.debug(
                "sweep fill symbol=%s aggressor_id=%s passive_id=%s side=%s price=%s qty=%s aggressor_remaining_after=%s",
                self.symbol,
                aggressor.id,
                best.id,
                _side.value,
                best_price,
                fill_qty,
                aggressor.remaining_qty - fill_qty,
            )
            # (5) Execute at the RESTING order's price, then loop: either the
            # aggressor is done, or `best` was exhausted and the next `_peek`
            # returns the next order in the queue.
            _apply_fill(aggressor, best, fill_qty, best_price, trades, events, now)

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

        EVERY trade in the exchange is born here.  Both ``_sweep``
        (continuous matching) and ``auction.execute_uncross`` call it.  In
        order, it:

        1. creates the ``Trade`` (buyer/seller are derived from the sides,
           whichever of the two is the aggressor);
        2. updates the book's running statistics (``last_trade_price`` --
           which drives stops --, daily volume, ``recent_trades``);
        3. reduces the aggressor's ``remaining_qty``, sets its status
           (PARTIAL / FILLED) and appends it to ``events``;
        4. does the same for the passive order, including the iceberg
           replenishment and the price-level index deduction;
        5. fires the quote-leg / OCO callbacks so the engine can cancel a
           sibling leg *now*, before another trade can hit it.

        Nothing is published here.  The caller returns ``trades`` and
        ``events`` up to the engine.

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
            # A triggered stop keeps its stop price when it turns MARKET/LIMIT.
            trigger_order_id=(
                aggressor.id
                if not both_resting and aggressor.stop_price_ticks is not None
                else None
            ),
        )
        trades.append(trade)
        self.last_trade_price = fill_price
        self.last_trade_id = trade.id
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

        # --- Update the aggressor -------------------------------------------
        # Orders are mutated IN PLACE.  The event list holds references, not
        # copies, which is why an order that fills several times shows up
        # several times in `events`, each showing its final state.
        aggressor.remaining_qty -= fill_qty
        # Only the "both_resting" (auction) and ICEBERG branches below touch
        # the index/heap for the aggressor: in continuous matching a plain
        # aggressor never rested, so there is nothing of it to remove.
        if aggressor.order_type == OrderType.ICEBERG:
            aggressor.displayed_qty = max(0, (aggressor.displayed_qty or 0) - fill_qty)
            if both_resting:
                if aggressor.remaining_qty > 0 and aggressor.displayed_qty == 0:
                    new_peak = min(aggressor.visible_qty or 0, aggressor.remaining_qty)
                    aggressor.displayed_qty = new_peak
                    aggressor.ts_ns = now
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

        # --- Update the passive (resting) order -----------------------------
        passive.remaining_qty -= fill_qty
        if passive.order_type == OrderType.ICEBERG:
            passive.displayed_qty = max(0, (passive.displayed_qty or 0) - fill_qty)
            # Slice used up but hidden quantity remains: show the next slice.
            # It is re-queued at the BACK of its price level, so this order
            # loses its time priority -- the usual iceberg trade-off.
            if passive.remaining_qty > 0 and passive.displayed_qty == 0:
                new_peak = min(passive.visible_qty or 0, passive.remaining_qty)
                passive.displayed_qty = new_peak
                # Reuse the cached batch timestamp for iceberg replenishment.
                passive.ts_ns = now
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

        # --- Callbacks into the engine (continuous matching only) -----------
        # A market maker's quote is a bid leg + an ask leg; when one leg
        # trades the engine may need to pull the other, and an OCO pair needs
        # its sibling cancelled.  This must happen NOW, between fills of one
        # sweep, not after process() returns -- otherwise the very next fill
        # (or a stop the fill triggers) could still trade against the leg the
        # engine is about to report as cancelled (findings X3, X15).
        if not both_resting and self.on_quote_leg_fill is not None:
            if passive.quote_id is not None:
                self.on_quote_leg_fill(passive)
            if aggressor.quote_id is not None:
                self.on_quote_leg_fill(aggressor)
        if not both_resting and self.on_oco_leg_done is not None:
            if (
                passive.oco_group_id is not None
                and passive.status == OrderStatus.FILLED
            ):
                self.on_oco_leg_done(passive)
            if (
                aggressor.oco_group_id is not None
                and aggressor.status == OrderStatus.FILLED
            ):
                self.on_oco_leg_done(aggressor)

    def _purge_from_indexes(self, order: Order) -> None:
        """Remove a terminal order from the id→order and id→entry maps and
        invalidate its heap entry so _peek drops it lazily (finding H7).

        Safe to call for a pure taker that was never rested — the pops are
        no-ops.  Idempotent.
        """
        entry = self._entry_index.pop(order.id, None)
        if entry is not None:
            entry.valid = False
            self._compact_heaps()
        self._order_index.pop(order.id, None)
        self._discard_from_gateway_index(order)

    def _compact_heaps(self) -> None:
        """Drop dead heap entries once they outnumber the live ones.

        A removed order only has its heap entry marked invalid; ``_peek`` pops
        it when it reaches the top. An entry deep in the book never does, so
        without this the heaps -- every entry holding its Order alive, and
        walked in full by every ``snapshot`` -- grow with each cancel for the
        life of the process (an AI swarm cancels thousands of stale orders a
        minute). Rebuilding when the heaps exceed twice the live orders keeps
        the cost amortised O(1) per removal.
        """
        heaps = (self._bids, self._asks, self._buy_stops, self._sell_stops)
        if sum(map(len, heaps)) <= (
            _COMPACT_FACTOR * len(self._entry_index) + _COMPACT_SLACK
        ):
            return
        for heap in heaps:
            heap[:] = [
                e for e in heap if e.valid and e.order.status not in _DEAD_STATUSES
            ]
            heapq.heapify(heap)

    def _track_gateway(self, order: Order) -> None:
        """Add ``order`` to ``_orders_by_gateway`` (and the GTC count)."""
        gateway_orders = self._orders_by_gateway.setdefault(order.gateway_id, {})
        if order.id not in gateway_orders:
            gateway_orders[order.id] = None
            if order.tif == TIF.GTC:
                self._gtc_count += 1

    def _discard_from_gateway_index(self, order: Order) -> None:
        """Remove ``order`` from ``_orders_by_gateway``, pruning the
        gateway's entry once it holds no more resting order ids.

        Shared by every removal path: ``_purge_from_indexes`` (cancel, full
        fill, SMP-cancel) and the direct ``_order_index`` pops in
        ``_check_stops``/``_check_trailing_stops`` when a stop triggers —
        those bypass ``_purge_from_indexes`` itself (see their call sites)
        but still need this half of the cleanup. No-op if ``order`` was
        never resting, or was already removed — idempotent like the
        ``_order_index``/``_entry_index`` pops it mirrors.
        """
        gateway_orders = self._orders_by_gateway.get(order.gateway_id)
        if gateway_orders is not None:
            if order.id in gateway_orders:
                del gateway_orders[order.id]
                if order.tif == TIF.GTC:
                    self._gtc_count -= 1
            if not gateway_orders:
                del self._orders_by_gateway[order.gateway_id]

    # ------------------------------------------------------------------
    # Heap management
    # ------------------------------------------------------------------

    def _deduct_qty_index(self, order: Order, qty: int) -> None:
        """Subtract qty from the price-level index for the given resting order.

        A level whose quantity reaches zero is DELETED from the dict, not left
        at 0: ``best_bid_ticks`` / ``best_ask_ticks`` and ``bid_levels`` rely
        on "key present" meaning "level exists".
        """
        if order.price_ticks is None or qty <= 0:
            return
        if order.side == Side.BUY:
            idx = self._bid_qty
        else:
            idx = self._ask_qty
        current = idx.get(order.price_ticks, 0)
        updated = current - qty
        if updated <= 0:
            idx.pop(order.price_ticks, None)
        else:
            idx[order.price_ticks] = updated

    def _rest(self, order: Order) -> None:
        """Place a resting order on the appropriate heap and update the qty index.

        This is the ONLY way a LIMIT / ICEBERG order becomes visible on the
        book.  Five structures are updated together (miss one and the book
        silently corrupts): the heap, the price-level qty index, the
        id -> Order index, the id -> entry index, and the per-gateway index.
        """
        assert order.price_ticks is not None, "Resting order must have a price"
        # L7: bind the narrowed price to a local so mypy keeps the non-None
        # narrowing across the following calls (attribute narrowing is dropped
        # after a method call) — removes the Optional-arithmetic type: ignores.
        price = order.price_ticks
        qty = (
            order.displayed_qty or 0
            if order.order_type == OrderType.ICEBERG
            else order.remaining_qty
        )
        # Engine-assigned arrival sequence drives time priority (finding H1).
        order.arrival_seq = self._next_seq()
        self._note("RESTED", order.id, order.arrival_seq)
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
        self._track_gateway(order)

    def _reinsert_iceberg(self, order: Order) -> None:
        """Invalidate old heap entry and push fresh one after peak replenishment.

        Called when an iceberg's displayed slice has been fully traded and a
        new slice is shown.  The old entry is retired (lazy deletion) and a new
        one with a fresh ``arrival_seq`` goes to the back of the queue at the
        same price.  The caller has already set ``displayed_qty`` to the new
        slice and deducted the traded quantity from the level index.
        """
        assert order.price_ticks is not None, "Iceberg must have a price"
        price = order.price_ticks
        old_entry = self._entry_index.get(order.id)
        if old_entry:
            old_entry.valid = False
        # Fresh arrival sequence sends the replenished peak to the back of the
        # queue at this price level (finding H1 — priority is seq-based).
        order.arrival_seq = self._next_seq()
        new_peak = order.displayed_qty or 0
        self._note("ICEBERG_REFILL", order.id, order.arrival_seq, new_peak)
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

        This is where dead entries are finally thrown away (see "Lazy
        deletion" in the module docstring).  It looks at ``heap[0]`` only and
        does NOT remove the live order it returns: the caller decides what to
        do with it, and a fully filled order is retired by ``_apply_fill``.
        Amortised cost is O(log n): each dead entry is popped at most once.

        Two kinds of dead entry exist: ``valid == False`` (cancelled, amended
        or refilled -- the order may even be alive under a NEWER entry) and
        a valid entry whose order is already in a terminal status.
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
        Release every stop whose trigger has been crossed by ``last_trade_price``.

        Triggering only converts the order (STOP -> MARKET, STOP_LIMIT ->
        LIMIT) and removes it from the book's indexes; it does NOT match it.
        The converted orders are returned to ``process()``, which matches each
        as a new order.  Until then they wait in ``self._triggered``, still
        cancellable (an OCO sibling's fill may cancel one before its turn).

        Check pending stop orders against last_trade_price using two heaps:
          _buy_stops  min-heap by stop_price — fire when last_price >= stop_price
          _sell_stops max-heap by -stop_price — fire when last_price <= stop_price
        O(k log k) where k = number of triggered stops (usually 0).
        """
        if self.last_trade_price is None:
            return []

        triggered: list[Order] = []

        if log.isEnabledFor(logging.DEBUG) and (self._buy_stops or self._sell_stops):
            buy_top = self._buy_stops[0].key[0] if self._buy_stops else None
            sell_top = -self._sell_stops[0].key[0] if self._sell_stops else None
            log.debug(
                "stop check symbol=%s last_trade_price=%s buy_stops_top=%s sell_stops_top=%s",
                self.symbol,
                self.last_trade_price,
                buy_top,
                sell_top,
            )

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
            # The heap top is the LOWEST buy stop.  If even that one has not
            # been reached, none of the others (higher triggers) has either.
            if self.last_trade_price < stop_price:
                break  # remaining stops need a higher price
            # Release this stop and convert it to the order type it becomes.
            # A plain STOP turns into a MARKET order, so its (absent) limit
            # price is cleared; a STOP_LIMIT turns into a LIMIT and keeps its
            # limit price.  (The pop + the type test below are matched
            # verbatim by tools/mutate_engine.py mutant M11: keep them
            # adjacent.)
            heapq.heappop(self._buy_stops)
            stop_order = entry.order
            self._note_trigger(stop_order)
            if stop_order.order_type == OrderType.STOP:
                stop_order.order_type = OrderType.MARKET
                stop_order.price_ticks = None
            else:
                stop_order.order_type = OrderType.LIMIT
            # Reuse the cached batch timestamp.
            stop_order.ts_ns = now
            self._order_index.pop(stop_order.id, None)
            # Remove from _entry_index; if the triggered order converts to MARKET
            # (never rests) the entry would otherwise leak indefinitely.
            # STOP_LIMIT→LIMIT orders overwrite this entry in _rest(), so popping
            # first is safe for both cases.
            self._entry_index.pop(stop_order.id, None)
            # Same reasoning for _orders_by_gateway: a STOP_LIMIT→LIMIT that
            # goes on to rest re-adds itself via _rest(); a STOP→MARKET that
            # matches immediately or dies for lack of liquidity never rests
            # again, so it must be discarded here or it would leak.
            self._discard_from_gateway_index(stop_order)
            log.debug(
                "stop triggered order_id=%s symbol=%s stop_price=%s trigger_price=%s converted_to=%s",
                stop_order.id,
                self.symbol,
                stop_price,
                self.last_trade_price,
                stop_order.order_type.value,
            )
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
            # The sell-stop key stores the NEGATED price (so the min-heap's top
            # is the HIGHEST stop, the first to fire as the price falls);
            # negate again to get the real trigger price.
            neg_stop_price, _ = entry.key
            stop_price = -neg_stop_price
            if self.last_trade_price > stop_price:
                break  # remaining stops need a lower price
            heapq.heappop(self._sell_stops)
            stop_order = entry.order
            self._note_trigger(stop_order)
            if stop_order.order_type == OrderType.STOP:
                stop_order.order_type = OrderType.MARKET
                stop_order.price_ticks = None
            else:
                stop_order.order_type = OrderType.LIMIT
            # Reuse the cached batch timestamp.
            stop_order.ts_ns = now
            self._order_index.pop(stop_order.id, None)
            self._entry_index.pop(stop_order.id, None)
            self._discard_from_gateway_index(stop_order)
            log.debug(
                "stop triggered order_id=%s symbol=%s stop_price=%s trigger_price=%s converted_to=%s",
                stop_order.id,
                self.symbol,
                stop_price,
                self.last_trade_price,
                stop_order.order_type.value,
            )
            triggered.append(stop_order)

        if not self._buy_stops and not self._sell_stops and not self._trailing_stops:
            self._has_stops = False

        for stop_order in triggered:
            self._triggered[stop_order.id] = stop_order
        return triggered

    def _check_trailing_stops(self, now: int) -> list[Order]:
        """
        Update trailing stop prices based on the latest trade and return any triggered orders.

        Example (SELL trailing stop, offset 5): the market trades at 100, the
        stop sits at 95.  The market rises to 110 -> the stop ratchets up to
        105.  The market then falls back to 105 -> triggered, a MARKET sell.
        A fall from 110 to 108 changes nothing: the stop never moves down.

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

            offset = order.trail_offset_ticks
            stop_price = order.stop_price_ticks
            if offset is None or stop_price is None:
                still_active.append(order)
                continue

            if order.side == Side.SELL:
                # Ratchet the stop up if the market has risen
                candidate = trade_price - offset
                if candidate > stop_price:
                    log.debug(
                        "trailing stop ratchet order_id=%s symbol=%s old_stop=%s new_stop=%s trade_price=%s",
                        order.id,
                        self.symbol,
                        stop_price,
                        candidate,
                        trade_price,
                    )
                    order.stop_price_ticks = candidate
                    stop_price = candidate
                    self._note("TRAILING_RATCHET", order.id, candidate, trade_price)
                # Trigger when price falls to/below the current stop
                if trade_price <= stop_price:
                    log.debug(
                        "trailing stop triggered order_id=%s symbol=%s stop_price=%s trade_price=%s",
                        order.id,
                        self.symbol,
                        stop_price,
                        trade_price,
                    )
                    self._note_trigger(order)
                    order.order_type = OrderType.MARKET
                    order.trail_offset_ticks = None
                    # Reuse the cached batch timestamp.
                    order.ts_ns = now
                    self._order_index.pop(order.id, None)
                    self._discard_from_gateway_index(order)
                    triggered.append(order)
                    continue
            else:  # BUY trailing stop
                # Ratchet the stop down if the market has fallen
                candidate = trade_price + offset
                if candidate < stop_price:
                    log.debug(
                        "trailing stop ratchet order_id=%s symbol=%s old_stop=%s new_stop=%s trade_price=%s",
                        order.id,
                        self.symbol,
                        stop_price,
                        candidate,
                        trade_price,
                    )
                    order.stop_price_ticks = candidate
                    stop_price = candidate
                    self._note("TRAILING_RATCHET", order.id, candidate, trade_price)
                # Trigger when price rises to/at the current stop
                if trade_price >= stop_price:
                    log.debug(
                        "trailing stop triggered order_id=%s symbol=%s stop_price=%s trade_price=%s",
                        order.id,
                        self.symbol,
                        stop_price,
                        trade_price,
                    )
                    self._note_trigger(order)
                    order.order_type = OrderType.MARKET
                    order.trail_offset_ticks = None
                    # Reuse the cached batch timestamp.
                    order.ts_ns = now
                    self._order_index.pop(order.id, None)
                    self._discard_from_gateway_index(order)
                    triggered.append(order)
                    continue

            still_active.append(order)

        self._trailing_stops = still_active
        if not self._trailing_stops and not self._buy_stops and not self._sell_stops:
            self._has_stops = False
        for order in triggered:
            self._triggered[order.id] = order
        return triggered

    def run_stops(self, now: int) -> tuple[list[Trade], list[Order]]:
        """Run the stop cascade at the current ``last_trade_price``.

        Every stop the price has reached is released and matched as a new
        order, in the order ``_check_stops`` / ``_check_trailing_stops``
        release them.  Stops released by *those* trades queue behind the ones
        already waiting (FIFO, rule G2 in the participant guide), so the
        cascade runs breadth-first.  Called by ``process`` after a trade and by
        ``Engine._run_uncross`` after the auction print, so both follow one
        rule.  Returns ``(trades, events)``, the same shape as ``process``.
        """
        trades: list[Trade] = []
        events: list[Order] = []
        if not self._has_stops:
            return trades, events
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
