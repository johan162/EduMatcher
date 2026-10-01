"""WP2: the deterministic model, §6–§10.

The golden tests hold the implementation to the worked example in
docs-design/EduMatcher-valuation.md §18.2–18.8 and §18.12: each value is
asserted to half a unit of the precision the document prints.
"""

import dataclasses
import random

import pytest

from edumatcher.valuation.model.bridge import dilution, fair_price, value_after_ipo
from edumatcher.valuation.model.dcf import dcf
from edumatcher.valuation.model.forecast import forecast, unit_economics
from edumatcher.valuation.model.rates import stage_rates
from edumatcher.valuation.model.valuation import (
    forecast_inputs,
    offering,
    rate_inputs,
    value,
)
from edumatcher.valuation.presets import load_presets
from edumatcher.valuation.resolve import resolve
from tests.test_valuation_resolve import AURORA

PRESETS = load_presets()
M = 1e6


@pytest.fixture(scope="module")
def aurora() -> dict:
    return dict(resolve(AURORA, PRESETS).values)


def _approx_m(values: list[float], printed: list[float]) -> None:
    """Money in millions, printed with one decimal."""
    assert [v / M for v in values] == pytest.approx(printed, abs=0.051)


# -- golden: the worked example -------------------------------------------------


def test_customer_build(aurora: dict) -> None:  # §18.2
    years = value(aurora).years[:10]
    assert [round(y.max_customers) for y in years] == [
        14222, 15067, 15853, 16563, 17183, 17699, 18098, 18372, 18511, 18511,
    ]  # fmt: skip
    assert [round(y.customers_end) for y in years] == [
        2700, 3956, 5610, 7625, 9832, 11947, 13688, 14910, 15643, 16001,
    ]  # fmt: skip
    # Calibrated to exactly the year-1 growth the student gave.
    assert years[0].customers_end == pytest.approx(1800 * 1.5)
    _approx_m(
        [y.revenue for y in years],
        [141.8, 219.6, 329.6, 475.0, 650.9, 841.3, 1023.3, 1176.5, 1291.8, 1371.4],
    )


def test_headcount(aurora: dict) -> None:  # §18.3
    years = value(aurora).years[:10]
    assert [round(y.headcount) for y in years] == [
        605, 805, 1047, 1324, 1618, 1902, 2148, 2341, 2479, 2578,
    ]  # fmt: skip
    _approx_m(
        [y.staff_cost for y in years],
        [94.0, 129.3, 174.0, 227.8, 288.2, 350.6, 410.0, 462.5, 506.8, 545.5],
    )


def test_income_statement(aurora: dict) -> None:  # §18.4
    years = value(aurora).years[:10]
    _approx_m(
        [y.gross_profit for y in years],
        [101.0, 162.8, 251.4, 369.7, 513.7, 670.3, 820.0, 945.7, 1039.3, 1102.2],
    )
    _approx_m(
        [y.paid_acquisition for y in years],
        [32.3, 46.8, 64.6, 83.2, 98.0, 104.0, 99.5, 88.1, 75.4, 64.9],
    )
    _approx_m(
        [y.ebitda for y in years],
        [-32.6, -24.1, -3.1, 35.8, 95.9, 174.4, 260.0, 336.9, 393.3, 424.7],
    )
    _approx_m(
        [y.ebit for y in years],
        [-35.6, -27.4, -7.2, 30.2, 88.1, 163.7, 245.6, 318.4, 370.7, 398.1],
    )


def test_taxes_reinvestment_and_fcff(aurora: dict) -> None:  # §18.5
    years = value(aurora).years[:10]
    _approx_m(
        [y.nol for y in years],
        [185.6, 213.0, 220.2, 190.0, 101.9, 0, 0, 0, 0, 0],
    )
    _approx_m(
        [y.taxes for y in years],
        [0, 0, 0, 0, 0, 15.4, 61.4, 79.6, 92.7, 99.5],
    )
    _approx_m(
        [y.delta_nwc for y in years],
        [-2.6, -3.9, -5.5, -7.3, -8.8, -9.5, -9.1, -7.7, -5.8, -4.0],
    )
    _approx_m(
        [y.fcff for y in years],
        [-34.3, -26.8, -7.5, 28.8, 85.1, 143.2, 176.9, 229.6, 267.7, 288.0],
    )


