"""pm-stats records what the engine published: regression tests for the
recorder findings X4, X6 and X7 (docs-design/EduMatcher-Sim-Forensics-
Workplan.md §9).

- X4: messages still queued on the SUB socket when pm-stats was told to
  stop were never read (a run lost its last trade and fill).
- X6: a quote.ack rejection without a quote id (a quote cancel for a symbol
  with no live quote) was dropped, and no event kept its reject_code.
- X7: oco.cancelled was stored under the OCO id only, so the cancelled leg
  looked live forever.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.models.message import encode
from edumatcher.stats.main import StatsProcess

TRADE = {
    "id": "000001-000000001",
    "run_seq": 1,
    "symbol": "AAPL",
    "buy_order_id": "B1",
    "sell_order_id": "S1",
    "buy_gateway_id": "GW01",
    "sell_gateway_id": "GW02",
    "price": 100.0,
    "quantity": 10,
    "aggressor_side": "BUY",
    "ts_ns": 1_792_850_048_220_023_754,
    "tick_decimals": 2,
}


@pytest.fixture
def sp(tmp_path: Path) -> Iterator[StatsProcess]:
    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_pusher", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_replier", return_value=MagicMock()),
    ):
        proc = StatsProcess(tmp_path / "stats.db")
    yield proc
    proc._running = False
    proc.close()


def events(sp: StatsProcess) -> list[tuple[Any, ...]]:
    return sp._conn.execute(
        "SELECT event_type, order_id, gateway_id, symbol, reason, reject_code, "
        "oco_group_id FROM order_events ORDER BY seq"
    ).fetchall()


# --- X4 ----------------------------------------------------------------------


def test_x4_messages_queued_at_the_stop_are_still_recorded(sp: StatsProcess) -> None:
    queue = [
        encode("trade.executed", {**TRADE, "id": f"000001-00000000{i}"})
        for i in (1, 2, 3)
    ]
    sub: Any = sp.sub
    sub.poll.side_effect = lambda timeout=0: bool(queue)
    sub.recv_multipart.side_effect = lambda: queue.pop(0)
    sp._running = False  # the stop arrived with three messages unread
    sp._receive_loop()
    (count,) = sp._conn.execute("SELECT count(*) FROM trade_log").fetchone()
    assert count == 3


def test_x4_the_drain_after_a_stop_is_bounded(sp: StatsProcess) -> None:
    """An engine that keeps publishing cannot hold pm-stats open."""
    sub: Any = sp.sub
    sub.poll.side_effect = lambda timeout=0: True
    sub.recv_multipart.side_effect = lambda: encode("system.anything", {})
    sp._running = False
    with patch("edumatcher.stats.main._DRAIN_SEC", 0.05):
        sp._receive_loop()


# --- X6 ----------------------------------------------------------------------


def test_x6_a_quote_cancel_rejection_without_a_quote_id_is_recorded(
    sp: StatsProcess,
) -> None:
    sp._on_order_event(
        "quote.ack.MM01",
        {
            "quote_id": "",
            "accepted": False,
            "symbol": "CB",
            "reason": "No active quote for symbol",
            "reject_code": "ORDER_NOT_FOUND",
            "bid_order_id": "",
            "ask_order_id": "",
        },
    )
    assert events(sp) == [
        ("QUOTE_REJECT", "", "MM01", "CB", "No active quote for symbol", "ORDER_NOT_FOUND", None)  # fmt: skip
    ]


def test_x6_an_order_rejection_keeps_its_reject_code(sp: StatsProcess) -> None:
    sp._on_order_event(
        "order.ack.GW01",
        {
            "order_id": "O1",
            "accepted": False,
            "symbol": "AAPL",
            "reason": "Insufficient liquidity",
            "reject_code": "INSUFFICIENT_LIQUIDITY",
        },
    )
    assert [e[5] for e in events(sp)] == ["INSUFFICIENT_LIQUIDITY"]


def test_x6_events_without_any_id_are_still_dropped(sp: StatsProcess) -> None:
    """Only a quote rejection may have no id: it names a (gateway, symbol)."""
    sp._on_order_event("order.ack.GW01", {"accepted": True})
    assert events(sp) == []


# --- X7 ----------------------------------------------------------------------


def test_x7_an_oco_cancel_also_records_the_cancelled_leg(sp: StatsProcess) -> None:
    sp._on_order_event(
        "oco.cancelled.GW01",
        {
            "gateway_id": "GW01",
            "oco_id": "OCO1",
            "cancelled_order_id": "LEG2",
            "reason": "Sibling filled",
        },
    )
    assert events(sp) == [
        ("OCO_CANCEL", "OCO1", "GW01", "", "Sibling filled", None, None),
        ("CANCEL", "LEG2", "GW01", "", "Sibling filled", None, "OCO1"),
    ]
