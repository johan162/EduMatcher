"""What the book did beyond trades and order events (S24): order.triggered
to the stop's owner, engine.trace for the audit, risk.band at startup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.engine.collar import CollarConfig
from edumatcher.engine.config_loader import SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.models.order import OrderType, Side, SmpAction
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
        "trigger_price_ticks": 10_000, "becomes": becomes, "tick_decimals": 2,
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
        "tick_decimals": 2,
    }  # fmt: skip


# --- S36: why the engine decided ---------------------------------------------


def in_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Engine, FakeSock]:  # fmt: skip
    e, pub = make_engine(monkeypatch, tmp_path, sessions_enabled=True)
    connect(e)
    for state in ("PRE_OPEN", "OPENING_AUCTION"):
        e._handle_session_transition({"to_state": state})
    return e, pub


@pytest.mark.parametrize(
    "bids, asks, eq, rule, tied",
    [
        ([(101.00, 10)], [(100.00, 4), (101.00, 6)], 10_100, "VOLUME", [10_100]),
        ([(101.00, 10), (100.00, 5)], [(100.00, 10)], 10_100, "SURPLUS", [10_000, 10_100]),  # fmt: skip
        ([(101.00, 10)], [(100.00, 10)], 10_000, "LOWEST_PRICE", [10_000, 10_100]),
    ],
)
def test_an_uncross_says_which_rule_chose_its_price(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bids: list[tuple[float, int]],
    asks: list[tuple[float, int]],
    eq: int,
    rule: str,
    tied: list[int],
) -> None:
    e, pub = in_call(monkeypatch, tmp_path)
    for side, book in ((Side.BUY, bids), (Side.SELL, asks)):
        for i, (price, qty) in enumerate(book):
            new(e, side, OrderType.LIMIT, qty, ("GW01", "GW02", "GW03")[i + (side == Side.SELL)], price=price)  # fmt: skip
    e._handle_session_transition({"to_state": "CONTINUOUS"})
    (trace,) = traces(pub, "UNCROSS_PRICE")
    (result,) = msgs(pub, f"auction.result.{SYMBOL}")
    assert trace == {
        "symbol": SYMBOL, "kind": "UNCROSS_PRICE", "auction_id": result["auction_id"],
        "eq_price_ticks": eq, "eq_qty": 10, "surplus": result["imbalance_qty"],
        "rule": rule, "tied_prices_ticks": tied, "tick_decimals": 2,
    }  # fmt: skip
    topics = [t for t, _ in all_msgs(pub)]
    assert topics.index(f"engine.trace.{SYMBOL}") < topics.index("trade.executed")


def test_an_imposed_uncross_price_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e, pub = in_call(monkeypatch, tmp_path)
    new(e, Side.BUY, OrderType.LIMIT, 10, "GW01", price=101.00)
    new(e, Side.SELL, OrderType.LIMIT, 10, "GW02", price=100.00)
    e._run_uncross(SYMBOL, reason="ADMIN_MANUAL", price_override=10_050)
    (trace,) = traces(pub, "UNCROSS_PRICE")
    assert (trace["rule"], trace["eq_price_ticks"]) == ("OVERRIDE", 10_050)
    assert "tied_prices_ticks" not in trace


def test_a_book_that_does_not_cross_has_no_uncross_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e, pub = in_call(monkeypatch, tmp_path)
    new(e, Side.BUY, OrderType.LIMIT, 10, "GW01", price=99.00)
    new(e, Side.SELL, OrderType.LIMIT, 10, "GW02", price=100.00)
    e._handle_session_transition({"to_state": "CONTINUOUS"})
    assert traces(pub, "UNCROSS_PRICE") == []


@pytest.mark.parametrize("smp", ["CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"])
def test_a_continuous_self_match_names_the_pair_and_the_policy(
    rig: tuple[Engine, FakeSock], smp: str
) -> None:
    e, pub = rig
    resting = new(e, Side.SELL, OrderType.LIMIT, 5, "GW01", price=100.00)
    incoming = new(e, Side.BUY, OrderType.LIMIT, 5, "GW01", price=100.00, smp_action=SmpAction(smp))  # fmt: skip
    (trace,) = traces(pub, "SMP_DECISION")
    assert trace == {
        "symbol": SYMBOL, "kind": "SMP_DECISION", "order_id": incoming,
        "other_order_id": resting, "smp_action": smp,
    }  # fmt: skip


def test_an_unfillable_fok_names_each_own_order_it_met(
    rig: tuple[Engine, FakeSock],
) -> None:
    e, pub = rig
    own = [new(e, Side.SELL, OrderType.LIMIT, 5, "GW01", price=p) for p in (100.00, 100.10)]  # fmt: skip
    new(e, Side.SELL, OrderType.LIMIT, 5, "GW02", price=100.20)
    fok = new(e, Side.BUY, OrderType.FOK, 50, "GW01", price=100.20, smp_action=SmpAction.CANCEL_RESTING)  # fmt: skip
    pairs = [(t["order_id"], t["other_order_id"], t["smp_action"]) for t in traces(pub, "SMP_DECISION")]  # fmt: skip
    assert pairs == [(fok, o, "CANCEL_RESTING") for o in own]


def test_an_uncross_self_match_names_the_pair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e, pub = in_call(monkeypatch, tmp_path)
    bid = new(e, Side.BUY, OrderType.LIMIT, 5, "GW01", price=101.00, smp_action=SmpAction.CANCEL_BOTH)  # fmt: skip
    ask = new(e, Side.SELL, OrderType.LIMIT, 5, "GW01", price=100.00)
    new(e, Side.SELL, OrderType.LIMIT, 5, "GW02", price=101.00)
    e._handle_session_transition({"to_state": "CONTINUOUS"})
    pairs = [(t["order_id"], t["other_order_id"], t["smp_action"]) for t in traces(pub, "SMP_DECISION")]  # fmt: skip
    assert pairs == [(bid, ask, "CANCEL_BOTH")]


@pytest.mark.parametrize(
    "liquidity, outcome, fillable, fillable_no_smp",
    [
        ({"AAPL": ("GW02", 10), "MSFT": ("GW02", 10)}, "MATCH", [10, 10], [10, 10]),
        ({}, "REST", [0, 0], [0, 0]),
        ({"AAPL": ("GW02", 10), "MSFT": ("GW01", 10)}, "REJECT", [10, 0], [10, 10]),
    ],
)
def test_an_aon_combo_reports_each_legs_fillable_and_its_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    liquidity: dict[str, tuple[str, int]],
    outcome: str,
    fillable: list[int],
    fillable_no_smp: list[int],
) -> None:
    e, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(e)
    for sym, (gw, qty) in liquidity.items():
        new(e, Side.SELL, OrderType.LIMIT, qty, gw, price=100.00, symbol=sym)
    e._handle_combo_order(
        {"combo_id": "C1", "gateway_id": "GW01", "combo_type": "AON", "tif": "DAY",
         "legs": [{"symbol": s, "side": "BUY", "order_type": "LIMIT", "quantity": 10,
                   "price_ticks": 10_000, "smp_action": "CANCEL_RESTING"} for s in ("AAPL", "MSFT")]}  # fmt: skip
    )
    got = [
        (t["symbol"], t["leg_index"], t["quantity"], t["fillable_qty"], t["fillable_no_smp_qty"], t["outcome"])  # fmt: skip
        for sym in ("AAPL", "MSFT")
        for t in msgs(pub, f"engine.trace.{sym}")
        if t["kind"] == "AON_PREFLIGHT" and t["combo_id"] == "C1"
    ]
    assert got == [
        (s, i, 10, f, n, outcome)
        for i, (s, f, n) in enumerate(zip(("AAPL", "MSFT"), fillable, fillable_no_smp))  # fmt: skip
    ]
    kinds = [p.get("kind") or t for t, p in all_msgs(pub)]
    assert kinds.index("combo.ack.GW01") < kinds.index("AON_PREFLIGHT")
