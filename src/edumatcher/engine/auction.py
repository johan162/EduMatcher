"""
Auction uncrossing — equilibrium price calculation and execution.

Standard Two-sided Auction:
  1. Compute equilibrium price that maximises executable quantity.
  2. Break ties by minimising surplus (imbalance).
  3. Execute all crossable interest at that single price using price-time priority.

An iceberg's hidden quantity takes part, ranked behind the visible quantity at
its price: the uncross fills at most its shown slice per pass and replenishes
the slice at the back of the queue, as continuous matching does. The demand and
supply curves count the same total quantity, so the indicative is what prints.

The functions in this module operate on an OrderBook instance and return
trades + events for the engine to publish.

How this differs from continuous matching (``order_book.py``)
-------------------------------------------------------------
In continuous trading an incoming order *aggresses* the book and trades at
the resting order's price, one order at a time.  In an auction (opening,
closing, or reopening after a halt) orders are only COLLECTED -- the book is
allowed to be crossed (best bid >= best ask) and nothing trades.  At the end
of the phase the engine calls, in this order:

1. ``compute_equilibrium(book)``  -> the ONE price that trades the most
   volume (also published during the phase as the "indicative" price);
2. ``execute_uncross(book, eq_price)`` -> every crossing order trades at
   that same price.  Everybody gets the same price; price improvement over
   an order's own limit is the norm, not the exception.

Worked example -- bids: 100 @ 10.2, 100 @ 10.0;  asks: 50 @ 9.9, 100 @ 10.1
  price 9.9 : buyers willing >= 9.9 = 200, sellers willing <= 9.9 =  50 -> 50
  price 10.0: buyers = 200, sellers = 50                              -> 50
  price 10.1: buyers = 100, sellers = 150                             -> 100  <-- max
  price 10.2: buyers = 100, sellers = 150                             -> 100  (tie)
The tie at 10.1 / 10.2 is broken by the smaller surplus (equal here), and
then by the lower price, because candidates are scanned in ascending order
and only a strictly better one replaces the current best.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edumatcher.engine.order_book import _DEAD_STATUSES, _self_match_action
from edumatcher.models.clock import now_ns

from edumatcher.models.order import Order, OrderType, Side, SmpAction
from edumatcher.models.trade import Trade

if TYPE_CHECKING:
    from edumatcher.engine.order_book import OrderBook

log = logging.getLogger(__name__)


@dataclass
class AuctionResult:
    """Outcome of an equilibrium price calculation."""

    eq_price: int | None  # None when nothing would print
    eq_qty: int  # total executable quantity
    surplus: int  # |buy_qty - sell_qty| at eq_price
    imbalance_side: str  # "BUY", "SELL", or "" if balanced
    # Price the book crosses at even when nothing prints there, because SMP
    # or an OCO pair consumes the whole overlap.  ``execute_uncross`` must
    # still run at this price to cancel that interest, but it is NOT an
    # equilibrium and is never published.  Set by ``compute_equilibrium``.
    resolve_price: int | None = None


def _auction_levels(book: "OrderBook") -> tuple[dict[int, int], dict[int, int]]:
    """Total live resting quantity per price level, bids and asks.

    Unlike the book's ``_bid_qty`` / ``_ask_qty`` index, which holds only an
    iceberg's shown slice, this counts each order's full ``remaining_qty`` --
    the quantity the uncross can actually execute. O(n) over the heaps, which
    is fine for an auction; a second persistent index would be one more
    structure to keep in sync.
    """
    levels: list[dict[int, int]] = []
    for heap in (book._bids, book._asks):
        qty: dict[int, int] = {}
        for entry in heap:
            o = entry.order
            if not entry.valid or o.status in _DEAD_STATUSES or o.price_ticks is None:
                continue
            qty[o.price_ticks] = qty.get(o.price_ticks, 0) + o.remaining_qty
        levels.append(qty)
    return levels[0], levels[1]


@dataclass
class _CandidateOrder:
    order: Order
    remaining: int
    shown: int
    #: Cancelled or filled; skipped when it reaches the head of its level.
    dead: bool = False


#: Live resting bids and asks, each in price-time priority (best first).
_LiveOrders = tuple[list[Order], list[Order]]


def _live_orders(book: "OrderBook") -> _LiveOrders:
    """Sorted once per calculation: every simulated price walks a prefix of it."""
    sides: list[list[Order]] = []
    for heap in (book._bids, book._asks):
        sides.append(
            [
                entry.order
                for entry in sorted(heap)
                if entry.valid
                and entry.order.status not in _DEAD_STATUSES
                and entry.order.price_ticks is not None
            ]
        )
    return sides[0], sides[1]


def _candidate_levels(
    orders: list[Order], eq_price: int, is_bid: bool
) -> list[deque[_CandidateOrder]]:
    """The prefix of *orders* that crosses *eq_price*, one queue per price level."""
    levels: list[deque[_CandidateOrder]] = []
    level_price: int | None = None
    for order in orders:
        price = order.price_ticks
        assert price is not None  # _live_orders keeps priced orders only
        if (price < eq_price) if is_bid else (price > eq_price):
            break
        if price != level_price:
            levels.append(deque())
            level_price = price
        levels[-1].append(
            _CandidateOrder(order, order.remaining_qty, _shown_qty(order))
        )
    return levels


def _head(
    levels: list[deque[_CandidateOrder]], start: int
) -> tuple[int, _CandidateOrder | None]:
    """The first live candidate at or after level *start*, dropping dead ones."""
    for i in range(start, len(levels)):
        level = levels[i]
        while level and level[0].dead:
            level.popleft()
        if level:
            return i, level[0]
    return len(levels), None


def _simulated_quantity(
    book: "OrderBook", eq_price: int, live: _LiveOrders | None = None
) -> tuple[int, int, str]:
    """Dry-run the price-time walk, including SMP and OCO, without generating trades.

    O(n) in the crossing orders: a cancelled order is only flagged, and
    dropped once it reaches the head of its level.
    """
    bid_orders, ask_orders = live if live is not None else _live_orders(book)
    bid_levels = _candidate_levels(bid_orders, eq_price, is_bid=True)
    ask_levels = _candidate_levels(ask_orders, eq_price, is_bid=False)
    all_orders = [c for side in (bid_levels, ask_levels) for lvl in side for c in lvl]
    # ``execute_uncross`` only cascades an OCO sibling when the engine has
    # wired up the callback; a bare OrderBook resolves the pair in place.
    groups: dict[tuple[str, str], list[_CandidateOrder]] = {}
    if book.on_oco_leg_done is not None:
        for candidate in all_orders:
            if candidate.order.oco_group_id is not None:
                key = (candidate.order.gateway_id, candidate.order.oco_group_id)
                groups.setdefault(key, []).append(candidate)

    def _kill(candidate: _CandidateOrder) -> None:
        candidate.remaining = candidate.shown = 0
        candidate.dead = True

    def _kill_siblings(candidate: _CandidateOrder) -> None:
        if candidate.order.oco_group_id is None:
            return
        key = (candidate.order.gateway_id, candidate.order.oco_group_id)
        for sibling in groups.get(key, ()):
            if sibling is not candidate:
                _kill(sibling)

    def _cancel(candidate: _CandidateOrder) -> None:
        """Mirror a book-side cancel: the order dies, and so does its sibling."""
        _kill(candidate)
        _kill_siblings(candidate)

    traded = 0
    bid_at = ask_at = 0
    while True:
        bid_at, bid = _head(bid_levels, bid_at)
        ask_at, ask = _head(ask_levels, ask_at)
        if bid is None or ask is None:
            break
        if (
            bid.order.oco_group_id is not None
            and bid.order.gateway_id == ask.order.gateway_id
            and bid.order.oco_group_id == ask.order.oco_group_id
        ):
            _cancel(bid)
            _kill(ask)
            continue
        action, from_ask = _auction_smp_action(bid.order, ask.order)
        if action != SmpAction.NONE:
            if action in (SmpAction.CANCEL_AGGRESSOR, SmpAction.CANCEL_BOTH):
                _cancel(ask if from_ask else bid)
            if action in (SmpAction.CANCEL_RESTING, SmpAction.CANCEL_BOTH):
                _cancel(bid if from_ask else ask)
            continue
        fill = min(bid.shown, ask.shown)
        traded += fill
        for level, candidate in ((bid_levels[bid_at], bid), (ask_levels[ask_at], ask)):
            candidate.remaining -= fill
            candidate.shown -= fill
            if candidate.remaining == 0:
                level.popleft()
                candidate.dead = True
                _kill_siblings(candidate)
            elif candidate.shown == 0:
                # A replenished iceberg slice queues at the back of its level.
                candidate.shown = min(
                    candidate.order.visible_qty or 0, candidate.remaining
                )
                level.popleft()
                level.append(candidate)
    buy_total = traded + sum(
        candidate.remaining
        for candidate in all_orders
        if candidate.order.side == Side.BUY
    )
    sell_total = traded + sum(
        candidate.remaining
        for candidate in all_orders
        if candidate.order.side == Side.SELL
    )
    imbalance = (
        "BUY" if buy_total > sell_total else "SELL" if sell_total > buy_total else ""
    )
    return traded, abs(buy_total - sell_total), imbalance


def _auction_smp_action(bid: Order, ask: Order) -> tuple[SmpAction, bool]:
    """Bid policy wins when both specify SMP; otherwise honour the ask's."""
    action = _self_match_action(bid, ask)
    if action != SmpAction.NONE:
        return action, False
    return _self_match_action(ask, bid), True


