"""
Randomized-operation invariant tests for OrderBook.

Instead of scripting specific scenarios, these tests drive the book with
seeded pseudo-random operation sequences and assert the structural
invariants (tests/engine_invariants.py) after EVERY step.  A failure
message includes the seed, the step, and the recent operation history, so
any counterexample is fully reproducible.

Four tiers:

  1. test_invariants_continuous_flow  — plain order flow (no icebergs, no
     SMP, no auctions, amends clamped to non-crossing prices).  This tier
     is expected to PASS today; it proves the invariant harness itself is
     sound.
  2. test_invariants_with_icebergs    — adds iceberg orders.  EXPECTED TO
     FAIL until review finding C7 is fixed (this tier is what DISCOVERED
     C7: passive icebergs fill beyond their displayed slice, jumping the
     queue and corrupting shared price levels in the qty index).
  3. test_invariants_with_smp         — adds self-match-prevention flags.
     EXPECTED TO FAIL until review finding C3 (SMP-cancelled aggressor is
     rested, corrupting the qty index) is fixed.
  4. test_invariants_with_auctions    — adds auction batches (rest without
     matching, then uncross).  EXPECTED TO FAIL until review finding C2
     (uncross never deducts the bid side of the qty index) is fixed.

Deliberately implemented with random.Random(seed) rather than hypothesis
so no new dependency is required; the operation generator is factored so a
future migration to hypothesis stateful testing is mechanical.
"""

from __future__ import annotations

import random

import pytest

from edumatcher.engine.auction import compute_equilibrium, execute_uncross
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderType, Side, SmpAction
from edumatcher.models.trade import Trade

from tests.engine_invariants import assert_book_invariants, assert_qty_conservation

SYMBOL = "AAPL"
GATEWAYS = ("GW1", "GW2", "GW3")
PRICE_MID = 10000
PRICE_SPAN = 200  # ticks either side of mid
SEEDS = range(10)
STEPS = 120


