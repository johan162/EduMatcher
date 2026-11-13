"""Small engine correctness items C13-C17 (engine review 2026-11, WP-ENG07)."""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path
from typing import Any

import pytest

import edumatcher.engine.main as engine_main
from edumatcher.engine.auction import execute_uncross
from edumatcher.engine.main import Engine
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderType, Side, SmpAction
from tests.engine_harness import (
    SYMBOL,
    connect,
    make_engine,
    msgs,
    order_payload,
)

# --- C13: no dead `verbose` parameter -------------------------------------------


def test_the_engine_takes_no_verbose_flag() -> None:
    assert "verbose" not in inspect.signature(Engine.__init__).parameters
    found = subprocess.run(
        ["git", "grep", "-n", r"Engine[(]verbose", "--", "src", "tests"],
        capture_output=True,
        text=True,
    )
    assert found.stdout == ""
    assert found.returncode == 1, found.stderr


# --- C14: one OCO callback per leg the uncross ends -----------------------------


def _resting(side: Side, price: int, **attrs: Any) -> Order:
    order = Order.create(
        symbol=SYMBOL,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=10,
        gateway_id="GW01",
        price_ticks=price,
    )
    for name, value in attrs.items():
        setattr(order, name, value)
    return order


def _uncross_counting(bid: Order, ask: Order) -> list[str]:
    book = OrderBook(SYMBOL)
    calls: list[str] = []
    book.on_oco_leg_done = lambda order: calls.append(order.id)
    book.process(bid, match=False)
    book.process(ask, match=False)
    execute_uncross(book, 10000)
    return calls


def test_two_crossing_legs_of_one_oco_report_the_cancelled_leg_once() -> None:
    bid = _resting(Side.BUY, 10100, oco_group_id="K1")
    ask = _resting(Side.SELL, 9900, oco_group_id="K1")
    assert _uncross_counting(bid, ask) == [bid.id]


def test_an_smp_cancel_of_two_oco_legs_reports_each_once() -> None:
    bid = _resting(Side.BUY, 10100, oco_group_id="K1", smp_action=SmpAction.CANCEL_BOTH)
    ask = _resting(Side.SELL, 9900, oco_group_id="K2", smp_action=SmpAction.CANCEL_BOTH)
    calls = _uncross_counting(bid, ask)
    assert sorted(calls) == sorted([bid.id, ask.id])


# --- C15: the symbols reply reads the caller's terms case-insensitively -------


def test_a_lower_case_caller_gets_its_market_maker_terms(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path, mm_gateways=("GW03",))
    engine._load_config()  # the books, as at startup
    assert engine._engine_config is not None
    gw = engine._engine_config.participants["GW03"]
    gw.enforce_mm_obligation, gw.mm_min_qty = True, 7

    engine._handle_symbols_request({"gateway_id": "GW03"})
    engine._handle_symbols_request({"gateway_id": "gw03"})

    (upper,) = msgs(pub, "system.symbols.GW03")[0]["symbols"]
    (lower,) = msgs(pub, "system.symbols.gw03")[0]["symbols"]  # topic keeps case
    assert upper["mm_min_qty"] == 7
    assert lower == upper


# --- C16: a failing shutdown step does not skip the rest ------------------------


def test_a_failed_save_still_ends_the_day_and_closes_the_sockets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(engine_main, "GTC_COMBOS_FILE", tmp_path / "gtc_combos.json")
    monkeypatch.setattr(engine_main, "BOOK_STATS_FILE", tmp_path / "book_stats.json")

    def disk_full(*_: object) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(engine_main, "save_gtc_orders", disk_full)

    engine._shutdown()

    assert len(msgs(pub, "system.eod")) == 1
    assert (tmp_path / "gtc_combos.json").exists()
    assert (tmp_path / "book_stats.json").exists()
    assert engine.pull_sock.closed and engine.pub_sock.closed
    assert "No space left on device" in caplog.text


# --- C17: an unknown smp_action is refused, not read as "omitted" -------------


def test_an_unknown_smp_action_does_not_decode() -> None:
    order = _resting(Side.BUY, 10000).to_dict()
    with pytest.raises(ValueError, match="CANCEL_ALL"):
        Order.from_dict({**order, "smp_action": "CANCEL_ALL"})
    assert Order.from_dict({**order, "smp_action": None}).smp_action is None


def test_an_order_with_an_unknown_smp_action_is_refused_as_malformed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    payload = order_payload(Side.BUY, OrderType.LIMIT, 10, "GW01", price=100.0)

    engine._handle_new_order({**payload, "smp_action": "CANCEL_ALL"})

    (ack,) = msgs(pub, "order.ack.GW01")
    assert (ack["accepted"], ack["reject_code"]) == (False, "MALFORMED_MESSAGE")
    assert "smp_action" in ack["reason"]
    assert engine._book(SYMBOL).resting_orders() == []