def _needs_simulation(book: "OrderBook") -> bool:
    """Whether SMP or an OCO could make the uncross trade differently from
    the plain demand and supply curves.

    SMP fires only when the walk meets a bid and an ask of one gateway at the
    head together, which needs that bid at or above that ask, with either one
    carrying a policy. An OCO matters only once two legs of one group rest in
    the book. Anything else is exactly the plain curves, so the (much dearer)
    walk is skipped.
    """
    # gateway -> [best price of any order, best price of an order with SMP]
    bid_best: dict[str, list[int | None]] = {}
    ask_best: dict[str, list[int | None]] = {}
    oco_legs: set[tuple[str, str]] = set()
    for heap, side_best, better in ((book._bids, bid_best, max), (book._asks, ask_best, min)):  # fmt: skip
        for entry in heap:
            o = entry.order
            price = o.price_ticks
            if not entry.valid or o.status in _DEAD_STATUSES or price is None:
                continue
            if o.oco_group_id is not None:
                key = (o.gateway_id, o.oco_group_id)
                if key in oco_legs:
                    return True
                oco_legs.add(key)
            prices = side_best.setdefault(o.gateway_id, [None, None])
            slots = (0, 1) if o.smp_action not in (None, SmpAction.NONE) else (0,)
            for slot in slots:
                current = prices[slot]
                prices[slot] = price if current is None else better(current, price)
    for gateway, (bid_any, bid_smp) in bid_best.items():
        ask_any, ask_smp = ask_best.get(gateway, (None, None))
        if bid_smp is not None and ask_any is not None and bid_smp >= ask_any:
            return True
        if ask_smp is not None and bid_any is not None and bid_any >= ask_smp:
            return True
    return False


