"""Admin mass cancels clear the leg a half-filled quote leaves behind.

With ``INACTIVATE_ON_ANY_FILL`` a quote hit on one side leaves the
``QuoteIndex`` at once, but the hit leg's unfilled remainder keeps resting by
design (see test_engine_quote_entry_fill). ``CANCEL_SYM`` and the gateway kill
switch only walked the ``QuoteIndex`` for quotes and skipped quote-origin
orders in the book, so that remainder survived both, and the Training Guide's
"clear the book before the experiment" step left a stray ask or bid behind.
"""

from __future__ import annotations

from typing import Any

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
