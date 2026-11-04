"""K18: cost assertions for the six hot paths (A3, C6, E3, I5, P7, S5).

These are *cost* tests, not behaviour tests — they count iterations, calls and
SQLite query plans rather than wall clock, so they are deterministic under
coverage and parallel execution. Each one fails on the pre-fix tree:

A3  ``compute_equilibrium`` rescans the price lists for every candidate price,
    so the comparison count is quadratic in the number of distinct levels.
C6  ``Ledger._remark_symbol`` walks *every* position and batch delta on every
    trade, not just the ones in the traded symbol.
E3  the stop cascade pops from the front of a ``list``, which is O(n) per pop.
I5  one trade recomputes the index aggregate cap three times, once of them
    only to build arguments for a ``log.debug`` that is switched off.
P7  a public trade is applied to every per-gateway cache, each of which writes
    the same last price.
S5  the rehydration query orders by ``quantity DESC`` with no usable index, so
    SQLite sorts the whole symbol-day into a temporary B-tree.

See ``docs-design/EduMatcher-Key-Component-Fixes-Workplan.md`` §5 K18.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, SupportsIndex

import pytest

from edumatcher.engine import auction
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderType, Side, TIF
from tests.support.counting import CallCounter, assert_query_plan_has_no_temp_btree

# ---------------------------------------------------------------------------
# A3 — equilibrium scan
# ---------------------------------------------------------------------------


class _CountingPrice(int):
    """A price tick that records every ordering comparison made against it."""

    comparisons = 0

    def __lt__(self, other: Any) -> bool:
        type(self).comparisons += 1
        return int.__lt__(self, other)

    def __gt__(self, other: Any) -> bool:
        type(self).comparisons += 1
        return int.__gt__(self, other)

    def __le__(self, other: Any) -> bool:
        type(self).comparisons += 1
        return int.__le__(self, other)

    def __ge__(self, other: Any) -> bool:
        type(self).comparisons += 1
        return int.__ge__(self, other)


def _crossed_book(levels: int) -> OrderBook:
    """A book with *levels* distinct prices on each side, fully crossed."""
    book = OrderBook("AAPL")
    for i in range(levels):
        for side, gw in ((Side.BUY, "TRADER01"), (Side.SELL, "TRADER02")):
            book.process(
                Order.create(
                    symbol="AAPL",
                    side=side,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    gateway_id=gw,
                    tif=TIF.DAY,
                    price_ticks=10_000 + i,
                ),
                match=False,
            )
    return book


def _equilibrium_comparisons(
    monkeypatch: pytest.MonkeyPatch, levels: int
) -> tuple[int, Any]:
    original = auction._auction_levels

    def _counted(book: OrderBook) -> tuple[dict[int, int], dict[int, int]]:
        bids, asks = original(book)
        return (
            {_CountingPrice(k): v for k, v in bids.items()},
            {_CountingPrice(k): v for k, v in asks.items()},
        )

    book = _crossed_book(levels)
    monkeypatch.setattr(auction, "_auction_levels", _counted)
    _CountingPrice.comparisons = 0
    result = auction.compute_equilibrium(book)
    monkeypatch.setattr(auction, "_auction_levels", original)
    return _CountingPrice.comparisons, result


def test_a3_equilibrium_scan_is_not_quadratic_in_price_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doubling the levels must not roughly quadruple the work.

    This runs per symbol on every indicative tick, so a deep book in an
    opening auction makes the whole engine loop late.
    """
    small, small_result = _equilibrium_comparisons(monkeypatch, 128)
    large, large_result = _equilibrium_comparisons(monkeypatch, 256)

    assert small > 0
    assert large / small < 3.0, (
        f"{small} -> {large} comparisons for 128 -> 256 price levels "
        "is quadratic growth"
    )
    # The cheaper scan must still pick the same price.
    assert small_result.eq_price == 10_063
    assert large_result.eq_price == 10_127


def test_a3_equilibrium_result_is_unchanged_on_an_uneven_book() -> None:
    """A guard for the rewrite: sizes differ per level and per side."""
    book = OrderBook("AAPL")
    for price, qty in ((10_005, 50), (10_003, 10), (10_001, 70)):
        book.process(
            Order.create(
                symbol="AAPL",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=qty,
                gateway_id="TRADER01",
                tif=TIF.DAY,
                price_ticks=price,
            ),
            match=False,
        )
    for price, qty in ((10_000, 20), (10_002, 30), (10_004, 90)):
        book.process(
            Order.create(
                symbol="AAPL",
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                quantity=qty,
                gateway_id="TRADER02",
                tif=TIF.DAY,
                price_ticks=price,
            ),
            match=False,
        )

    result = auction.compute_equilibrium(book)

    # 10_002 and 10_003 tie on (quantity, surplus); the lowest price wins.
    assert (result.eq_price, result.eq_qty, result.surplus) == (10_002, 50, 10)


