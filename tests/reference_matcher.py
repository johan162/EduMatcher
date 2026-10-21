"""
A deliberately naive reference model of EduMatcher's matching rules.

Written from the documented rules — participant guide (order types, the order
book, the trading day and auctions) and operator guide (equilibrium price,
self-match prevention) — not from ``engine/order_book.py``. It is the oracle
the engine is checked against (workplan T2/T3), so it must stay independent:

- plain lists of orders, re-scanned for the best order on every step;
- no heaps, no price-level index, no lazy deletion, no caching;
- every rule spelled out once, in the order the docs give it.

Where the docs were silent the rule was written into the docs first; those
places are marked "(rule Gn)" — see
docs-design/EduMatcher-Matching-Test-Quality-Workplan.md, insights log.

Session gating, collars, order limits and message publication are the
engine's concern, not matching, and are not modelled. Prices are integer
ticks; sides and order types are the wire strings ("BUY", "LIMIT", ...).

Not a test module (no test_ prefix) — pytest will not collect it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

STOP_TYPES = ("STOP", "STOP_LIMIT", "TRAILING_STOP")
#: May not enter while the market is not matching: they can never rest.
IMMEDIATE_TYPES = ("MARKET", "IOC", "FOK")
TERMINAL = ("FILLED", "CANCELLED", "REJECTED", "EXPIRED")


@dataclass(eq=False)  # identity: orders are found in lists by `is`, not by value
class ROrder:
    id: str
    side: str  # "BUY" | "SELL"
    type: str  # MARKET LIMIT IOC FOK ICEBERG STOP STOP_LIMIT TRAILING_STOP
    qty: int
    gw: str
    price: int | None = None  # limit price; STOP_LIMIT's limit after trigger
    stop: int | None = None  # trigger price (STOP, STOP_LIMIT, TRAILING_STOP)
    trail: int | None = None  # TRAILING_STOP offset
    visible: int | None = None  # ICEBERG peak size
    smp: str = "NONE"  # NONE | CANCEL_AGGRESSOR | CANCEL_RESTING | CANCEL_BOTH
    remaining: int = field(init=False)
    shown: int | None = field(init=False)  # ICEBERG: current displayed peak
    seq: int = 0  # arrival sequence: time priority
    status: str = "NEW"
    cancel_reason: str | None = None

    def __post_init__(self) -> None:
        self.remaining = self.qty
        self.shown = min(self.visible, self.qty) if self.visible is not None else None

    @property
    def available(self) -> int:
        """What one match may take from this order while it rests."""
        return self.shown if self.shown is not None else self.remaining


@dataclass(frozen=True)
class RTrade:
    buy_id: str
    sell_id: str
    price: int
    qty: int
    aggressor: str  # "BUY" | "SELL" | "AUCTION"


class ReferenceMatcher:
    """One symbol's book, matching by the documented rules."""

    def __init__(self) -> None:
        self.bids: list[ROrder] = []
        self.asks: list[ROrder] = []
        self.stops: list[ROrder] = []  # every dormant stop, any of the 3 types
        self.orders: dict[str, ROrder] = {}  # every order ever submitted
        self.trades: list[RTrade] = []
        self.last_price: int | None = None
        self._seq = 0

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    def submit(self, order: ROrder, *, matching: bool = True) -> list[RTrade]:
        """Accept a new order. *matching* is False in pre-open, an auction
        call or a halt: nothing trades, orders only collect."""
        self.orders[order.id] = order
        start = len(self.trades)
        if not matching:
            if order.type in IMMEDIATE_TYPES:
                order.status = "REJECTED"  # cannot rest
            elif order.type in STOP_TYPES:
                self._store_stop(order)  # no entry check while not matching (rule G8)
            else:
                self._rest(order)
            return []
        if order.type in STOP_TYPES:
            # A stop already breached on entry triggers at once (rule G3).
            if self.last_price is not None and self._triggered(order):
                self._activate(order)
            else:
                self._store_stop(order)
        else:
            self._execute(order)
        if len(self.trades) > start:
            self._run_stops()
        return self.trades[start:]

    def cancel(self, order_id: str) -> bool:
        order = self.orders.get(order_id)
        if order is None or order.status in TERMINAL:
            return False
        self._remove(order)
        order.status = "CANCELLED"
        return True

    def amend(
        self,
        order_id: str,
        price: int | None = None,
        qty: int | None = None,
        *,
        matching: bool = True,
    ) -> bool:
        """Amend a resting LIMIT/ICEBERG (participant guide, Order Amendment).
        Returns False when the amend is rejected."""
        order = self.orders.get(order_id)
        if order is None or order.status in TERMINAL:
            return False
        if order.type not in ("LIMIT", "ICEBERG") or order not in self._side(order):
            return False
        assert order.price is not None
        new_price = order.price if price is None else price
        new_qty = order.qty if qty is None else qty
        filled = order.qty - order.remaining
        if new_qty <= 0 or new_qty <= filled or new_price <= 0:
            return False
        loses_priority = new_price != order.price or new_qty > order.qty
        order.price, order.qty, order.remaining = new_price, new_qty, new_qty - filled
        if order.shown is not None:
            assert order.visible is not None
            # Only an amend that loses priority may refill the peak.
            order.shown = (
                min(order.visible, order.remaining)
                if loses_priority
                else min(order.shown, order.remaining)
            )
        if loses_priority:
            order.seq = self._next_seq()
        best = self._best(self._opposite(order.side))
        if matching and best is not None and self._crosses(order, best.price):
            # A marketable amend is matched like a fresh aggressive order.
            start = len(self.trades)
            self._side(order).remove(order)
            self._execute(order)
            if len(self.trades) > start:
                self._run_stops()
        return True

    def equilibrium(self) -> tuple[int | None, int, int, str]:
        """(price, executable qty, surplus, imbalance side) by brute force over
        every resting price (operator guide, Equilibrium price). An iceberg's
        hidden quantity counts (participant guide, Icebergs in the uncross)."""
        best: tuple[int, int, int] | None = None  # (exec, -surplus, -price)
        for p in sorted(
            {o.price for o in self.bids + self.asks if o.price is not None}
        ):
            buy = sum(
                o.remaining for o in self.bids if o.price is not None and o.price >= p
            )
            sell = sum(
                o.remaining for o in self.asks if o.price is not None and o.price <= p
            )
            key = (min(buy, sell), -abs(buy - sell), -p)
            if best is None or key > best:
                best = key
        if best is None or best[0] == 0:
            return None, 0, 0, ""
        price, executable, surplus = -best[2], best[0], -best[1]
        buy = sum(
            o.remaining for o in self.bids if o.price is not None and o.price >= price
        )
        sell = sum(
            o.remaining for o in self.asks if o.price is not None and o.price <= price
        )
        side = "BUY" if buy > sell else "SELL" if sell > buy else ""
        return price, executable, surplus, side

    def uncross(self) -> list[RTrade]:
        """Execute all crossable interest at the equilibrium price, then
        evaluate stops against that print."""
        price, _, _, _ = self.equilibrium()
        start = len(self.trades)
        if price is None:
            return []
        while True:
            bid, ask = self._best(self.bids), self._best(self.asks)
            if bid is None or ask is None:
                break
            assert bid.price is not None and ask.price is not None
            if bid.price < price or ask.price > price:
                break
            # No SMP in the uncross (rule G6); icebergs one peak at a time.
            self._fill(bid, ask, min(bid.available, ask.available), price, "AUCTION")
        if len(self.trades) > start:
            self._run_stops()
        return self.trades[start:]

    def book(self) -> dict[str, list[tuple[str, int, int, int]]]:
        """Resting orders in priority order: (id, price, remaining, available)."""
        out: dict[str, list[tuple[str, int, int, int]]] = {}
        for name, side in (("bids", self.bids), ("asks", self.asks)):
            ordered = sorted(side, key=self._priority)
            out[name] = [
                (o.id, o.price or 0, o.remaining, o.available) for o in ordered
            ]
        return out

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _execute(self, order: ROrder) -> None:
        """Match an active (non-stop) order, then rest or cancel what is left."""
        if order.type == "FOK" and not self._fok_can_fill(order):
            self._kill_fok(order)
            return
        self._sweep(order)
        if order.status in TERMINAL or order.remaining == 0:
            return
        if order.type == "LIMIT":
            self._rest(order)
        elif order.type == "ICEBERG":
            # An incoming iceberg trades its full quantity like a LIMIT; only
            # the remainder hides, behind a full peak (rule G4).
            assert order.visible is not None
            order.shown = min(order.visible, order.remaining)
            self._rest(order)
        else:  # MARKET / IOC; a FOK never gets here with quantity left
            order.status = "CANCELLED"
            order.cancel_reason = "INSUFFICIENT_LIQUIDITY"

    def _sweep(self, order: ROrder) -> None:
        """Price-time sweep of the opposite side with per-match SMP."""
        opposite = self._opposite(order.side)
        while order.remaining > 0:
            best = self._best(opposite)
            if best is None or not self._crosses(order, best.price):
                return
            if order.smp != "NONE" and best.gw == order.gw:
                if order.smp in ("CANCEL_RESTING", "CANCEL_BOTH"):
                    # The whole resting order goes, iceberg reserve too (rule G5).
                    self._remove(best)
                    best.status, best.cancel_reason = (
                        "CANCELLED",
                        "SELF_MATCH_PREVENTED",
                    )
                if order.smp in ("CANCEL_AGGRESSOR", "CANCEL_BOTH"):
                    order.status, order.cancel_reason = (
                        "CANCELLED",
                        "SELF_MATCH_PREVENTED",
                    )
                    return
                continue
            assert best.price is not None
            buy, sell = (order, best) if order.side == "BUY" else (best, order)
            qty = min(order.remaining, best.available)
            self._fill(buy, sell, qty, best.price, order.side)

    def _fok_can_fill(self, order: ROrder) -> bool:
        """Dry run: would the sweep fill the whole FOK? Simulated on a copy, so
        it agrees with the sweep by construction (all-or-nothing, SMP included)."""
        trial = copy.deepcopy(self)
        probe = trial.orders[order.id]
        trial._sweep(probe)
        return probe.remaining == 0

    def _kill_fok(self, order: ROrder) -> None:
        """A FOK that cannot fill: resolve SMP as the sweep would, else reject
        (operator guide, FOK — self-match liquidity is excluded)."""
        own = [
            o
            for o in self._opposite(order.side)
            if o.gw == order.gw and self._crosses(order, o.price)
        ]
        if order.smp in ("CANCEL_RESTING", "CANCEL_BOTH"):
            for o in own:
                self._remove(o)
                o.status, o.cancel_reason = "CANCELLED", "SELF_MATCH_PREVENTED"
        if order.smp in ("CANCEL_AGGRESSOR", "CANCEL_BOTH") and own:
            order.status, order.cancel_reason = "CANCELLED", "SELF_MATCH_PREVENTED"
        else:
            order.status = "REJECTED"

    def _fill(
        self, buy: ROrder, sell: ROrder, qty: int, price: int, aggressor: str
    ) -> None:
        self.trades.append(RTrade(buy.id, sell.id, price, qty, aggressor))
        self.last_price = price
        for o in (buy, sell):
            o.remaining -= qty
            o.status = "FILLED" if o.remaining == 0 else "PARTIAL"
            if o not in self._side(o):
                continue  # the aggressor of a sweep is not resting
            if o.remaining == 0:
                self._side(o).remove(o)
            elif o.shown is not None:
                assert o.visible is not None
                o.shown -= qty
                if o.shown == 0:
                    # A used-up peak is replenished at the back of the queue.
                    o.shown = min(o.visible, o.remaining)
                    o.seq = self._next_seq()

    # ------------------------------------------------------------------
    # Stops
    # ------------------------------------------------------------------

    def _triggered(self, stop: ROrder) -> bool:
        assert self.last_price is not None and stop.stop is not None
        if stop.side == "BUY":
            return self.last_price >= stop.stop
        return self.last_price <= stop.stop

    def _run_stops(self) -> None:
        """Evaluate stops once, after the incoming order finished (rule G1);
        run the triggered ones in turn, queueing any they trigger (rule G2)."""
        queue = self._collect_triggered()
        while queue:
            stop = queue.pop(0)
            start = len(self.trades)
            self._activate(stop)
            if len(self.trades) > start:
                queue.extend(self._collect_triggered())

    def _collect_triggered(self) -> list[ROrder]:
        """Triggered stops in execution order (rule G2): BUY stops lowest stop
        first, SELL stops highest first, each then by arrival; then trailing
        stops by arrival, each ratcheted against the last price first."""
        assert self.last_price is not None
        plain = [
            s for s in self.stops if s.type != "TRAILING_STOP" and self._triggered(s)
        ]
        buys = sorted(
            (s for s in plain if s.side == "BUY"), key=lambda s: (s.stop or 0, s.seq)
        )
        sells = sorted(
            (s for s in plain if s.side == "SELL"),
            key=lambda s: (-(s.stop or 0), s.seq),
        )
        trailing: list[ROrder] = []
        for s in sorted(
            (s for s in self.stops if s.type == "TRAILING_STOP"), key=lambda s: s.seq
        ):
            assert s.stop is not None and s.trail is not None
            if s.side == "SELL":
                s.stop = max(s.stop, self.last_price - s.trail)
            else:
                s.stop = min(s.stop, self.last_price + s.trail)
            if self._triggered(s):
                trailing.append(s)
        triggered = buys + sells + trailing
        for s in triggered:
            self.stops.remove(s)
        return triggered

    def _activate(self, stop: ROrder) -> None:
        """Convert a triggered stop to its live type and match it as a new
        aggressive order (it gets fresh time priority if it rests)."""
        if stop.type == "STOP_LIMIT":
            stop.type = "LIMIT"
        else:  # STOP, TRAILING_STOP
            stop.type, stop.price = "MARKET", None
        self._execute(stop)

    def _store_stop(self, order: ROrder) -> None:
        order.seq = self._next_seq()
        self.stops.append(order)

    # ------------------------------------------------------------------
    # Book helpers
    # ------------------------------------------------------------------

    def _rest(self, order: ROrder) -> None:
        order.seq = self._next_seq()
        self._side(order).append(order)

    def _remove(self, order: ROrder) -> None:
        for container in (self.bids, self.asks, self.stops):
            if order in container:
                container.remove(order)

    def _side(self, order: ROrder) -> list[ROrder]:
        return self.bids if order.side == "BUY" else self.asks

    def _opposite(self, side: str) -> list[ROrder]:
        return self.asks if side == "BUY" else self.bids

    @staticmethod
    def _priority(o: ROrder) -> tuple[int, int]:
        """Better price first (highest bid, lowest ask), then earlier arrival."""
        assert o.price is not None
        return (-o.price if o.side == "BUY" else o.price, o.seq)

    def _best(self, side: list[ROrder]) -> ROrder | None:
        return min(side, key=self._priority) if side else None

    @staticmethod
    def _crosses(order: ROrder, resting_price: int | None) -> bool:
        if order.price is None:  # MARKET
            return True
        assert resting_price is not None
        if order.side == "BUY":
            return resting_price <= order.price
        return resting_price >= order.price

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq
