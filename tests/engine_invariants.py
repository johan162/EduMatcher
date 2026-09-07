"""
Structural invariants of the OrderBook — the conservation laws that must
hold after ANY operation, regardless of which code path executed.

Motivation (see docs-design/EduMatcher-Engine-Review.md, §10):
the book keeps several denormalized structures in sync by hand (heaps,
_entry_index, _bid_qty/_ask_qty, _order_index).  Several review findings
(C2, C3, H7, H8) were consistency failures between them that no test
noticed, because tests asserted only the direct return value of the
operation under test.  Calling ``assert_book_invariants(book)`` at the end
of any book-level test makes that entire bug class visible mechanically.

Usage:
    from engine_invariants import assert_book_invariants
    ...
    book.process(order)
    assert_book_invariants(book)

``include_hygiene=True`` additionally asserts that terminal (filled /
cancelled / rejected / expired) orders have been purged from the lookup
indexes (review finding H7).  Keep it off in tests that only target
matching correctness, on in lifecycle tests.

Not a test module (no test_ prefix) — pytest will not collect it.

This module is now a thin facade over ``edumatcher.systest.invariants``,
which is the single source of truth for I1-I6 (see design.md Components §2
and Requirement 2). It exists only to keep every existing caller working
unmodified.
"""

from __future__ import annotations

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order
from edumatcher.models.trade import Trade
from edumatcher.systest.invariants import (
    check_i1_price_level_qty,
    check_i2_not_crossed,
    check_i3_order_qty_bounds,
    check_i4_heap_entry_consistency,
    check_i5_hygiene,
    check_i6_qty_conservation,
)


def assert_book_invariants(
    book: OrderBook, *, include_hygiene: bool = False, context: str = ""
) -> None:
    """Assert every structural invariant of *book*.  See module docstring."""
    check_i1_price_level_qty(book, context=context)
    check_i2_not_crossed(book, context=context)
    check_i3_order_qty_bounds(book, context=context)
    check_i4_heap_entry_consistency(book, context=context)
    if include_hygiene:
        check_i5_hygiene(book, context=context)


def assert_qty_conservation(
    orders: list[Order], trades: list[Trade], *, context: str = ""
) -> None:
    """For every order: quantity executed in trades == quantity - remaining.

    Catches double-fills, lost fills, and remaining_qty corruption across
    any sequence of operations.
    """
    check_i6_qty_conservation(orders, trades, context=context)