def compute_equilibrium(book: "OrderBook") -> AuctionResult:  # noqa: F821
    """
    Find the price that maximises executable quantity.

    Builds the curves from total resting quantity per price level, hidden
    iceberg quantity included (see ``_auction_levels``).

    Algorithm
    ---------
    For each candidate price *P*:
      buy_qty  = Σ resting bid qty where bid_price ≥ P
      sell_qty = Σ resting ask qty where ask_price ≤ P
      exec_qty = min(buy_qty, sell_qty)
      surplus  = |buy_qty − sell_qty|

    Pick P that maximises exec_qty; break ties by minimising surplus.
    If still tied, the LOWEST such price wins.

    When SMP or an OCO can change what trades (``_needs_simulation``),
    exec_qty is a dry run of the uncross walk at P instead, and only the
    prices whose min(buy_qty, sell_qty) could still beat the best walk found
    are walked.

    Complexity is O(P^2) in the number of distinct price levels because the
    cumulative lookups below rescan the price lists; that is fine for an
    auction, which runs once per phase, and keeps the code obvious.
    """
    bid_qty, ask_qty = _auction_levels(book)
    bid_prices = sorted(bid_qty.keys(), reverse=True)  # highest first
    ask_prices = sorted(ask_qty.keys())  # lowest first

    if not bid_prices or not ask_prices:
        log.debug(
            "uncross calc symbol=%s no crossable interest (empty side)", book.symbol
        )
        return AuctionResult(eq_price=None, eq_qty=0, surplus=0, imbalance_side="")

    # Build cumulative buy qty from highest price downward:
    # cum_buy[price] = total bid qty at prices >= price
    cum_buy: dict[int, int] = {}
    running = 0
    for p in bid_prices:
        running += bid_qty[p]
        cum_buy[p] = running

    # Build cumulative sell qty from lowest price upward:
    # cum_sell[price] = total ask qty at prices <= price
    cum_sell: dict[int, int] = {}
    running = 0
    for p in ask_prices:
        running += ask_qty[p]
        cum_sell[p] = running

    # Candidate prices = union of all bid and ask price levels, sorted
    all_prices = sorted(set(bid_prices) | set(ask_prices))

    # (index in all_prices, price, buy_qty, sell_qty) of every crossing price
    candidates: list[tuple[int, int, int, int]] = []
    for index, price in enumerate(all_prices):
        # Buy qty: sum of bids at prices >= candidate
        # cum_buy is keyed by descending bid prices; we want the lowest bp >= price
        buy_qty = 0
        for bp in bid_prices:  # highest first
            if bp >= price:
                buy_qty = cum_buy[
                    bp
                ]  # keep updating — last match is the lowest bp >= price
            else:
                break

        # Sell qty: sum of asks at prices <= candidate
        # cum_sell is keyed by ascending ask prices; we want the highest ap <= price
        sell_qty = 0
        for ap in ask_prices:  # lowest first
            if ap <= price:
                sell_qty = cum_sell[
                    ap
                ]  # keep updating — last match is the highest ap <= price
            else:
                break

        if min(buy_qty, sell_qty):
            candidates.append((index, price, buy_qty, sell_qty))

    if not candidates:
        return AuctionResult(eq_price=None, eq_qty=0, surplus=0, imbalance_side="")

    # With SMP or an OCO in play the quantity at a price is a walk of the
    # book, not min(buy, sell) -- but never more than min(buy, sell). So the
    # prices are tried best bound first, and once a bound falls below the
    # best quantity found nothing after it can win. The winner is the same
    # as a full scan's: most quantity, then least surplus, then lowest price.
    simulate = _needs_simulation(book)
    live = _live_orders(book) if simulate else None
    best: tuple[int, int, int] | None = None  # (-qty, surplus, index): least wins
    best_price = 0
    imbalance_side = ""
    for index, price, buy_qty, sell_qty in sorted(
        candidates, key=lambda c: -min(c[2], c[3])
    ):
        if best is not None and min(buy_qty, sell_qty) < -best[0]:
            break
        if simulate:
            exec_qty, surplus, side = _simulated_quantity(book, price, live)
        else:
            exec_qty, surplus = min(buy_qty, sell_qty), abs(buy_qty - sell_qty)
            side = "BUY" if buy_qty > sell_qty else "SELL" if sell_qty > buy_qty else ""
        key = (-exec_qty, surplus, index)
        if best is None or key < best:
            best, best_price, imbalance_side = key, price, side
    assert best is not None  # candidates is not empty
    best_qty, best_surplus = -best[0], best[1]

    log.debug(
        "uncross calc symbol=%s eq_price=%s eq_qty=%s surplus=%s imbalance_side=%s candidates=%d",
        book.symbol,
        best_price,
        best_qty,
        best_surplus,
        imbalance_side,
        len(all_prices),
    )
    return AuctionResult(
        eq_price=best_price if best_qty > 0 else None,
        eq_qty=best_qty,
        surplus=best_surplus,
        imbalance_side=imbalance_side,
        resolve_price=best_price,
    )


