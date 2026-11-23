"""WP-MOD01: the engine refuses an order or combo whose ticks or quantities
are not integers, and ``from_ticks`` takes ticks only.

A float tick count used to rest off the grid and print on ``trade.executed``
as a display price 10**tick_decimals too large (Models review 2026-11, H1).
Driven through the real engine with the payload a raw client would send.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.engine.persistence import load_gtc_orders, save_gtc_orders
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.order import TIF, Order, OrderType, Side
from edumatcher.models.price import (
    clear_tick_registry,
    from_ticks,
    register_tick_decimals,
)
from tests.engine_harness import SYMBOL, connect, make_engine, msgs, order_payload


def _new(engine: Any, payload: dict[str, Any]) -> None:
    engine._handle_new_order(payload)


def _refused(pub: Any, gw: str = "GW02") -> dict[str, Any]:
    acks = msgs(pub, f"order.ack.{gw}")
    assert acks, "no ack published"
    return acks[-1]


_STOP_LIMIT: dict[str, Any] = {"price": 99.00, "stop_price": 99.50}
_TRAILING: dict[str, Any] = {"trail_offset": 0.50, "stop_price": 98.50}
_ICEBERG: dict[str, Any] = {"price": 99.00, "visible_qty": 5}


@pytest.mark.parametrize(
    "field, value, order_type, extra",
    [
        ("price_ticks", 9900.5, OrderType.LIMIT, {}),
        ("price_ticks", 9900.0, OrderType.LIMIT, {}),
        ("stop_price_ticks", 9950.5, OrderType.STOP_LIMIT, _STOP_LIMIT),
        ("trail_offset_ticks", 50.5, OrderType.TRAILING_STOP, _TRAILING),
        ("visible_qty", 5.0, OrderType.ICEBERG, _ICEBERG),
        ("quantity", 10.5, OrderType.LIMIT, {}),
        ("quantity", True, OrderType.LIMIT, {}),
        ("quantity", "10", OrderType.LIMIT, {}),
        ("remaining_qty", 10.0, OrderType.LIMIT, {}),
        ("tick_decimals", 2.0, OrderType.LIMIT, {}),
    ],
)
def test_order_new_with_a_non_integer_field_is_refused(
    monkeypatch: Any,
    tmp_path: Path,
    field: str,
    value: Any,
    order_type: OrderType,
    extra: dict[str, Any],
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    kwargs = extra or {"price": 99.00}
    payload = order_payload(Side.BUY, order_type, 10, "GW02", **kwargs)
    payload[field] = value
    _new(engine, payload)
    ack = _refused(pub)
    assert ack["accepted"] is False
    assert ack["reject_code"] == "MALFORMED_MESSAGE"
    assert field in ack["reason"]
    assert list(engine._book(SYMBOL).resting_orders()) == []


def test_a_float_tick_never_prints(monkeypatch: Any, tmp_path: Path) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    bid = order_payload(Side.BUY, OrderType.LIMIT, 10, "GW02", price=99.00)
    bid["price_ticks"] = 9900.5
    _new(engine, bid)
    _new(engine, order_payload(Side.SELL, OrderType.LIMIT, 10, "GW01", price=99.00))
    assert msgs(pub, "trade.executed") == []


def test_an_integer_order_still_trades(monkeypatch: Any, tmp_path: Path) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    _new(engine, order_payload(Side.BUY, OrderType.LIMIT, 10, "GW02", price=99.00))
    _new(engine, order_payload(Side.SELL, OrderType.LIMIT, 10, "GW01", price=99.00))
    trades = msgs(pub, "trade.executed")
    assert [(t["price"], t["price_ticks"], t["quantity"]) for t in trades] == [
        (99.0, 9900, 10)
    ]


def _combo_payload() -> dict[str, Any]:
    combo = ComboOrder.create(
        "c1",
        "GW01",
        ComboType.AON,
        TIF.DAY,
        [
            ComboLeg("AAPL", Side.BUY, OrderType.LIMIT, 10, 2, 10000),
            ComboLeg("MSFT", Side.SELL, OrderType.LIMIT, 5, 2, 40000),
        ],
    )
    return combo.to_submission_dict()


@pytest.mark.parametrize(
    "leg, field, value",
    [
        (0, "price_ticks", 9900.5),
        (1, "quantity", 5.5),
        (1, "quantity", False),
        (1, "tick_decimals", 2.0),
    ],
)
def test_combo_with_a_non_integer_leg_field_is_refused(
    monkeypatch: Any, tmp_path: Path, leg: int, field: str, value: Any
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    payload = _combo_payload()
    payload["legs"][leg][field] = value
    engine._handle_combo_order(payload)
    acks = msgs(pub, "combo.ack.GW01")
    assert acks and acks[-1]["accepted"] is False
    assert field in acks[-1]["reason"]
    assert list(engine._book("AAPL").resting_orders()) == []
    assert list(engine._book("MSFT").resting_orders()) == []


def test_an_integer_combo_is_still_accepted(monkeypatch: Any, tmp_path: Path) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    engine._handle_combo_order(_combo_payload())
    assert msgs(pub, "combo.ack.GW01")[-1]["accepted"] is True


def test_from_ticks_takes_ticks_only() -> None:
    clear_tick_registry()
    register_tick_decimals("AAPL", 2)
    try:
        assert from_ticks(10000, "AAPL") == 100.0
        with pytest.raises(TypeError):
            from_ticks(100.0, "AAPL")  # type: ignore[arg-type]
    finally:
        clear_tick_registry()


def test_a_persisted_integer_order_restores_unchanged(tmp_path: Path) -> None:
    order = Order.create(
        "AAPL", Side.BUY, OrderType.LIMIT, 10, "GW01", TIF.GTC, price_ticks=9900
    )
    path = tmp_path / "gtc.json"
    save_gtc_orders([order], path)
    (restored,) = load_gtc_orders(path)
    assert restored.to_dict() == order.to_dict()


# --- Holistic review (HR1): engine-owned fields are not the client's to set ----


@pytest.mark.parametrize(
    "field, value",
    [
        ("status", "FILLED"),
        ("status", "CANCELLED"),
        ("status", "EXPIRED"),
        ("cum_notional_ticks", 5_000_000),
        ("quote_id", "Q-FAKE"),
        ("origin", "QUOTE"),
        ("is_seed", True),
        ("combo_parent_id", "C-FAKE"),
        ("leg_index", 1),
        ("oco_group_id", "G-FAKE"),
        ("arrival_seq", -5),
    ],
)
def test_order_new_cannot_set_engine_owned_state(
    monkeypatch: Any, tmp_path: Path, field: str, value: Any
) -> None:
    """``Order.from_dict`` decodes both a client's order.new and the engine's
    own persistence file, so it reads these; on order.new they are the
    engine's to set. An order sent as ``status: FILLED`` used to be acked and
    then vanish; a sent ``cum_notional_ticks`` became the fill's average."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    payload = order_payload(Side.BUY, OrderType.LIMIT, 10, "GW02", price=99.00)
    payload[field] = value
    _new(engine, payload)
    _new(engine, order_payload(Side.SELL, OrderType.LIMIT, 4, "GW01", price=99.00))

    (fill,) = msgs(pub, "order.fill.GW02")
    assert (fill["fill_qty"], fill["status"]) == (4, "PARTIAL")
    assert fill["cum_notional_ticks"] == 4 * 9900
    for group_field in ("quote_id", "combo_parent_id", "leg_index", "oco_group_id"):
        assert group_field not in fill
    (resting,) = engine._book(SYMBOL).resting_orders()
    assert resting.id == payload["id"]
    assert resting.origin.value == "ORDER"
    assert resting.is_seed is False
    assert resting.arrival_seq > 0
