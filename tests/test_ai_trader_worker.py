"""ai_trader.worker and transport: routing, startup, budget, wire encoding."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from edumatcher.ai_trader.orders import LiveOrder
from edumatcher.ai_trader.preset import TempoSpec, get_preset
from edumatcher.ai_trader.transport import (
    DoneEvent,
    FillEvent,
    PositionsEvent,
    SessionEvent,
)
from edumatcher.ai_trader.worker import AgentSpec, Worker


class FakeTransport:
    def __init__(self, accept: set[str] | None = None) -> None:
        self.accept = accept
        self.sent: list[tuple[str, Any, int]] = []
        self.events: list[tuple[str, Any]] = []
        self.positions_requested: list[str] = []
        self.heartbeats = 0
        self.disconnected: list[str] = []
        self.maintain_events: list[tuple[str, Any]] = []

    def connect(self, gateway_ids: list[str], timeout: float) -> set[str]:
        return (
            set(gateway_ids) if self.accept is None else self.accept & set(gateway_ids)
        )

    def send(self, gateway_id: str, action: Any, tick_decimals: int) -> bool:
        self.sent.append((gateway_id, action, tick_decimals))
        return True

    def request_positions(self, gateway_id: str) -> None:
        self.positions_requested.append(gateway_id)

    def heartbeat(self, gateway_ids: list[str]) -> None:
        self.heartbeats += 1

    def poll_events(self, ready: list[str]) -> list[tuple[str, Any]]:
        out, self.events = self.events, []
        return out

    def is_up(self, gateway_id: str) -> bool:
        return True

    def fileno_map(self) -> dict[int, tuple[str, object]]:
        return {}

    def maintain(self, now: float) -> list[tuple[str, Any]]:
        out, self.maintain_events = self.maintain_events, []
        return out

    def disconnect(self, gateway_ids: list[str]) -> None:
        self.disconnected += gateway_ids

    def close(self) -> None:
        pass


def _spec(
    gw: str = "AI001", preset: str = "noise-retail", symbols: list[str] | None = None
) -> AgentSpec:
    p = get_preset(preset)
    p = replace(p, tempo=TempoSpec(600.0, 1, 10))
    return AgentSpec(gw, p, symbols or [], seed=5)


def _book(bid: float, ask: float) -> dict[str, Any]:
    return {
        "tick_decimals": 2,
        "bids": [{"price": bid, "qty": 10}],
        "asks": [{"price": ask, "qty": 10}],
    }


def _started(
    monkeypatch: pytest.MonkeyPatch,
    specs: list[AgentSpec],
    transport: FakeTransport,
    session: str = "CONTINUOUS",
) -> Worker:
    w = Worker(specs, transport, name="t", summary_dir=Path(tempfile.mkdtemp()))
    snapshots: list[str] = []
    monkeypatch.setattr(
        w, "_request_snapshot", lambda sym, now, force=False: snapshots.append(sym)
    )
    references: list[int] = []
    monkeypatch.setattr(w, "_request_reference", lambda: references.append(1))

    def fake_drain(wait_ms: int = 0, max_messages: int = 5000) -> int:
        gw = w._ref_gw
        w.handle_market(
            f"system.symbols.{gw}",
            {
                "symbols": [
                    {"symbol": "AAPL", "tick_decimals": 2},
                    {"symbol": "MSFT", "tick_decimals": 4},
                ]
            },
        )
        w.handle_market(
            f"system.session_status.{gw}", {"state": session, "sessions_enabled": True}
        )
        return 2

    monkeypatch.setattr(w, "_drain_market", fake_drain)
    assert w.start(timeout=1.0)
    w.snapshots = snapshots  # type: ignore[attr-defined]
    w.references = references  # type: ignore[attr-defined]
    return w


class TestStartup:
    def test_builds_agents_and_seeds_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        t = FakeTransport()
        w = _started(
            monkeypatch, [_spec("AI001"), _spec("AI002", symbols=["MSFT", "NOPE"])], t
        )
        assert sorted(w.agents) == ["AI001", "AI002"]
        assert w.agents["AI001"].universe == ["AAPL", "MSFT"]
        assert w.agents["AI002"].universe == ["MSFT"]
        assert t.positions_requested == ["AI001", "AI002"]
        assert sorted(w.snapshots) == ["AAPL", "MSFT"]  # type: ignore[attr-defined]
        assert w.market.symbols["MSFT"].tick_decimals == 4
        w.close()

    def test_refused_participants_are_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        w = _started(
            monkeypatch, [_spec("AI001"), _spec("AI002")], FakeTransport({"AI002"})
        )
        assert list(w.agents) == ["AI002"]
        w.close()

    def test_nobody_logged_on(self) -> None:
        w = Worker([_spec()], FakeTransport(set()), name="t")
        assert w.start(timeout=0.5) is False
        w.close()


class TestRouting:
    def test_market_topics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w = _started(monkeypatch, [_spec()], FakeTransport())
        w.handle_market("book.AAPL", _book(1.0, 1.2))
        w.handle_market("depth.AAPL", {"microprice": 1.1, "imbalance": 0.25})
        w.handle_market(
            "trade.executed", {"symbol": "AAPL", "price": 1.05, "aggressor_side": "BUY"}
        )
        w.handle_market(
            "auction.indicative.AAPL", {"eq_price": 1.07, "imbalance_qty": 0}
        )
        w.handle_market("circuit_breaker.halt.AAPL", {})
        st = w.market.symbols["AAPL"]
        assert (
            st.best_bid,
            st.best_ask,
            st.microprice,
            st.last_trade,
            st.indicative_price,
        ) == (100, 120, 110, 105, 107)
        assert st.imbalance == 0.25 and st.halted
        w.handle_market("circuit_breaker.resume.AAPL", {})
        assert not st.halted
        w.close()

    def test_close_and_reopen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w = _started(
            monkeypatch,
            [_spec(preset="institutional")],
            FakeTransport(),
            session="CONTINUOUS",
        )
        w.agents["AI001"].executor.twaps["AAPL"] = object()
        w.handle_market("auction.indicative.AAPL", {"eq_price": 1.0})
        w.handle_market("session.state", {"state": "CLOSING_AUCTION"})
        w.handle_market("session.state", {"state": "CLOSED"})
        assert w.agents["AI001"].executor.twaps == {}
        assert w.market.symbols["AAPL"].indicative_price is None
        w.snapshots.clear()  # type: ignore[attr-defined]
        w.handle_market("session.state", {"state": "PRE_OPEN"})
        assert sorted(w.snapshots) == ["AAPL", "MSFT"]  # type: ignore[attr-defined]
        w.close()

    def test_day_closes_after_the_grace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w = _started(monkeypatch, [_spec("AI001"), _spec("AI002")], FakeTransport())
        w.handle_market("session.state", {"state": "CLOSING_AUCTION"})
        w.handle_market("session.state", {"state": "CLOSED"})
        assert w._day_close_at is not None and w.days_closed == 0
        w.close_day()
        (path,) = list(w.summary_dir.glob("*-t.jsonl"))
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert [r["agent"] for r in rows] == ["AI001", "AI002"]
        assert all(r["day"] == 1 and "pnl_mtm" in r and r["closed_at"] for r in rows)
        assert w._day_close_at is None
        w.close()

    def test_next_day_before_the_grace_closes_the_day_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        w = _started(monkeypatch, [_spec()], FakeTransport())
        w.handle_market("session.state", {"state": "CLOSING_AUCTION"})
        w.handle_market("session.state", {"state": "CLOSED"})
        w.handle_market("session.state", {"state": "PRE_OPEN"})
        assert w.days_closed == 1 and w._day_close_at is None
        w.close()

    def test_engine_restart_rereads_reference_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        w = _started(monkeypatch, [_spec()], FakeTransport())
        w.references.clear()  # type: ignore[attr-defined]
        w.snapshots.clear()  # type: ignore[attr-defined]
        w.handle_market("system.startup_recovery", {"restored_orders": 3})
        assert w.references == [1]  # type: ignore[attr-defined]
        assert sorted(w.snapshots) == ["AAPL", "MSFT"]  # type: ignore[attr-defined]
        # asked again until the session status answers
        assert w._resync_at is not None
        w.handle_market("system.session_status.AI001", {"state": "CLOSED"})
        assert w._resync_at is None and w.market.phase == "CLOSED"
        w.close()

    def test_dispatch_converts_fill_price_with_the_symbols_scale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        w = _started(monkeypatch, [_spec()], FakeTransport())
        w.dispatch("AI001", FillEvent("E1", None, "MSFT", "BUY", 3, 12.3456, 0))
        pos = w.agents["AI001"].orders.position("MSFT")
        assert (pos.qty, pos.avg_cost) == (3, 123456)
        w.dispatch("AI001", PositionsEvent({"AAPL": (-7, 1.25)}))
        assert w.agents["AI001"].orders.position("AAPL").avg_cost == 125
        w.dispatch("NOBODY", DoneEvent("x", None))  # ignored
        w.close()

    def test_reconnect_forgets_orders_and_rereads_positions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        t = FakeTransport()
        w = _started(monkeypatch, [_spec()], t)
        agent = w.agents["AI001"]
        agent.orders.orders["stale"] = cast(LiveOrder, object())
        t.positions_requested.clear()
        w.dispatch("AI001", SessionEvent(up=True))
        assert agent.orders.orders == {} and t.positions_requested == ["AI001"]
        assert w._resync_at is not None  # market data re-read too
        w.close()


class TestRun:
    def test_agents_trade_and_disconnect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        t = FakeTransport()
        w = _started(monkeypatch, [_spec("AI001"), _spec("AI002")], t)
        w.handle_market("book.AAPL", _book(1.0, 1.2))
        w.handle_market("book.MSFT", {**_book(1.0, 1.2), "tick_decimals": 4})
        monkeypatch.setattr(w, "_drain_market", lambda *a, **k: 0)
        w.run(duration=0.5)
        assert {gw for gw, _, _ in t.sent} == {"AI001", "AI002"}
        assert all(d == (4 if a.symbol == "MSFT" else 2) for _, a, d in t.sent)
        assert t.heartbeats >= 1 and sorted(t.disconnected) == ["AI001", "AI002"]
        assert w.actions_sent == len(t.sent)
        w.close()


class TestBudget:
    def test_initial_scale_and_feedback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w = _started(monkeypatch, [_spec("AI001"), _spec("AI002")], FakeTransport())
        w.budget = 5.0
        w._apply_budget(0.0, initial=True)
        assert w.agents["AI001"].rate_scale == pytest.approx(5.0 / 20.0)  # 2 x 600/min
        # Measured 40 actions/s against a budget of 5: damped, bounded step down.
        w._sent_window = [(t, 40) for t in range(0, 21)]
        before = w.agents["AI001"].rate_scale
        w._apply_budget(20.0)
        assert w.agents["AI001"].rate_scale == pytest.approx(before / 1.5**0.5)
        w.close()

    def test_no_budget_no_scaling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w = _started(monkeypatch, [_spec()], FakeTransport())
        w._apply_budget(0.0, initial=True)
        assert w.agents["AI001"].rate_scale == 1.0
        w.close()


def test_reconnect_on_a_reused_fd_number_is_watched() -> None:
    """A reconnect that gets the closed socket's fd number back must be
    registered again: epoll forgot the fd when the old socket closed."""
    import selectors
    import socket

    t = FakeTransport()
    w = Worker([_spec()], t, name="t", summary_dir=Path(tempfile.mkdtemp()))
    sel = selectors.DefaultSelector()
    known: dict[int, tuple[str, object]] = {}
    old, old_peer = socket.socketpair()
    t.fileno_map = lambda: {old.fileno(): ("AI001", old)}
    w._sync_selector(sel, known)
    fd = old.fileno()
    fresh, new_peer = socket.socketpair()
    os.dup2(fresh.fileno(), fd)  # closes the old socket; fd now names the new one
    old.detach()
    fresh.close()
    new = socket.socket(fileno=fd)
    t.fileno_map = lambda: {fd: ("AI001", new)}
    w._sync_selector(sel, known)
    new_peer.send(b"WELCOME\n")
    assert [k.data for k, _ in sel.select(1.0)] == ["AI001"]
    sel.close()
    for sock in (old_peer, new, new_peer):
        sock.close()
    w.close()
