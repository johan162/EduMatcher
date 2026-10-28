"""system.book_checkpoint (S25): every book, as a replay needs it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.engine.main import Engine
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import all_msgs, connect, make_engine, msgs, order_payload


def new(
    engine: Engine, side: Side, kind: OrderType, qty: int, gw: str, **kw: Any
) -> str:
    p = order_payload(side, kind, qty, gw, **kw)
    engine._dispatch_pull_message("order.new", p)
    return str(p["id"])


def test_each_session_transition_checkpoints_every_book(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"), sessions_enabled=True)  # fmt: skip
    e._load_config()  # the books, as at startup
    connect(e)
    e._handle_session_transition({"to_state": "PRE_OPEN"})
    marks = [(p["symbol"], p["reason"], p["phase"]) for t, p in _checkpoints(pub)]
    assert marks == [("AAPL", "PHASE", "PRE_OPEN"), ("MSFT", "PHASE", "PRE_OPEN")]


def test_a_checkpoint_holds_priority_hidden_quantity_and_stop_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    e, pub = make_engine(monkeypatch, tmp_path)
    connect(e)
    ice = new(e, Side.SELL, OrderType.ICEBERG, 100, "GW01", price=100.00, visible_qty=10)  # fmt: skip
    plain = new(e, Side.SELL, OrderType.LIMIT, 5, "GW01", price=100.00)
    new(e, Side.BUY, OrderType.LIMIT, 10, "GW02", price=100.00)  # ice refills, behind
    far = new(e, Side.BUY, OrderType.STOP, 5, "GW03", stop_price=102.00)
    near = new(e, Side.BUY, OrderType.STOP, 5, "GW03", stop_price=101.00)
    e._publish_checkpoints("PHASE")
    ((_, p),) = _checkpoints(pub)
    asks = [
        (r["order_id"], r["remaining_qty"], r.get("displayed_qty")) for r in p["asks"]
    ]
    assert asks == [(plain, 5, None), (ice, 90, 10)]
    assert [r["order_id"] for r in p["buy_stops"]] == [near, far]
    assert p["last_trade_price_ticks"] == 10_000
    assert p["last_trade_id"] == msgs(pub, "trade.executed")[-1]["id"]


def _checkpoints(pub: Any) -> list[tuple[str, dict[str, Any]]]:
    return [(t, p) for t, p in all_msgs(pub) if t.startswith("system.book_checkpoint.")]
