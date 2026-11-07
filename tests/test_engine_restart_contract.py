"""A restart gives back what the checkpoint holds, as it was (S20b).

Each test runs engine A, restarts from A's own checkpoint -- its resting
orders through ``Order.to_dict``/``from_dict`` and its book statistics
through ``save_book_stats``/``load_book_stats``, as the files carry them --
into engine B, and compares. Findings X23-X26 of the simulation forensics
(check E6, docs-design/EduMatcher-Sim-Forensics-Workplan.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import edumatcher.engine.main as engine_main
from edumatcher.engine.circuit_breaker import CircuitBreakerConfig, CircuitBreakerLevel
from edumatcher.engine.config_loader import SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.engine.order_book import _DEAD_STATUSES, OrderBook
from edumatcher.engine import persistence
from edumatcher.engine.persistence import load_book_stats, save_book_stats
from edumatcher.models.clock import now_ns
from edumatcher.models.order import Order, OrderType, Side
from tests.engine_harness import (
    SYMBOL,
    FakeSock,
    connect,
    make_engine,
    msgs,
    order_payload,
)


def restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, a: Engine, **kw: Any
) -> tuple[Engine, FakeSock]:
    orders = [Order.from_dict(o.to_dict()) for o in a._resting_gtc_orders()]
    save_book_stats(a.books, a._circuit_breakers, tmp_path / "book_stats.json")
    stats = load_book_stats(tmp_path / "book_stats.json")
    monkeypatch.setattr(engine_main, "GTC_COMBOS_FILE", tmp_path / "no_combos.json")
    b, pub = make_engine(monkeypatch, tmp_path, gtc_orders=orders, book_stats=stats, **kw)  # fmt: skip
    b._restore_gtc()
    b._load_config()
    connect(b)
    return b, pub


def priority(book: OrderBook, side: str) -> list[str]:
    heap = book._bids if side == "BUY" else book._asks
    live = [e for e in heap if e.valid and e.order.status not in _DEAD_STATUSES]
    return [e.order.id for e in sorted(live, key=lambda e: e.key)]


def new(engine: Engine, side: Side, kind: OrderType, qty: int, gw: str, **kw: Any) -> str:  # fmt: skip
    p = order_payload(side, kind, qty, gw, **kw)
    engine._handle_new_order(p)
    return str(p["id"])


def test_x23_a_restart_keeps_an_oco_pair_linked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, _ = make_engine(monkeypatch, tmp_path)
    connect(a)
    a._handle_oco_order(
        {"oco_id": "K1", "gateway_id": "GW01", "symbol": SYMBOL, "quantity": 5, "tif": "DAY", "tick_decimals": 2,  # fmt: skip
         "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10100},
         "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9900}}  # fmt: skip
    )
    assert len(a._oco_groups[("GW01", "K1")]) == 2

    b, pub = restart(monkeypatch, tmp_path, a)
    assert b._oco_groups == a._oco_groups
    # The limit leg fills: the stop leg must go with it.
    new(b, Side.BUY, OrderType.LIMIT, 5, "GW02", price=101.00)
    (cancelled,) = msgs(pub, "oco.cancelled.GW01")
    assert cancelled["cancelled_order_id"] == a._oco_groups[("GW01", "K1")][1]


def test_x24_a_restart_keeps_the_last_trade_price(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, _ = make_engine(monkeypatch, tmp_path)
    connect(a)
    new(a, Side.SELL, OrderType.LIMIT, 5, "GW01", price=100.25)
    new(a, Side.BUY, OrderType.LIMIT, 5, "GW02", price=100.25)
    assert a.books[SYMBOL].last_trade_price == 10025

    b, _ = restart(monkeypatch, tmp_path, a)
    assert b.books[SYMBOL].last_trade_price == 10025


def test_x25_a_restart_in_a_call_phase_leaves_the_book_for_the_auction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pre-open collects crossing orders; a restart must not print them
    (sim run 2026-10-28: 825 trades on restore). The auction does."""
    a, _ = make_engine(monkeypatch, tmp_path, sessions_enabled=True)
    connect(a)
    a._handle_session_transition({"to_state": "PRE_OPEN"})
    new(a, Side.BUY, OrderType.LIMIT, 5, "GW01", price=101.00)
    new(a, Side.SELL, OrderType.LIMIT, 5, "GW02", price=100.00)

    b, pub = restart(monkeypatch, tmp_path, a, sessions_enabled=True)
    assert msgs(pub, "trade.executed") == []
    assert len(b.books[SYMBOL].resting_orders()) == 2
    for state in ("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS"):
        b._handle_session_transition({"to_state": state})
    assert [t["quantity"] for t in msgs(pub, "trade.executed")] == [5]


