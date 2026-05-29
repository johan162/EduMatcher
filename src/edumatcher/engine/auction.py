"""
Auction uncrossing — equilibrium price calculation and execution.

Standard Two-sided Auction:
  1. Compute equilibrium price that maximises executable quantity.
  2. Break ties by minimising surplus (imbalance).
  3. Execute all crossable interest at that single price using price-time priority.

The functions in this module operate on an OrderBook instance and return
trades + events for the engine to publish.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from edumatcher.models.clock import now_ns

from edumatcher.models.order import Order
from edumatcher.models.trade import Trade

if TYPE_CHECKING:
    from edumatcher.engine.order_book import OrderBook


@dataclass
class AuctionResult:
    """Outcome of an equilibrium price calculation."""

    eq_price: int | None  # None when no crossable interest
    eq_qty: int  # total executable quantity
    surplus: int  # |buy_qty - sell_qty| at eq_price
    imbalance_side: str  # "BUY", "SELL", or "" if balanced


def compute_equilibrium(book: "OrderBook") -> AuctionResult:  # noqa: F821
    """
    Find the price that maximises executable quantity.

    Uses the book's price-level quantity indexes (_bid_qty / _ask_qty) for
    an O(p) scan over p distinct price levels.

    Algorithm
    ---------
    For each candidate price *P*:
      buy_qty  = Σ resting bid qty where bid_price ≥ P
      sell_qty = Σ resting ask qty where ask_price ≤ P
      exec_qty = min(buy_qty, sell_qty)
      surplus  = |buy_qty − sell_qty|

    Pick P that maximises exec_qty; break ties by minimising surplus.
    """
    bid_prices = sorted(book._bid_qty.keys(), reverse=True)  # highest first
    ask_prices = sorted(book._ask_qty.keys())  # lowest first

    if not bid_prices or not ask_prices:
        return AuctionResult(eq_price=None, eq_qty=0, surplus=0, imbalance_side="")

    # Build cumulative buy qty from highest price downward:
    # cum_buy[price] = total bid qty at prices >= price
    cum_buy: dict[int, int] = {}
    running = 0
    for p in bid_prices:
        running += book._bid_qty[p]
        cum_buy[p] = running

    # Build cumulative sell qty from lowest price upward:
    # cum_sell[price] = total ask qty at prices <= price
    cum_sell: dict[int, int] = {}
    running = 0
    for p in ask_prices:
        running += book._ask_qty[p]
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

    return AuctionResult(
        eq_price=best_price,
        eq_qty=best_qty,
        surplus=int(best_surplus),
        imbalance_side=imbalance_side,
    )


def execute_uncross(
    book: "OrderBook", eq_price: int
) -> tuple[list[Trade], list[Order]]:
    """
    Execute all crossable interest at the equilibrium price.

    Sweeps bids (highest-first) against asks (lowest-first), all fills at
    eq_price.  Uses price-time priority within each side.

    Returns (trades, events) — same shape as OrderBook.process().
    """
    trades: list[Trade] = []
    events: list[Order] = []

    # PERF #3: Single time.time() for the entire uncross batch — all fills
    # within an auction uncross are logically simultaneous at the same price.
    now = now_ns()

    while True:
        best_bid = book._peek(book._bids)
        best_ask = book._peek(book._asks)

        if best_bid is None or best_ask is None:
            break
        if best_bid.price < eq_price:  # type: ignore[operator]
            break  # remaining bids below equilibrium
        if best_ask.price > eq_price:  # type: ignore[operator]
            break  # remaining asks above equilibrium

        fill_qty = min(best_bid.remaining_qty, best_ask.remaining_qty)
        book._apply_fill(best_bid, best_ask, fill_qty, eq_price, trades, events, now)

    # Update book state
    if trades:
        book.last_trade_price = eq_price
        book.last_trade_qty = trades[-1].quantity

    return trades, events
