"""ai_trader.strategies: side lean follows the signal, noise stays balanced."""

from __future__ import annotations

import math
import random

from edumatcher.ai_trader.market_state import MarketState, SymbolState
from edumatcher.ai_trader.strategies import (
    DecisionContext,
    NoiseStrategy,
    ReversionStrategy,
    NewsStrategy,
    TrendStrategy,
    ValueStrategy,
)


def _trending_market(
    up: bool, symbols: tuple[str, ...] = ("A", "B", "C")
) -> MarketState:
    m = MarketState()
    step = 1.005 if up else 0.995
    for sym in symbols:
        st = m.get(sym)
        prices = [1000] * 60 + [round(1000 * step**i) for i in range(1, 40)]
        for i, p in enumerate(prices):
            st.observe(p, now=100.0 + 2 * i)
        st.best_bid, st.best_ask = prices[-1] - 1, prices[-1] + 1
    return m


def _ctx(m: MarketState, seed: int = 7) -> DecisionContext:
    return DecisionContext(
        rng=random.Random(seed),
        market=m,
        universe=sorted(m.symbols),
        position=lambda s: 0,
    )


def _buy_share(strategy: object, m: MarketState, n: int = 4000) -> float:
    ctx = _ctx(m)
    buys = total = 0
    for _ in range(n):
        intent = strategy.decide(ctx)  # type: ignore[attr-defined]
        assert intent is not None
        total += 1
        buys += intent.side == "BUY"
    return buys / total


def test_trend_buys_an_uptrend() -> None:
    assert _buy_share(TrendStrategy(strength=0.8), _trending_market(True)) >= 0.70


def test_trend_sells_a_downtrend() -> None:
    assert _buy_share(TrendStrategy(strength=0.8), _trending_market(False)) <= 0.30


def test_reversion_sells_an_uptrend() -> None:
    assert _buy_share(ReversionStrategy(strength=0.8), _trending_market(True)) <= 0.30


def test_noise_is_balanced() -> None:
    share = _buy_share(NoiseStrategy(), _trending_market(True), n=10_000)
    assert 0.47 <= share <= 0.53


def test_zero_strength_ignores_the_signal() -> None:
    share = _buy_share(TrendStrategy(strength=0.0), _trending_market(True), n=10_000)
    assert 0.47 <= share <= 0.53


def test_unpriced_and_halted_symbols_are_skipped() -> None:
    m = MarketState()
    m.get("NOPRICE")
    halted = m.get("HALTED")
    halted.best_bid, halted.best_ask, halted.halted = 99, 101, True
    ctx = _ctx(m)
    assert NoiseStrategy().decide(ctx) is None or False
    for _ in range(50):
        assert TrendStrategy().decide(ctx) is None


def test_signal_strategy_picks_the_strongest_symbol() -> None:
    m = _trending_market(True, ("UP",))
    flat = m.get("FLAT")
    for i in range(100):
        flat.observe(1000, now=100.0 + 2 * i)
    flat.best_bid, flat.best_ask = 999, 1001
    picks = {TrendStrategy(sample=2).decide(_ctx(m, seed=s)).symbol for s in range(30)}  # type: ignore[union-attr]
    assert picks == {"UP"}


def test_same_seed_same_decisions() -> None:
    m = _trending_market(True)
    a = [TrendStrategy().decide(_ctx(m, seed=3)) for _ in range(1)]
    b = [TrendStrategy().decide(_ctx(m, seed=3)) for _ in range(1)]
    assert a == b


def test_empty_universe() -> None:
    ctx = DecisionContext(random.Random(1), MarketState(), [], lambda s: 0)
    assert NoiseStrategy().decide(ctx) is None
    assert TrendStrategy().decide(ctx) is None


def test_symbolstate_type_is_reused() -> None:
    assert isinstance(_trending_market(True).symbols["A"], SymbolState)


def _valued(values: dict[str, float | None]) -> MarketState:
    m = MarketState()
    for sym, value in values.items():
        st = m.get(sym)
        st.best_bid, st.best_ask = 999, 1001  # mid 1000 ticks
        st.true_value = value
    return m


def test_value_needs_a_true_value() -> None:
    assert ValueStrategy().decide(_ctx(_valued({"A": None}))) is None


def test_value_buys_below_and_sells_above() -> None:
    no_bias = ValueStrategy(bias_std=0.0)
    cheap = no_bias.decide(_ctx(_valued({"A": 1020.0})))
    assert cheap is not None and (cheap.side, cheap.symbol) == ("BUY", "A")
    rich = ValueStrategy(bias_std=0.0).decide(_ctx(_valued({"A": 980.0})))
    assert rich is not None and rich.side == "SELL"


def test_value_holds_inside_the_threshold() -> None:
    s = ValueStrategy(bias_std=0.0, threshold=0.004)
    assert s.decide(_ctx(_valued({"A": 1003.0}))) is None  # 0.3% gap


def test_value_conviction_scales_size_and_urgency_capped() -> None:
    s = ValueStrategy(bias_std=0.0, threshold=0.004, urgency=0.4)
    small = s.decide(_ctx(_valued({"A": 1006.0})))  # ~1.5x threshold
    big = s.decide(_ctx(_valued({"A": 1200.0})))  # far beyond
    assert small is not None and big is not None
    assert 1.4 < small.size < 1.6 and big.size == 3.0
    assert big.urgency == 1.0 and small.urgency < big.urgency


