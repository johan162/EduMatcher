"""ai_trader.market_state: prices in ticks, signals, session and reference data."""

from __future__ import annotations

import math

import pytest

from edumatcher.ai_trader.market_state import (
    TAU_FAST,
    WARMUP_OBSERVATIONS,
    MarketState,
    SymbolState,
)


def _book(bid: float | None, ask: float | None, last: float | None = None) -> dict:
    return {
        "tick_decimals": 2,
        "bids": [{"price": bid, "qty": 100, "count": 1}] if bid else [],
        "asks": [{"price": ask, "qty": 100, "count": 1}] if ask else [],
        "last_price": last,
    }


class TestPrices:
    def test_book_prices_become_ticks(self) -> None:
        m = MarketState()
        m.on_book("AAPL", _book(100.10, 100.30, 100.20), now=1.0)
        st = m.symbols["AAPL"]
        assert (st.best_bid, st.best_ask, st.last_trade) == (10010, 10030, 10020)
        assert st.mid == 10020
        assert st.updated_at == 1.0

    def test_tick_decimals_from_symbols_reply(self) -> None:
        m = MarketState()
        m.on_symbols(
            {"symbols": [{"symbol": "x", "tick_decimals": 4, "prev_close": 1.2345}]}
        )
        st = m.symbols["X"]
        assert st.ticks(1.2345) == 12345
        assert st.prev_close == 12345
        assert st.static_ref == 12345

    def test_one_sided_book_has_no_mid_but_a_reference(self) -> None:
        st = SymbolState("A")
        st.best_bid = 990
        assert st.mid is None
        assert st.reference() == 990

    def test_reference_falls_back_to_prev_close(self) -> None:
        st = SymbolState("A", prev_close=500)
        assert st.reference() == 500

    def test_auction_reference_prefers_indicative(self) -> None:
        st = SymbolState("A", best_bid=99, best_ask=101, indicative_price=105)
        assert st.reference(auction=True) == 105
        assert st.reference() == 100

    def test_null_last_price_keeps_trade_price(self) -> None:
        m = MarketState()
        m.on_trade({"symbol": "A", "price": 1.5, "aggressor_side": "BUY"}, now=1.0)
        m.on_book("A", _book(None, None, None), now=2.0)
        assert m.symbols["A"].last_trade == 150

    @pytest.mark.parametrize("bad", ["x", None, float("nan"), -1.0, 0.0])
    def test_garbage_prices_are_ignored(self, bad: object) -> None:
        m = MarketState()
        m.on_trade({"symbol": "A", "price": bad}, now=1.0)
        assert "A" not in m.symbols or m.symbols["A"].last_trade is None


class TestCollar:
    def test_no_collar_configured(self) -> None:
        assert SymbolState("A", static_ref=1000).collar_band() is None

    def test_static_and_dynamic_bands_intersect(self) -> None:
        st = SymbolState(
            "A",
            static_ref=1000,
            last_trade=1100,
            collar_static_pct=0.2,
            collar_dynamic_pct=0.02,
        )
        lo, hi = st.collar_band(margin=1.0)  # type: ignore[misc]
        assert (lo, hi) == (1078, 1122)

    def test_margin_shrinks_the_band(self) -> None:
        st = SymbolState("A", static_ref=1000, collar_static_pct=0.1)
        assert st.collar_band(margin=0.5) == (950, 1050)


