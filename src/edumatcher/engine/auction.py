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
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edumatcher.engine.order_book import _DEAD_STATUSES
from edumatcher.models.clock import now_ns

from edumatcher.models.order import Order, OrderType
from edumatcher.models.trade import Trade

if TYPE_CHECKING:
    from edumatcher.engine.order_book import OrderBook

log = logging.getLogger(__name__)


@dataclass
class AuctionResult:
    """Outcome of an equilibrium price calculation."""

    eq_price: int | None  # None when no crossable interest
    eq_qty: int  # total executable quantity
    surplus: int  # |buy_qty - sell_qty| at eq_price
    imbalance_side: str  # "BUY", "SELL", or "" if balanced


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
    If still tied, the LOWEST such price wins (candidates are scanned in
    ascending order and a later one must be strictly better to replace it).

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

    best_price: int | None = None
    best_qty = 0
    best_surplus = float("inf")

    for price in all_prices:
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

        exec_qty = min(buy_qty, sell_qty)
        surplus = abs(buy_qty - sell_qty)

        if exec_qty > best_qty or (exec_qty == best_qty and surplus < best_surplus):
            best_price = price
            best_qty = exec_qty
            best_surplus = int(surplus)

    if best_price is None or best_qty == 0:
        return AuctionResult(eq_price=None, eq_qty=0, surplus=0, imbalance_side="")

    # Determine imbalance side at equilibrium
    buy_at_eq = 0
    for bp in bid_prices:
        if bp >= best_price:
            buy_at_eq = cum_buy[bp]
        else:
            break
    sell_at_eq = 0
    for ap in ask_prices:
        if ap <= best_price:
            sell_at_eq = cum_sell[ap]
        else:
            break

    if buy_at_eq > sell_at_eq:
        imbalance_side = "BUY"
    elif sell_at_eq > buy_at_eq:
        imbalance_side = "SELL"
    else:
        imbalance_side = ""

    log.debug(
        "uncross calc symbol=%s eq_price=%s eq_qty=%s surplus=%s imbalance_side=%s candidates=%d",
        book.symbol,
        best_price,
        best_qty,
        int(best_surplus),
        imbalance_side,
        len(all_prices),
    )
    return AuctionResult(
        eq_price=best_price,
        eq_qty=best_qty,
        surplus=int(best_surplus),
        imbalance_side=imbalance_side,
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
    exec_qty = min(buy_qty, sell_qty)
    surplus = abs(buy_qty - sell_qty)
    if buy_qty > sell_qty:
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