def test_value_picks_the_widest_gap() -> None:
    s = ValueStrategy(bias_std=0.0, sample=3)
    intent = s.decide(_ctx(_valued({"A": 1010.0, "B": 950.0, "C": 1001.0})))
    assert intent is not None and (intent.symbol, intent.side) == ("B", "SELL")


def test_value_bias_persists_until_redrawn() -> None:
    m = _valued({"A": 1000.0})
    sticky = ValueStrategy(bias_std=0.05, redraw=0.0, threshold=1e-6)
    ctx = _ctx(m)
    sides = {sticky.decide(ctx).side for _ in range(50)}  # type: ignore[union-attr]
    assert len(sides) == 1  # one agent, one view
    agents = [
        ValueStrategy(bias_std=0.05, redraw=0.0, threshold=1e-6) for _ in range(40)
    ]
    views = {a.decide(_ctx(m, seed=i)).side for i, a in enumerate(agents)}  # type: ignore[union-attr]
    assert views == {"BUY", "SELL"}  # agents disagree, so they trade


def test_value_view_shifts_with_open_rumours() -> None:
    m = _valued({"A": 1000.0})
    m.sectors = {}
    m.on_news(
        {
            "id": "N1",
            "scope": "SYMBOL",
            "targets": ["A"],
            "status": "RUMOUR",
            "sentiment": 1.0,
            "credibility": 0.8,
            "kind": "MNA",
            "headline": "",
        },
        now=0.0,
    )
    s = ValueStrategy(bias_std=0.0, rumour_shift=0.05)
    intent = s.decide(_ctx(m))
    assert intent is not None and intent.side == "BUY"  # 4% richer in its eyes


def _newsy(sentiment: float = 0.9, weight_key: str = "CONFIRMED") -> MarketState:
    m = _valued({"A": 1000.0, "B": 1000.0})
    payload = {
        "id": "N1",
        "scope": "SYMBOL",
        "targets": ["A"],
        "status": weight_key,
        "sentiment": sentiment,
        "kind": "EARNINGS",
        "headline": "",
    }
    if weight_key == "RUMOUR":
        payload["credibility"] = 0.5
    m.on_news(payload, now=100.0)
    return m


def test_news_trader_waits_for_its_lag_then_follows_the_sentiment() -> None:
    s = NewsStrategy(lag_sec=10.0, lag_sigma=0.0, half_life_sec=60.0, threshold=0.15)
    m = _newsy(sentiment=-0.9)
    ctx = _ctx(m)
    ctx.now = 105.0
    assert s.decide(ctx) is None  # not heard yet
    ctx.now = 111.0
    intent = s.decide(ctx)
    assert intent is not None and (intent.symbol, intent.side) == ("A", "SELL")
    assert intent.size == 3.0 and intent.urgency == 1.0
    ctx.now = 110.0 + 60.0 * 3  # three half-lives: 0.9/8 < 0.15
    assert s.decide(ctx) is None


def test_news_trader_weighs_rumours_by_credibility() -> None:
    s = NewsStrategy(lag_sec=0.0, lag_sigma=0.0, threshold=0.5)
    ctx = _ctx(_newsy(sentiment=0.9, weight_key="RUMOUR"))  # 0.45 < 0.5
    ctx.now = 101.0
    assert s.decide(ctx) is None
    ctx2 = _ctx(_newsy(sentiment=0.9))
    ctx2.now = 101.0
    assert s.decide(ctx2) is not None


def test_news_trader_ignores_news_outside_its_universe() -> None:
    s = NewsStrategy(lag_sec=0.0, lag_sigma=0.0)
    m = _newsy()
    ctx = DecisionContext(
        rng=random.Random(1), market=m, universe=["B"], position=lambda _s: 0, now=200.0
    )
    assert s.decide(ctx) is None


def test_news_trader_lags_differ_between_agents() -> None:
    lags = {
        round(NewsStrategy()._lag(_ctx(_newsy(), seed=i), "N1"), 3) for i in range(20)
    }
    assert len(lags) == 20


def test_value_limit_is_its_view_less_the_threshold() -> None:
    # Value 10% above the 1000-tick mid: pay up to value * exp(-threshold),
    # not one tick past the touch -- otherwise a jump in the value takes a
    # thousand one-tick orders to price in.
    s = ValueStrategy(bias_std=0.0, threshold=0.004)
    buy = s.decide(_ctx(_valued({"A": 1100.0})))
    assert buy is not None and buy.limit == int(1100.0 * math.exp(-0.004))
    sell = ValueStrategy(bias_std=0.0, threshold=0.004).decide(
        _ctx(_valued({"A": 900.0}))
    )
    assert sell is not None and sell.limit == math.ceil(900.0 * math.exp(0.004))


def test_news_limit_is_anchored_on_the_price_it_first_saw() -> None:
    s = NewsStrategy(lag_sec=0.0, lag_sigma=0.0, half_life_sec=1e6, move=0.08)
    m = _newsy(sentiment=0.9)
    ctx = _ctx(m)
    ctx.now = 101.0
    first = s.decide(ctx)
    assert first is not None and first.side == "BUY"
    assert first.limit == math.floor(1000 * math.exp(0.08 * 0.9 * 0.5 ** (1 / 1e6)))
    # Its own buying lifts the mid; the target stays where it was.
    m.symbols["A"].best_bid, m.symbols["A"].best_ask = 1049, 1051
    again = s.decide(ctx)
    assert again is not None and again.limit == first.limit
