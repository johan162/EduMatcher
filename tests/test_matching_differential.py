"""
Differential fuzz: the matching engine against the reference matcher.

Seeded random operation streams are applied both to the engine and to
``tests/reference_matcher.py`` — an independent, deliberately naive model
written from the documented rules (workplan T2). After every step the two
must agree exactly: the trades of that step (order, counterparties, price,
quantity, aggressor), each order's status and remaining quantity, the resting
book in priority order (with each iceberg's shown slice), the dormant stops
(with each trailing stop's ratcheted trigger) and, for an auction, the
equilibrium. The book must also pass ``assert_book_invariants``.

Two variants:

  * ``test_book_matches_reference`` drives ``OrderBook`` directly. Amends
    never cross: re-matching a marketable amend is the engine's job.
  * ``test_engine_matches_reference`` drives ``Engine`` through
    ``tests/engine_harness.py`` and compares what it publishes. It adds
    crossing amends (``Engine._handle_amend`` re-matches them) and runs
    auctions through the session phase and ``Engine._run_uncross``.

Both cover every order type, SMP, cancels, amends and auction batches with
icebergs and stops. A failure prints the seed, the step, the recent
operations and the first difference. ``-m heavy`` runs 1000 seeds.

Background: docs-design/EduMatcher-Matching-Test-Quality-Workplan.md (T3).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import pytest

from edumatcher.engine.auction import compute_equilibrium, execute_uncross
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, SmpAction
from edumatcher.models.price import from_ticks, to_ticks
from edumatcher.models.session import SessionState
from edumatcher.models.trade import Trade

from tests.engine_harness import SYMBOL, connect, make_engine
from tests.engine_invariants import assert_book_invariants
from tests.reference_matcher import TERMINAL, ReferenceMatcher, ROrder

GATEWAYS = ("GW01", "GW02", "GW03")
MID = 10000  # ticks (100.00)
SPAN = 8  # a narrow band, so prices collide and orders queue at one level
SEEDS = range(50)
HEAVY_SEEDS = range(1000)
STEPS = 300

_DEAD = (
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
)

TradeKey = tuple[str, str, int, int, str]
Equilibrium = tuple[int | None, int, int, str]


@dataclass(frozen=True)
class _Spec:
    """One new order, buildable for either side of the comparison."""

    side: str
    type: str
    qty: int
    gw: str
    price: int | None = None
    stop: int | None = None
    trail: int | None = None
    visible: int | None = None
    smp: str = "NONE"

    def order(self) -> Order:
        return Order.create(
            symbol=SYMBOL,
            side=Side(self.side),
            order_type=OrderType(self.type),
            quantity=self.qty,
            gateway_id=self.gw,
            price_ticks=self.price,
            stop_price_ticks=self.stop,
            trail_offset_ticks=self.trail,
            visible_qty=self.visible,
            smp_action=SmpAction(self.smp),
        )

    def ref(self, order_id: str) -> ROrder:
        return ROrder(
            order_id,
            self.side,
            self.type,
            self.qty,
            self.gw,
            price=self.price,
            stop=self.stop,
            trail=self.trail,
            visible=self.visible,
            smp=self.smp,
        )

    def __str__(self) -> str:
        extra = "".join(
            f" {k}={v}"
            for k, v in (
                ("px", self.price),
                ("stop", self.stop),
                ("trail", self.trail),
                ("show", self.visible),
            )
            if v is not None
        )
        smp = f" smp={self.smp}" if self.smp != "NONE" else ""
        return f"{self.type} {self.side} {self.qty}{extra} {self.gw}{smp}"


# ----------------------------------------------------------------------
# Operation generator (reads the reference only to pick ids and prices)
# ----------------------------------------------------------------------


class _Gen:
    def __init__(self, rng: random.Random, ref: ReferenceMatcher, crossing: bool):
        self.rng = rng
        self.ref = ref
        self.crossing = crossing  # may an amend cross the opposite side?

    def _price(self) -> int:
        return MID + self.rng.randint(-SPAN, SPAN)

    def spec(self, *, auction: bool = False) -> _Spec:
        rng = self.rng
        side = rng.choice(("BUY", "SELL"))
        gw = rng.choice(GATEWAYS)
        qty = rng.randint(1, 40)
        smp = (
            rng.choice(("CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"))
            if rng.random() < 0.2
            else "NONE"
        )
        types = ["LIMIT"] * 5 + ["ICEBERG"] * 3 + ["STOP", "STOP_LIMIT"] * 2
        types += ["TRAILING_STOP"] + (
            ["MARKET"] if auction else ["MARKET", "IOC", "FOK"] * 2
        )
        kind = rng.choice(types)
        base = self.ref.last_price if self.ref.last_price is not None else MID
        stop = base + rng.randint(-3, 3)
        if kind in ("LIMIT", "IOC", "FOK"):
            return _Spec(side, kind, qty, gw, price=self._price(), smp=smp)
        if kind == "ICEBERG":
            qty = max(qty, 2)
            show = rng.randint(1, max(1, qty // 2))
            return _Spec(
                side, kind, qty, gw, price=self._price(), visible=show, smp=smp
            )
        if kind == "MARKET":
            return _Spec(side, kind, qty, gw, smp=smp)
        if kind == "STOP":
            return _Spec(side, kind, qty, gw, stop=stop, smp=smp)
        if kind == "STOP_LIMIT":
            limit = stop + rng.randint(-2, 2)
            return _Spec(side, kind, qty, gw, price=limit, stop=stop, smp=smp)
        return _Spec(side, kind, qty, gw, stop=stop, trail=rng.randint(1, 4), smp=smp)

    def _live(self) -> list[ROrder]:
        return [o for o in self.ref.orders.values() if o.status not in TERMINAL]

    def _amend(self, *, matching: bool) -> tuple[Any, ...] | None:
        rng = self.rng
        resting = self.ref.bids + self.ref.asks
        if not resting:
            return None
        o = rng.choice(resting)
        filled = o.qty - o.remaining
        qty = (
            rng.randint(max(1, filled - 2), o.qty + 20) if rng.random() < 0.7 else None
        )
        price = self._price() if rng.random() < 0.6 or qty is None else None
        if price is not None and matching and not self.crossing:
            best = self.ref._best(self.ref._opposite(o.side))
            if best is not None and best.price is not None:
                limit = best.price - 1 if o.side == "BUY" else best.price + 1
                price = min(price, limit) if o.side == "BUY" else max(price, limit)
            if price <= 0 or (price == o.price and qty is None):
                return None
        return ("amend", o.id, price, qty)

    def step(self) -> tuple[Any, ...]:
        r = self.rng.random()
        live = self._live()
        if r < 0.04:
            return (
                "auction",
                [self._batch_op() for _ in range(self.rng.randint(3, 8))],
            )
        if r < 0.16 and live:
            return ("cancel", self.rng.choice(live).id)
        if r < 0.28:
            op = self._amend(matching=True)
            if op is not None:
                return op
        return ("new", self.spec())

    def _batch_op(self) -> tuple[Any, ...]:
        """One operation while the market is not matching."""
        if self.rng.random() < 0.15:
            op = self._amend(matching=False)
            if op is not None:
                return op
        return ("new", self.spec(auction=True))


def _describe(op: tuple[Any, ...]) -> str:
    kind = op[0]
    if kind == "new":
        return f"NEW {op[1]}"
    if kind == "cancel":
        return f"CANCEL {op[1][:8]}"
    if kind == "amend":
        return f"AMEND {op[1][:8]} px={op[2]} qty={op[3]}"
    return "AUCTION [" + "; ".join(_describe(o) for o in op[1]) + "]"


# ----------------------------------------------------------------------
# State snapshots of both sides, in one comparable shape
# ----------------------------------------------------------------------


def _book_state(book: OrderBook) -> dict[str, Any]:
    def side(heap: list[Any]) -> list[tuple[str, int, int, int]]:
        live = sorted(
            (e for e in heap if e.valid and e.order.status not in _DEAD),
            key=lambda e: e.key,
        )
        return [
            (
                e.order.id,
                e.order.price_ticks,
                e.order.remaining_qty,
                (
                    e.order.displayed_qty
                    if e.order.order_type == OrderType.ICEBERG
                    else e.order.remaining_qty
                ),
            )
            for e in live
        ]

    stops = [
        e.order
        for e in book._buy_stops + book._sell_stops
        if e.valid and e.order.status not in _DEAD
    ] + [o for o in book._trailing_stops if o.status not in _DEAD]
    return {
        "bids": side(book._bids),
        "asks": side(book._asks),
        "stops": sorted((o.id, o.stop_price_ticks) for o in stops),
    }


def _ref_state(ref: ReferenceMatcher) -> dict[str, Any]:
    return {**ref.book(), "stops": sorted((s.id, s.stop) for s in ref.stops)}


def _trade_keys(trades: list[Trade]) -> list[TradeKey]:
    return [
        (t.buy_order_id, t.sell_order_id, t.price, t.quantity, t.aggressor_side)
        for t in trades
    ]


def _ref_keys(trades: list[Any]) -> list[TradeKey]:
    return [(t.buy_id, t.sell_id, t.price, t.qty, t.aggressor) for t in trades]


def _ref_eq(ref: ReferenceMatcher) -> Equilibrium:
    price, qty, surplus, side = ref.equilibrium()
    return (price, qty, surplus, side) if price is not None else (None, 0, 0, "")


# ----------------------------------------------------------------------
# Drivers: the engine side of each variant
# ----------------------------------------------------------------------


class _BookDriver:
    """``OrderBook`` + ``execute_uncross``, as the engine composes them."""

    def __init__(self) -> None:
        self.book = OrderBook(SYMBOL)
        self.orders: dict[str, Order] = {}

    def new(self, spec: _Spec, *, matching: bool) -> tuple[str, list[TradeKey]]:
        order = spec.order()
        self.orders[order.id] = order
        trades, _ = self.book.process(order, match=matching)
        return order.id, _trade_keys(trades)

    def cancel(self, order_id: str) -> tuple[bool, list[TradeKey]]:
        return self.book.cancel_order(order_id) is not None, []

    def amend(
        self, order_id: str, price: int | None, qty: int | None, *, matching: bool
    ) -> tuple[bool, list[TradeKey]]:
        amended, _, _ = self.book.amend_order(order_id, new_price=price, new_qty=qty)
        return amended is not None, []

    def uncross(self) -> tuple[Equilibrium, list[TradeKey]]:
        result = compute_equilibrium(self.book)
        eq = (result.eq_price, result.eq_qty, result.surplus, result.imbalance_side)
        if result.eq_price is None or result.eq_qty == 0:
            return (None, 0, 0, ""), []
        trades, _ = execute_uncross(self.book, result.eq_price)
        out = _trade_keys(trades)
        if trades:
            sub, _ = self.book.run_stops(0)
            out += _trade_keys(sub)
        return eq, out

    def statuses(self) -> dict[str, tuple[str, int]]:
        return {i: (o.status.value, o.remaining_qty) for i, o in self.orders.items()}


class _EngineDriver:
    """``Engine`` with fake sockets; reads back what it publishes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        self.engine, self.pub = make_engine(monkeypatch, tmp_path, gateways=GATEWAYS)
        connect(self.engine, *GATEWAYS)
        self.book = self.engine._book(SYMBOL)
        self._seen = len(self.pub.sent)

    def _published(self) -> list[tuple[str, dict[str, Any]]]:
        new = self.pub.sent[self._seen :]
        self._seen = len(self.pub.sent)
        return [decode(frames) for frames in new]

    def _trades(self, published: list[tuple[str, dict[str, Any]]]) -> list[TradeKey]:
        return [
            (
                p["buy_order_id"],
                p["sell_order_id"],
                to_ticks(p["price"], SYMBOL),
                p["quantity"],
                p["aggressor_side"],
            )
            for t, p in published
            if t == "trade.executed"
        ]

    def _phase(self, matching: bool) -> None:
        self.engine._session_state = (
            SessionState.CONTINUOUS if matching else SessionState.OPENING_AUCTION
        )

    def new(self, spec: _Spec, *, matching: bool) -> tuple[str, list[TradeKey]]:
        self._phase(matching)
        payload = spec.order().to_dict()
        self.engine._handle_new_order(payload)
        return payload["id"], self._trades(self._published())

    def cancel(self, order_id: str) -> tuple[bool, list[TradeKey]]:
        gw = self._owner(order_id)
        self.engine._handle_cancel({"order_id": order_id, "gateway_id": gw})
        published = self._published()
        ok = any(t.startswith("order.cancelled.") for t, _ in published)
        return ok, self._trades(published)

    def amend(
        self, order_id: str, price: int | None, qty: int | None, *, matching: bool
    ) -> tuple[bool, list[TradeKey]]:
        self._phase(matching)
        payload: dict[str, Any] = {
            "order_id": order_id,
            "gateway_id": self._owner(order_id),
        }
        if price is not None:
            payload["price"] = from_ticks(price, SYMBOL)
        if qty is not None:
            payload["qty"] = qty
        self.engine._handle_amend(payload)
        published = self._published()
        ok = any(t.startswith("order.amended.") for t, _ in published)
        return ok, self._trades(published)

    def uncross(self) -> tuple[Equilibrium, list[TradeKey]]:
        self._phase(True)
        self.engine._run_uncross(reason="SCHEDULED")
        published = self._published()
        (result,) = [p for t, p in published if t == f"auction.result.{SYMBOL}"]
        if result["eq_price"] is None or result["eq_qty"] == 0:
            eq: Equilibrium = (None, 0, 0, "")
        else:
            eq = (
                to_ticks(result["eq_price"], SYMBOL),
                result["eq_qty"],
                result["imbalance_qty"],
                result.get("imbalance_side", ""),  # omitted when balanced
            )
        return eq, self._trades(published)

    def _owner(self, order_id: str) -> str:
        order = self.book.get_order(order_id)
        return order.gateway_id if order is not None else GATEWAYS[0]

    def statuses(self) -> None:
        return None  # the engine's Order objects are its own; book + trades suffice


