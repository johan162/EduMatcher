"""
Regression test: ``tests/engine_invariants.py``'s facade functions
(``assert_book_invariants``, ``assert_qty_conservation``) must produce
IDENTICAL pass/fail outcomes and IDENTICAL violation content as calling
``edumatcher.systest.invariants``'s ``check_i1``..``check_i6`` functions
directly, given the same book/order/trade fixtures.

This proves the task 2.2 refactor (facade over the shared module) is a pure
delegation with no behavioral drift between the two call sites — see
design.md Components §2 and requirements.md Requirement 2, Criteria 4 and 5.

Each invariant gets a passing fixture (shared, built once for I1-I5) and a
violating fixture that is deliberately corrupted to trip *only* that one
invariant, so the facade's sequential check_i1 -> check_i2 -> ... -> check_i5
dispatch reaches (and raises from) the same function the direct call site
would raise from.
"""

from __future__ import annotations

import functools
from typing import Callable

import pytest

from edumatcher.engine.order_book import OrderBook, _HeapEntry
from edumatcher.models.order import Order, OrderStatus, OrderType, Side
from edumatcher.models.trade import Trade
from edumatcher.systest.invariants import (
    InvariantViolation,
    check_i1_price_level_qty,
    check_i2_not_crossed,
    check_i3_order_qty_bounds,
    check_i4_heap_entry_consistency,
    check_i5_hygiene,
    check_i6_qty_conservation,
)

from tests.engine_invariants import assert_book_invariants, assert_qty_conservation

SYMBOL = "AAPL"
GW = "GW1"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _limit(side: Side, qty: int, price: int, gw: str = GW) -> Order:
    return Order.create(
        symbol=SYMBOL,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        gateway_id=gw,
        price=price,
    )


def _rest(book: OrderBook, order: Order) -> None:
    """Rest *order* on *book* without matching (auction-style queueing)."""
    book.process(order, match=False)


def _valid_book() -> OrderBook:
    """A two-sided, non-crossed book with no terminal orders — I1-I5 all hold."""
    book = OrderBook(SYMBOL)
    _rest(book, _limit(Side.BUY, 100, 10000))
    _rest(book, _limit(Side.SELL, 100, 10100))
    return book


def _book_violating_i1() -> OrderBook:
    """Price-level qty index diverges from live resting quantity (I1)."""
    book = OrderBook(SYMBOL)
    _rest(book, _limit(Side.BUY, 100, 10000))
    book._bid_qty[10000] += 1  # corrupt the index directly
    return book


def _book_violating_i2() -> OrderBook:
    """Book left crossed: best live bid >= best live ask (I2)."""
    book = OrderBook(SYMBOL)
    _rest(book, _limit(Side.BUY, 100, 10100))
    _rest(book, _limit(Side.SELL, 100, 10000))
    return book


def _book_violating_i3() -> OrderBook:
    """Resting order's remaining_qty exceeds its own (shrunk) quantity (I3)."""
    book = OrderBook(SYMBOL)
    order = _limit(Side.BUY, 100, 10000)
    _rest(book, order)
    order.quantity = 50  # remaining_qty (100) now > quantity (50)
    return book


def _book_violating_i4() -> OrderBook:
    """_entry_index points at a stale entry, not the live heap entry (I4)."""
    book = OrderBook(SYMBOL)
    order = _limit(Side.BUY, 100, 10000)
    _rest(book, order)
    stale = _HeapEntry(key=(-10000, 999_999), order=order)
    book._entry_index[order.id] = stale
    return book


def _book_violating_i5() -> OrderBook:
    """A FILLED order lingers in the lookup indexes instead of being purged (I5)."""
    book = OrderBook(SYMBOL)
    order = _limit(Side.BUY, 100, 10000)
    _rest(book, order)
    order.status = OrderStatus.FILLED
    order.remaining_qty = 0
    book._bid_qty.pop(10000, None)  # qty index correctly deducted...
    # ...but the order was never purged from _order_index/_entry_index.
    return book


def _orders_trades_valid_i6() -> tuple[list[Order], list[Trade]]:
    order = _limit(Side.BUY, 100, 10000)
    order.remaining_qty = 40  # filled = quantity - remaining = 60
    trade = Trade(
        id="000000-000000001",
        symbol=SYMBOL,
        buy_order_id=order.id,
        sell_order_id="other-order",
        buy_gateway_id=GW,
        sell_gateway_id="GW2",
        price=10000,
        quantity=60,
        aggressor_side="BUY",
        timestamp=0,
    )
    return [order], [trade]