class TestSignals:
    def _feed(self, st: SymbolState, prices: list[int], dt: float = 2.0) -> None:
        for i, p in enumerate(prices):
            st.observe(p, now=100.0 + i * dt)

    def test_neutral_until_warmed_up(self) -> None:
        st = SymbolState("A")
        self._feed(st, [1000 + i for i in range(WARMUP_OBSERVATIONS - 1)], dt=10.0)
        assert not st.warmed_up
        assert st.momentum_score() == 0.0
        assert st.reversion_score() == 0.0

    def test_warmup_needs_time_as_well_as_observations(self) -> None:
        st = SymbolState("A")
        self._feed(st, [1000] * (WARMUP_OBSERVATIONS + 5), dt=TAU_FAST / 1000)
        assert not st.warmed_up

    def test_uptrend_gives_positive_momentum_and_negative_reversion(self) -> None:
        st = SymbolState("A")
        # Flat for a while, then a steady climb of 0.5% per observation.
        prices = [1000] * 60 + [round(1000 * 1.005**i) for i in range(1, 40)]
        self._feed(st, prices)
        assert st.momentum_score() > 0.5
        assert st.reversion_score() < -0.5

    def test_downtrend_is_the_mirror_image(self) -> None:
        st = SymbolState("A")
        prices = [1000] * 60 + [round(1000 * 0.995**i) for i in range(1, 40)]
        self._feed(st, prices)
        assert st.momentum_score() < -0.5
        assert st.reversion_score() > 0.5

    def test_scores_are_clipped(self) -> None:
        st = SymbolState("A")
        self._feed(st, [1000] * 30 + [5000] * 5)
        assert -1.0 <= st.momentum_score() <= 1.0
        assert -1.0 <= st.reversion_score() <= 1.0

    def test_flat_price_is_neutral(self) -> None:
        st = SymbolState("A")
        self._feed(st, [1000] * 100)
        assert st.momentum_score() == 0.0
        assert st.reversion_score() == 0.0

    def test_variance_is_per_second(self) -> None:
        # Same returns observed twice as often must not double the rate.
        a, b = SymbolState("A"), SymbolState("B")
        for i in range(2000):
            p = 1000 if i % 2 == 0 else 1010
            a.observe(p, now=i * 2.0)
            b.observe(p, now=i * 4.0)
        assert a.var_rate == pytest.approx(2 * b.var_rate, rel=0.05)

    def test_flow_tracks_aggressor_side(self) -> None:
        st = SymbolState("A")
        for i in range(50):
            st.observe_flow("BUY", now=float(i))
        assert st.flow > 0.5
        for i in range(50, 400):
            st.observe_flow("SELL", now=float(i))
        assert st.flow < -0.9


class TestSession:
    def test_unknown_session_cannot_trade(self) -> None:
        assert MarketState().can_trade() is False

    def test_sessions_disabled_always_trades_as_continuous(self) -> None:
        m = MarketState()
        m.on_session_status({"state": "CLOSED", "sessions_enabled": False}, wall=0.0)
        assert m.can_trade() and m.phase == "CONTINUOUS"

    def test_closed_cannot_trade(self) -> None:
        m = MarketState()
        m.on_session_status({"state": "CLOSED", "sessions_enabled": True}, wall=0.0)
        assert not m.can_trade()
        assert m.on_session_state({"state": "PRE_OPEN"}, wall=5.0) is True
        assert m.can_trade() and m.phase_since == 5.0

    def test_next_transition_is_parsed(self) -> None:
        m = MarketState()
        m.on_session_state(
            {
                "state": "CONTINUOUS",
                "next": {"state": "CLOSING_AUCTION", "at": "2026-10-09T14:00:00Z"},
            },
            wall=0.0,
        )
        assert m.next_state == "CLOSING_AUCTION"
        assert m.next_at == pytest.approx(1791554400.0)

    def test_same_state_is_not_a_change(self) -> None:
        m = MarketState()
        m.on_session_state({"state": "CONTINUOUS"}, wall=1.0)
        assert m.on_session_state({"state": "CONTINUOUS"}, wall=2.0) is False
        assert m.phase_since == 1.0


