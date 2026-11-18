"""A trailing stop's offset is checked before its reference price (For-Later
L026, WP-FL10).

A TRAILING_STOP with ``trail_offset -1.00`` on a symbol without trades was
refused "Trailing stop requires STOP= or a prior trade price": the client was
told to add a price when the offset was what was wrong. With a prior trade, the
same order reached the book's ``assert`` instead of a reject.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.balf_gwy.protocol import (
    RC_INVALID_FIELD,
    RC_TRAILING_STOP_NO_PRICE,
    classify_engine_reject,
)
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import connect, make_engine, msgs, order_payload


def _rejects(pub: Any) -> list[dict[str, Any]]:
    return [a for a in msgs(pub, "order.ack.GW01") if not a["accepted"]]


@pytest.mark.parametrize("offset", [-1.0, 0.0])
@pytest.mark.parametrize("traded", [False, True])
def test_a_non_positive_offset_is_an_invalid_value(
    monkeypatch: Any, tmp_path: Any, offset: float, traded: bool
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    if traded:
        engine._handle_new_order(order_payload(Side.SELL, OrderType.LIMIT, 5, "GW02", price=100.0))  # fmt: skip
        engine._handle_new_order(order_payload(Side.BUY, OrderType.LIMIT, 5, "GW03", price=100.0))  # fmt: skip

    engine._handle_new_order(
        order_payload(
            Side.SELL, OrderType.TRAILING_STOP, 10, "GW01", trail_offset=offset
        )
    )

    (reject,) = _rejects(pub)
    assert reject["reject_code"] == "INVALID_VALUE"
    assert "trail_offset" in reject["reason"]
    assert "prior trade price" not in reject["reason"]


def test_a_positive_offset_without_a_trade_still_asks_for_a_price(
    monkeypatch: Any, tmp_path: Any
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    engine._handle_new_order(
        order_payload(Side.SELL, OrderType.TRAILING_STOP, 10, "GW01", trail_offset=1.0)
    )
    (reject,) = _rejects(pub)
    assert reject["reject_code"] == "MISSING_FIELD"
    assert reject["reason"] == "Trailing stop requires STOP= or a prior trade price"


def test_balf_reports_the_offset_as_an_invalid_field(
    monkeypatch: Any, tmp_path: Any
) -> None:
    """The engine's reject as pm-balf-gwy classifies it (protocol.py)."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    engine._handle_new_order(
        order_payload(Side.SELL, OrderType.TRAILING_STOP, 10, "GW01", trail_offset=-1.0)
    )
    (reject,) = _rejects(pub)
    code = classify_engine_reject(reject["reject_code"], reject["reason"])
    assert code == RC_INVALID_FIELD
    assert code != RC_TRAILING_STOP_NO_PRICE