class _OpDriver:
    """Generates and applies one random operation per call."""

    def __init__(
        self,
        book: OrderBook,
        rng: random.Random,
        allow_smp: bool,
        allow_icebergs: bool = True,
    ) -> None:
        self.book = book
        self.rng = rng
        self.allow_smp = allow_smp
        self.allow_icebergs = allow_icebergs
        self.live_ids: list[str] = []
        self.all_orders: list[Order] = []
        self.all_trades: list[Trade] = []
        self.history: list[str] = []

    # -- helpers -------------------------------------------------------
    def _price(self) -> int:
        return PRICE_MID + self.rng.randrange(-PRICE_SPAN, PRICE_SPAN + 1, 10)

    def _smp(self) -> SmpAction:
        if self.allow_smp and self.rng.random() < 0.15:
            return self.rng.choice(
                [
                    SmpAction.CANCEL_AGGRESSOR,
                    SmpAction.CANCEL_RESTING,
                    SmpAction.CANCEL_BOTH,
                ]
            )
        return SmpAction.NONE

    def _submit(self, order: Order) -> None:
        trades, _events = self.book.process(order)
        self.all_orders.append(order)
        self.all_trades.extend(trades)
        self.live_ids.append(order.id)

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

    # -- one step ------------------------------------------------------
    def step(self) -> str:
        r = self.rng.random()
        rng = self.rng
        side = rng.choice([Side.BUY, Side.SELL])
        gw = rng.choice(GATEWAYS)
        qty = rng.randint(1, 300)

        if r < 0.40:  # LIMIT
            price = self._price()
            o = Order.create(
                symbol=SYMBOL,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=qty,
                gateway_id=gw,
                price=price,
                smp_action=self._smp(),
            )
            self._submit(o)
            return f"LIMIT {side.value} {qty}@{price} gw={gw} smp={o.smp_action.value}"

        if r < 0.50:  # MARKET
            o = Order.create(
                symbol=SYMBOL,
                side=side,
                order_type=OrderType.MARKET,
                quantity=qty,
                gateway_id=gw,
                smp_action=self._smp(),
            )
            self._submit(o)
            return f"MARKET {side.value} {qty} gw={gw} smp={o.smp_action.value}"

        if r < 0.60:  # IOC
            price = self._price()
            o = Order.create(
                symbol=SYMBOL,
                side=side,
                order_type=OrderType.IOC,
                quantity=qty,
                gateway_id=gw,
                price=price,
                smp_action=self._smp(),
            )
            self._submit(o)
            return f"IOC {side.value} {qty}@{price} gw={gw} smp={o.smp_action.value}"

        if r < 0.67:  # FOK
            price = self._price()
            o = Order.create(
                symbol=SYMBOL,
                side=side,
                order_type=OrderType.FOK,
                quantity=qty,
                gateway_id=gw,
                price=price,
                smp_action=self._smp(),
            )
            self._submit(o)
            return f"FOK {side.value} {qty}@{price} gw={gw} smp={o.smp_action.value}"

        if r < 0.77:  # ICEBERG (falls back to LIMIT when disabled)
            price = self._price()
            if not self.allow_icebergs:
                o = Order.create(
                    symbol=SYMBOL,
                    side=side,
                    order_type=OrderType.LIMIT,
                    quantity=qty,
                    gateway_id=gw,
                    price=price,
                    smp_action=self._smp(),
                )
                self._submit(o)
                return f"LIMIT {side.value} {qty}@{price} gw={gw} (iceberg tier off)"
            visible = max(1, qty // rng.randint(2, 10))
            o = Order.create(
                symbol=SYMBOL,
                side=side,
                order_type=OrderType.ICEBERG,
                quantity=qty,
                gateway_id=gw,
                price=price,
                visible_qty=visible,
                smp_action=self._smp(),
            )
            self._submit(o)
            return f"ICEBERG {side.value} {qty}(show {visible})@{price} gw={gw}"

        if r < 0.92 and self.live_ids:  # CANCEL
            oid = rng.choice(self.live_ids)
            self.book.cancel_order(oid)
            return f"CANCEL {oid[:8]}"

        if self.live_ids:  # AMEND (never crossing, never on stops)
            oid = rng.choice(self.live_ids)
            order = self.book.get_order(oid)
            if order is None or order.order_type not in (
                OrderType.LIMIT,
                OrderType.ICEBERG,
            ):
                return "AMEND skipped (not amendable)"
            filled = order.quantity - order.remaining_qty
            new_qty = rng.randint(filled + 1, order.quantity + 100)
            new_price = self._non_crossing_amend_price(order)
            if new_price is None:
                return "AMEND skipped (no non-crossing price available)"
            self.book.amend_order(oid, new_price=new_price, new_qty=new_qty)
            return f"AMEND {oid[:8]} → {new_qty}@{new_price}"

        return "NOOP"

    def auction_batch(self) -> str:
        """Rest a burst of (possibly crossed) limits without matching, then uncross."""
        rng = self.rng
        n = rng.randint(2, 6)
        for _ in range(n):
            o = Order.create(
                symbol=SYMBOL,
                side=rng.choice([Side.BUY, Side.SELL]),
                order_type=OrderType.LIMIT,
                quantity=rng.randint(1, 300),
                gateway_id=rng.choice(GATEWAYS),
                price=self._price(),
            )
            self.book.process(o, match=False)
            self.all_orders.append(o)
            self.live_ids.append(o.id)
        result = compute_equilibrium(self.book)
        if result.eq_price is not None and result.eq_qty > 0:
            trades, _events = execute_uncross(self.book, result.eq_price)
            self.all_trades.extend(trades)
            return f"AUCTION {n} orders, uncrossed {result.eq_qty}@{result.eq_price}"
        return f"AUCTION {n} orders, no cross"


def _run(
    seed: int,
    *,
    allow_smp: bool,
    auction_every: int | None,
    allow_icebergs: bool = True,
) -> None:
    rng = random.Random(seed)
    book = OrderBook(SYMBOL)
    driver = _OpDriver(book, rng, allow_smp=allow_smp, allow_icebergs=allow_icebergs)

    for step_no in range(STEPS):
        if auction_every and step_no and step_no % auction_every == 0:
            op = driver.auction_batch()
        else:
            op = driver.step()
        driver.history.append(op)
        recent = " | ".join(driver.history[-6:])
        assert_book_invariants(book, context=f"seed={seed} step={step_no}: …{recent}")

    assert_qty_conservation(
        driver.all_orders, driver.all_trades, context=f"seed={seed} end-of-run"
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_continuous_flow(seed: int) -> None:
    """Tier 1 — plain flow.  Must pass today; validates the harness."""
    _run(seed, allow_smp=False, auction_every=None, allow_icebergs=False)


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_with_icebergs(seed: int) -> None:
    """Tier 2 — adds icebergs.  EXPECTED TO FAIL until review C7 is fixed."""
    _run(seed, allow_smp=False, auction_every=None, allow_icebergs=True)


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_with_smp(seed: int) -> None:
    """Tier 3 — adds SMP.  EXPECTED TO FAIL until review C3 is fixed."""
    _run(seed, allow_smp=True, auction_every=None, allow_icebergs=False)


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_with_auctions(seed: int) -> None:
    """Tier 4 — adds auction batches.  EXPECTED TO FAIL until review C2 is fixed."""
    _run(seed, allow_smp=False, auction_every=20, allow_icebergs=False)
