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
"""

from __future__ import annotations

from collections import defaultdict

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderStatus, OrderType
from edumatcher.models.trade import Trade

_DEAD = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)


def _visible_qty(order: Order) -> int:
    if order.order_type == OrderType.ICEBERG:
        return order.displayed_qty or 0
    return order.remaining_qty


def _live_level_qty(book: OrderBook, side_heap) -> dict[int, int]:
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


def assert_book_invariants(
    book: OrderBook, *, include_hygiene: bool = False, context: str = ""
) -> None:
    """Assert every structural invariant of *book*.  See module docstring."""
    ctx = f" [{context}]" if context else ""

    # ------------------------------------------------------------------
    # I1 — price-level quantity index equals visible resting quantity.
    #      (violated by review findings C2 and C3)
    # ------------------------------------------------------------------
    for side_name, heap, index in (
        ("bid", book._bids, book._bid_qty),
        ("ask", book._asks, book._ask_qty),
    ):
        expected = _live_level_qty(book, heap)
        actual = {p: q for p, q in index.items() if q != 0}
        assert actual == expected, (
            f"I1{ctx}: {side_name} qty index diverged from live resting "
            f"orders.\n  index    = {dict(sorted(actual.items()))}\n"
            f"  expected = {dict(sorted(expected.items()))}\n"
            f"  phantom  = "
            f"{ {p: actual.get(p, 0) - expected.get(p, 0) for p in set(actual) | set(expected) if actual.get(p, 0) != expected.get(p, 0)} }"
        )

    # ------------------------------------------------------------------
    # I2 — the book is never crossed (best live bid < best live ask).
    #      (violated after a crossing amend — review finding H2)
    # ------------------------------------------------------------------
    live_bids = _live_level_qty(book, book._bids)
    live_asks = _live_level_qty(book, book._asks)
    if live_bids and live_asks:
        best_bid, best_ask = max(live_bids), min(live_asks)
        assert best_bid < best_ask, (
            f"I2{ctx}: book is crossed — best bid {best_bid} >= best ask "
            f"{best_ask}; continuous matching must never leave a crossed book"
        )

    # ------------------------------------------------------------------
    # I3 — per-order quantity sanity.
    # ------------------------------------------------------------------
    for o in book._order_index.values():
        if o.status in _DEAD:
            continue
        assert 0 <= o.remaining_qty <= o.quantity, (
            f"I3{ctx}: order {o.id[:8]} has remaining_qty={o.remaining_qty} "
            f"outside [0, quantity={o.quantity}]"
        )
        if o.order_type == OrderType.ICEBERG:
            displayed = o.displayed_qty or 0
            assert 0 <= displayed <= o.remaining_qty, (
                f"I3{ctx}: iceberg {o.id[:8]} displayed_qty={displayed} "
                f"exceeds remaining_qty={o.remaining_qty}"
            )

    # ------------------------------------------------------------------
    # I4 — every live bid/ask heap entry agrees with _entry_index.
    # ------------------------------------------------------------------
    for heap in (book._bids, book._asks):
        for entry in heap:
            if not entry.valid or entry.order.status in _DEAD:
                continue
            registered = book._entry_index.get(entry.order.id)
            assert registered is entry, (
                f"I4{ctx}: live heap entry for order {entry.order.id[:8]} is "
                f"not the entry registered in _entry_index (stale duplicate "
                f"not invalidated?)"
            )

    # ------------------------------------------------------------------
    # I5 (hygiene) — terminal orders are purged from the indexes.
    #      (review finding H7)
    # ------------------------------------------------------------------
    if include_hygiene:
        dead_in_orders = [
            o.id[:8] for o in book._order_index.values() if o.status in _DEAD
        ]
        assert not dead_in_orders, (
            f"I5{ctx}: terminal orders retained in _order_index: "
            f"{dead_in_orders} (unbounded growth — review H7)"
        )
        dead_in_entries = [
            oid[:8]
            for oid, entry in book._entry_index.items()
            if entry.order.status in _DEAD
        ]
        assert not dead_in_entries, (
            f"I5{ctx}: terminal orders retained in _entry_index: "
            f"{dead_in_entries} (unbounded growth — review H7)"
        )


def assert_qty_conservation(
    orders: list[Order], trades: list[Trade], *, context: str = ""
) -> None:
    """For every order: quantity executed in trades == quantity - remaining.

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
        assert executed.get(o.id, 0) == expected, (
            f"QTY{ctx}: order {o.id[:8]} ({o.side.value} {o.order_type.value}) "
            f"shows {expected} filled on the order but {executed.get(o.id, 0)} "
            f"in the trade stream"
        )