def test_x25_a_restart_straight_into_continuous_still_uncrosses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without sessions the engine starts in CONTINUOUS, which must never
    hold a crossed book: there the restore's uncross stays."""
    a, _ = make_engine(monkeypatch, tmp_path, sessions_enabled=True)
    connect(a)
    a._handle_session_transition({"to_state": "PRE_OPEN"})
    new(a, Side.BUY, OrderType.LIMIT, 5, "GW01", price=101.00)
    new(a, Side.SELL, OrderType.LIMIT, 5, "GW02", price=100.00)

    b, pub = restart(monkeypatch, tmp_path, a, sessions_enabled=False)
    assert [t["quantity"] for t in msgs(pub, "trade.executed")] == [5]
    assert b.books[SYMBOL].resting_orders() == []


def test_x26_a_restart_keeps_time_priority_after_an_iceberg_refill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The iceberg arrived first, but its refill sent it behind L."""
    a, _ = make_engine(monkeypatch, tmp_path)
    connect(a)
    ice = new(a, Side.SELL, OrderType.ICEBERG, 100, "GW01", price=100.00, visible_qty=10)  # fmt: skip
    plain = new(a, Side.SELL, OrderType.LIMIT, 5, "GW01", price=100.00)
    new(a, Side.BUY, OrderType.LIMIT, 10, "GW02", price=100.00)  # takes the slice
    assert priority(a.books[SYMBOL], "SELL") == [plain, ice]

    b, _ = restart(monkeypatch, tmp_path, a)
    assert priority(b.books[SYMBOL], "SELL") == [plain, ice]


# --- the circuit breaker's reference window ----------------------------------

MIN = 60_000_000_000


def with_breaker() -> dict[str, SymbolConfig]:
    cb = CircuitBreakerConfig(symbol=SYMBOL, levels=[CircuitBreakerLevel("L1", 0.05, 5 * MIN)])  # fmt: skip
    return {SYMBOL: SymbolConfig(name=SYMBOL, last_buy_price=100.0, circuit_breaker=cb)}


def traded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Engine:
    a, _ = make_engine(monkeypatch, tmp_path, symbol_configs=with_breaker())
    a._load_config()
    connect(a)
    for price in (100.00, 101.00, 102.00):
        new(a, Side.SELL, OrderType.LIMIT, 5, "GW01", price=price)
        new(a, Side.BUY, OrderType.LIMIT, 5, "GW02", price=price)
    return a


def test_a_restart_keeps_the_breakers_reference_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The reference is the average of the window's trades: seeded afresh
    from the last price, a restarted engine halted where the uninterrupted
    one did not (EA, 2026-11-07 run, E6: 25325 against 25407)."""
    a = traded(monkeypatch, tmp_path)
    window = list(a._circuit_breakers[SYMBOL].trade_history)
    assert len(window) == 4  # the seed and three trades

    b, _ = restart(monkeypatch, tmp_path, a, symbol_configs=with_breaker())
    cb = b._circuit_breakers[SYMBOL]
    assert list(cb.trade_history) == window
    assert cb.reference_price == a._circuit_breakers[SYMBOL].reference_price


def test_a_restart_on_a_later_day_seeds_the_breaker_from_the_last_price(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Yesterday's window says nothing about today's market: as before, the
    breaker starts from the last price."""
    a = traded(monkeypatch, tmp_path)
    day = 86_400 * 10**9
    monkeypatch.setattr(persistence, "now_ns", lambda: now_ns() - day)
    b, _ = restart(monkeypatch, tmp_path, a, symbol_configs=with_breaker())
    cb = b._circuit_breakers[SYMBOL]
    assert [p for _, p in cb.trade_history] == [b.books[SYMBOL].last_buy_price]
    assert cb.reference_price == 10_200