# ----------------------------------------------------------------------
# The comparison loop
# ----------------------------------------------------------------------


def _apply(
    driver: Any, ref: ReferenceMatcher, op: tuple[Any, ...], *, matching: bool = True
) -> tuple[list[TradeKey], list[TradeKey], str]:
    """Apply *op* to both sides; return (engine trades, reference trades, problem)."""
    kind = op[0]
    if kind == "new":
        spec: _Spec = op[1]
        oid, got = driver.new(spec, matching=matching)
        want = _ref_keys(ref.submit(spec.ref(oid), matching=matching))
        return got, want, ""
    if kind == "cancel":
        ok, got = driver.cancel(op[1])
        ref_ok = ref.cancel(op[1])
        return got, [], "" if ok == ref_ok else f"cancel accepted {ok} vs {ref_ok}"
    if kind == "amend":
        start = len(ref.trades)
        ok, got = driver.amend(op[1], op[2], op[3], matching=matching)
        ref_ok = ref.amend(op[1], op[2], op[3], matching=matching)
        want = _ref_keys(ref.trades[start:])
        return got, want, "" if ok == ref_ok else f"amend accepted {ok} vs {ref_ok}"
    got, want, problem = [], [], ""
    for sub in op[1]:
        g, w, p = _apply(driver, ref, sub, matching=False)
        got, want, problem = got + g, want + w, problem or p
    ref_eq = _ref_eq(ref)
    eq, g = driver.uncross()
    want += _ref_keys(ref.uncross())
    if not problem and eq != ref_eq:
        problem = f"equilibrium {eq} vs reference {ref_eq}"
    return got + g, want, problem