def test_unit_economics(aurora: dict) -> None:  # §18.6
    years = value(aurora).years
    first = unit_economics(years[0], aurora["customers.churn"])
    assert round(first.ltv) == 560_868
    assert round(first.cac_full) == 57_901
    assert first.ltv_to_cac == pytest.approx(9.7, abs=0.05)
    assert first.payback_months == pytest.approx(15.5, abs=0.05)
    assert round(unit_economics(years[9], 0.08).cac_full) == 142_019


def test_dcf(aurora: dict) -> None:  # §18.7
    result = value(aurora)
    assert result.stage1.rate == pytest.approx(0.1625)
    assert result.stage2.rate == pytest.approx(0.1025)
    assert [round(r.discount_factor, 4) for r in result.dcf.rows] == [
        0.8602, 0.7400, 0.6365, 0.5476, 0.4710,
        0.4272, 0.3875, 0.3515, 0.3188, 0.2892,
    ]  # fmt: skip
    _approx_m(
        [r.pv for r in result.dcf.rows],
        [-29.5, -19.8, -4.8, 15.8, 40.1, 61.2, 68.6, 80.7, 85.3, 83.3],
    )
    d = result.dcf
    _approx_m(
        [d.pv_explicit, d.ebit_terminal, d.nopat_terminal, d.fcff_terminal],
        [380.9, 399.0, 299.2, 238.2],
    )
    _approx_m(
        [d.terminal_value, d.pv_terminal, d.enterprise_value],
        [3073.3, 888.7, 1269.5],
    )
    assert d.reinvestment_rate == pytest.approx(0.204, abs=0.0005)
    assert d.tv_share == pytest.approx(0.700, abs=0.0005)
    assert result.ev_to_ntm_revenue == pytest.approx(9.0, abs=0.05)
    assert result.ev_to_ebit_n == pytest.approx(3.2, abs=0.05)


def test_bridge_and_fair_value(aurora: dict) -> None:  # §18.8
    result = value(aurora)
    _approx_m([result.equity_pre, result.comps_ev], [1329.5, 1417.5])
    assert result.dcf_price == pytest.approx(16.29, abs=0.005)
    assert result.comps_price == pytest.approx(18.14, abs=0.005)
    assert result.fair_value == pytest.approx(16.85, abs=0.005)


def test_dilution_at_the_offer_price(aurora: dict) -> None:  # §18.12
    d = dilution(
        14.50,
        offering(aurora),
        cash=aurora["capital.cash"],
        ppe_0=aurora["capital.ppe_start"],
        nwc_0=aurora["capital.nwc_pct"] * aurora["customers.last_fy_revenue"],
        debt=aurora["capital.debt"],
    )
    assert d.ntbv_pre / M == pytest.approx(67.5)
    assert d.ntbv_pre_per_share == pytest.approx(0.84, abs=0.005)
    assert d.ntbv_post_per_share == pytest.approx(3.39, abs=0.005)
    assert d.increase_per_share == pytest.approx(2.55, abs=0.005)
    assert d.dilution_per_share == pytest.approx(11.11, abs=0.005)
    assert d.dilution_pct == pytest.approx(0.766, abs=0.0005)


# -- identities --------------------------------------------------------------------


def test_discount_factor_is_a_product_of_both_rates(aurora: dict) -> None:
    result = value(aurora)
    r1, r2 = result.stage1.rate, result.stage2.rate
    for row in result.dcf.rows:
        expected = (1 + r1) ** -min(row.t, 5) * (1 + r2) ** -max(0, row.t - 5)
        assert row.discount_factor == pytest.approx(expected)


def test_no_value_creation_gives_the_no_growth_terminal_value(aurora: dict) -> None:
    """With RONIC = r2, growth creates no value: TV = NOPAT / r2 for any g."""
    years = forecast(forecast_inputs(aurora))
    for g in (0.0, 0.02, 0.04):
        d = dcf(years, 0.16, 0.10, 5, g, ronic_spread=0.0, tax_rate=0.25)
        assert d.terminal_value == pytest.approx(d.nopat_terminal / 0.10)


def test_fair_price_is_worth_exactly_what_it_costs(aurora: dict) -> None:
    """At the fair price, the IPO transfers no value between old and new (§9.2)."""
    result = value(aurora)
    offer = offering(aurora)
    price = fair_price(result.equity_pre, offer)
    # Only the rounding of primary shares to whole shares separates the two.
    assert value_after_ipo(price, result.equity_pre, offer) == pytest.approx(
        price, rel=1e-6
    )


