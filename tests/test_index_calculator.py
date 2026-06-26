from __future__ import annotations

import pytest

from edumatcher.index.calculator import ConstituentConfig, IndexCalculator


def _make_calc() -> IndexCalculator:
    return IndexCalculator(
        constituents=[
            ConstituentConfig(
                "AAPL", shares_outstanding=15_000_000_000, initial_price=209.50
            ),
            ConstituentConfig(
                "MSFT", shares_outstanding=7_400_000_000, initial_price=415.00
            ),
            ConstituentConfig(
                "TSLA", shares_outstanding=3_200_000_000, initial_price=248.00
            ),
        ],
        base_value=1000.0,
    )


def test_constructor_validation() -> None:
    with pytest.raises(ValueError):
        IndexCalculator(constituents=[], base_value=1000.0)

    with pytest.raises(ValueError):
        IndexCalculator(
            constituents=[
                ConstituentConfig("AAPL", shares_outstanding=1, initial_price=1.0)
            ],
            base_value=0.0,
        )


def test_duplicate_constituent_rejected() -> None:
    with pytest.raises(ValueError):
        IndexCalculator(
            constituents=[
                ConstituentConfig("AAPL", shares_outstanding=1, initial_price=1.0),
                ConstituentConfig("aapl", shares_outstanding=2, initial_price=2.0),
            ],
            base_value=1000.0,
        )


def test_invalid_manual_divisor_rejected() -> None:
    with pytest.raises(ValueError):
        IndexCalculator(
            constituents=[
                ConstituentConfig("AAPL", shares_outstanding=1, initial_price=1.0)
            ],
            base_value=1000.0,
            divisor=0.0,
        )


def test_initial_level_equals_base_value() -> None:
    calc = _make_calc()
    assert calc.recalculate() == pytest.approx(1000.0, rel=0.0, abs=0.01)


def test_divisor_is_nonzero() -> None:
    calc = _make_calc()
    assert calc.divisor > 0


def test_price_rise_increases_level() -> None:
    calc = _make_calc()
    calc.update_price("AAPL", 230.00)
    assert calc.recalculate() > 1000.0


def test_price_fall_decreases_level() -> None:
    calc = _make_calc()
    calc.update_price("AAPL", 190.00)
    assert calc.recalculate() < 1000.0


def test_non_constituent_update_ignored() -> None:
    calc = _make_calc()
    before = calc.recalculate()
    calc.update_price("AMZN", 200.00)
    assert calc.recalculate() == pytest.approx(before)


def test_non_positive_price_rejected() -> None:
    calc = _make_calc()
    with pytest.raises(ValueError):
        calc.update_price("AAPL", 0.0)


def test_split_preserves_index_level() -> None:
    calc = _make_calc()
    before = calc.recalculate()
    calc.apply_split("AAPL", ratio_numerator=2, ratio_denominator=1)
    after = calc.recalculate()
    assert after == pytest.approx(before, rel=0.0, abs=0.01)


def test_split_updates_shares_and_price() -> None:
    calc = _make_calc()
    old_shares = calc.shares_outstanding("AAPL")
    old_price = calc.last_price("AAPL")
    calc.apply_split("AAPL", 2, 1)
    assert calc.shares_outstanding("AAPL") == old_shares * 2
    assert calc.last_price("AAPL") == pytest.approx(old_price / 2.0)


def test_invalid_split_ratio_rejected() -> None:
    calc = _make_calc()
    with pytest.raises(ValueError):
        calc.apply_split("AAPL", 0, 1)


def test_unknown_symbol_rejections() -> None:
    calc = _make_calc()
    with pytest.raises(KeyError):
        calc.apply_split("AMZN", 2, 1)
    with pytest.raises(KeyError):
        calc.apply_cash_dividend("AMZN", 1.0)
    with pytest.raises(KeyError):
        calc.apply_shares_issuance("AMZN", 100)
    with pytest.raises(KeyError):
        calc.last_price("AMZN")
    with pytest.raises(KeyError):
        calc.shares_outstanding("AMZN")


def test_dividend_preserves_index_level_and_adjusts_divisor() -> None:
    calc = _make_calc()
    before_level = calc.recalculate()
    before_divisor = calc.divisor
    calc.apply_cash_dividend("MSFT", 2.50)
    after_level = calc.recalculate()
    assert after_level == pytest.approx(before_level, rel=0.0, abs=0.01)
    assert calc.divisor != before_divisor


def test_dividend_non_positive_price_rejected() -> None:
    calc = _make_calc()
    with pytest.raises(ValueError):
        calc.apply_cash_dividend("TSLA", 10_000.0)


def test_dividend_requires_positive_amount() -> None:
    calc = _make_calc()
    with pytest.raises(ValueError):
        calc.apply_cash_dividend("TSLA", 0.0)


def test_shares_issuance_preserves_index_level() -> None:
    calc = _make_calc()
    before = calc.recalculate()
    calc.apply_shares_issuance("TSLA", 3_500_000_000)
    after = calc.recalculate()
    assert after == pytest.approx(before, rel=0.0, abs=0.01)


def test_invalid_shares_issuance_rejected() -> None:
    calc = _make_calc()
    with pytest.raises(ValueError):
        calc.apply_shares_issuance("TSLA", 0)


def test_delist_preserves_index_level_and_removes_constituent() -> None:
    calc = _make_calc()
    before = calc.recalculate()
    calc.delist_symbol("TSLA")
    after = calc.recalculate()
    assert after == pytest.approx(before, rel=0.0, abs=0.01)
    assert "TSLA" not in calc.constituent_symbols()


def test_delisted_symbol_price_update_ignored() -> None:
    calc = _make_calc()
    calc.delist_symbol("TSLA")
    before = calc.recalculate()
    calc.update_price("TSLA", 500.0)
    assert calc.recalculate() == pytest.approx(before)


def test_delist_non_constituent_rejected() -> None:
    calc = _make_calc()
    with pytest.raises(KeyError):
        calc.delist_symbol("AMZN")


def test_add_constituent_preserves_level() -> None:
    calc = _make_calc()
    before = calc.recalculate()
    calc.add_constituent("AMZN", shares_outstanding=10_500_000_000, initial_price=195.0)
    after = calc.recalculate()
    assert after == pytest.approx(before, rel=0.0, abs=0.01)


def test_new_constituent_moves_index_after_price_update() -> None:
    calc = _make_calc()
    calc.add_constituent("AMZN", 10_500_000_000, 195.0)
    before = calc.recalculate()
    calc.update_price("AMZN", 220.0)
    assert calc.recalculate() > before


def test_add_constituent_validation() -> None:
    calc = _make_calc()
    with pytest.raises(ValueError):
        calc.add_constituent("AMZN", 0, 195.0)
    with pytest.raises(ValueError):
        calc.add_constituent("AMZN", 10, 0.0)


def test_add_constituent_duplicate_rejected() -> None:
    calc = _make_calc()
    with pytest.raises(KeyError):
        calc.add_constituent("AAPL", 10, 195.0)
