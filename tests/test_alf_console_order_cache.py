"""What the ALF console's ORDERS table learns from order.ack.

A refused AMEND must not make a live order look rejected: a rejected ack
carries the RTAG of the AMEND or CANCEL it refuses, and the console used to
mark the cached order REJECTED regardless.

The children of a combo or OCO were never listed at all: the gateway sends the
parent, so only their acks tell it they exist.
"""

from __future__ import annotations

from unittest.mock import patch

from edumatcher.alf_console.main import Gateway
from tests.test_alf_console_quote_ack import _make_gateway


def _reject(gw: Gateway, **extra: object) -> None:
    payload = {
        "order_id": "A1",
        "accepted": False,
        "reason": "refused",
        "reject_code": "QTY_OUT_OF_RANGE",
        **extra,
    }
    with patch("edumatcher.alf_console.main.console.print"):
        gw._handle_event("order.ack.GW01", payload)


def test_rejected_amend_leaves_resting_order_status() -> None:
    gw, _ = _make_gateway()
    gw.order_cache["A1"] = {"status": "NEW"}
    _reject(gw, request_tag="AMD-BAD-001")
    assert gw.order_cache["A1"]["status"] == "NEW"


def test_rejected_new_order_is_marked_rejected() -> None:
    gw, _ = _make_gateway()
    gw.order_cache["A1"] = {"status": "PENDING"}
    _reject(gw)
    assert gw.order_cache["A1"]["status"] == "REJECTED"


def test_combo_child_ack_registers_the_order() -> None:
    gw, _ = _make_gateway()
    with patch("edumatcher.alf_console.main.console.print"):
        gw._handle_event(
            "order.ack.GW01",
            {
                "order_id": "C1",
                "accepted": True,
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "qty": 100,
                "price": 150.0,
                "combo_parent_id": "PAIR-1",
            },
        )
    row = gw.order_cache["C1"]
    assert (row["symbol"], row["qty"], row["remaining"], row["status"]) == (
        "AAPL",
        100,
        100,
        "NEW",
    )


def test_oco_sibling_cancel_updates_the_cache() -> None:
    gw, _ = _make_gateway()
    gw.order_cache["S1"] = {"status": "NEW"}
    with patch("edumatcher.alf_console.main.console.print"):
        gw._handle_event(
            "oco.cancelled.GW01",
            {"oco_id": "O1", "cancelled_order_id": "S1", "reason": "sibling filled"},
        )
    assert gw.order_cache["S1"]["status"] == "CANCELLED"