def _first_diff(a: Any, b: Any) -> str:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                return f"{k}: engine {a.get(k)} vs reference {b.get(k)}"
    if isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return f"[{i}] engine {x} vs reference {y}"
        return f"lengths {len(a)} vs {len(b)}"
    return f"engine {a} vs reference {b}"


def _run(driver: Any, seed: int, *, crossing_amends: bool) -> None:
    rng = random.Random(seed)
    ref = ReferenceMatcher()
    gen = _Gen(rng, ref, crossing=crossing_amends)
    history: list[str] = []
    for step in range(STEPS):
        op = gen.step()
        history.append(_describe(op))
        where = f"seed={seed} step={step}\n  " + "\n  ".join(history[-8:])

        got, want, problem = _apply(driver, ref, op)
        assert not problem, f"{where}\n{problem}"
        assert got == want, f"{where}\ntrades differ: {_first_diff(got, want)}"
        state, ref_state = _book_state(driver.book), _ref_state(ref)
        assert (
            state == ref_state
        ), f"{where}\nbook differs: {_first_diff(state, ref_state)}"
        statuses = driver.statuses()
        if statuses is not None:
            ref_statuses = {
                i: (o.status, o.remaining)
                for i, o in ref.orders.items()
                if i in statuses
            }
            assert (
                statuses == ref_statuses
            ), f"{where}\nstatus differs: {_first_diff(statuses, ref_statuses)}"
        assert_book_invariants(driver.book, context=where)


@pytest.mark.parametrize("seed", SEEDS)
def test_book_matches_reference(seed: int) -> None:
    _run(_BookDriver(), seed, crossing_amends=False)


@pytest.mark.parametrize("seed", SEEDS)
def test_engine_matches_reference(
    seed: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    _run(_EngineDriver(monkeypatch, tmp_path), seed, crossing_amends=True)


@pytest.mark.heavy
@pytest.mark.parametrize("seed", HEAVY_SEEDS)
def test_book_matches_reference_heavy(seed: int) -> None:
    _run(_BookDriver(), seed, crossing_amends=False)


@pytest.mark.heavy
@pytest.mark.parametrize("seed", HEAVY_SEEDS)
def test_engine_matches_reference_heavy(
    seed: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    _run(_EngineDriver(monkeypatch, tmp_path), seed, crossing_amends=True)
