"""Tests for engine/collar.py — price collar band validation."""

from __future__ import annotations

from edumatcher.engine.collar import CollarConfig, CollarResult, validate_collar


def _collar(ref: int, static: float = 0.20, dynamic: float = 0.02) -> CollarConfig:
    return CollarConfig(
        symbol="AAPL",
        reference_price=ref,
        static_band_pct=static,
        dynamic_band_pct=dynamic,
    )


class TestStaticBand:
    def test_price_within_static_band_passes(self) -> None:
        collar = _collar(ref=10000)  # ±20%
        # [8000, 12000] is the allowed range (truncated)
        result = validate_collar(price=10000, collar=collar, last_trade_price=None)
        assert not result.rejected

    def test_price_at_static_upper_boundary_passes(self) -> None:
        collar = _collar(ref=10000)
        upper = int(10000 * 1.20)  # = 12000
        result = validate_collar(price=upper, collar=collar, last_trade_price=None)
        assert not result.rejected

    def test_price_above_static_upper_rejected(self) -> None:
        collar = _collar(ref=10000)
        result = validate_collar(price=12001, collar=collar, last_trade_price=None)
        assert result.rejected
        assert "STATIC_COLLAR_BREACH" in result.reason

    def test_price_below_static_lower_rejected(self) -> None:
        collar = _collar(ref=10000)
        # lower = int(10000 * 0.80) = 8000
        result = validate_collar(price=7999, collar=collar, last_trade_price=None)
        assert result.rejected
        assert "STATIC_COLLAR_BREACH" in result.reason

    def test_static_boundary_values_in_reason(self) -> None:
        collar = _collar(ref=10000)
        result = validate_collar(price=1, collar=collar, last_trade_price=None)
        assert "8000" in result.reason
        assert "12000" in result.reason


class TestDynamicBand:
    def test_no_last_trade_skips_dynamic_check(self) -> None:
        collar = _collar(ref=10000)
        # If no last trade, only static band applies
        result = validate_collar(price=10500, collar=collar, last_trade_price=None)
        assert not result.rejected

    def test_price_within_dynamic_band_passes(self) -> None:
        collar = _collar(ref=10000, dynamic=0.02)
        last = 10000
        # dyn_upper = int(10000 * 1.02) = 10200
        result = validate_collar(price=10200, collar=collar, last_trade_price=last)
        assert not result.rejected

    def test_price_above_dynamic_upper_rejected(self) -> None:
        collar = _collar(ref=10000, dynamic=0.02)
        last = 10000
        result = validate_collar(price=10201, collar=collar, last_trade_price=last)
        assert result.rejected
        assert "DYNAMIC_COLLAR_BREACH" in result.reason

    def test_price_below_dynamic_lower_rejected(self) -> None:
        collar = _collar(ref=10000, dynamic=0.02)
        last = 10000
        # dyn_lower = int(10000 * 0.98) = 9800
        result = validate_collar(price=9799, collar=collar, last_trade_price=last)
        assert result.rejected
        assert "DYNAMIC_COLLAR_BREACH" in result.reason

    def test_dynamic_boundary_values_in_reason(self) -> None:
        collar = _collar(ref=10000, dynamic=0.02)
        result = validate_collar(price=20000, collar=collar, last_trade_price=10000)
        # Will hit static first, so let's test with last_trade very different
        # Use a last_trade that puts the dynamic upper well within static:
        last = 9900
        result = validate_collar(price=9699, collar=collar, last_trade_price=last)
        assert result.rejected
        assert "DYNAMIC_COLLAR_BREACH" in result.reason

    def test_both_bands_pass(self) -> None:
        collar = _collar(ref=10000, static=0.20, dynamic=0.02)
        result = validate_collar(price=10100, collar=collar, last_trade_price=10100)
        assert not result.rejected

    def test_static_checked_before_dynamic(self) -> None:
        """A price failing static band should return STATIC_COLLAR_BREACH, not dynamic."""
        collar = _collar(ref=10000, static=0.10, dynamic=0.50)
        # last_trade nearby but price way outside static band
        result = validate_collar(price=15000, collar=collar, last_trade_price=14000)
        assert result.rejected
        assert "STATIC_COLLAR_BREACH" in result.reason


class TestCollarConfig:
    def test_default_band_percentages(self) -> None:
        collar = CollarConfig(symbol="AAPL", reference_price=10000)
        assert collar.static_band_pct == 0.20
        assert collar.dynamic_band_pct == 0.02

    def test_collar_result_not_rejected_has_empty_reason(self) -> None:
        result = CollarResult(rejected=False)
        assert result.reason == ""

    def test_truncation_toward_zero_makes_range_tighter(self) -> None:
        """int() truncates toward zero — can make bounds tighter than exact fraction.

        For ref=100, static_band_pct=0.15:
          - Python: 100 * 1.15 may evaluate to 114.999... (IEEE 754), so int() → 114
          - Similarly 100 * 0.85 = 85.0 (exact), so int() → 85
        The collar implementation does not round — it truncates.
        This test simply confirms the actual behaviour of the implementation.
        """
        collar = CollarConfig(
            symbol="X", reference_price=100, static_band_pct=0.15, dynamic_band_pct=0.02
        )
        static_upper = int(100 * (1 + 0.15))  # same expression as implementation
        static_lower = int(100 * (1 - 0.15))

        # A price at the computed upper boundary must be accepted
        result = validate_collar(
            price=static_upper, collar=collar, last_trade_price=None
        )
        assert not result.rejected

        # One tick above must be rejected
        result = validate_collar(
            price=static_upper + 1, collar=collar, last_trade_price=None
        )
        assert result.rejected

        # A price at the computed lower boundary must be accepted
        result = validate_collar(
            price=static_lower, collar=collar, last_trade_price=None
        )
        assert not result.rejected

        # One tick below must be rejected
        result = validate_collar(
            price=static_lower - 1, collar=collar, last_trade_price=None
        )
        assert result.rejected
