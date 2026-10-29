"""What the book did beyond trades and order events (S24): order.triggered
to the stop's owner, engine.trace for the audit, risk.band at startup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.engine.collar import CollarConfig
from edumatcher.engine.config_loader import SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import (
    SYMBOL,
    FakeSock,
    all_msgs,
    connect,
    make_engine,
    msgs,
    order_payload,
)


def new(
    engine: Engine, side: Side, kind: OrderType, qty: int, gw: str, **kw: Any
) -> str:
    p = order_payload(side, kind, qty, gw, **kw)
    engine._dispatch_pull_message("order.new", p)
    return str(p["id"])


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Engine, FakeSock]:
    e, pub = make_engine(monkeypatch, tmp_path)
    connect(e)
    return e, pub


def traces(pub: FakeSock, kind: str) -> list[dict[str, Any]]:
    return [m for m in msgs(pub, f"engine.trace.{SYMBOL}") if m["kind"] == kind]


def test_a_resting_order_reports_its_place_after_its_ack(
    rig: tuple[Engine, FakeSock],
) -> None:
    e, pub = rig
    oid = new(e, Side.SELL, OrderType.LIMIT, 5, "GW01", price=100.00)
    topics = [t for t, p in all_msgs(pub) if p.get("order_id") == oid]
    assert topics == ["order.ack.GW01", f"engine.trace.{SYMBOL}"]
    (rested,) = traces(pub, "RESTED")
    assert rested["priority_seq"] == e.books[SYMBOL]._order_index[oid].arrival_seq


def test_an_amend_that_loses_priority_reports_the_new_place(
    rig: tuple[Engine, FakeSock],
) -> None:
    e, pub = rig
    oid = new(e, Side.SELL, OrderType.LIMIT, 5, "GW01", price=101.00)
    e._dispatch_pull_message("order.amend", {"order_id": oid, "gateway_id": "GW01", "price": 101.5})  # fmt: skip
    first, second = traces(pub, "RESTED")
    assert second["priority_seq"] > first["priority_seq"]
    assert second["priority_seq"] == msgs(pub, "order.amended.GW01")[0]["priority_seq"]


def test_an_iceberg_refill_reports_its_slice_and_new_place(
    rig: tuple[Engine, FakeSock],
) -> None:
    e, pub = rig
    ice = new(e, Side.SELL, OrderType.ICEBERG, 100, "GW01", price=100.00, visible_qty=10)  # fmt: skip
    new(e, Side.BUY, OrderType.LIMIT, 10, "GW02", price=100.00)
    (refill,) = traces(pub, "ICEBERG_REFILL")
    assert (refill["order_id"], refill["displayed_qty"]) == (ice, 10)
    assert refill["priority_seq"] == e.books[SYMBOL]._order_index[ice].arrival_seq


def test_a_trailing_stop_reports_each_ratchet(rig: tuple[Engine, FakeSock]) -> None:
    e, pub = rig
    new(e, Side.SELL, OrderType.LIMIT, 1, "GW01", price=100.00)
    new(e, Side.BUY, OrderType.LIMIT, 1, "GW02", price=100.00)  # last 100.00
    trail = new(e, Side.SELL, OrderType.TRAILING_STOP, 5, "GW03", stop_price=99.00, trail_offset=0.50)  # fmt: skip
    new(e, Side.SELL, OrderType.LIMIT, 1, "GW01", price=100.20)
    new(e, Side.BUY, OrderType.LIMIT, 1, "GW02", price=100.20)  # last 100.20
    ratchets = [r for r in traces(pub, "TRAILING_RATCHET") if r["order_id"] == trail]
    assert (ratchets[-1]["stop_price_ticks"], ratchets[-1]["last_price_ticks"]) == (9_970, 10_020)  # fmt: skip
    assert e.books[SYMBOL]._order_index[trail].stop_price_ticks == 9_970


@pytest.mark.parametrize(
    "kind, extra, becomes",
    [
        (OrderType.STOP, {}, "MARKET"),
        (OrderType.STOP_LIMIT, {"price": 100.50}, "LIMIT"),
    ],
)
def test_a_fired_stop_tells_its_owner_before_it_trades(
    rig: tuple[Engine, FakeSock], kind: OrderType, extra: dict[str, Any], becomes: str
) -> None:
    e, pub = rig
    new(e, Side.SELL, OrderType.LIMIT, 20, "GW01", price=100.00)
    stop = new(e, Side.BUY, kind, 5, "GW02", stop_price=100.00, **extra)
    new(e, Side.BUY, OrderType.LIMIT, 5, "GW03", price=100.00)  # the trigger
    first = msgs(pub, "trade.executed")[0]
    (fired,) = msgs(pub, "order.triggered.GW02")
    fired.pop("client_tag", None)
    assert fired == {
        "order_id": stop, "symbol": SYMBOL, "order_type": kind.value,
        "stop_price_ticks": 10_000, "trigger_trade_id": first["id"],
        "trigger_price_ticks": 10_000, "becomes": becomes,
    }  # fmt: skip
    topics = [t for t, p in all_msgs(pub) if p.get("order_id") == stop]
    assert topics.index("order.triggered.GW02") < topics.index("order.fill.GW02")


def test_a_stop_breached_on_entry_names_the_last_trade(
    rig: tuple[Engine, FakeSock],
) -> None:
    e, pub = rig
    new(e, Side.SELL, OrderType.LIMIT, 20, "GW01", price=100.00)
    new(e, Side.BUY, OrderType.LIMIT, 1, "GW03", price=100.00)
    stop = new(e, Side.BUY, OrderType.STOP, 5, "GW02", stop_price=99.00)
    (fired,) = msgs(pub, "order.triggered.GW02")
    assert fired["order_id"] == stop
    assert fired["trigger_trade_id"] == msgs(pub, "trade.executed")[0]["id"]


def test_a_collared_symbol_announces_its_band_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = SymbolConfig(name=SYMBOL, last_buy_price=100.0, collar=CollarConfig(symbol=SYMBOL))  # fmt: skip
    e, pub = make_engine(monkeypatch, tmp_path, symbol_configs={SYMBOL: cfg})
    e._startup(1)
    (band,) = msgs(pub, f"risk.band.{SYMBOL}")
    assert band == {
        "symbol": SYMBOL, "kind": "COLLAR", "reference_price_ticks": 10_000,
        "static_low_ticks": 8_000, "static_high_ticks": 12_000, "dynamic_band_pct": 0.02,
    }  # fmt: skip
