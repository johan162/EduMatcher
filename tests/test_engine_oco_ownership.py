"""An OCO pair belongs to the gateway that submitted it.

``oco_id`` is chosen by the client, so it is unique only within one gateway.
The engine used to key its pairs by ``oco_id`` alone, which made two defects
(found in WP-API17, review section 9.13):

* any gateway could cancel another's pair by naming its id -- the cancel had
  no owner check;
* two gateways using the same id collided: one pair overwrote the other, and a
  leg ending could cancel the *other* gateway's sibling. A gateway reusing its
  own live id did the same to itself.

Pairs are now keyed by ``(gateway_id, oco_id)``, and a submit reusing a live
key is refused. These tests pin that by behaviour, not by internals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.models.order import OrderType, Side
from tests.engine_harness import SYMBOL, connect, make_engine, msgs, resting_ids
from tests.test_engine_restart_contract import new, restart


def _oco(engine: Any, gw: str, oco_id: str, limit_ticks: int = 10100) -> None:
    engine._handle_oco_order(
        {"oco_id": oco_id, "gateway_id": gw, "symbol": SYMBOL, "quantity": 5,
         "tif": "DAY", "tick_decimals": 2,
         "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": limit_ticks},
         "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9900}}
    )  # fmt: skip


def _legs(pub: Any, gw: str, oco_id: str) -> tuple[str, str]:
    (ack,) = [
        a for a in msgs(pub, f"oco.ack.{gw}") if a["oco_id"] == oco_id and a["accepted"]
    ]
    return ack["order_id_1"], ack["order_id_2"]


def _live(engine: Any) -> set[str]:
    """Every live order on the book, resting limits and waiting stops alike."""
    return resting_ids(engine.books[SYMBOL])


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, Any]:
    eng, pub = make_engine(monkeypatch, tmp_path)
    connect(eng)
    return eng, pub


def test_another_gateway_cannot_cancel_a_pair(engine: tuple[Any, Any]) -> None:
    eng, pub = engine
    _oco(eng, "GW01", "X")
    legs = _legs(pub, "GW01", "X")
    eng._handle_oco_cancel({"oco_id": "X", "gateway_id": "GW02"})
    (ack,) = msgs(pub, "oco.cancel_ack.GW02")
    # Refused as unknown, so the reply does not reveal that GW01 has an "X".
    assert (ack["accepted"], ack["reject_code"]) == (False, "ORDER_NOT_FOUND")
    assert set(legs) <= _live(eng)
    assert msgs(pub, "order.cancelled.GW01") == []


def test_two_gateways_may_use_the_same_id(engine: tuple[Any, Any]) -> None:
    eng, pub = engine
    _oco(eng, "GW01", "X")
    _oco(eng, "GW02", "X")
    gw1, gw2 = _legs(pub, "GW01", "X"), _legs(pub, "GW02", "X")
    eng._handle_oco_cancel({"oco_id": "X", "gateway_id": "GW01"})
    (ack,) = msgs(pub, "oco.cancel_ack.GW01")
    assert sorted(ack["cancelled_order_ids"]) == sorted(gw1)
    assert set(gw2) <= _live(eng) and not set(gw1) & _live(eng)


def test_a_fill_pulls_only_its_own_pairs_sibling(engine: tuple[Any, Any]) -> None:
    eng, pub = engine
    _oco(eng, "GW01", "X", limit_ticks=10100)
    _oco(eng, "GW02", "X", limit_ticks=10050)  # the better offer fills first
    gw1, gw2 = _legs(pub, "GW01", "X"), _legs(pub, "GW02", "X")
    new(eng, Side.BUY, OrderType.LIMIT, 5, "GW03", price=100.50)
    (sibling,) = msgs(pub, "oco.cancelled.GW02")
    assert sibling["cancelled_order_id"] == gw2[1]
    assert msgs(pub, "oco.cancelled.GW01") == []
    assert set(gw1) <= _live(eng)


def test_reusing_a_live_id_is_refused(engine: tuple[Any, Any]) -> None:
    eng, pub = engine
    _oco(eng, "GW01", "X")
    first = _legs(pub, "GW01", "X")
    _oco(eng, "GW01", "X", limit_ticks=10200)
    refused = [a for a in msgs(pub, "oco.ack.GW01") if not a["accepted"]]
    assert len(refused) == 1 and "already" in refused[0]["reason"]
    # The first pair is intact and still linked.
    eng._handle_oco_cancel({"oco_id": "X", "gateway_id": "GW01"})
    (ack,) = msgs(pub, "oco.cancel_ack.GW01")
    assert sorted(ack["cancelled_order_ids"]) == sorted(first)


def test_an_id_is_free_again_once_its_pair_is_done(engine: tuple[Any, Any]) -> None:
    eng, pub = engine
    _oco(eng, "GW01", "X")
    eng._handle_oco_cancel({"oco_id": "X", "gateway_id": "GW01"})
    _oco(eng, "GW01", "X")
    assert [a["accepted"] for a in msgs(pub, "oco.ack.GW01")] == [True, True]


def test_a_restart_keeps_same_id_pairs_apart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, apub = make_engine(monkeypatch, tmp_path)
    connect(a)
    _oco(a, "GW01", "X", limit_ticks=10100)
    _oco(a, "GW02", "X", limit_ticks=10050)
    gw2 = _legs(apub, "GW02", "X")
    b, pub = restart(monkeypatch, tmp_path, a)
    new(b, Side.BUY, OrderType.LIMIT, 5, "GW03", price=100.50)
    (sibling,) = msgs(pub, "oco.cancelled.GW02")
    assert sibling["cancelled_order_id"] == gw2[1]
    assert msgs(pub, "oco.cancelled.GW01") == []


def test_a_fok_counts_each_gateways_pair_separately(engine: tuple[Any, Any]) -> None:
    """The FOK liquidity check counts one leg per pair (only the first leg
    met can trade); two gateways' pairs with the same id are two pairs."""
    eng, pub = engine
    _oco(eng, "GW01", "X", limit_ticks=10000)
    _oco(eng, "GW02", "X", limit_ticks=10000)
    new(eng, Side.BUY, OrderType.FOK, 10, "GW03", price=100.00)
    fills = msgs(pub, "order.fill.GW03")
    assert sum(f["fill_qty"] for f in fills) == 10
