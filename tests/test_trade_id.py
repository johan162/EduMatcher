from __future__ import annotations

import re

import pytest

from edumatcher.models.trade import Trade, reset_trade_ids_for_tests, set_run_seq


def _make_trade() -> Trade:
    return Trade.create(
        symbol="AAPL",
        buy_order_id="B1",
        sell_order_id="S1",
        buy_gateway_id="GW01",
        sell_gateway_id="GW02",
        price=15000,
        quantity=100,
        aggressor_side="BUY",
    )


def test_trade_create_requires_run_seq() -> None:
    reset_trade_ids_for_tests()
    with pytest.raises(RuntimeError, match="set_run_seq"):
        _make_trade()


def test_set_run_seq_only_once() -> None:
    reset_trade_ids_for_tests()
    set_run_seq(42)
    with pytest.raises(RuntimeError, match="already set"):
        set_run_seq(43)


def test_trade_id_format_and_run_seq() -> None:
    reset_trade_ids_for_tests()
    set_run_seq(42)

    first = _make_trade()
    second = _make_trade()

    assert first.id == "000042-000000001"
    assert second.id == "000042-000000002"
    assert first.run_seq == 42
    assert re.fullmatch(r"\d{6}-\d{9}", first.id)


def test_lexicographic_sort_matches_chronological_order() -> None:
    reset_trade_ids_for_tests()
    set_run_seq(2)
    run_two = [_make_trade().id for _ in range(3)]
    reset_trade_ids_for_tests()
    set_run_seq(3)
    run_three = [_make_trade().id for _ in range(2)]

    chronological = [*run_two, *run_three]
    assert sorted(chronological) == chronological


def test_from_dict_reads_old_payload_without_run_seq() -> None:
    restored = Trade.from_dict(
        {
            "id": "000001-000000001",
            "symbol": "AAPL",
            "buy_order_id": "B1",
            "sell_order_id": "S1",
            "buy_gateway_id": "GW01",
            "sell_gateway_id": "GW02",
            "price": 15000,
            "quantity": 100,
            "aggressor_side": "BUY",
            "timestamp": 1,
        }
    )
    assert restored.run_seq is None
