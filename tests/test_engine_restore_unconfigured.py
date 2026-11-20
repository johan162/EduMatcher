"""A restart restores only what the deployed configuration still allows.

The engine restores the same day's resting orders at start, also after a
new configuration was deployed. A seed quote is the configuration's own
order, though: switching from ``s10-basic`` to ``s3-basic-nomm`` (which
declares no seeds) brought MM01's ``s10-basic`` seeds back into the
``s3-basic-nomm`` books, and a beginner's first buy traded against them
(Quick Start review 2026-11). Now a restored seed quote whose market maker
and symbol have no seed in the configuration is discarded, as are orders
of a participant or symbol that is no longer configured. Each discard is a
``DISCARDED_UNCONFIGURED`` recovery item and counts in
``discarded_unconfigured_orders``; ordinary orders, GTC included, survive a
redeploy as before.
"""

from __future__ import annotations

from typing import Any

from edumatcher.engine.config_loader import MMQuoteSeed, SymbolConfig
from edumatcher.models.order import Order, OrderOrigin, OrderType, Side, TIF

from .engine_harness import make_engine, msgs, resting_ids

MM = "MM01"
SYM = "AAPL"


def _seed_leg(side: Side, price_ticks: int, gateway_id: str = MM) -> Order:
    order = Order.create(
        symbol=SYM,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=1000,
        gateway_id=gateway_id,
        tif=TIF.DAY,
        price_ticks=price_ticks,
        is_seed=True,
    )
    order.origin = OrderOrigin.QUOTE
    order.quote_id = f"SEED-{gateway_id}-{SYM}-1"
    return order


def _plain(gateway_id: str, symbol: str = SYM, tif: TIF = TIF.GTC) -> Order:
    return Order.create(
        symbol=symbol,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        gateway_id=gateway_id,
        tif=tif,
        price_ticks=9000,
    )


def _start(monkeypatch: Any, tmp_path: Any, orders: list[Order], **kw: Any):
    kw.setdefault("gateways", ("GW01", MM))
    kw.setdefault("mm_gateways", (MM,))
    engine, pub = make_engine(monkeypatch, tmp_path, gtc_orders=orders, **kw)
    engine._restore_gtc()
    engine._load_config()
    return engine, pub


def _outcomes(pub: Any) -> dict[str, str]:
    return {m["entity_id"]: m["outcome"] for m in msgs(pub, "system.recovery_item")}


def _summary(pub: Any) -> dict[str, Any]:
    (summary,) = msgs(pub, "system.startup_recovery")
    return summary


def test_a_seed_the_configuration_no_longer_declares_is_discarded(
    monkeypatch, tmp_path
) -> None:
    bid, ask = _seed_leg(Side.BUY, 2288), _seed_leg(Side.SELL, 2298)
    engine, pub = _start(monkeypatch, tmp_path, [bid, ask])

    assert resting_ids(engine.books[SYM]) == set()
    assert engine._quote_index.get(MM, SYM) is None
    assert _outcomes(pub) == {
        bid.id: "DISCARDED_UNCONFIGURED",
        ask.id: "DISCARDED_UNCONFIGURED",
    }
    assert _summary(pub)["discarded_unconfigured_orders"] == 2
    assert _summary(pub)["restored_orders"] == 0


def test_a_seed_the_configuration_still_declares_is_restored(
    monkeypatch, tmp_path
) -> None:
    bid, ask = _seed_leg(Side.BUY, 2288), _seed_leg(Side.SELL, 2298)
    symbol_configs = {
        SYM: SymbolConfig(
            name=SYM,
            market_maker_quotes=[
                MMQuoteSeed(
                    gateway_id=MM,
                    bid_price_ticks=2288,
                    ask_price_ticks=2298,
                    bid_qty=1000,
                    ask_qty=1000,
                    seed_once=True,
                )
            ],
        )
    }
    engine, pub = _start(
        monkeypatch, tmp_path, [bid, ask], symbol_configs=symbol_configs
    )

    assert resting_ids(engine.books[SYM]) == {bid.id, ask.id}
    assert _summary(pub)["discarded_unconfigured_orders"] == 0


def test_a_market_makers_own_quote_is_not_a_seed_and_survives(
    monkeypatch, tmp_path
) -> None:
    """Only the configuration's seeds belong to it: a quote the market maker
    (or its bot) sent itself is restored under any configuration."""
    bid, ask = _seed_leg(Side.BUY, 2288), _seed_leg(Side.SELL, 2298)
    bid.is_seed = ask.is_seed = False
    engine, pub = _start(monkeypatch, tmp_path, [bid, ask])

    assert resting_ids(engine.books[SYM]) == {bid.id, ask.id}
    assert _summary(pub)["discarded_unconfigured_orders"] == 0


def test_orders_of_an_unconfigured_participant_are_discarded(
    monkeypatch, tmp_path
) -> None:
    kept, gone = _plain("GW01"), _plain("GONE01")
    engine, pub = _start(monkeypatch, tmp_path, [kept, gone])

    assert resting_ids(engine.books[SYM]) == {kept.id}
    assert _outcomes(pub) == {kept.id: "RESTORED", gone.id: "DISCARDED_UNCONFIGURED"}
    assert _summary(pub)["discarded_unconfigured_orders"] == 1


def test_orders_for_an_unconfigured_symbol_are_reported(monkeypatch, tmp_path) -> None:
    """They were already skipped, but only in the process log."""
    gone = _plain("GW01", symbol="GONE")
    _engine, pub = _start(monkeypatch, tmp_path, [gone])

    assert _outcomes(pub) == {gone.id: "DISCARDED_UNCONFIGURED"}
    assert _summary(pub)["discarded_unconfigured_orders"] == 1