def test_mid_year_moves_every_flow_half_a_year_earlier(aurora: dict) -> None:
    years = forecast(forecast_inputs(aurora))
    end = dcf(years, 0.16, 0.10, 5, 0.025, 0.02, 0.25)
    mid = dcf(years, 0.16, 0.10, 5, 0.025, 0.02, 0.25, mid_year=True)
    for a, b in zip(end.rows, mid.rows):
        assert b.pv == pytest.approx(a.pv * (1 + a.rate) ** 0.5)
    assert mid.pv_terminal == pytest.approx(end.pv_terminal * 1.10**0.5)


def test_rates_with_debt_and_overrides(aurora: dict) -> None:
    levered = {**aurora, "rates.debt_ratio": 0.2, "rates.cost_of_debt": 0.08}
    stage1, stage2 = stage_rates(rate_inputs(levered))
    assert stage2.rate == pytest.approx(0.8 * 0.1025 + 0.2 * 0.08 * 0.75)
    fixed = {**aurora, "rates.r1_override": 0.2, "rates.r2_override": 0.09}
    stage1, stage2 = stage_rates(rate_inputs(fixed))
    assert (stage1.rate, stage2.rate) == (0.2, 0.09)
    assert stage1.overridden and stage1.cost_of_equity == pytest.approx(0.1625)


@pytest.mark.parametrize(
    ("key", "delta", "direction"),
    [
        ("rates.execution_premium", 0.02, -1),  # r1 up
        ("rates.beta_stage2", 0.2, -1),  # r2 up
        ("customers.churn", 0.02, -1),
        ("customers.growth_y1", 0.1, +1),
        ("market.p_max", 0.02, +1),
    ],
)
def test_value_moves_the_right_way(
    aurora: dict, key: str, delta: float, direction: int
) -> None:
    base = value(aurora).dcf_price
    moved = value({**aurora, key: aurora[key] + delta}).dcf_price
    assert (moved - base) * direction > 0


def test_acquisition_never_overfills_the_market() -> None:
    rng = random.Random(7)
    for _ in range(200):
        answers = {
            "customers.growth_y1": rng.uniform(-0.3, 3.0),
            "customers.churn": rng.uniform(0.01, 0.6),
            "market.structure": rng.choice(list(PRESETS.market_structures)),
            "customers.arpu_growth": rng.uniform(-0.2, 0.3),
        }
        for year in forecast(forecast_inputs(resolve(answers, PRESETS).values)):
            # Acquisition never pushes customers above the cap. The cap itself
            # can fall below the base (ARPU outgrowing the market); then the
            # company only loses customers to churn.
            assert year.gross_adds >= 0
            if year.gross_adds:
                assert year.customers_end <= year.max_customers * (1 + 1e-9)


def test_loss_carry_forward_balances(aurora: dict) -> None:
    years = forecast(forecast_inputs(aurora))
    losses = sum(-y.ebit for y in years if y.ebit < 0)
    used = sum(y.nol_used for y in years)
    expected = aurora["capital.nol"] + losses - used
    assert years[-1].nol == pytest.approx(expected, abs=1.0)
    for y in years:
        assert y.taxes == pytest.approx(0.25 * max(0.0, y.ebit - y.nol_used))


def test_explicit_headcount_path(aurora: dict) -> None:
    explicit = {**aurora, "people.headcount_mode": "explicit"}
    years = forecast(forecast_inputs(explicit))
    assert years[0].headcount_growth == pytest.approx(0.25)
    assert years[9].headcount_growth == pytest.approx(0.04)


def test_a_company_already_at_its_market_cap_is_rejected(aurora: dict) -> None:
    saturated = {**aurora, "customers.now": 20_000}
    with pytest.raises(ValueError, match="maximum market share"):
        forecast(forecast_inputs(saturated))


def test_stage_2_rate_must_exceed_terminal_growth(aurora: dict) -> None:
    years = forecast(forecast_inputs(aurora))
    with pytest.raises(ValueError, match="must exceed terminal growth"):
        dcf(years, 0.16, 0.025, 5, 0.025, 0.02, 0.25)


def test_forecast_inputs_are_frozen(aurora: dict) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        forecast_inputs(aurora).horizon = 3  # type: ignore[misc]