def executable_at(book: "OrderBook", eq_price: int) -> AuctionResult:  # noqa: F821
    """
    Read-only: what would cross at a fixed *eq_price*, without mutating the book.

    Mirrors ``compute_equilibrium``'s curves at one operator-chosen price
    instead of scanning for the maximiser. Used by the ``reopen --dry-run``
    peek to show what an asserted price would print. ``eq_price`` is echoed
    only when something would cross; ``None`` means the price prints nothing.
    """
    bid_qty, ask_qty = _auction_levels(book)
    buy_qty = sum(q for p, q in bid_qty.items() if p >= eq_price)
    sell_qty = sum(q for p, q in ask_qty.items() if p <= eq_price)
    simulate = _needs_simulation(book)
    exec_qty, surplus, simulated_side = (
        _simulated_quantity(book, eq_price)
        if simulate
        else (min(buy_qty, sell_qty), abs(buy_qty - sell_qty), "")
    )
    if simulate:
        imbalance_side = simulated_side
    elif buy_qty > sell_qty:
        imbalance_side = "BUY"
    elif sell_qty > buy_qty:
        imbalance_side = "SELL"
    else:
        imbalance_side = ""
    return AuctionResult(
        eq_price=eq_price if exec_qty > 0 else None,
        eq_qty=exec_qty,
        surplus=surplus,
        imbalance_side=imbalance_side,
    )


def _shown_qty(order: Order) -> int:
    """What one uncross pass may fill against *order*."""
    if order.order_type == OrderType.ICEBERG and order.displayed_qty is not None:
        return order.displayed_qty
    return order.remaining_qty


