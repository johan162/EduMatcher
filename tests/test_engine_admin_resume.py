"""An administrator's resume ends the halt with a reopening auction.

Regression tests for X29 of the simulation forensics
(docs-design/EduMatcher-Sim-Forensics-Workplan.md §9): a halt is a call
phase -- limit orders rest unmatched and may cross -- and the breaker's timed
reopen uncrosses before continuous trading resumes, but ``risk.symbol_resume``
and ``risk.circuit_breaker_resume_all`` only cleared the halt, leaving the
book crossed. Decided 2026-10-29: the administrator's resume uncrosses
unconditionally (no ACE corridor: the operator decided to reopen).
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.order import OrderType, Side
from edumatcher.models.session import SessionState
from tests.engine_harness import all_msgs, connect, make_engine, order_payload

GWS = ("GW01", "GW02", "OPS")


def halted_and_crossed(monkeypatch: Any, tmp_path: Any) -> Any:
    """AAPL halted by the administrator, a buy at 101 and a sell at 99 in it."""
    engine, pub = make_engine(
        monkeypatch, tmp_path, symbols=("AAPL",), gateways=GWS, admin_gateways=("OPS",)
    )
    connect(engine, *GWS)
    engine._handle_symbol_halt({"gateway_id": "OPS", "symbol": "AAPL"})
    for side, price, gw in ((Side.BUY, 101.0, "GW01"), (Side.SELL, 99.0, "GW02")):
        engine._handle_new_order(
            order_payload(side, OrderType.LIMIT, 10, gw, price=price, symbol="AAPL")
        )
    assert len(engine.books["AAPL"].resting_orders()) == 2  # crossed, unmatched
    pub.sent.clear()
    return engine, pub


def topics(pub: Any) -> list[str]:
    return [t for t, _ in all_msgs(pub) if t.split(".")[0] in ("auction", "circuit_breaker", "trade")]  # fmt: skip


def test_a_symbol_resume_uncrosses_before_trading_resumes(monkeypatch, tmp_path) -> None:  # fmt: skip
    engine, pub = halted_and_crossed(monkeypatch, tmp_path)

    engine._handle_symbol_resume({"gateway_id": "OPS", "symbol": "AAPL"})

    assert topics(pub) == ["trade.executed", "auction.result.AAPL", "circuit_breaker.resume.AAPL"]  # fmt: skip
    assert engine.books["AAPL"].resting_orders() == []
    assert not engine._halted_symbols["AAPL"]


def test_a_resume_all_uncrosses_every_halted_symbol(monkeypatch, tmp_path) -> None:
    engine, pub = halted_and_crossed(monkeypatch, tmp_path)

    engine._handle_circuit_breaker_resume_all({"gateway_id": "OPS"})

    assert topics(pub)[:3] == ["trade.executed", "auction.result.AAPL", "circuit_breaker.resume.AAPL"]  # fmt: skip
    assert engine.books["AAPL"].resting_orders() == []


def test_outside_a_matching_phase_the_session_auction_uncrosses(monkeypatch, tmp_path) -> None:  # fmt: skip
    engine, pub = halted_and_crossed(monkeypatch, tmp_path)
    engine._session_state = SessionState.PRE_OPEN

    engine._handle_symbol_resume({"gateway_id": "OPS", "symbol": "AAPL"})

    assert topics(pub) == ["circuit_breaker.resume.AAPL"]
    assert len(engine.books["AAPL"].resting_orders()) == 2
