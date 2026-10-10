"""ai_trader.agent: decisions, risk, housekeeping, protection, events."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import pytest

from edumatcher.ai_trader.actions import CancelOco, CancelOrder, NewOco, NewOrder
from edumatcher.ai_trader.agent import Agent, intraday_multiplier
from edumatcher.ai_trader.market_state import MarketState
from edumatcher.ai_trader.orders import LiveOrder
from edumatcher.ai_trader.preset import TempoSpec, get_preset
from edumatcher.ai_trader.risk import RiskSpec
from edumatcher.models.order import TIF, OrderType


def _market(
    symbols: tuple[str, ...] = ("AAPL", "MSFT"), session: str = "CONTINUOUS"
) -> MarketState:
    m = MarketState()
    m.on_session_status({"state": session, "sessions_enabled": True}, wall=0.0)
    for sym in symbols:
        st = m.get(sym)
        st.best_bid, st.best_ask, st.last_trade = 990, 1010, 1000
    return m


def _agent(preset: str = "noise-retail", **risk: Any) -> Agent:
    p = get_preset(preset)
    if risk:
        p = replace(p, risk=replace(p.risk, **risk))
    # very fast tempo so tests need few steps
    p = replace(
        p,
        tempo=TempoSpec(
            600.0, p.tempo.size_min, p.tempo.size_max, p.tempo.size_distribution
        ),
    )
    return Agent("AI001", p, ["AAPL", "MSFT"], seed=3, now=0.0)


def _run(
    agent: Agent, market: MarketState, seconds: float, dt: float = 0.05, t0: float = 0.0
):
    out = []
    t = t0
    while t < t0 + seconds:
        out += agent.step(t, t, market)
        t += dt
    return out


def _ack_all(agent: Agent, actions: list) -> None:
    for i, a in enumerate(actions):
        if isinstance(a, NewOrder):
            agent.on_ack(
                0.0,
                order_id=f"E{a.tag}",
                tag=a.tag,
                accepted=True,
                code=None,
                reason="",
                request_tag=None,
            )


class TestDeterminism:
    def test_same_seed_same_actions(self) -> None:
        a = _run(_agent(), _market(), 30)
        b = _run(_agent(), _market(), 30)
        assert a and a == b

    def test_different_seed_differs(self) -> None:
        p = get_preset("noise-retail")
        x = _run(Agent("AI001", p, ["AAPL", "MSFT"], 1, 0.0), _market(), 120)
        y = _run(Agent("AI001", p, ["AAPL", "MSFT"], 2, 0.0), _market(), 120)
        assert x != y


class TestGating:
    def test_closed_market_does_nothing(self) -> None:
        assert _run(_agent(), _market(session="CLOSED"), 30) == []

    def test_breaker_pauses_decisions(self) -> None:
        agent = _agent()
        for _ in range(agent.breaker.max_rejects):
            agent.on_ack(
                0.0,
                order_id="x",
                tag=None,
                accepted=False,
                code="PRICE_OUT_OF_RANGE",
                reason="bad",
                request_tag=None,
            )
        assert agent.stats.breaker_trips == 1
        assert _run(agent, _market(), 4.0, t0=0.0) == []

    @pytest.mark.parametrize("code", ["ORDER_NOT_FOUND", "MARKET_CLOSED"])
    def test_benign_rejects_do_not_trip(self, code: str) -> None:
        agent = _agent()
        for _ in range(100):
            agent.on_ack(
                0.0,
                order_id="x",
                tag=None,
                accepted=False,
                code=code,
                reason="",
                request_tag=None,
            )
        assert agent.stats.breaker_trips == 0

    def test_refused_cancel_is_not_counted_as_reject(self) -> None:
        agent = _agent()
        agent.on_ack(
            0.0,
            order_id="E1",
            tag=None,
            accepted=False,
            code="NOT_OWNER",
            reason="",
            request_tag="CXL-AI001-1",
        )
        assert sum(agent.stats.rejected.values()) == 0


class TestRisk:
    def test_position_limit_counts_open_orders(self) -> None:
        agent = _agent(
            max_position=30, max_live_orders_per_symbol=100, max_order_age_sec=1e9
        )
        actions = _run(agent, _market(), 60)
        new = [a for a in actions if isinstance(a, NewOrder)]
        for sym in ("AAPL", "MSFT"):
            for side in ("BUY", "SELL"):
                assert (
                    sum(a.qty for a in new if a.symbol == sym and a.side == side) <= 30
                )

    def test_live_order_cap(self) -> None:
        agent = _agent(max_live_orders_per_symbol=1, max_order_age_sec=1e9)
        actions = _run(agent, _market(), 60)
        _ack_all(agent, actions)
        assert all(len(agent.orders.live(s)) <= 1 for s in ("AAPL", "MSFT"))


class TestHousekeeping:
    def test_old_orders_are_cancelled_once(self) -> None:
        agent = _agent(max_order_age_sec=5.0, max_live_orders_per_symbol=1)
        m = _market()
        first = _run(agent, m, 1.0)
        _ack_all(agent, first)
        later = _run(agent, m, 10.0, t0=1.0)
        cancels = [a for a in later if isinstance(a, CancelOrder)]
        assert cancels
        assert len({c.order_id for c in cancels}) == len(cancels)

    def test_unacked_orders_are_not_cancelled_by_id(self) -> None:
        agent = _agent(max_order_age_sec=1.0)
        later = _run(agent, _market(), 10.0)
        assert not any(isinstance(a, CancelOrder) for a in later)

    def test_unanswered_cancel_is_forgotten(self) -> None:
        agent = _agent(max_order_age_sec=1.0, max_live_orders_per_symbol=1)
        m = _market()
        _ack_all(agent, _run(agent, m, 0.5))
        _run(agent, m, 2.0, t0=0.5)
        n_pending = sum(
            1 for o in agent.orders.orders.values() if o.state.value == "CANCEL_PENDING"
        )
        assert n_pending
        agent.preset = replace(
            agent.preset, tempo=TempoSpec(0.01, 1, 1)
        )  # stop new orders
        agent.next_decision_at = 1e9
        _run(agent, m, 20.0, t0=2.5, dt=0.5)
        assert agent.orders.orders == {}


class TestProtection:
    def _filled(self, preset: str, qty: int = 100) -> tuple[Agent, MarketState]:
        agent = _agent(preset)
        agent.next_decision_at = 1e9  # no trading decisions, protection only
        agent.on_fill(
            order_id="E1",
            tag=None,
            symbol="AAPL",
            side="BUY",
            fill_qty=qty,
            fill_price_ticks=1000,
            remaining=0,
        )
        return agent, _market()

    def test_stop(self) -> None:
        agent, m = self._filled("trend-follower")
        [o] = agent.step(0.0, 0.0, m)
        assert isinstance(o, NewOrder)
        assert (o.order_type, o.side, o.qty) == (OrderType.STOP, "SELL", 100)
        assert o.stop_price_ticks == math.floor(
            1000 * (1 - agent.preset.risk.protection_pct)
        )

    def test_stop_limit(self) -> None:
        agent, m = self._filled("block-taker")
        [o] = agent.step(0.0, 0.0, m)
        assert o.order_type == OrderType.STOP_LIMIT  # type: ignore[union-attr]
        assert o.price_ticks < o.stop_price_ticks  # type: ignore[union-attr,operator]

    def test_trailing(self) -> None:
        agent, m = self._filled("scalper")
        [o] = agent.step(0.0, 0.0, m)
        assert o.order_type == OrderType.TRAILING_STOP and o.trail_offset_ticks == 10  # type: ignore[union-attr]

    def test_bracket_is_one_oco_with_tracked_legs(self) -> None:
        agent, m = self._filled("contrarian")
        [o] = agent.step(0.0, 0.0, m)
        assert isinstance(o, NewOco)
        assert o.leg1.order_type == OrderType.LIMIT and o.leg1.price_ticks > 1000  # type: ignore[operator]
        assert o.leg2.order_type == OrderType.STOP and o.leg2.stop_price_ticks < 1000  # type: ignore[operator]
        assert len(agent.orders.live("AAPL", None)) == 2
        # Position grows: the bracket is cancelled as one OCO, then replaced.
        agent.on_oco_ack(o.tag, True, ("L1", "L2"), "")
        agent.on_fill(
            order_id="E2",
            tag=None,
            symbol="AAPL",
            side="BUY",
            fill_qty=50,
            fill_price_ticks=1000,
            remaining=0,
        )
        out = agent.step(1.0, 1.0, m)
        assert out == [CancelOco(tag=o.tag, symbol="AAPL")]

    def test_short_position_protects_with_a_buy_above(self) -> None:
        agent = _agent("trend-follower")
        agent.next_decision_at = 1e9
        agent.on_fill(
            order_id="E1",
            tag=None,
            symbol="AAPL",
            side="SELL",
            fill_qty=10,
            fill_price_ticks=1000,
            remaining=0,
        )
        [o] = agent.step(0.0, 0.0, _market())
        assert o.side == "BUY" and o.stop_price_ticks > 1010  # type: ignore[union-attr,operator]

    def test_no_protection_outside_continuous(self) -> None:
        agent, _ = self._filled("trend-follower")
        assert agent.step(0.0, 0.0, _market(session="CLOSING_AUCTION")) == []

    def test_flat_position_cancels_protection(self) -> None:
        agent, m = self._filled("trend-follower")
        [o] = agent.step(0.0, 0.0, m)
        agent.on_ack(
            0.0,
            order_id="S1",
            tag=o.tag,
            accepted=True,
            code=None,
            reason="",
            request_tag=None,
        )
        agent.on_fill(
            order_id="E9",
            tag=None,
            symbol="AAPL",
            side="SELL",
            fill_qty=100,
            fill_price_ticks=1000,
            remaining=0,
        )
        assert agent.step(2.0, 2.0, m) == [
            CancelOrder(order_id="S1", tag=o.tag, symbol="AAPL")
        ]

    def test_replacement_is_rate_limited(self) -> None:
        agent, m = self._filled("trend-follower")
        [o] = agent.step(0.0, 0.0, m)
        agent.on_done(order_id=None, tag=o.tag)
        assert agent.step(1.5, 1.5, m) == []  # within PROTECTION_INTERVAL
        assert len(agent.step(6.0, 6.0, m)) == 1


class TestArrivals:
    def test_poisson_rate_and_exponential_gaps(self) -> None:
        p = replace(get_preset("noise-retail"), tempo=TempoSpec(60.0, 1, 1))  # 1/s
        agent = Agent("AI001", p, ["AAPL"], seed=11, now=0.0)
        gaps = [agent._interval(1.0) for _ in range(20_000)]
        mean = sum(gaps) / len(gaps)
        assert mean == pytest.approx(1.0, rel=0.03)
        # Exponential: P(gap > mean) = e^-1
        assert sum(g > 1.0 for g in gaps) / len(gaps) == pytest.approx(
            math.exp(-1), abs=0.01
        )

    def test_rate_scale_and_ceiling(self) -> None:
        p = replace(get_preset("noise-retail"), tempo=TempoSpec(60.0, 1, 1))
        agent = Agent("AI001", p, ["AAPL"], seed=11, now=0.0)
        agent.rate_scale = 4.0
        assert sum(
            agent._interval(1.0) for _ in range(20_000)
        ) / 20_000 == pytest.approx(0.25, rel=0.05)
        agent.rate_scale = 1e6
        assert sum(
            agent._interval(1.0) for _ in range(20_000)
        ) / 20_000 == pytest.approx(0.1, rel=0.05)


class TestIntraday:
    def test_u_shape(self) -> None:
        m = _market()
        m.phase_since, m.next_at = 0.0, 100.0
        ends = intraday_multiplier(m, 0.0), intraday_multiplier(m, 100.0)
        mid = intraday_multiplier(m, 50.0)
        assert ends[0] == pytest.approx(2.2 * 15 / 17) and ends[1] == ends[0]
        assert mid == pytest.approx(0.6 * 15 / 17)
        avg = sum(intraday_multiplier(m, x / 10) for x in range(1001)) / 1001
        assert avg == pytest.approx(1.0, abs=0.01)

    def test_unknown_boundaries_or_other_phase(self) -> None:
        assert intraday_multiplier(_market(), 5.0) == 1.0
        m = _market(session="PRE_OPEN")
        m.phase_since, m.next_at = 0.0, 100.0
        assert intraday_multiplier(m, 0.0) == 1.0


def test_summary_mentions_preset_and_types() -> None:
    agent = _agent()
    _run(agent, _market(), 5)
    s = agent.summary()
    assert "preset=noise-retail" in s and "types=LIMIT/DAY:" in s


def test_session_close_drops_twaps() -> None:
    agent = _agent("institutional")
    market = _market()
    for st in market.symbols.values():
        st.true_value = 1100.0  # 10% above the market: the value agent buys
    _run(agent, market, 10)
    assert agent.executor.twaps
    agent.on_session_closed()
    assert agent.executor.twaps == {}


def test_riskspec_defaults() -> None:
    assert RiskSpec().protection == "none"


def test_fok_kill_is_not_a_reject() -> None:
    agent = _agent()
    for _ in range(100):
        agent.on_ack(
            0.0,
            order_id="x",
            tag=None,
            accepted=False,
            code="INSUFFICIENT_LIQUIDITY",
            reason="Insufficient liquidity",
            request_tag=None,
        )
    assert agent.stats.killed == 100
    assert sum(agent.stats.rejected.values()) == 0 and agent.stats.breaker_trips == 0


class TestEndOfDay:
    def _order(self, tag: str, tif: TIF) -> LiveOrder:
        return LiveOrder(tag, "AAPL", "BUY", OrderType.LIMIT, tif, 5, 5, 990, 0.0)

    def test_drops_expired_orders_and_reports_the_day(self) -> None:
        agent, market = _agent(), _market()
        agent.orders.track(self._order("D", TIF.DAY))
        agent.orders.track(self._order("A", TIF.ATC))
        agent.orders.track(self._order("G", TIF.GTC))
        agent.stats.submitted = 3
        # bought 10 @ 9.80, sold 4 @ 10.10 -> realized 4 x 0.30
        agent.on_fill(
            order_id=None,
            tag=None,
            symbol="AAPL",
            side="BUY",
            fill_qty=10,
            fill_price_ticks=980,
            remaining=None,
        )
        agent.on_fill(
            order_id=None,
            tag=None,
            symbol="AAPL",
            side="SELL",
            fill_qty=4,
            fill_price_ticks=1010,
            remaining=None,
        )
        day = agent.end_of_day(market)
        assert list(agent.orders.orders) == ["G"]
        assert day["unseen_expiries"] == 2 and day["gtc_orders"] == 1
        assert (day["submitted"], day["fills"], day["filled_qty"]) == (3, 2, 14)
        assert day["gross_position"] == 6
        assert day["pnl_realized"] == pytest.approx(1.20)
        # 6 left at 9.80, marked at the last trade 10.00
        assert day["pnl_mtm"] == pytest.approx(1.20 + 6 * 0.20)

        agent.stats.submitted = 5
        nxt = agent.end_of_day(market)
        assert (nxt["submitted"], nxt["fills"], nxt["unseen_expiries"]) == (2, 0, 0)
