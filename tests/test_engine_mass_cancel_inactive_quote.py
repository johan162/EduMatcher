"""Admin mass cancels clear the leg a half-filled quote leaves behind.

With ``INACTIVATE_ON_ANY_FILL`` a quote hit on one side leaves the
``QuoteIndex`` at once, but the hit leg's unfilled remainder keeps resting by
design (see test_engine_quote_entry_fill). ``CANCEL_SYM`` and the gateway kill
switch only walked the ``QuoteIndex`` for quotes and skipped quote-origin
orders in the book, so that remainder survived both, and the Training Guide's
"clear the book before the experiment" step left a stray ask or bid behind.
"""

from __future__ import annotations

import pytest

from typing import Any

from edumatcher.models.participant import DisconnectBehaviour
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import (
    SYMBOL,
    connect,
    make_engine,
    msgs,
    order_payload,
    submit_quote,
)

ADMIN = "ADM01"
MM = "GW03"
SELLER = "GW01"


def _engine_with_a_half_filled_quote(
    monkeypatch: Any, tmp_path: Any
) -> tuple[Any, Any]:
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        gateways=(SELLER, MM, ADMIN),
        mm_gateways=(MM,),
        admin_gateways=(ADMIN,),
    )
    connect(engine, SELLER, MM, ADMIN)
    engine._handle_new_order(
        order_payload(
            gateway_id=SELLER, symbol=SYMBOL, side=Side.SELL,
            order_type=OrderType.LIMIT, price=100.0, qty=40,
        )
    )  # fmt: skip
    submit_quote(engine, MM, 100.0, 101.0)
    # The 40 sold hit the bid leg: the quote is inactive, 60 of the bid rests.
    assert engine._quote_index.get(MM, SYMBOL) is None
    assert [o.remaining_qty for o in engine.books[SYMBOL].resting_orders()] == [60]
    pub.sent.clear()
    return engine, pub


def test_cancel_symbol_clears_the_leg_of_an_inactivated_quote(monkeypatch, tmp_path):
    engine, pub = _engine_with_a_half_filled_quote(monkeypatch, tmp_path)
    engine._handle_cancel_symbol({"gateway_id": ADMIN, "symbol": SYMBOL})
    (ack,) = msgs(pub, f"risk.cancel_symbol_ack.{ADMIN}")
    assert ack["accepted"] is True
    assert (ack["cancelled_orders"], ack["cancelled_quotes"]) == (0, 1)
    assert list(engine.books[SYMBOL].resting_orders()) == []


def test_the_gateway_kill_switch_clears_the_leg_of_an_inactivated_quote(
    monkeypatch, tmp_path
):
    engine, pub = _engine_with_a_half_filled_quote(monkeypatch, tmp_path)
    engine._handle_kill_switch_gateway({"gateway_id": ADMIN, "target_gateway_id": MM})
    (ack,) = msgs(pub, f"risk.kill_switch_gateway_ack.{ADMIN}")
    assert ack["accepted"] is True
    assert (ack["cancelled_orders"], ack["cancelled_quotes"]) == (0, 1)
    assert list(engine.books[SYMBOL].resting_orders()) == []


def test_the_global_kill_switch_clears_the_leg_of_an_inactivated_quote(
    monkeypatch, tmp_path
):
    """The market-wide stop walked the QuoteIndex and skipped quote-origin
    orders in the books, as the two above once did (S31, C13)."""
    engine, pub = _engine_with_a_half_filled_quote(monkeypatch, tmp_path)
    engine._handle_kill_switch_global({"gateway_id": ADMIN})
    (ack,) = msgs(pub, f"risk.kill_switch_global_ack.{ADMIN}")
    assert ack["accepted"] is True
    assert (ack["cancelled_orders"], ack["cancelled_quotes"]) == (0, 1)
    assert ack["affected_gateway_ids"] == [MM]
    assert list(engine.books[SYMBOL].resting_orders()) == []


