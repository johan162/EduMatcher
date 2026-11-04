"""``order.ack`` and ``order.fill`` carry the engine's clock (A7).

Without it the only wall time on an acceptance or a fill is the audit
recorder's receipt time, which a dispute about "when did the exchange accept
this" cannot rest on.  The fill's time is its trade's: one clock read per
match, shared by the print and the fills that report it.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.message import decode
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import connect, make_engine, order_payload


def published(pub: Any, prefix: str) -> list[dict[str, Any]]:
    out = []
    for frames in pub.sent:
        topic, payload = decode(frames)
        if topic.startswith(prefix):
            out.append(payload)
    return out


@pytest.fixture
def engine_and_pub(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine, "GW01", "GW02")
    return engine, pub


def test_an_acceptance_carries_the_engine_clock(engine_and_pub: Any) -> None:
    engine, pub = engine_and_pub
    engine._handle_new_order(
        order_payload(Side.SELL, OrderType.LIMIT, 100, "GW01", price=10.0)
    )
    (ack,) = published(pub, "order.ack.GW01")
    assert ack["accepted"] is True
    assert isinstance(ack["ts_ns"], int) and ack["ts_ns"] > 0


def test_a_rejection_carries_it_too(engine_and_pub: Any) -> None:
    engine, pub = engine_and_pub
    engine._handle_new_order(
        order_payload(Side.SELL, OrderType.LIMIT, 100, "NOPE", price=10.0)
    )
    (ack,) = published(pub, "order.ack.NOPE")
    assert ack["accepted"] is False
    assert ack["ts_ns"] > 0


def test_a_fill_carries_its_trades_time_on_both_sides(engine_and_pub: Any) -> None:
    engine, pub = engine_and_pub
    engine._handle_new_order(
        order_payload(Side.SELL, OrderType.LIMIT, 100, "GW01", price=10.0)
    )
    engine._handle_new_order(
        order_payload(Side.BUY, OrderType.LIMIT, 100, "GW02", price=10.0)
    )
    (trade,) = published(pub, "trade.executed")
    maker = published(pub, "order.fill.GW01")
    taker = published(pub, "order.fill.GW02")
    assert [f["ts_ns"] for f in maker + taker] == [trade["ts_ns"]] * 2


def test_acks_are_strictly_ordered_by_the_clock(engine_and_pub: Any) -> None:
    engine, pub = engine_and_pub
    for price in (10.0, 10.1, 10.2):
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 10, "GW01", price=price)
        )
    stamps = [a["ts_ns"] for a in published(pub, "order.ack.GW01")]
    assert stamps == sorted(set(stamps))
