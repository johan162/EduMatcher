"""Strategies: *what* an agent believes, expressed as an Intent.

A strategy looks at the market and the agent's position and either does
nothing or says "I want to buy/sell this symbol, this urgently". How the
intent becomes orders is the execution style's job (execution.py); how big
and how often is the tempo's (preset.py).

Side choice follows v2 section 5.3: ``P(buy) = (1 + score * strength) / 2``
with ``score`` in [-1, 1], so a strategy leans without becoming
deterministic.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Protocol

from edumatcher.ai_trader.market_state import MarketState, SymbolState


@dataclass(frozen=True)
class Intent:
    symbol: str
    side: str  # "BUY" | "SELL"
    #: 0 = happy to wait for a fill, 1 = wants to trade now.
    urgency: float
    #: Multiplies the tempo's order size (conviction).
    size: float = 1.0
    #: Furthest price (ticks) the agent will pay (buy) or accept (sell) when
    #: it crosses; None = ``cross_ticks`` past the touch. An informed agent
    #: prices off what it believes the symbol is worth, not off the touch,
    #: or a 10% move would take a thousand one-tick steps.
    limit: int | None = None


@dataclass
class DecisionContext:
    rng: random.Random
    market: MarketState
    universe: list[str]
    position: Callable[[str], int]
    now: float = 0.0  # monotonic


class Strategy(Protocol):
    name: str

    def decide(self, ctx: DecisionContext) -> Intent | None: ...


def _priced(ctx: DecisionContext, symbol: str) -> SymbolState | None:
    st = ctx.market.symbols.get(symbol)
    if st is None or st.reference(auction=True) is None or st.halted:
        return None
    return st


def _side(rng: random.Random, score: float, strength: float) -> str:
    p_buy = (1.0 + score * strength) / 2.0
    return "BUY" if rng.random() < p_buy else "SELL"


@dataclass(frozen=True)
class NoiseStrategy:
    """Uninformed liquidity: random symbol, random side."""

    urgency: float = 0.3
    name: str = "noise"

    def decide(self, ctx: DecisionContext) -> Intent | None:
        if not ctx.universe:
            return None
        sym = ctx.rng.choice(ctx.universe)
        if _priced(ctx, sym) is None:
            return None
        return Intent(sym, _side(ctx.rng, 0.0, 0.0), self.urgency)


@dataclass(frozen=True)
class _SignalStrategy:
    """Look at ``sample`` symbols, act on the one with the strongest signal."""

    strength: float = 0.8
    sample: int = 3
    urgency: float = 0.5
    name: str = "signal"

    def score(self, st: SymbolState) -> float:  # pragma: no cover - abstract
        raise NotImplementedError

    def decide(self, ctx: DecisionContext) -> Intent | None:
        if not ctx.universe:
            return None
        k = min(self.sample, len(ctx.universe))
        best: tuple[float, str] | None = None
        for sym in ctx.rng.sample(ctx.universe, k):
            st = _priced(ctx, sym)
            if st is None:
                continue
            s = self.score(st)
            if best is None or abs(s) > abs(best[0]):
                best = (s, sym)
        if best is None:
            return None
        score, sym = best
        urgency = min(1.0, self.urgency * (0.5 + abs(score)))
        return Intent(sym, _side(ctx.rng, score, self.strength), urgency)


@dataclass(frozen=True)
class TrendStrategy(_SignalStrategy):
    """Chases momentum: fast average above slow average means buy."""

    name: str = "trend"

    def score(self, st: SymbolState) -> float:
        return st.momentum_score()


@dataclass(frozen=True)
class ReversionStrategy(_SignalStrategy):
    """Fades moves: price above its slow average means sell."""

    name: str = "reversion"

    def score(self, st: SymbolState) -> float:
        return st.reversion_score()


@dataclass
class ValueStrategy:
    """Trades the gap between price and (its own view of) the true value.

    The agent sees pm-market-sim's value V through a persistent bias of its
    own, ``V̂ = V·exp(ε)`` with ε ~ N(0, bias_std) per symbol, re-drawn now and
    then. It acts on the symbol, of ``sample`` looked at, whose
    ``|ln(V̂ / P)|`` is largest, once that exceeds ``threshold``: it buys
    below its value and sells above, more urgently and in more size the
    larger the gap (up to three times). Different biases are what make value
    agents disagree with each other, and so trade.
    """

    threshold: float = 0.004
    bias_std: float = 0.01
    #: Chance, each time a symbol is looked at, that its bias is re-drawn.
    redraw: float = 0.02
    sample: int = 5
    urgency: float = 0.4
    #: How far an open rumour moves the agent's view: sentiment x credibility x this.
    rumour_shift: float = 0.05
    name: str = "value"
    _bias: dict[str, float] = field(default_factory=dict, repr=False)

    def decide(self, ctx: DecisionContext) -> Intent | None:
        if not ctx.universe:
            return None
        best: tuple[float, str] | None = None
        for sym in ctx.rng.sample(ctx.universe, min(self.sample, len(ctx.universe))):
            st = _priced(ctx, sym)
            if st is None or st.true_value is None:
                continue
            price = st.reference(auction=True)
            if not price or price <= 0:
                continue
            bias = self._bias.get(sym)
            if bias is None or ctx.rng.random() < self.redraw:
                bias = self._bias[sym] = ctx.rng.gauss(0.0, self.bias_std)
            shift = self.rumour_shift * ctx.market.rumour_tilt(sym)
            gap = math.log(st.true_value / price) + bias + shift
            if best is None or abs(gap) > abs(best[0]):
                best = (gap, sym)
        if best is None or abs(best[0]) < self.threshold:
            return None
        gap, sym = best
        conviction = min(3.0, abs(gap) / self.threshold)
        price = ctx.market.symbols[sym].reference(auction=True)
        assert price is not None  # checked while sampling
        # Its view of the value, less the edge it insists on.
        edge = abs(gap) - self.threshold
        buy = gap > 0
        limit = price * math.exp(edge if buy else -edge)
        return Intent(
            sym,
            "BUY" if buy else "SELL",
            min(1.0, self.urgency * conviction),
            size=conviction,
            limit=math.floor(limit) if buy else math.ceil(limit),
        )


@dataclass
class NewsStrategy:
    """Trades the headlines, fast and in their direction.

    Each piece of news reaches this agent after its own lag (lognormal,
    median ``lag_sec``); from then on the agent's conviction is the news'
    |sentiment| times its weight (credibility for a rumour), halving every
    ``half_life_sec``. It trades the most convincing item touching its
    symbols while conviction exceeds ``threshold``: urgently, in size up to
    three times its usual, in the direction of the sentiment.
    """

    lag_sec: float = 5.0
    lag_sigma: float = 0.8
    half_life_sec: float = 120.0
    threshold: float = 0.15
    urgency: float = 0.8
    #: Log move it expects from news of full conviction; it pays up to that
    #: much (times its conviction) beyond the price it first saw.
    move: float = 0.08
    name: str = "news"
    _lags: dict[str, float] = field(default_factory=dict, repr=False)
    #: (news id, symbol) -> reference price when it first acted on it.
    _anchors: dict[tuple[str, str], int] = field(default_factory=dict, repr=False)

    def _lag(self, ctx: DecisionContext, news_id: str) -> float:
        lag = self._lags.get(news_id)
        if lag is None:
            lag = self._lags[news_id] = self.lag_sec * math.exp(
                ctx.rng.gauss(0.0, self.lag_sigma)
            )
            if len(self._lags) > 1000:  # forget the oldest
                self._lags.pop(next(iter(self._lags)))
        return lag

    def decide(self, ctx: DecisionContext) -> Intent | None:
        if not ctx.universe:
            return None
        best: tuple[float, float, list[str], str] | None = None
        for item in ctx.market.news.values():
            age = ctx.now - item.seen_at - self._lag(ctx, item.news_id)
            if age < 0:
                continue
            conviction = (
                abs(item.sentiment) * item.weight * 0.5 ** (age / self.half_life_sec)
            )
            if best is not None and conviction <= best[0]:
                continue
            symbols = [s for s in ctx.universe if item.touches(s)]
            if symbols:
                best = (conviction, item.sentiment, symbols, item.news_id)
        if best is None or best[0] < self.threshold:
            return None
        conviction, sentiment, symbols, news_id = best
        sym = ctx.rng.choice(symbols)
        st = _priced(ctx, sym)
        if st is None:
            return None
        price = st.reference(auction=True)
        assert price is not None  # _priced checked it
        # Anchored on the price before it acted, so its own buying does not
        # ratchet its target up.
        anchor = self._anchors.setdefault((news_id, sym), price)
        if len(self._anchors) > 1000:  # forget the oldest
            self._anchors.pop(next(iter(self._anchors)))
        buy = sentiment > 0
        limit = anchor * math.exp(self.move * conviction * (1 if buy else -1))
        strength = min(3.0, conviction / self.threshold)
        return Intent(
            sym,
            "BUY" if buy else "SELL",
            min(1.0, self.urgency * strength),
            size=strength,
            limit=math.floor(limit) if buy else math.ceil(limit),
        )


STRATEGIES: dict[str, type] = {
    "noise": NoiseStrategy,
    "trend": TrendStrategy,
    "reversion": ReversionStrategy,
    "value": ValueStrategy,
    "news": NewsStrategy,
}
