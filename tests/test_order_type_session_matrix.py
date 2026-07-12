"""
Specification matrix: EVERY order type × EVERY session mode.

Systemic gap this closes (review §10): the old no-match tests mirrored the
branches that exist in the code (MARKET/FOK/IOC reject, STOP parks, "else
rests"), so order types the code forgot — TRAILING_STOP — were never
tested.  This suite enumerates the full specification matrix instead and
demands, for every cell, the universal contract:

    An accepted order must end in a DEFINED state, and its owner must be
    able to know that state from the published messages:
      - resting/tracked on the book, OR
      - a terminal notification (reject ack / cancelled / expired / fill).
    The handler must never raise.

Known failing cells today (review findings in parentheses):
  TRAILING_STOP × pre_open / halted   — handler crashes after ACK   (C6)
  MARKET        × continuous, empty book — ACKed then silently gone (C4/M1)
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.order import OrderType, Side

from tests.engine_harness import (
    SYMBOL,
    connect,
    make_engine,
    order_payload,
    terminal_notifications_for,
)

MODES = ("continuous", "pre_open", "halted")

# (order_type, extra payload fields) — every type the engine advertises.
ORDER_TYPES: list[tuple[OrderType, dict[str, Any]]] = [
    (OrderType.MARKET, {}),
    (OrderType.LIMIT, {"price": 100.0}),
    (OrderType.IOC, {"price": 100.0}),
    (OrderType.FOK, {"price": 100.0}),
    (OrderType.ICEBERG, {"price": 100.0, "visible_qty": 10}),
    (OrderType.STOP, {"stop_price": 105.0}),
    (OrderType.STOP_LIMIT, {"price": 105.0, "stop_price": 105.0}),
    (OrderType.TRAILING_STOP, {"stop_price": 95.0, "trail_offset": 5.0}),
]

_PARAMS = [
    pytest.param(ot, extra, mode, id=f"{ot.value}-{mode}")
    for ot, extra in ORDER_TYPES
    for mode in MODES
]


@pytest.mark.parametrize("order_type,extra,mode", _PARAMS)
def test_every_order_type_ends_in_a_defined_state(
    monkeypatch, tmp_path, order_type: OrderType, extra: dict, mode: str
) -> None:
    engine, pub = make_engine(
        monkeypatch, tmp_path, sessions_enabled=(mode == "pre_open")
    )
    connect(engine)
    if mode == "pre_open":
        engine._handle_session_transition({"to_state": "PRE_OPEN"})
    elif mode == "halted":
        engine._halted_symbols[SYMBOL] = True

    payload = order_payload(Side.BUY, order_type, 100, "GW01", **extra)

    # Contract part 1: the handler never raises.  (C6: TRAILING_STOP in any
    # no-match mode crashes with AssertionError after the positive ACK.)
    engine._handle_new_order(payload)

    # Contract part 2: the order is accounted for — tracked on the book or
    # terminally notified.  (C4/M1: unfilled MARKET in continuous mode is
    # ACKed accepted=True and then vanishes.)
    book = engine.books.get(SYMBOL)
    tracked = book is not None and book.get_order(payload["id"]) is not None
    notified = terminal_notifications_for(pub, "GW01", payload["id"])
    assert tracked or notified, (
        f"{order_type.value} × {mode}: order was ACKed accepted=True but is "
        f"neither resting/tracked on the book nor terminally notified — the "
        f"owner has no way to learn what happened to it"
    )