@pytest.mark.parametrize(
    ("behaviour", "ordinary_order_remains", "quote_remainder_remains"),
    [
        (DisconnectBehaviour.CANCEL_QUOTES_ONLY, True, False),
        (DisconnectBehaviour.CANCEL_ALL, False, False),
        (DisconnectBehaviour.LEAVE_ALL, True, True),
    ],
)
def test_disconnect_applies_policy_to_inactivated_quote_remainder(
    monkeypatch,
    tmp_path,
    behaviour,
    ordinary_order_remains,
    quote_remainder_remains,
):
    engine, pub = _engine_with_a_half_filled_quote(monkeypatch, tmp_path)
    engine._sessions[MM].disconnect_behaviour = behaviour
    ordinary = order_payload(
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=10,
        gateway_id=MM,
        price=90.0,
    )
    engine._handle_new_order(ordinary)
    quote_remainder = engine.books[SYMBOL].quote_orders_for_gateway(MM)[0]
    pub.sent.clear()

    engine._handle_gateway_disconnect({"gateway_id": MM})

    remaining = list(engine.books[SYMBOL].resting_orders())
    expected_remaining = []
    if ordinary_order_remains:
        expected_remaining.append(ordinary["id"])
    if quote_remainder_remains:
        expected_remaining.append(quote_remainder.id)
    assert {order.id for order in remaining} == set(expected_remaining)
    cancellations = msgs(pub, f"order.cancelled.{MM}")
    assert {item["order_id"] for item in cancellations} == (
        set()
        if quote_remainder_remains
        else (
            {quote_remainder.id}
            if ordinary_order_remains
            else {quote_remainder.id, ordinary["id"]}
        )
    )
    assert all(item["cancel_reason"] == "GATEWAY_DISCONNECT" for item in cancellations)


def test_participant_kill_clears_and_acknowledges_inactivated_quote_remainder(
    monkeypatch, tmp_path
):
    engine, pub = _engine_with_a_half_filled_quote(monkeypatch, tmp_path)
    ordinary = order_payload(
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=10,
        gateway_id=MM,
        price=90.0,
    )
    engine._handle_new_order(ordinary)
    quote_remainder = engine.books[SYMBOL].quote_orders_for_gateway(MM)[0]

    engine._handle_kill_switch({"gateway_id": MM})

    (ack,) = msgs(pub, f"risk.kill_switch_ack.{MM}")
    assert (ack["cancelled_orders"], ack["cancelled_quotes"]) == (1, 1)
    assert ack["cancelled_order_ids"] == [ordinary["id"]]
    assert ack["cancelled_quote_order_ids"] == [quote_remainder.id]
    assert list(engine.books[SYMBOL].resting_orders()) == []


@pytest.mark.parametrize("tif, ends", [("DAY", True), ("GTC", False)])
def test_a_day_quote_ends_with_its_legs_at_the_close(
    monkeypatch, tmp_path, tif: str, ends: bool
) -> None:
    """The close expired a DAY quote's legs but left the quote in the
    QuoteIndex, ACTIVE to every subscriber (X41, C14). It now ends as a
    halt or a kill switch ends one: quote.status CANCELLED."""
    engine, pub = make_engine(
        monkeypatch, tmp_path, gateways=(MM,), mm_gateways=(MM,), sessions_enabled=True
    )
    connect(engine, MM)
    engine._handle_session_transition({"to_state": "PRE_OPEN"})
    submit_quote(engine, MM, 100.0, 101.0, tif=tif)
    for state in ("OPENING_AUCTION", "CONTINUOUS", "CLOSING_AUCTION", "CLOSED"):
        engine._handle_session_transition({"to_state": state})
    statuses = [p["status"] for p in msgs(pub, f"quote.status.{MM}")]
    assert (statuses[-1] == "CANCELLED") is ends
    assert (engine._quote_index.get(MM, SYMBOL) is None) is ends
    assert len(msgs(pub, f"order.expired.{MM}")) == (2 if ends else 0)