class TestReference:
    def test_collar_and_order_limits(self) -> None:
        m = MarketState()
        m.on_reference(
            {
                "symbols": [
                    {
                        "symbol": "A",
                        "collar": {"static_band_pct": 0.2, "dynamic_band_pct": 0.05},
                        "order_limits": {
                            "max_order_qty": 500,
                            "max_order_value": 10000.0,
                        },
                    }
                ]
            }
        )
        st = m.symbols["A"]
        assert (st.collar_static_pct, st.collar_dynamic_pct) == (0.2, 0.05)
        assert (st.max_order_qty, st.max_order_value) == (500, 10000.0)

    def test_halts(self) -> None:
        m = MarketState()
        m.on_halt_status({"halted": [{"symbol": "a"}]})
        assert m.symbols["A"].halted
        m.on_halt("A", False)
        assert not m.symbols["A"].halted

    def test_indicative(self) -> None:
        m = MarketState()
        m.on_indicative(
            "A", {"eq_price": 1.23, "imbalance_side": "buy", "imbalance_qty": 7}
        )
        st = m.symbols["A"]
        assert (st.indicative_price, st.indicative_side, st.indicative_qty) == (
            123,
            "BUY",
            7,
        )
        m.clear_indicatives()
        assert st.indicative_price is None


def test_log_returns_not_raw_ticks() -> None:
    # A 1% move must score the same at price 100 and price 10 000.
    lo, hi = SymbolState("LO"), SymbolState("HI")
    for i in range(120):
        lo.observe(round(10000 * 1.001**i), now=i * 2.0)
        hi.observe(round(1000000 * 1.001**i), now=i * 2.0)
    assert math.isclose(lo.momentum_score(), hi.momentum_score(), abs_tol=0.05)


def test_sim_values_land_in_ticks_for_known_symbols_only() -> None:
    m = MarketState()
    m.get("AAPL").tick_decimals = 2
    m.on_sim_value(
        {
            "values": [
                {"symbol": "aapl", "value": 101.25},
                {"symbol": "NOPE", "value": 1.0},
            ]
        }
    )
    assert m.symbols["AAPL"].true_value == 10125.0
    assert "NOPE" not in m.symbols


def _news(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "N1",
        "scope": "SYMBOL",
        "targets": ["AAPL"],
        "kind": "EARNINGS",
        "status": "CONFIRMED",
        "headline": "h",
        "sentiment": 0.8,
        "related_id": "",
    }
    base.update(kw)
    return base


def test_news_lifecycle_in_the_market_state() -> None:
    m = MarketState()
    m.sectors = {"TECH": frozenset({"AAPL", "MSFT"})}
    rumour = m.on_news(
        _news(
            id="N1", status="RUMOUR", scope="SECTOR", targets=["TECH"], credibility=0.4
        ),
        now=0.0,
    )
    assert rumour is not None and rumour.symbols == frozenset({"AAPL", "MSFT"})
    assert m.rumour_tilt("MSFT") == pytest.approx(0.32) and m.rumour_tilt("XOM") == 0.0
    confirmed = m.on_news(
        _news(id="N2", scope="SECTOR", targets=["TECH"], related_id="N1"), now=1.0
    )
    assert confirmed is not None and confirmed.weight == 1.0 and not confirmed.rumour
    assert set(m.news) == {"N2"} and m.rumour_tilt("AAPL") == 0.0
    m.on_news(_news(id="N3", status="RUMOUR", sentiment=0.6, credibility=0.5), now=2.0)
    retraction = m.on_news(_news(id="N4", status="RETRACTED", related_id="N3"), now=3.0)
    assert retraction is not None
    assert (retraction.sentiment, retraction.weight) == (-0.6, 0.5)
    assert (
        m.on_news(_news(id="N5", status="RETRACTED", related_id="N99"), now=4.0) is None
    )
    market = m.on_news(_news(id="N6", scope="MARKET", targets=[]), now=5.0)
    assert market is not None and market.touches("ANYTHING")
    m.on_news(_news(id="N7"), now=5.0 + 1801.0)
    assert set(m.news) == {"N7"}  # old news forgotten


def test_news_sentiment_and_credibility_keep_sign_and_zero() -> None:
    m = MarketState()
    bad = m.on_news(_news(id="N1", sentiment=-0.7), now=0.0)
    assert bad is not None and bad.sentiment == -0.7
    doubted = m.on_news(_news(id="N2", status="RUMOUR", credibility=0.0), now=0.0)
    assert doubted is not None and doubted.weight == 0.0
