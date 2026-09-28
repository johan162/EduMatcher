"""Tests for the ``passive`` pricing strategy (step behind others + fade).

See docs/user-guide/100-mm-bot.md, "The passive strategy". Prices below use
tick 0.01, gap 0.10, so with mid 100.00 the home quote is 99.95 / 100.05.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.mm_bot.bot import BotState, MMBot, _others_levels
from edumatcher.mm_bot.params import TIER2_DEFAULTS, validate_symbol_params
from edumatcher.mm_bot.pricer import PassiveParams, PassivePricer, create_strategy

TICK = 0.01


def _params(**overrides: Any) -> PassiveParams:
    values: dict[str, Any] = {
        "retreat_ticks": 5,
        "behind_ticks": 1,
        "min_cover_qty": 1,
        "fade_ticks": 2,
        "fade_sec": 3.0,
    }
    values.update(overrides)
    return PassiveParams(**values)


def _pricer(
    max_spread_ticks: int | None = None, drift_ticks: int = 3, **overrides: Any
) -> PassivePricer:
    p = PassivePricer(
        tick_size=TICK,
        gap=0.10,
        drift_ticks=drift_ticks,
        params=_params(**overrides),
        max_spread_ticks=max_spread_ticks,
    )
    p.set_mid(100.0)
    return p


# ========================================================================
# Construction and factory
# ========================================================================


class TestConstruction:
    def test_factory_builds_passive(self) -> None:
        strategy = create_strategy(
            "passive", tick_size=TICK, gap=0.10, drift_ticks=3, passive=_params()
        )
        assert isinstance(strategy, PassivePricer)

    def test_factory_without_params_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="PassiveParams"):
            create_strategy("passive", tick_size=TICK, gap=0.10, drift_ticks=3)

    @pytest.mark.parametrize(
        "key,value",
        [
            ("retreat_ticks", -1),
            ("behind_ticks", 0),
            ("min_cover_qty", 0),
            ("fade_ticks", -1),
            ("fade_sec", -0.5),
        ],
    )
    def test_out_of_range_knob_is_rejected(self, key: str, value: Any) -> None:
        with pytest.raises(ValueError, match=key):
            _pricer(**{key: value})


class TestParamsValidation:
    def _values(self, **overrides: Any) -> dict[str, Any]:
        return {**TIER2_DEFAULTS, "strategy": "passive", **overrides}

    def test_defaults_validate(self) -> None:
        out = validate_symbol_params("AAPL", self._values())
        assert out["retreat_ticks"] == 5
        assert out["fade_sec"] == 3.0

    @pytest.mark.parametrize(
        "key,value",
        [
            ("retreat_ticks", -1),
            ("behind_ticks", 0),
            ("min_cover_qty", 0),
            ("fade_ticks", -1),
            ("fade_sec", -1.0),
            ("behind_ticks", 1.5),
        ],
    )
    def test_bad_value_names_symbol_and_key(self, key: str, value: Any) -> None:
        with pytest.raises(ValueError, match=rf"\[AAPL\] {key}"):
            validate_symbol_params("AAPL", self._values(**{key: value}))


# ========================================================================
# B — stepping behind other traders
# ========================================================================


class TestStepBehind:
    def test_empty_book_quotes_home(self) -> None:
        p = _pricer()
        p.update_book([], [])
        assert p.compute_prices() == (99.95, 100.05)

    def test_mid_kept_when_book_empty(self) -> None:
        p = _pricer()
        p.update_book([], [])
        assert p.mid_price == pytest.approx(100.0)

    def test_other_bid_inside_band_pushes_bid_behind_it(self) -> None:
        p = _pricer()
        # Other bid at 99.93 (band is 99.90..99.95); others' ask far away
        # keeps the mid near 100 on the other side.
        p.update_book([(99.93, 100)], [(100.07, 100)])
        bid, ask = p.compute_prices()
        # mid = 100.00; home bid 99.95; behind 99.93 by one tick.
        assert bid == pytest.approx(99.92)
        # Other ask at 100.07 is inside the ask band (100.05..100.10).
        assert ask == pytest.approx(100.08)

    def test_other_bid_better_than_home_keeps_home(self) -> None:
        p = _pricer()
        p.update_book([(99.99, 100)], [(100.01, 100)])
        bid, ask = p.compute_prices()
        # mid 100.00: others are tighter than home — stay at home, which is
        # already behind them. Never quote tighter than gap.
        assert bid == pytest.approx(99.95)
        assert ask == pytest.approx(100.05)

    def test_retreat_is_bounded_by_band(self) -> None:
        p = _pricer(retreat_ticks=2)
        # Others' bid right at the band floor (99.93): join it, don't go below.
        p.update_book([(99.93, 100)], [(100.07, 100)])
        bid, ask = p.compute_prices()
        assert bid == pytest.approx(99.93)
        assert ask == pytest.approx(100.07)

    def test_liquidity_outside_band_does_not_cover(self) -> None:
        p = _pricer(retreat_ticks=2)
        p.update_book([(99.80, 1000)], [(100.20, 1000)])
        # mid 100.00, nothing within 2 ticks of home -> the MM is the market.
        assert p.compute_prices() == (99.95, 100.05)

    def test_min_cover_qty_threshold(self) -> None:
        p = _pricer(min_cover_qty=300)
        p.update_book([(99.94, 100), (99.92, 100)], [(100.06, 400)])
        bid, ask = p.compute_prices()
        assert bid == pytest.approx(99.95)  # 200 < 300: not covered
        assert ask == pytest.approx(100.07)  # 400 >= 300: covered

    def test_behind_ticks(self) -> None:
        p = _pricer(behind_ticks=3)
        p.update_book([(99.95, 100)], [(100.05, 100)])
        bid, ask = p.compute_prices()
        assert bid == pytest.approx(99.92)
        assert ask == pytest.approx(100.08)

    def test_retreat_zero_behaves_like_symmetric_at_home(self) -> None:
        p = _pricer(retreat_ticks=0, fade_ticks=0)
        p.update_book([(99.95, 100)], [(100.05, 100)])
        assert p.compute_prices() == (99.95, 100.05)

    def test_obligation_narrows_band(self) -> None:
        # Home spread is 10 ticks; a 14-tick obligation leaves 2 per side.
        p = _pricer(max_spread_ticks=14)
        # Others at the narrowed band edge: behind would be 99.92, clamped.
        p.update_book([(99.93, 100)], [(100.07, 100)])
        bid, ask = p.compute_prices()
        assert bid == pytest.approx(99.93)
        assert ask == pytest.approx(100.07)
        assert round((ask - bid) / TICK) <= 14


# ========================================================================
# E — fading after a fill
# ========================================================================


class TestFade:
    def test_fade_widens_only_the_hit_side(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p = _pricer()
        p.update_book([], [])
        monkeypatch.setattr("edumatcher.mm_bot.pricer.time.monotonic", lambda: 10.0)
        p.on_fill("BID", 10.0)
        assert p.compute_prices() == (99.93, 100.05)

    def test_fade_expires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = _pricer()
        p.update_book([], [])
        p.on_fill("ASK", 10.0)
        monkeypatch.setattr("edumatcher.mm_bot.pricer.time.monotonic", lambda: 13.0)
        assert p.compute_prices() == (99.95, 100.05)

    def test_fade_clamped_to_band(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = _pricer(retreat_ticks=1, fade_ticks=5)
        p.update_book([], [])
        monkeypatch.setattr("edumatcher.mm_bot.pricer.time.monotonic", lambda: 10.0)
        p.on_fill("ASK", 10.0)
        assert p.compute_prices() == (99.95, 100.06)

    @pytest.mark.parametrize("key", ["fade_ticks", "fade_sec"])
    def test_zero_disables_fade(
        self, monkeypatch: pytest.MonkeyPatch, key: str
    ) -> None:
        p = _pricer(**{key: 0})
        p.update_book([], [])
        monkeypatch.setattr("edumatcher.mm_bot.pricer.time.monotonic", lambda: 10.0)
        p.on_fill("BID", 10.0)
        assert p.compute_prices() == (99.95, 100.05)


# ========================================================================
# When to requote
# ========================================================================


class TestRequoteDue:
    def test_nothing_quoted_yet(self) -> None:
        assert _pricer().requote_due(0.0) is False

    def test_unchanged_book_is_not_due(self) -> None:
        p = _pricer()
        p.update_book([], [])
        p.compute_prices()
        assert p.requote_due(0.0) is False

    def test_side_becoming_covered_is_due(self) -> None:
        p = _pricer()
        p.update_book([], [])
        p.compute_prices()
        p.update_book([(99.95, 100)], [])
        assert p.requote_due(0.0) is True

    def test_covered_side_must_step_back_immediately(self) -> None:
        p = _pricer(drift_ticks=10)
        p.update_book([(99.94, 100)], [(100.06, 100)])
        p.compute_prices()  # bid 99.93
        p.update_book([(99.93, 100)], [(100.06, 100)])
        # Only half a tick of mid move, far under drift — but the MM would
        # now be level with the trader it yields to.
        assert p.requote_due(0.0) is True

    def test_covered_side_moves_up_lazily(self) -> None:
        p = _pricer(drift_ticks=3)
        p.update_book([(99.92, 100)], [(100.08, 100)])
        p.compute_prices()  # bid 99.91, ask 100.09
        p.update_book([(99.93, 100)], [(100.08, 100)])
        assert p.requote_due(0.0) is False

    def test_fade_expiry_is_due(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = _pricer()
        p.update_book([], [])
        p.on_fill("BID", 0.0)
        monkeypatch.setattr("edumatcher.mm_bot.pricer.time.monotonic", lambda: 1.0)
        p.compute_prices()  # faded
        assert p.requote_due(2.0) is False
        assert p.requote_due(3.5) is True

    def test_has_drifted_falls_back_before_first_quote(self) -> None:
        p = _pricer(drift_ticks=3)
        p.set_mid(100.05)
        assert p.has_drifted(100.0) is True


# ========================================================================
# Own-quote exclusion
# ========================================================================


class TestOthersLevels:
    def test_removes_sole_own_order(self) -> None:
        levels = [
            {"price": 99.95, "qty": 500, "count": 1},
            {"price": 99.9, "qty": 7, "count": 1},
        ]
        assert _others_levels(levels, 99.95, 500, TICK) == [(99.9, 7)]

    def test_subtracts_from_shared_level(self) -> None:
        levels = [{"price": 99.95, "qty": 700, "count": 2}]
        assert _others_levels(levels, 99.95, 500, TICK) == [(99.95, 200)]

    def test_level_smaller_than_own_is_untouched(self) -> None:
        levels = [{"price": 99.95, "qty": 100, "count": 1}]
        assert _others_levels(levels, 99.95, 500, TICK) == [(99.95, 100)]

    def test_no_own_quote(self) -> None:
        levels = [{"price": 99.95, "qty": 100, "count": 1}]
        assert _others_levels(levels, None, 0, TICK) == [(99.95, 100)]


# ========================================================================
# MMBot integration
# ========================================================================


class _Sock:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)


def _bot() -> MMBot:
    bot = MMBot(
        gateway_id="MM_AAPL_01",
        symbol="AAPL",
        strategy="passive",
        gap=0.10,
        gap_was_explicit=True,
        qty=500,
        drift_ticks=3,
        reissue_delay_ms=200,
        tif="DAY",
        heartbeat_interval_sec=5.0,
        startup_session_timeout_sec=0.1,
        bootstrap_timeout_sec=0.1,
        cancel_timeout_sec=1.0,
        shutdown_timeout_sec=0.1,
        qlegs_reconcile_interval_sec=15.0,
        initial_min=None,
        initial_max=None,
        engine_pull="tcp://127.0.0.1:5555",
        engine_pub="tcp://127.0.0.1:5556",
        verbose=False,
    )
    bot._push_sock = _Sock()
    st = bot._symbols_state["AAPL"]
    pricer = _pricer()
    pricer.update_book([], [])
    st.pricer = pricer
    return bot


def _book(
    bids: list[tuple[float, int, int]], asks: list[tuple[float, int, int]]
) -> dict[str, Any]:
    return {
        "bids": [{"price": p, "qty": q, "count": c} for p, q, c in bids],
        "asks": [{"price": p, "qty": q, "count": c} for p, q, c in asks],
    }


class TestMMBotPassive:
    def test_passive_knobs_reach_symbol_state(self) -> None:
        bot = MMBot(
            gateway_id="MM_AAPL_01",
            symbol="AAPL",
            strategy="passive",
            gap=0.10,
            gap_was_explicit=True,
            qty=500,
            drift_ticks=3,
            reissue_delay_ms=200,
            tif="DAY",
            heartbeat_interval_sec=5.0,
            startup_session_timeout_sec=0.1,
            bootstrap_timeout_sec=0.1,
            cancel_timeout_sec=1.0,
            shutdown_timeout_sec=0.1,
            qlegs_reconcile_interval_sec=15.0,
            initial_min=None,
            initial_max=None,
            engine_pull="tcp://127.0.0.1:5555",
            engine_pub="tcp://127.0.0.1:5556",
            verbose=False,
            overrides={"AAPL": {"retreat_ticks": 9, "fade_sec": 1.5}},
        )
        st = bot._symbols_state["AAPL"]
        assert st.retreat_ticks == 9
        assert st.fade_sec == 1.5
        assert st.behind_ticks == TIER2_DEFAULTS["behind_ticks"]

    def test_send_quote_records_own_legs(self) -> None:
        bot = _bot()
        bot._send_quote("AAPL")
        st = bot._symbols_state["AAPL"]
        assert (st.own_bid_price, st.own_ask_price) == (99.95, 100.05)
        assert st.own_bid_qty == st.own_ask_qty == 500

    def test_own_quote_in_book_does_not_cover_itself(self) -> None:
        bot = _bot()
        bot._send_quote("AAPL")
        st = bot._symbols_state["AAPL"]
        st.state = BotState.QUOTING
        st.quote_id = "q1"
        sent_before = len(bot._push_sock.sent)  # type: ignore[union-attr]
        bot._handle_book(_book([(99.95, 500, 1)], [(100.05, 500, 1)]), "AAPL")
        assert st.pricer is not None
        assert st.pricer.requote_due(0.0) is False  # type: ignore[attr-defined]
        assert len(bot._push_sock.sent) == sent_before  # type: ignore[union-attr]

    def test_other_trader_joining_triggers_step_back(self) -> None:
        bot = _bot()
        bot._send_quote("AAPL")
        st = bot._symbols_state["AAPL"]
        st.state = BotState.QUOTING
        st.quote_id = "q1"
        bot._dispatch("book.AAPL", _book([(99.95, 600, 2)], [(100.05, 500, 1)]))
        # 100 from someone else at our price: step behind and cancel/reissue.
        assert st.state == BotState.REPRICING
        assert st.awaiting_cancel_for_reissue is True

    def test_fill_reduces_own_leg_and_starts_fade(self) -> None:
        bot = _bot()
        bot._send_quote("AAPL")
        st = bot._symbols_state["AAPL"]
        st.bid_order_id, st.ask_order_id = "b1", "a1"
        bot._handle_order_fill({"order_id": "b1", "fill_qty": 200, "fill_price": 99.95})
        assert st.own_bid_qty == 300
        assert st.pricer is not None
        assert st.pricer._fade_until["BID"] > 0  # type: ignore[attr-defined]  # noqa: SLF001

    def test_clear_quote_state_forgets_own_legs(self) -> None:
        bot = _bot()
        bot._send_quote("AAPL")
        bot._clear_quote_state("AAPL")
        st = bot._symbols_state["AAPL"]
        assert st.own_bid_price is None and st.own_bid_qty == 0

    def test_tick_requotes_when_fade_expires(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot = _bot()
        st = bot._symbols_state["AAPL"]
        assert st.pricer is not None
        st.pricer.on_fill("BID", 0.0)  # type: ignore[attr-defined]
        monkeypatch.setattr("edumatcher.mm_bot.pricer.time.monotonic", lambda: 1.0)
        bot._send_quote("AAPL")  # faded quote
        st.state = BotState.QUOTING
        st.quote_id = "q1"
        bot._tick_symbol("AAPL", 2.0)
        assert st.state == BotState.QUOTING
        bot._tick_symbol("AAPL", 3.5)
        assert bot._symbols_state["AAPL"].state == BotState.REPRICING
