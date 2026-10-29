"""
Randomized-operation invariant tests for OrderBook.

Instead of scripting specific scenarios, these tests drive the book with
seeded pseudo-random operation sequences and assert the structural
invariants (tests/engine_invariants.py) and quantity conservation after
EVERY step.  A failure message includes the seed, the step, and the recent
operation history, so any counterexample is fully reproducible.

Tiers, each adding one feature to plain order flow (LIMIT, MARKET, IOC, FOK,
cancels, non-crossing amends):

  1. test_invariants_continuous_flow  — plain flow only; proves the harness.
  2. test_invariants_with_icebergs    — adds icebergs (found review C7).
  3. test_invariants_with_smp         — adds self-match prevention (C3).
  4. test_invariants_with_auctions    — adds auction batches with icebergs:
     rest without matching, then uncross (C2, bug A).
  5. test_invariants_with_stops       — adds STOP, STOP_LIMIT and
     TRAILING_STOP near the last trade price, so they trigger and cascade.
  6. test_invariants_everything       — all of the above, plus amends that
     cross the opposite side (re-matched as the engine does, H2).

The review findings named above are fixed; the tiers stay as regression
guards. Background: docs-design/EduMatcher-Matching-Test-Quality-Workplan.md
(T6).

Deliberately implemented with random.Random(seed) rather than hypothesis
so no new dependency is required; the operation generator is factored so a
future migration to hypothesis stateful testing is mechanical.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pytest

from edumatcher.engine.auction import compute_equilibrium, execute_uncross
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, SmpAction
from edumatcher.models.trade import Trade

from tests.engine_invariants import assert_book_invariants, assert_qty_conservation

SYMBOL = "AAPL"
GATEWAYS = ("GW1", "GW2", "GW3")
PRICE_MID = 10000
PRICE_SPAN = 200  # ticks either side of mid
SEEDS = range(25)
STEPS = 200
STOP_TYPES = (OrderType.STOP, OrderType.STOP_LIMIT, OrderType.TRAILING_STOP)


@dataclass(frozen=True)
class _Features:
    icebergs: bool = False
    smp: bool = False
    stops: bool = False
    crossing_amends: bool = False
    auction_every: int | None = None


class _OpDriver:
    """Generates and applies one random operation per call."""

    def __init__(
        self, book: OrderBook, rng: random.Random, features: _Features
    ) -> None:
        self.book = book
        self.rng = rng
        self.f = features
        self.live_ids: list[str] = []
        self.all_orders: list[Order] = []
        self.all_trades: list[Trade] = []
        self.history: list[str] = []

    # -- helpers -------------------------------------------------------
    def _price(self) -> int:
        return PRICE_MID + self.rng.randrange(-PRICE_SPAN, PRICE_SPAN + 1, 10)

    def _smp(self) -> SmpAction:
        if self.f.smp and self.rng.random() < 0.15:
            return self.rng.choice(
                [
                    SmpAction.CANCEL_AGGRESSOR,
                    SmpAction.CANCEL_RESTING,
                    SmpAction.CANCEL_BOTH,
                ]
            )
        return SmpAction.NONE

    def _submit(self, order: Order, *, match: bool = True) -> None:
        trades, _events = self.book.process(order, match=match)
        self.all_orders.append(order)
        self.all_trades.extend(trades)
        self.live_ids.append(order.id)

    def _iceberg(self, side: Side, qty: int, gw: str) -> tuple[Order, str]:
        price = self._price()
        visible = max(1, qty // self.rng.randint(2, 10))
        o = Order.create(
            symbol=SYMBOL,
            side=side,
            order_type=OrderType.ICEBERG,
            quantity=qty,
            gateway_id=gw,
            price_ticks=price,
            visible_qty=visible,
            smp_action=self._smp(),
        )
        return o, f"ICEBERG {side.value} {qty}(show {visible})@{price} gw={gw}"

    def _stop(self, side: Side, qty: int, gw: str) -> tuple[Order, str]:
        """A stop whose trigger is within 3 levels of the last trade, so it
        can trigger (or is already breached on entry)."""
        rng = self.rng
        base = self.book.last_trade_price or PRICE_MID
        stop = base + rng.randrange(-30, 31, 10)
        type_ = rng.choice(STOP_TYPES)
        price = (
            stop + rng.randrange(-20, 21, 10) if type_ == OrderType.STOP_LIMIT else None
        )
        trail = rng.choice((10, 20, 30)) if type_ == OrderType.TRAILING_STOP else None
        o = Order.create(
            symbol=SYMBOL,
            side=side,
            order_type=type_,
            quantity=qty,
            gateway_id=gw,
            price_ticks=price,
            stop_price_ticks=stop,
            trail_offset_ticks=trail,
            smp_action=self._smp(),
        )
        return (
            o,
            f"{type_.value} {side.value} {qty} stop={stop} px={price} trail={trail} gw={gw}",
        )

    def _non_crossing_amend_price(self, order: Order) -> int | None:
        """A random new price that cannot cross the opposite side."""
        if order.side == Side.BUY:
            asks = [p for p, q in self.book._ask_qty.items() if q > 0]
            ceiling = (min(asks) - 10) if asks else PRICE_MID + PRICE_SPAN
            if ceiling < PRICE_MID - PRICE_SPAN:
                return None
            return self.rng.randrange(PRICE_MID - PRICE_SPAN, ceiling + 1, 10)
        bids = [p for p, q in self.book._bid_qty.items() if q > 0]
        floor = (max(bids) + 10) if bids else PRICE_MID - PRICE_SPAN
        if floor > PRICE_MID + PRICE_SPAN:
            return None
        return self.rng.randrange(floor, PRICE_MID + PRICE_SPAN + 1, 10)

    def _rematch_if_marketable(self, order: Order) -> None:
        """What ``Engine._handle_amend`` does after an amend (H2): an order
        that now crosses the opposite best is pulled and matched afresh."""
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return
        if order.side == Side.BUY:
            best = self.book.best_ask_ticks()
            marketable = best is not None and order.price_ticks >= best  # type: ignore[operator]
        else:
            best = self.book.best_bid_ticks()
            marketable = best is not None and order.price_ticks <= best  # type: ignore[operator]
        if marketable:
            self.book.cancel_order(order.id)
            order.status = OrderStatus.NEW
            trades, _events = self.book.process(order)
            self.all_trades.extend(trades)

    # -- one step ------------------------------------------------------
    def step(self) -> str:
        r = self.rng.random()
        rng = self.rng
        side = rng.choice([Side.BUY, Side.SELL])
        gw = rng.choice(GATEWAYS)
        qty = rng.randint(1, 300)

        if r < 0.35:  # LIMIT
            price = self._price()
            smp = self._smp()
            o = Order.create(
                symbol=SYMBOL,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=qty,
                gateway_id=gw,
                price_ticks=price,
                smp_action=smp,
            )
            self._submit(o)
            return f"LIMIT {side.value} {qty}@{price} gw={gw} smp={smp.value}"

        if r < 0.45:  # MARKET
            smp = self._smp()
            o = Order.create(
                symbol=SYMBOL,
                side=side,
                order_type=OrderType.MARKET,
                quantity=qty,
                gateway_id=gw,
                smp_action=smp,
            )
            self._submit(o)
            return f"MARKET {side.value} {qty} gw={gw} smp={smp.value}"

        if r < 0.53:  # IOC
            price = self._price()
            smp = self._smp()
            o = Order.create(
                symbol=SYMBOL,
                side=side,
                order_type=OrderType.IOC,
                quantity=qty,
                gateway_id=gw,
                price_ticks=price,
                smp_action=smp,
            )
            self._submit(o)
            return f"IOC {side.value} {qty}@{price} gw={gw} smp={smp.value}"

        if r < 0.59:  # FOK
            price = self._price()
            smp = self._smp()
            o = Order.create(
                symbol=SYMBOL,
                side=side,
                order_type=OrderType.FOK,
                quantity=qty,
                gateway_id=gw,
                price_ticks=price,
                smp_action=smp,
            )
            self._submit(o)
            return f"FOK {side.value} {qty}@{price} gw={gw} smp={smp.value}"

        if r < 0.67 and self.f.icebergs:
            o, desc = self._iceberg(side, qty, gw)
            self._submit(o)
            return desc

        if r < 0.77 and self.f.stops:
            o, desc = self._stop(side, qty, gw)
            self._submit(o)
            return desc

        if r < 0.90 and self.live_ids:  # CANCEL
            oid = rng.choice(self.live_ids)
            self.book.cancel_order(oid)
            return f"CANCEL {oid[:8]}"

        amendable = [
            o
            for o in self.book.resting_orders()
            if o.order_type in (OrderType.LIMIT, OrderType.ICEBERG)
        ]
        if amendable:  # AMEND a resting LIMIT/ICEBERG
            order = rng.choice(amendable)
            oid = order.id
            filled = order.quantity - order.remaining_qty
            new_qty = rng.randint(filled + 1, order.quantity + 100)
            if self.f.crossing_amends:
                new_price: int | None = self._price()
            else:
                new_price = self._non_crossing_amend_price(order)
                if new_price is None:
                    return "AMEND skipped (no non-crossing price available)"
            amended, _, _ = self.book.amend_order(
                oid, new_price=new_price, new_qty=new_qty
            )
            if amended is not None and self.f.crossing_amends:
                self._rematch_if_marketable(amended)
            return f"AMEND {oid[:8]} → {new_qty}@{new_price}"

        return "NOOP"

    def auction_batch(self) -> str:
        """Collect a burst of orders without matching (the book may cross),
        then uncross and run the stops the print triggers, as
        ``Engine._run_uncross`` does."""
        rng = self.rng
        n = rng.randint(2, 6)
        for _ in range(n):
            side = rng.choice([Side.BUY, Side.SELL])
            gw = rng.choice(GATEWAYS)
            qty = rng.randint(1, 300)
            kind = rng.random()
            if kind < 0.3 and self.f.icebergs:
                o, _ = self._iceberg(side, qty, gw)
            elif kind < 0.45 and self.f.stops:
                o, _ = self._stop(side, qty, gw)
            else:
                o = Order.create(
                    symbol=SYMBOL,
                    side=side,
                    order_type=OrderType.LIMIT,
                    quantity=qty,
                    gateway_id=gw,
                    price_ticks=self._price(),
                )
            self._submit(o, match=False)
        result = compute_equilibrium(self.book)
        if result.eq_price is not None and result.eq_qty > 0:
            trades, _events = execute_uncross(self.book, result.eq_price)
            self.all_trades.extend(trades)
            stop_trades, _events = self.book.run_stops(0)
            self.all_trades.extend(stop_trades)
            return f"AUCTION {n} orders, uncrossed {result.eq_qty}@{result.eq_price}"
        return f"AUCTION {n} orders, no cross"


def _run(seed: int, features: _Features) -> None:
    rng = random.Random(seed)
    book = OrderBook(SYMBOL)
    driver = _OpDriver(book, rng, features)
    every = features.auction_every

    for step_no in range(STEPS):
        if every and step_no and step_no % every == 0:
            op = driver.auction_batch()
        else:
            op = driver.step()
        driver.history.append(op)
        recent = " | ".join(driver.history[-6:])
        context = f"seed={seed} step={step_no}: …{recent}"
        assert_book_invariants(book, context=context)
        assert_qty_conservation(driver.all_orders, driver.all_trades, context=context)


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_continuous_flow(seed: int) -> None:
    _run(seed, _Features())


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_with_icebergs(seed: int) -> None:
    _run(seed, _Features(icebergs=True))


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_with_smp(seed: int) -> None:
    _run(seed, _Features(smp=True))


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_with_auctions(seed: int) -> None:
    _run(seed, _Features(icebergs=True, auction_every=20))


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_with_stops(seed: int) -> None:
    _run(seed, _Features(stops=True))


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_everything(seed: int) -> None:
    _run(
        seed,
        _Features(
            icebergs=True,
            smp=True,
            stops=True,
            crossing_amends=True,
            auction_every=20,
        ),
    )
