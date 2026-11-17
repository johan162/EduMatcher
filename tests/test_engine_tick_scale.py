"""The engine refuses a price at the wrong tick scale (For-Later L032, WP-FL01).

Every engine-inbound message that carries tick prices also carries the
``tick_decimals`` its sender converted with. A sender with a wrong tick
registry (pm-mm-bot after its symbols reply timed out falls back to 2
decimals) produces prices 10^n away from the intended ones. The engine knows
each symbol's scale, so it refuses a mismatch instead of resting the price.
"""

from __future__ import annotations

from typing import Any

from edumatcher.engine.config_loader import SymbolConfig
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.order import TIF, OrderType, Side
from edumatcher.models.price import register_tick_decimals
from tests.engine_harness import connect, last_ack, make_engine, msgs, order_payload

TWO = "TSA"  # 2 decimals: 150.00 == 15000 ticks
THREE = "TSB"  # 3 decimals: 150.000 == 150000 ticks
MM = "GW03"


def setup(monkeypatch: Any, tmp_path: Any) -> Any:
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        mm_gateways=(MM,),
        symbol_configs={
            TWO: SymbolConfig(name=TWO, tick_decimals=2),
            THREE: SymbolConfig(name=THREE, tick_decimals=3),
        },
    )
    connect(engine)
    # Engine.run() registers the configured scales; the harness does not run.
    register_tick_decimals(TWO, 2)
    register_tick_decimals(THREE, 3)
    return engine, pub


def quote(engine: Any, symbol: str, tick_decimals: int, bid: int, ask: int) -> None:
    engine._handle_quote_new(
        {
            "gateway_id": MM,
            "symbol": symbol,
            "quote_id": "Q1",
            "tick_decimals": tick_decimals,
            "bid_price_ticks": bid,
            "ask_price_ticks": ask,
            "bid_qty": 100,
            "ask_qty": 100,
            "tif": "DAY",
        }
    )


def resting(engine: Any, symbol: str) -> list[Any]:
    book = engine.books.get(symbol)
    return [] if book is None else list(book.resting_orders())


# -- quote.new ---------------------------------------------------------------


def test_a_quote_at_a_finer_scale_is_refused_naming_both_scales(
    monkeypatch, tmp_path
) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    quote(engine, TWO, 4, 1_499_000, 1_501_000)  # 149.90/150.10 at 4 decimals
    (ack,) = msgs(pub, f"quote.ack.{MM}")
    assert ack["accepted"] is False
    assert "tick_decimals 4" in ack["reason"] and f"{TWO}'s 2" in ack["reason"]
    assert resting(engine, TWO) == []


def test_a_quote_at_a_coarser_scale_is_refused(monkeypatch, tmp_path) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    quote(engine, TWO, 0, 149, 151)
    (ack,) = msgs(pub, f"quote.ack.{MM}")
    assert ack["accepted"] is False
    assert resting(engine, TWO) == []


def test_a_quote_at_the_symbols_scale_is_accepted(monkeypatch, tmp_path) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    quote(engine, THREE, 3, 149_900, 150_100)
    (ack,) = msgs(pub, f"quote.ack.{MM}")
    assert ack["accepted"] is True
    assert sorted(o.price_ticks for o in resting(engine, THREE)) == [149_900, 150_100]


# -- order.new ---------------------------------------------------------------


def test_a_limit_order_at_the_wrong_scale_is_refused_as_invalid_value(
    monkeypatch, tmp_path
) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    payload = order_payload(Side.BUY, OrderType.LIMIT, 10, "GW01", price=150.0, symbol=THREE)  # fmt: skip
    payload["tick_decimals"] = 2
    payload["price_ticks"] = 15_000
    engine._handle_new_order(payload)
    _, ack = last_ack(pub.sent)
    assert ack["accepted"] is False
    assert ack["reject_code"] == "INVALID_VALUE"
    assert "tick_decimals 2" in ack["reason"] and f"{THREE}'s 3" in ack["reason"]
    assert resting(engine, THREE) == []


def test_a_limit_order_at_the_symbols_scale_is_accepted(monkeypatch, tmp_path) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    payload = order_payload(Side.BUY, OrderType.LIMIT, 10, "GW01", price=150.0, symbol=THREE)  # fmt: skip
    engine._handle_new_order(payload)
    _, ack = last_ack(pub.sent)
    assert ack["accepted"] is True
    assert [o.price_ticks for o in resting(engine, THREE)] == [150_000]


def test_a_market_order_carries_no_price_and_is_not_checked(
    monkeypatch, tmp_path
) -> None:
    """Nothing in a MARKET order is scaled, so a mismatch harms nothing."""
    engine, pub = setup(monkeypatch, tmp_path)
    payload = order_payload(Side.BUY, OrderType.MARKET, 10, "GW01", symbol=THREE)
    payload["tick_decimals"] = 2
    engine._handle_new_order(payload)
    _, ack = last_ack(pub.sent)
    assert ack.get("reject_code") != "INVALID_VALUE"


# -- order.oco ---------------------------------------------------------------


def oco(engine: Any, tick_decimals: int) -> None:
    engine._handle_oco_order(
        {
            "oco_id": "O1",
            "gateway_id": "GW01",
            "symbol": THREE,
            "tick_decimals": tick_decimals,
            "quantity": 10,
            "tif": "DAY",
            "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 160_000},
            "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 140_000},
        }
    )


def test_an_oco_at_the_wrong_scale_is_refused(monkeypatch, tmp_path) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    oco(engine, 2)
    (ack,) = msgs(pub, "oco.ack.GW01")
    assert ack["accepted"] is False
    assert "tick_decimals 2" in ack["reason"] and f"{THREE}'s 3" in ack["reason"]
    assert resting(engine, THREE) == []


def test_an_oco_at_the_symbols_scale_is_accepted(monkeypatch, tmp_path) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    oco(engine, 3)
    (ack,) = msgs(pub, "oco.ack.GW01")
    assert ack["accepted"] is True


# -- order.combo -------------------------------------------------------------


def combo(engine: Any, leg1_decimals: int) -> None:
    c = ComboOrder.create(
        combo_id="C1",
        gateway_id="GW01",
        combo_type=ComboType.AON,
        tif=TIF.DAY,
        legs=[
            ComboLeg(TWO, Side.BUY, OrderType.LIMIT, 10, tick_decimals=2, price_ticks=15_000),  # fmt: skip
            ComboLeg(THREE, Side.SELL, OrderType.LIMIT, 10, tick_decimals=leg1_decimals, price_ticks=160_000),  # fmt: skip
        ],
    )
    engine._handle_combo_order(c.to_submission_dict())


def test_a_combo_with_a_leg_at_the_wrong_scale_is_refused(
    monkeypatch, tmp_path
) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    combo(engine, 2)
    (ack,) = msgs(pub, "combo.ack.GW01")
    assert ack["accepted"] is False
    assert ack["reason"].startswith("Leg 1: ")
    assert "tick_decimals 2" in ack["reason"] and f"{THREE}'s 3" in ack["reason"]
    assert resting(engine, TWO) == [] and resting(engine, THREE) == []


def test_a_combo_at_the_legs_scales_is_accepted(monkeypatch, tmp_path) -> None:
    engine, pub = setup(monkeypatch, tmp_path)
    combo(engine, 3)
    (ack,) = msgs(pub, "combo.ack.GW01")
    assert ack["accepted"] is True
