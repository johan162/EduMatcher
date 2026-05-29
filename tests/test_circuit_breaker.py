"""Tests for engine/circuit_breaker.py — per-symbol circuit breaker."""

from __future__ import annotations

from edumatcher.engine.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerLevel,
    CircuitBreakerState,
)


def _make_cb(
    *,
    reference_window_ns: int = 300_000_000_000,
    levels: list[CircuitBreakerLevel] | None = None,
) -> CircuitBreakerState:
    if levels is None:
        levels = [
            CircuitBreakerLevel(
                name="L1",
                price_shift_pct=0.07,
                halt_duration_ns=300_000_000_000,
                resumption_mode="AUCTION",
            ),
            CircuitBreakerLevel(
                name="L2",
                price_shift_pct=0.13,
                halt_duration_ns=900_000_000_000,
                resumption_mode="AUCTION",
            ),
            CircuitBreakerLevel(
                name="L3",
                price_shift_pct=0.20,
                halt_duration_ns=None,
                resumption_mode="AUCTION",
            ),
        ]
    cfg = CircuitBreakerConfig(
        symbol="MSFT",
        reference_window_ns=reference_window_ns,
        levels=levels,
    )
    return CircuitBreakerState(symbol="MSFT", config=cfg)


T0 = 1_000_000_000_000  # arbitrary base nanosecond timestamp


class TestRecordTrade:
    def test_single_trade_does_not_fire(self) -> None:
        cb = _make_cb()
        level = cb.record_trade(10000, T0)
        assert level is None

    def test_price_within_band_does_not_fire(self) -> None:
        cb = _make_cb()
        # Seed some history at 10000
        for i in range(5):
            cb.record_trade(10000, T0 + i * 1_000_000)
        # Price shift 6% < L1 threshold 7%
        level = cb.record_trade(10600, T0 + 5_000_000)
        assert level is None

    def test_l1_fires_for_moderate_move(self) -> None:
        cb = _make_cb()
        # Establish stable average at 10000
        for i in range(10):
            cb.record_trade(10000, T0 + i * 1_000_000)
        # +8% => L1 (>=7%, <13%)
        level = cb.record_trade(10800, T0 + 10_000_000)
        assert level is not None
        assert level.name == "L1"

    def test_l2_fires_for_larger_move(self) -> None:
        cb = _make_cb()
        for i in range(10):
            cb.record_trade(10000, T0 + i * 1_000_000)
        # +14% => L2
        level = cb.record_trade(11400, T0 + 10_000_000)
        assert level is not None
        assert level.name == "L2"

    def test_l3_fires_for_extreme_move(self) -> None:
        cb = _make_cb()
        for i in range(10):
            cb.record_trade(10000, T0 + i * 1_000_000)
        # +22% => L3
        level = cb.record_trade(12200, T0 + 10_000_000)
        assert level is not None
        assert level.name == "L3"

    def test_trigger_price_set_when_fired(self) -> None:
        cb = _make_cb()
        for i in range(5):
            cb.record_trade(10000, T0 + i * 1_000_000)
        cb.record_trade(10800, T0 + 5_000_000)
        assert cb.trigger_price == 10800
        assert cb.triggered_level == "L1"

    def test_reference_price_is_prior_rolling_average(self) -> None:
        cb = _make_cb()
        # All at 10000, prior average should be exactly 10000
        for i in range(5):
            cb.record_trade(10000, T0 + i * 1_000_000)
        # Trigger: reference is computed from prior history only.
        cb.record_trade(10800, T0 + 5_000_000)
        assert cb.reference_price == 10000

    def test_already_halted_does_not_double_fire(self) -> None:
        cb = _make_cb()
        for i in range(5):
            cb.record_trade(10000, T0 + i * 1_000_000)
        # Trigger and activate
        level = cb.record_trade(10800, T0 + 5_000_000)
        assert level is not None
        cb.activate(T0 + 5_000_000, level)
        assert cb.halted
        # A second extreme price should return False immediately
        fired_again = cb.record_trade(12200, T0 + 6_000_000)
        assert fired_again is None


