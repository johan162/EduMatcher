"""Shared book-structural invariants I1-I6, lifted from tests/engine_invariants.py.

These are the conservation laws that must hold on an ``OrderBook`` after ANY
operation, regardless of which code path executed, plus the per-order
quantity-conservation check against the trade stream. See
``tests/engine_invariants.py``'s module docstring for the motivating review
findings (docs-design/EduMatcher-Engine-Review.md, §10) — this module is the
single source of truth for I1-I6; ``tests/engine_invariants.py`` becomes a
thin facade over it (see design.md Components §2 and Requirement 2).

Each ``check_i*`` function is independently callable and raises
``InvariantViolation`` (a subclass of ``AssertionError``) identifying the
invariant's id and the specific violating values, so a caller (e.g. the
systest Layer 1 invariant runner) can catch a single, systest-specific
exception type without pattern-matching on message text.

This module imports nothing else from ``edumatcher.systest`` — it depends
only on ``edumatcher.engine.order_book``, ``edumatcher.models.order``,
``edumatcher.models.trade``, and the standard library — so it is importable
without pulling the orchestrator, drivers, or CLI into the unit-test
dependency graph (Requirement 1.3).
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from edumatcher.models.order import Order, OrderStatus, OrderType
from edumatcher.models.trade import Trade

if TYPE_CHECKING:
    from edumatcher.engine.order_book import OrderBook

__all__ = [
    "InvariantViolation",
    "check_i1_price_level_qty",
    "check_i2_not_crossed",
    "check_i3_order_qty_bounds",
    "check_i4_heap_entry_consistency",
    "check_i5_hygiene",
    "check_i6_qty_conservation",
]

_DEAD = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)


class InvariantViolation(AssertionError):
    """Raised by a ``check_i*`` function when its invariant does not hold.

    A subclass of ``AssertionError`` so existing ``assert``-based callers
    (e.g. ``tests/engine_invariants.py``'s facade) continue to work
    unmodified, while systest code can catch this specific type to
    distinguish an invariant failure from an unrelated assertion error.
    """


def _visible_qty(order: Order) -> int:
    if order.order_type == OrderType.ICEBERG:
        return order.displayed_qty or 0
    return order.remaining_qty


def _live_level_qty(book: "OrderBook", side_heap) -> dict[int, int]:
    """Recompute per-price visible quantity from live heap entries.

    An order may appear in the heap through multiple entries (amend,
    iceberg replenish); only the entry currently registered in
    _entry_index is authoritative, so count each live order once.
    """
    seen: set[str] = set()
    levels: dict[int, int] = defaultdict(int)
    for entry in side_heap:
        if not entry.valid:
            continue
        o = entry.order
        if o.status in _DEAD or o.id in seen:
            continue
        seen.add(o.id)
        if o.price is not None:
            levels[o.price] += _visible_qty(o)
    return {p: q for p, q in levels.items() if q != 0}


def check_i1_price_level_qty(book: "OrderBook", *, context: str = "") -> None:
    """I1 — price-level quantity index equals visible resting quantity.

    Violated by review findings C2 and C3.
    """
    ctx = f" [{context}]" if context else ""

    for side_name, heap, index in (
        ("bid", book._bids, book._bid_qty),
        ("ask", book._asks, book._ask_qty),
    ):
        expected = _live_level_qty(book, heap)
        actual = {p: q for p, q in index.items() if q != 0}
        if actual != expected:
            phantom = {
                p: actual.get(p, 0) - expected.get(p, 0)
                for p in set(actual) | set(expected)
                if actual.get(p, 0) != expected.get(p, 0)
            }
            raise InvariantViolation(
                f"I1{ctx}: {side_name} qty index diverged from live resting "
                f"orders.\n  index    = {dict(sorted(actual.items()))}\n"
                f"  expected = {dict(sorted(expected.items()))}\n"
                f"  phantom  = {phantom}"
            )


def check_i2_not_crossed(book: "OrderBook", *, context: str = "") -> None:
    """I2 — the book is never crossed (best live bid < best live ask).

    Violated after a crossing amend — review finding H2.
    """
    ctx = f" [{context}]" if context else ""

    live_bids = _live_level_qty(book, book._bids)
    live_asks = _live_level_qty(book, book._asks)
    if live_bids and live_asks:
        best_bid, best_ask = max(live_bids), min(live_asks)
        if not (best_bid < best_ask):
            raise InvariantViolation(
                f"I2{ctx}: book is crossed — best bid {best_bid} >= best ask "
                f"{best_ask}; continuous matching must never leave a crossed "
                f"book"
            )


def check_i3_order_qty_bounds(book: "OrderBook", *, context: str = "") -> None:
    """I3 — per-order quantity sanity."""
    ctx = f" [{context}]" if context else ""

    for o in book._order_index.values():
        if o.status in _DEAD:
            continue
        if not (0 <= o.remaining_qty <= o.quantity):
            raise InvariantViolation(
                f"I3{ctx}: order {o.id[:8]} has remaining_qty="
                f"{o.remaining_qty} outside [0, quantity={o.quantity}]"
            )
        if o.order_type == OrderType.ICEBERG:
            displayed = o.displayed_qty or 0
            if not (0 <= displayed <= o.remaining_qty):
                raise InvariantViolation(
                    f"I3{ctx}: iceberg {o.id[:8]} displayed_qty={displayed} "
                    f"exceeds remaining_qty={o.remaining_qty}"
                )


def check_i4_heap_entry_consistency(book: "OrderBook", *, context: str = "") -> None:
    """I4 — every live bid/ask heap entry agrees with _entry_index."""
    ctx = f" [{context}]" if context else ""

    for heap in (book._bids, book._asks):
        for entry in heap:
            if not entry.valid or entry.order.status in _DEAD:
                continue
            registered = book._entry_index.get(entry.order.id)
            if registered is not entry:
                raise InvariantViolation(
                    f"I4{ctx}: live heap entry for order "
                    f"{entry.order.id[:8]} is not the entry registered in "
                    f"_entry_index (stale duplicate not invalidated?)"
                )


def check_i5_hygiene(book: "OrderBook", *, context: str = "") -> None:
    """I5 (hygiene) — terminal orders are purged from the indexes.

    Violated by review finding H7. Only meaningful post-terminal-state;
    the caller decides when to invoke it (see the original
    ``include_hygiene`` flag's intent in ``tests/engine_invariants.py``).
    """
    ctx = f" [{context}]" if context else ""

    dead_in_orders = [
        o.id[:8] for o in book._order_index.values() if o.status in _DEAD
    ]
    if dead_in_orders:
        raise InvariantViolation(
            f"I5{ctx}: terminal orders retained in _order_index: "
            f"{dead_in_orders} (unbounded growth — review H7)"
        )
    dead_in_entries = [
        oid[:8]
        for oid, entry in book._entry_index.items()
        if entry.order.status in _DEAD
    ]
    if dead_in_entries:
        raise InvariantViolation(
            f"I5{ctx}: terminal orders retained in _entry_index: "
            f"{dead_in_entries} (unbounded growth — review H7)"
        )


def check_i6_qty_conservation(
    orders: list[Order], trades: list[Trade], *, context: str = ""
) -> None:
    """I6 — for every order: quantity executed in trades == quantity - remaining.

    Catches double-fills, lost fills, and remaining_qty corruption across
    any sequence of operations.
    """
    ctx = f" [{context}]" if context else ""
    executed: dict[str, int] = defaultdict(int)
    for t in trades:
        executed[t.buy_order_id] += t.quantity
        executed[t.sell_order_id] += t.quantity

    for o in orders:
        expected = o.quantity - o.remaining_qty
        actual = executed.get(o.id, 0)
        if actual != expected:
            raise InvariantViolation(
                f"I6{ctx}: order {o.id[:8]} ({o.side.value} "
                f"{o.order_type.value}) shows {expected} filled on the "
                f"order but {actual} in the trade stream"
            )