# ---------------------------------------------------------------------------
# C6 — per-trade re-mark
# ---------------------------------------------------------------------------


class _CountingDict(dict[Any, Any]):
    """Counts how many entries a full ``items()`` walk visits."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.visited = 0

    def items(self) -> Any:
        for pair in super().items():
            self.visited += 1
            yield pair


def test_c6_remarking_a_symbol_does_not_walk_every_position() -> None:
    """One trade in one symbol must not cost O(all open positions)."""
    from edumatcher.clearing.ledger import Ledger

    ledger = Ledger()
    for i in range(400):
        ledger.apply_trade(
            symbol=f"SYM{i:03d}",
            buy_gateway_id=f"GW{i:03d}",
            sell_gateway_id=f"GX{i:03d}",
            price=10_000,
            quantity=10,
            ts_ns=1_700_000_000_000_000_000,
            ingest_ts_ns=1_700_000_000_000_000_000,
        )

    positions = _CountingDict(ledger._positions)
    deltas = _CountingDict(ledger._batch_deltas)
    ledger._positions = positions
    ledger._batch_deltas = deltas

    ledger.apply_trade(
        symbol="SYM000",
        buy_gateway_id="GW000",
        sell_gateway_id="GX000",
        price=10_100,
        quantity=5,
        ts_ns=1_700_000_000_000_000_000,
        ingest_ts_ns=1_700_000_000_000_000_000,
    )

    assert (
        positions.visited + deltas.visited < 50
    ), "the re-mark scanned the whole book to find one symbol's positions"


def test_c6_remarking_still_touches_every_holder_of_the_symbol() -> None:
    """The index must not lose a gateway that is not in this trade."""
    from edumatcher.clearing.ledger import Ledger

    ledger = Ledger()
    common = dict(
        ts_ns=1_700_000_000_000_000_000, ingest_ts_ns=1_700_000_000_000_000_000
    )
    ledger.apply_trade(
        symbol="AAPL",
        buy_gateway_id="GW1",
        sell_gateway_id="GW2",
        price=10_000,
        quantity=10,
        **common,
    )
    ledger.apply_trade(
        symbol="AAPL",
        buy_gateway_id="GW3",
        sell_gateway_id="GW4",
        price=10_500,
        quantity=10,
        **common,
    )

    # GW1 did not trade at 10_500 but must still be marked to it.
    position = ledger.position("GW1", "AAPL")
    assert position is not None and position.mark_price == 10_500


# ---------------------------------------------------------------------------
# E3 — stop cascade
# ---------------------------------------------------------------------------


class _NoFrontPop(list[Any]):
    """A list that refuses the O(n) ``pop(0)`` the cascade used to do."""

    def pop(self, index: SupportsIndex = -1) -> Any:
        assert (
            index.__index__() != 0
        ), "the stop cascade must pop from a deque, not a list front"
        return super().pop(index)

    def __add__(self, other: Any) -> "_NoFrontPop":
        return _NoFrontPop(list(self) + list(other))


def test_e3_stop_cascade_does_not_pop_from_the_front_of_a_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``list.pop(0)`` shifts the whole tail, making a wide cascade O(n²)."""
    book = OrderBook("AAPL")
    book.process(
        Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=1_000,
            gateway_id="TRADER02",
            tif=TIF.DAY,
            price_ticks=9_900,
        ),
        match=False,
    )
    stops = [
        Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=1,
            gateway_id="TRADER01",
            tif=TIF.DAY,
        )
        for _ in range(50)
    ]
    book._has_stops = True
    monkeypatch.setattr(OrderBook, "_check_stops", lambda self, now: _NoFrontPop(stops))
    monkeypatch.setattr(
        OrderBook, "_check_trailing_stops", lambda self, now: _NoFrontPop()
    )

    trades, _events = book.run_stops(now=0)

    assert len(trades) == 50


# ---------------------------------------------------------------------------
# I5 — index aggregate cap per trade
# ---------------------------------------------------------------------------


def _calc(constituents: int = 200) -> Any:
    from edumatcher.index.calculator import ConstituentConfig, IndexCalculator

    return IndexCalculator(
        constituents=[
            ConstituentConfig(
                symbol=f"S{i:03d}", shares_outstanding=1_000_000, initial_price=10.0
            )
            for i in range(constituents)
        ],
        base_value=1000.0,
    )