def execute_uncross(
    book: "OrderBook", eq_price: int
) -> tuple[list[Trade], list[Order]]:
    """
    Execute all crossable interest at the equilibrium price.

    Sweeps bids (highest-first) against asks (lowest-first), all fills at
    eq_price.  Uses price-time priority within each side; an iceberg fills at
    most its shown slice per pass (see the module docstring).

    Returns (trades, events) — same shape as OrderBook.process().
    """
    trades: list[Trade] = []
    events: list[Order] = []

    # PERF #3: Single time.time() for the entire uncross batch — all fills
    # within an auction uncross are logically simultaneous at the same price.
    now = now_ns()

    # Match the best bid against the best ask until they no longer overlap
    # the equilibrium price.  Unlike _sweep there is no "aggressor": BOTH
    # orders are resting, so we pick the best of each side and trade them
    # at the one price eq_price.  `_peek` skips dead entries for us; and
    # because _apply_fill retires a fully-filled order, each pass moves
    # forward.  Price-time priority holds on each side as usual.
    while True:
        best_bid = book._peek(book._bids)
        best_ask = book._peek(book._asks)

        if best_bid is None or best_ask is None:
            break
        # Resting orders always carry a price; the type: ignore is only there
        # because the field is Optional[int] for the benefit of MARKET/stop
        # orders, which can never be on a bid/ask heap.
        if best_bid.price_ticks < eq_price:  # type: ignore[operator]
            break  # remaining bids below equilibrium
        if best_ask.price_ticks > eq_price:  # type: ignore[operator]
            break  # remaining asks above equilibrium

        if (
            best_bid.oco_group_id is not None
            and best_bid.gateway_id == best_ask.gateway_id
            and best_bid.oco_group_id == best_ask.oco_group_id
        ):
            # Two legs of one OCO crossing each other: only one may stand, as
            # if the other had ended. Not SMP -- the gateway may allow
            # self-trades -- so the cancel carries no classified reason, like
            # any OCO sibling cancel.
            book._smp_cancel_resting(best_bid, events, reason=None)
            if book.on_oco_leg_done is not None:
                book.on_oco_leg_done(best_bid)
            else:
                book._smp_cancel_resting(best_ask, events, reason=None)
            continue

        action, from_ask = _auction_smp_action(best_bid, best_ask)
        if action != SmpAction.NONE:
            aggressor = best_ask if from_ask else best_bid
            passive = best_bid if from_ask else best_ask
            if action in (SmpAction.CANCEL_AGGRESSOR, SmpAction.CANCEL_BOTH):
                book._smp_cancel_resting(aggressor, events)
                if aggressor.oco_group_id and book.on_oco_leg_done is not None:
                    book.on_oco_leg_done(aggressor)
            if action in (SmpAction.CANCEL_RESTING, SmpAction.CANCEL_BOTH):
                book._smp_cancel_resting(passive, events)
                if passive.oco_group_id and book.on_oco_leg_done is not None:
                    book.on_oco_leg_done(passive)
            continue

        # Cap an iceberg at its shown slice, as _sweep does for a passive one
        # (finding #17): _apply_fill replenishes a used-up slice at the back of
        # the queue, and the level index only ever held the shown slice, so a
        # larger fill would both jump the queue and over-deduct the level.
        fill_qty = min(_shown_qty(best_bid), _shown_qty(best_ask))
        log.debug(
            "uncross fill symbol=%s bid_id=%s ask_id=%s eq_price=%s qty=%s",
            book.symbol,
            best_bid.id,
            best_ask.id,
            eq_price,
            fill_qty,
        )
        # both_resting=True: in an uncross both orders are resting and counted
        # in the level index, so both sides must be deducted (finding #3).
        # The "aggressor" argument is just the first parameter slot: the
        # trade is flagged AUCTION and neither side is the taker.
        book._apply_fill(
            best_bid,
            best_ask,
            fill_qty,
            eq_price,
            trades,
            events,
            now,
            both_resting=True,
        )

    # Update book state.  _apply_fill already set last_trade_price after
    # each print; setting it again makes the intent explicit: the auction
    # price becomes the new reference for stops, collars and circuit
    # breakers.  Triggered stops are NOT released here -- the engine calls
    # book.run_stops() afterwards (see Engine._run_uncross).
    if trades:
        book.last_trade_price = eq_price
        book.last_trade_qty = trades[-1].quantity

    log.debug(
        "uncross done symbol=%s eq_price=%s trades=%d total_qty=%s",
        book.symbol,
        eq_price,
        len(trades),
        sum(t.quantity for t in trades),
    )
    return trades, events
