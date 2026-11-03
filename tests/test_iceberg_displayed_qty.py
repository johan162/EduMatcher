"""K3 (E2): an ICEBERG that reaches the engine without ``displayed_qty``.

``Order.from_dict`` leaves ``displayed_qty`` None when the key is absent. The
level index then counted 0 visible quantity for the resting order while the
auction uncross fell back to its full remaining quantity, so the two
disagreed about what the order shows. ``displayed_qty`` is the engine's own
bookkeeping, so on acceptance it is derived from the client's ``visible_qty``
and whatever arrived on the wire is ignored.
See docs-design/EduMatcher-Key-Component-Fixes-Workplan.md K3.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.order import OrderType, Side
from edumatcher.models.session import SessionState

from tests.engine_harness import (
    SYMBOL,
    connect,
    make_engine,
    msgs,
    order_payload,
)
from tests.engine_invariants import assert_book_invariants


def _iceberg(gateway: str = "GW01", **overrides: Any) -> dict[str, Any]:
    payload = order_payload(
        Side.SELL, OrderType.ICEBERG, 100, gateway, price=100.0, visible_qty=10
    )
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("displayed", ["absent", None, 0, -5, 101])
def test_iceberg_slice_is_derived_from_visible_qty_not_the_wire(
    monkeypatch, tmp_path, displayed
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine, "GW01")
    engine._session_state = SessionState.OPENING_AUCTION
    payload = _iceberg()
    if displayed == "absent":
        del payload["displayed_qty"]
    else:
        payload["displayed_qty"] = displayed

    engine._handle_new_order(payload)

    assert [a["accepted"] for a in msgs(pub, "order.ack.GW01")] == [True]
    book = engine._book(SYMBOL)
    (order,) = book._order_index.values()
    assert order.displayed_qty == 10
    assert book._ask_qty == {order.price_ticks: 10}
    assert_book_invariants(book, include_hygiene=True)


def test_iceberg_with_an_invalid_visible_qty_is_still_rejected(
    monkeypatch, tmp_path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine, "GW01")
    engine._session_state = SessionState.OPENING_AUCTION

    engine._handle_new_order(_iceberg(visible_qty=101))

    assert [a["accepted"] for a in msgs(pub, "order.ack.GW01")] == [False]
    assert engine._book(SYMBOL)._order_index == {}


def test_iceberg_with_its_slice_rests_and_uncrosses_consistently(
    monkeypatch, tmp_path
) -> None:
    engine, _pub = make_engine(monkeypatch, tmp_path)
    connect(engine, "GW01")
    engine._session_state = SessionState.OPENING_AUCTION

    engine._handle_new_order(_iceberg())

    book = engine._book(SYMBOL)
    assert book._ask_qty == {book._asks[0].order.price_ticks: 10}
    assert_book_invariants(book, include_hygiene=True)