class TestRollingWindow:
    def test_old_trades_trimmed(self) -> None:
        window_ns = 10_000_000  # tiny 10ms window
        cb = _make_cb(reference_window_ns=window_ns)
        # Record trades within the window
        for i in range(5):
            cb.record_trade(10000, T0 + i * 100_000)
        # Advance past the window so old trades are trimmed
        now = T0 + window_ns + 1_000_000
        # After trimming, history is empty, so no reference → no fire
        fired = cb.record_trade(99999, now)  # extreme price, but no prior history
        assert not fired
        # Only the new entry remains
        assert len(cb.trade_history) == 1

    def test_within_window_reference_used(self) -> None:
        window_ns = 10_000_000_000  # 10 seconds
        cb = _make_cb(reference_window_ns=window_ns)
        for i in range(5):
            cb.record_trade(10000, T0 + i * 100_000)
        # Still within window — 5-trade history gives ref=10000.
        # 8% shift crosses L1 threshold.
        level = cb.record_trade(10800, T0 + 500_000)
        assert level is not None
        assert level.name == "L1"


class TestActivateDeactivate:
    def test_activate_sets_halt_and_timestamps(self) -> None:
        level = CircuitBreakerLevel(
            name="L1",
            price_shift_pct=0.07,
            halt_duration_ns=60_000_000_000,
            resumption_mode="AUCTION",
        )
        cb = _make_cb(levels=[level])
        cb.activate(T0, level)
        assert cb.halted
        assert cb.halted_at_ns == T0
        assert cb.resume_at_ns == T0 + 60_000_000_000
        assert cb.active_resumption_mode == "AUCTION"

    def test_should_resume_before_duration_is_false(self) -> None:
        level = CircuitBreakerLevel(
            name="L1",
            price_shift_pct=0.07,
            halt_duration_ns=60_000_000_000,
            resumption_mode="AUCTION",
        )
        cb = _make_cb(levels=[level])
        cb.activate(T0, level)
        assert not cb.should_resume(T0 + 59_999_999_999)

    def test_should_resume_at_exact_time_is_true(self) -> None:
        level = CircuitBreakerLevel(
            name="L1",
            price_shift_pct=0.07,
            halt_duration_ns=60_000_000_000,
            resumption_mode="AUCTION",
        )
        cb = _make_cb(levels=[level])
        cb.activate(T0, level)
        assert cb.should_resume(T0 + 60_000_000_000)

    def test_should_resume_after_duration_is_true(self) -> None:
        level = CircuitBreakerLevel(
            name="L1",
            price_shift_pct=0.07,
            halt_duration_ns=60_000_000_000,
            resumption_mode="AUCTION",
        )
        cb = _make_cb(levels=[level])
        cb.activate(T0, level)
        assert cb.should_resume(T0 + 120_000_000_000)

    def test_level_with_no_duration_never_auto_resumes(self) -> None:
        level = CircuitBreakerLevel(
            name="L3",
            price_shift_pct=0.20,
            halt_duration_ns=None,
            resumption_mode="AUCTION",
        )
        cb = _make_cb(levels=[level])
        cb.activate(T0, level)
        assert not cb.should_resume(T0 + 999_999_999_999)

    def test_deactivate_clears_halt_state(self) -> None:
        level = CircuitBreakerLevel(
            name="L1",
            price_shift_pct=0.07,
            halt_duration_ns=60_000_000_000,
            resumption_mode="AUCTION",
        )
        cb = _make_cb(levels=[level])
        cb.activate(T0, level)
        cb.deactivate()
        assert not cb.halted
        assert cb.halted_at_ns is None
        assert cb.resume_at_ns is None
        assert cb.trigger_price is None
        assert cb.triggered_level is None

    def test_deactivate_keeps_reference_price(self) -> None:
        cb = _make_cb()
        for i in range(5):
            cb.record_trade(10000, T0 + i * 1_000_000)
        level = cb.record_trade(10800, T0 + 5_000_000)
        assert level is not None
        cb.activate(T0 + 5_000_000, level)
        ref = cb.reference_price
        cb.deactivate()
        assert cb.reference_price == ref  # kept for diagnostics

    def test_should_resume_returns_false_when_not_halted(self) -> None:
        cb = _make_cb()
        assert not cb.should_resume(T0 + 999_999_999_999)


class TestCircuitBreakerConfig:
    def test_default_config_values(self) -> None:
        cfg = CircuitBreakerConfig(symbol="X")
        assert cfg.reference_window_ns == 300_000_000_000
        assert cfg.levels == []