def test_i5_one_trade_recomputes_the_aggregate_cap_at_most_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full constituent scan per trade is fine; repeating it for a value
    that has not changed since the last scan is not."""
    calc = _calc()
    counter = CallCounter(calc._compute_cap)
    monkeypatch.setattr(calc, "_compute_cap", counter)

    calc.update_price("S000", 11.0)
    level = calc.recalculate()
    cap = calc.aggregate_cap()

    assert cap / calc.divisor == pytest.approx(level)
    assert counter.calls == 1, "the cap was rescanned for a value it already had"


def test_i5_the_cached_cap_is_invalidated_by_every_mutation() -> None:
    """Caching is only safe if nothing can change the inputs behind its back."""
    calc = _calc(constituents=3)
    before = calc.aggregate_cap()

    calc.update_price("S000", 20.0)
    assert calc.aggregate_cap() == pytest.approx(before + 10.0 * 1_000_000)

    calc.apply_split("S000", 2, 1)
    assert calc.aggregate_cap() == pytest.approx(before + 10.0 * 1_000_000)


def test_i5_the_per_trade_debug_line_is_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``log.debug("...", idx.calc.aggregate_cap())`` evaluates its arguments
    whether or not the record is ever emitted, so the scan happened on every
    trade in production, where DEBUG is off."""
    import edumatcher.index.main as index_main

    assert (
        "isEnabledFor" in index_main.IndexProcess._handle_trade.__code__.co_names
    ), "the per-trade aggregate_cap() in the debug line must be guarded"


# ---------------------------------------------------------------------------
# P7 — public trade fan-out into per-gateway caches
# ---------------------------------------------------------------------------


def test_p7_a_public_trade_is_not_applied_to_every_gateway_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last traded price is venue-wide; writing it into N identical
    per-session dicts is N-1 wasted writes on the busiest topic there is."""
    from edumatcher.api_gateway.caches import SessionCaches
    from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED

    client = _make_engine_client(monkeypatch)
    for i in range(50):
        client.get_caches(f"GW{i:02d}")

    applies = 0
    original = SessionCaches.apply

    def _counted(self: SessionCaches, topic: str, payload: dict[str, Any]) -> None:
        nonlocal applies
        applies += 1
        original(self, topic, payload)

    monkeypatch.setattr(SessionCaches, "apply", _counted)
    client._handle_event(TOPIC_TRADE_EXECUTED, {"symbol": "AAPL", "price": 101.5})

    assert applies <= 1, f"the trade was folded into {applies} caches"
    assert client.get_caches("GW00").last_prices["AAPL"] == 101.5
    assert client.get_caches("GW49").last_prices["AAPL"] == 101.5


def test_p7_a_gateway_created_later_still_sees_the_last_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED

    client = _make_engine_client(monkeypatch)
    client._handle_event(TOPIC_TRADE_EXECUTED, {"symbol": "AAPL", "price": 99.0})

    assert client.get_caches("LATE").last_prices["AAPL"] == 99.0


def _make_engine_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    import edumatcher.api_gateway.engine_client as ec

    monkeypatch.setattr(ec, "make_pusher", lambda *_a, **_k: _NullSocket())
    monkeypatch.setattr(ec, "make_subscriber", lambda *_a, **_k: _NullSocket())
    return ec.EngineClient(
        "inproc://k18-pull", "inproc://k18-pub", asyncio.new_event_loop()
    )


class _NullSocket:
    def send_multipart(self, frames: list[bytes]) -> None:
        pass

    def setsockopt(self, *_a: Any, **_k: Any) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# S5 — rehydration sort
# ---------------------------------------------------------------------------


def test_s5_largest_trade_rehydration_does_not_sort_into_a_temp_btree(
    tmp_path: Any,
) -> None:
    """``ORDER BY quantity DESC`` on a symbol-day has to be served from an
    index, or every pm-stats restart re-sorts the whole day per symbol."""
    import edumatcher.stats.main as stats_main

    conn = sqlite3.connect(tmp_path / "stats.db")
    conn.executescript(stats_main.SCHEMA)

    assert_query_plan_has_no_temp_btree(
        conn,
        "SELECT quantity, price FROM trade_log "
        "INDEXED BY idx_tl_symbol_qty "
        "WHERE symbol = ? AND ts >= ? AND ts < ? "
        "ORDER BY quantity DESC, ts ASC, rowid ASC LIMIT 1",
        ("AAPL", "2026-11-04T00:00:00Z", "2026-11-05T00:00:00Z"),
    )
    conn.close()
