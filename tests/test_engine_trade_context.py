"""trade.executed says how the trade came about (S23): match_type, the
uncross it belongs to (auction_id, also on auction.result), and whether
its aggressor was a triggered stop (trigger_order_id)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.engine.main import Engine
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import (
    SYMBOL,
    FakeSock,
    connect,
    make_engine,
    msgs,
    order_payload,
)


def new(
    engine: Engine, side: Side, kind: OrderType, qty: int, gw: str, **kw: Any
) -> str:
    p = order_payload(side, kind, qty, gw, **kw)
    engine._handle_new_order(p)
    return str(p["id"])


def in_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *path: str
) -> tuple[Engine, FakeSock]:
    """An engine with sessions, walked through *path*, holding a crossed book."""
    e, pub = make_engine(monkeypatch, tmp_path, sessions_enabled=True)
    connect(e)
    for state in path:
        e._handle_session_transition({"to_state": state})
    new(e, Side.BUY, OrderType.LIMIT, 5, "GW01", price=100.10)
    new(e, Side.SELL, OrderType.LIMIT, 5, "GW02", price=100.00)
    return e, pub


def test_a_continuous_match_says_so_and_names_no_auction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e, pub = make_engine(monkeypatch, tmp_path)
    connect(e)
    new(e, Side.SELL, OrderType.LIMIT, 5, "GW01", price=100.00)
    new(e, Side.BUY, OrderType.LIMIT, 5, "GW02", price=100.00)
    (trade,) = msgs(pub, "trade.executed")
    assert trade["match_type"] == "CONTINUOUS"
    assert "auction_id" not in trade and "trigger_order_id" not in trade


@pytest.mark.parametrize(
    "path, leave, match_type",
    [
        (("PRE_OPEN", "OPENING_AUCTION"), "CONTINUOUS", "OPENING_AUCTION"),
        (("PRE_OPEN", "CONTINUOUS", "CLOSING_AUCTION"), "CLOSED", "CLOSING_AUCTION"),
    ],
)
def test_a_scheduled_uncross_names_its_auction_and_ties_prints_to_the_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: tuple[str, ...],
    leave: str,
    match_type: str,
) -> None:
    e, pub = in_call(monkeypatch, tmp_path, *path)
    e._handle_session_transition({"to_state": leave})
    (trade,) = msgs(pub, "trade.executed")
    (result,) = msgs(pub, f"auction.result.{SYMBOL}")
    assert trade["match_type"] == match_type
    assert trade["auction_id"] == result["auction_id"] == "AUC-000001-000001"


@pytest.mark.parametrize(
    "reason, match_type",
    [
        ("REOPEN", "REOPEN_AUCTION"),
        ("RECOVERY", "RECOVERY_AUCTION"),
        ("BACKSTOP", "BACKSTOP"),
        ("ADMIN_MANUAL", "FORCE_UNCROSS"),
    ],
)
def test_every_other_uncross_names_its_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reason: str, match_type: str
) -> None:
    e, pub = in_call(monkeypatch, tmp_path, "PRE_OPEN")
    e._run_uncross(symbol_filter=SYMBOL, reason=reason)
    (trade,) = msgs(pub, "trade.executed")
    assert trade["match_type"] == match_type
    assert trade["auction_id"] == msgs(pub, f"auction.result.{SYMBOL}")[0]["auction_id"]


def test_each_uncross_gets_its_own_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e, pub = in_call(monkeypatch, tmp_path, "PRE_OPEN")
    e._run_uncross(symbol_filter=SYMBOL, reason="ADMIN_MANUAL")
    e._run_uncross(symbol_filter=SYMBOL, reason="ADMIN_MANUAL")
    ids = [r["auction_id"] for r in msgs(pub, f"auction.result.{SYMBOL}")]
    assert ids == ["AUC-000001-000001", "AUC-000001-000002"]


def test_a_triggered_stops_trade_names_the_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e, pub = make_engine(monkeypatch, tmp_path)
    connect(e)
    new(e, Side.SELL, OrderType.LIMIT, 20, "GW01", price=100.00)
    stop = new(e, Side.BUY, OrderType.STOP, 5, "GW02", stop_price=100.00)
    new(e, Side.BUY, OrderType.LIMIT, 5, "GW03", price=100.00)  # the trigger
    first, second = msgs(pub, "trade.executed")
    assert "trigger_order_id" not in first
    assert second["buy_order_id"] == second["trigger_order_id"] == stop
    assert second["match_type"] == "CONTINUOUS"
