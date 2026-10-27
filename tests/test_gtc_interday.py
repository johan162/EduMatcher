"""Long (TIF=GTC) orders across the close and across an engine restart.

The simulation's AI traders now leave a few GTC orders behind each day, so the
engine's hand-over from one day to the next is exercised for real: the close
expires the DAY orders, the shutdown writes what is left to ``gtc_orders.json``,
and the next engine reads it back and keeps matching against it. These tests
drive that whole path through the engine's real handlers and real files, and
pin the per-book GTC count the operator dashboard shows in its "Long" column.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from edumatcher.engine import main as _engine_main
from edumatcher.engine.order_book import OrderBook
from edumatcher.engine.persistence import load_gtc_orders, save_gtc_orders
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.price import to_ticks

from .engine_harness import SYMBOL, connect, make_engine, msgs, order_payload

em: Any = _engine_main

_DAY_NS = 86_400 * 1_000_000_000


def _submit(engine: Any, gw: str, side: Side, qty: int, price: float, tif: TIF) -> None:
    engine._dispatch_pull_message(
        em.TOPIC_ORDER_NEW,
        order_payload(side, OrderType.LIMIT, qty, gw, price, tif=tif),
    )


def _recount(book: OrderBook) -> int:
    return sum(1 for o in book._order_index.values() if o.tif == TIF.GTC)


def _files(tmp_path: Path) -> tuple[Any, ...]:
    return (
        patch("edumatcher.engine.main.GTC_ORDERS_FILE", tmp_path / "gtc_orders.json"),
        patch("edumatcher.engine.main.GTC_COMBOS_FILE", tmp_path / "gtc_combos.json"),
        patch("edumatcher.engine.main.BOOK_STATS_FILE", tmp_path / "book_stats.json"),
    )


class TestGtcCount:
    def test_follows_rest_fill_cancel_and_trigger(self, monkeypatch, tmp_path) -> None:
        engine, _ = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01", "GW02")
        book = engine._book(SYMBOL)

        def check(expected: int) -> None:
            assert book.book_stats().gtc_orders == expected == _recount(book)

        check(0)
        _submit(engine, "GW01", Side.BUY, 100, 99.0, TIF.GTC)
        _submit(engine, "GW01", Side.BUY, 50, 98.0, TIF.DAY)
        _submit(engine, "GW02", Side.SELL, 40, 105.0, TIF.GTC)
        check(2)
        assert book.book_stats().resting_orders == 3

        # A stop held back by the engine is a long order too.
        engine._dispatch_pull_message(
            em.TOPIC_ORDER_NEW,
            order_payload(
                Side.SELL,
                OrderType.STOP,
                10,
                "GW02",
                stop_price=90.0,
                tif=TIF.GTC,
            ),
        )
        check(3)

        # A partial fill leaves the order resting, and still long.
        _submit(engine, "GW02", Side.SELL, 30, 99.0, TIF.DAY)
        check(3)
        # The fill that exhausts it takes it out.
        _submit(engine, "GW02", Side.SELL, 70, 99.0, TIF.DAY)
        check(2)

        gtc_ask = next(o for o in book.resting_orders() if o.side == Side.SELL)
        assert book.cancel_order(gtc_ask.id) is not None
        check(1)

    def test_the_close_expires_day_orders_and_keeps_long_ones(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, _ = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        book = engine._book(SYMBOL)
        _submit(engine, "GW01", Side.BUY, 100, 99.0, TIF.GTC)
        _submit(engine, "GW01", Side.BUY, 100, 98.0, TIF.DAY)
        engine._expire_tif(TIF.DAY)
        stats = book.book_stats()
        assert (stats.resting_orders, stats.gtc_orders) == (1, 1)


class TestRestartReadsLongOrders:
    def test_old_gtc_orders_come_back_and_still_trade(
        self, monkeypatch, tmp_path
    ) -> None:
        engine1, _ = make_engine(monkeypatch, tmp_path)
        connect(engine1, "GW01", "GW02")
        book1 = engine1._book(SYMBOL)
        _submit(engine1, "GW01", Side.BUY, 100, 99.0, TIF.GTC)
        _submit(engine1, "GW02", Side.SELL, 40, 105.0, TIF.GTC)
        _submit(engine1, "GW01", Side.BUY, 50, 98.0, TIF.DAY)
        _submit(engine1, "GW02", Side.SELL, 30, 99.0, TIF.DAY)  # hits the GTC bid
        engine1._expire_tif(TIF.DAY)  # the close
        saved = {o.id: o for o in book1.resting_orders()}
        assert len(saved) == 2 and all(o.tif == TIF.GTC for o in saved.values())

        f1, f2, f3 = _files(tmp_path)
        with f1, f2, f3:
            engine1._shutdown()

            # Three days pass; a DAY order left from back then is stale.
            path = tmp_path / "gtc_orders.json"
            persisted = load_gtc_orders(path)
            assert {o.id for o in persisted} == set(saved)
            for o in persisted:
                o.ts_ns -= 3 * _DAY_NS
            stale = Order.create(
                symbol=SYMBOL,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=10,
                gateway_id="GW01",
                tif=TIF.DAY,
                price_ticks=to_ticks(97.0, SYMBOL),
            )
            stale.ts_ns -= 3 * _DAY_NS
            save_gtc_orders([*persisted, stale], path)

            loaded = load_gtc_orders(path)
        assert len(loaded) == 3

        engine2, pub2 = make_engine(monkeypatch, tmp_path, gtc_orders=loaded, run_seq=2)
        engine2._restore_gtc()
        engine2._load_config()
        connect(engine2, "GW01", "GW02")
        book2 = engine2._book(SYMBOL)

        restored = {o.id: o for o in book2.resting_orders()}
        assert set(restored) == set(saved), "GTC back, the stale DAY order gone"
        for oid, before in saved.items():
            after = restored[oid]
            assert (after.side, after.price_ticks, after.tif) == (
                before.side,
                before.price_ticks,
                TIF.GTC,
            )
            assert after.remaining_qty == before.remaining_qty
        assert book2.book_stats().gtc_orders == 2 == _recount(book2)

        # The restored bid (70 left of 100) is a live counterparty.
        _submit(engine2, "GW02", Side.SELL, 70, 99.0, TIF.DAY)
        trades = msgs(pub2, "trade.executed")
        assert [t["quantity"] for t in trades] == [70]
        assert book2.book_stats().gtc_orders == 1 == _recount(book2)