def _orders_trades_violating_i6() -> tuple[list[Order], list[Trade]]:
    order = _limit(Side.BUY, 100, 10000)
    order.remaining_qty = 40  # implies 60 filled...
    trade = Trade(
        id="000000-000000001",
        symbol=SYMBOL,
        buy_order_id=order.id,
        sell_order_id="other-order",
        buy_gateway_id=GW,
        sell_gateway_id="GW2",
        price=10000,
        quantity=30,  # ...but the trade stream only shows 30 (lost fill)
        aggressor_side="BUY",
        timestamp=0,
    )
    return [order], [trade]


# ---------------------------------------------------------------------------
# Equivalence harness
# ---------------------------------------------------------------------------


def _outcome(fn: Callable, /, *args, **kwargs) -> tuple[bool, str | None]:
    """Call *fn*; return (passed, violation message or None)."""
    try:
        fn(*args, **kwargs)
    except InvariantViolation as exc:
        return False, str(exc)
    return True, None


def _assert_equivalent(
    direct_fn: Callable, facade_fn: Callable, *args, **kwargs
) -> bool:
    """Assert *direct_fn* (systest/invariants.py) and *facade_fn*
    (tests/engine_invariants.py) agree exactly given the same args: same
    pass/fail outcome AND byte-identical violation content.

    Returns the shared pass/fail outcome for the caller's own assertions.
    """
    direct_passed, direct_msg = _outcome(direct_fn, *args, **kwargs)
    facade_passed, facade_msg = _outcome(facade_fn, *args, **kwargs)
    assert direct_passed == facade_passed, (
        f"direct check and facade disagree on pass/fail outcome: "
        f"direct passed={direct_passed}, facade passed={facade_passed}"
    )
    assert direct_msg == facade_msg, (
        "direct check and facade produced different violation content:\n"
        f"  direct call site = {direct_msg!r}\n"
        f"  facade call site = {facade_msg!r}"
    )
    return direct_passed


# ---------------------------------------------------------------------------
# I1-I5 (book invariants)
# ---------------------------------------------------------------------------

# (invariant id, direct check_i* function, include_hygiene flag for the
# facade's assert_book_invariants call)
INVARIANT_CHECKS = [
    ("I1", check_i1_price_level_qty, False),
    ("I2", check_i2_not_crossed, False),
    ("I3", check_i3_order_qty_bounds, False),
    ("I4", check_i4_heap_entry_consistency, False),
    ("I5", check_i5_hygiene, True),
]

VIOLATION_BUILDERS: dict[str, Callable[[], OrderBook]] = {
    "I1": _book_violating_i1,
    "I2": _book_violating_i2,
    "I3": _book_violating_i3,
    "I4": _book_violating_i4,
    "I5": _book_violating_i5,
}


def test_valid_book_state_passes_identically_at_both_call_sites() -> None:
    book = _valid_book()
    for name, direct_fn, include_hygiene in INVARIANT_CHECKS:
        facade_fn = functools.partial(
            assert_book_invariants, include_hygiene=include_hygiene
        )
        passed = _assert_equivalent(
            direct_fn, facade_fn, book, context=f"{name} valid state"
        )
        assert passed is True, f"{name} should pass on a valid book at both call sites"


@pytest.mark.parametrize(
    "name, direct_fn, include_hygiene",
    INVARIANT_CHECKS,
    ids=[c[0] for c in INVARIANT_CHECKS],
)
def test_violating_book_state_fails_identically_at_both_call_sites(
    name: str, direct_fn: Callable, include_hygiene: bool
) -> None:
    book = VIOLATION_BUILDERS[name]()
    facade_fn = functools.partial(
        assert_book_invariants, include_hygiene=include_hygiene
    )
    passed = _assert_equivalent(
        direct_fn, facade_fn, book, context=f"{name} violating state"
    )
    assert (
        passed is False
    ), f"{name} fixture should violate its own invariant at both call sites"


# ---------------------------------------------------------------------------
# I6 (order/trade qty conservation)
# ---------------------------------------------------------------------------


def test_valid_qty_conservation_passes_identically_at_both_call_sites() -> None:
    orders, trades = _orders_trades_valid_i6()
    passed = _assert_equivalent(
        check_i6_qty_conservation,
        assert_qty_conservation,
        orders,
        trades,
        context="I6 valid state",
    )
    assert passed is True


def test_violating_qty_conservation_fails_identically_at_both_call_sites() -> None:
    orders, trades = _orders_trades_violating_i6()
    passed = _assert_equivalent(
        check_i6_qty_conservation,
        assert_qty_conservation,
        orders,
        trades,
        context="I6 violating state",
    )
    assert passed is False
