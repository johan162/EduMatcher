"""WP4: scenarios, Monte Carlo and the warnings catalogue (§11, §12, §24).

Golden values are the worked example, docs-design/EduMatcher-valuation.md
§18.9–18.10, asserted to the precision the document prints.
"""

import statistics

import pytest

from edumatcher.valuation.model.checks import Severity, findings, rate_errors
from edumatcher.valuation.model.montecarlo import (
    share_below,
    simulate,
    summarize,
    triangular,
)
from edumatcher.valuation.model.offering import price_ipo
from edumatcher.valuation.model.scenarios import scenarios
from edumatcher.valuation.model.valuation import value
from edumatcher.valuation.presets import load_presets
from edumatcher.valuation.resolve import InvalidAnswers, resolve
from tests.test_valuation_resolve import AURORA

PRESETS = load_presets()
M = 1e6


def _values(**changes: object) -> dict:
    return dict(resolve({**AURORA, **changes}, PRESETS).values)


@pytest.fixture(scope="module")
def aurora() -> dict:
    return _values()


@pytest.fixture(scope="module")
def mc(aurora: dict):
    return simulate(aurora, draws=10_000, seed=42, rho=0.5)


# -- golden: scenarios (§18.9) -----------------------------------------------------


def test_scenario_table(aurora: dict) -> None:
    s = scenarios(aurora, value(aurora))
    assert s.bear is not None and s.bull is not None
    assert (s.bear.stage1.rate, s.bear.stage2.rate) == pytest.approx((0.1925, 0.1175))
    assert (s.bull.stage1.rate, s.bull.stage2.rate) == pytest.approx((0.1425, 0.0925))
    rows = [
        (s.bear, 738.3, -0.007, -177.9, -1.80, 11.62, 2.23),
        (s.bull, 1964.5, 0.463, 3976.9, 50.14, 25.31, 42.69),
    ]
    for case, revenue, margin, ev, dcf, comps, fair in rows:
        assert case.years[9].revenue / M == pytest.approx(revenue, abs=0.051)
        assert case.years[9].ebit_margin == pytest.approx(margin, abs=0.0005)
        assert case.dcf.enterprise_value / M == pytest.approx(ev, abs=0.051)
        assert (case.dcf_price, case.comps_price, case.fair_value) == pytest.approx(
            (dcf, comps, fair), abs=0.005
        )


def test_tornado(aurora: dict) -> None:
    tornado = scenarios(aurora, value(aurora)).tornado
    assert [bar.key for bar in tornado] == [
        "people.elasticity",
        "market.p_max",
        "customers.growth_y1",
        "investors.comps_multiple",
        "rates.beta_stage2",
        "customers.churn",
        "rates.execution_premium",
        "costs.cac_paid",
        "customers.arpu_growth",
        "rates.terminal_growth",
    ]
    ends = [end for bar in tornado[:3] for end in (bar.bear, bar.bull)]
    assert ends == pytest.approx([10.99, 21.56, 12.13, 21.35, 11.51, 18.20], abs=0.005)
    assert tornado[-1].swing == pytest.approx(0.89, abs=0.005)


def test_sensitivity_grids(aurora: dict) -> None:
    s = scenarios(aurora, value(aurora))
    assert s.rate2_growth.rows == pytest.approx(
        (0.0825, 0.0925, 0.1025, 0.1125, 0.1225)
    )
    assert s.rate2_growth.cells[0] == pytest.approx(
        (19.20, 20.09, 21.06, 22.12, 23.23), abs=0.005
    )
    assert s.rate2_growth.cells[2][2] == pytest.approx(16.29, abs=0.005)
    assert s.rate1_customer_growth.cols == pytest.approx((0.3, 0.4, 0.5, 0.6, 0.7))
    assert s.rate1_customer_growth.cells[4] == pytest.approx(
        (7.84, 11.67, 13.76, 14.75, 15.25), abs=0.005
    )


def test_invalid_grid_cells_are_none(aurora: dict) -> None:
    near = {**aurora, "rates.terminal_growth": 0.08, "rates.r2_override": 0.09}
    grid = scenarios(near, value(near)).rate2_growth
    assert grid.cells[0][-1] is None  # r2 = 7% below g = 9%


# -- golden: Monte Carlo (§18.10) --------------------------------------------------


def test_monte_carlo_summary(mc) -> None:
    dcf = summarize([s.dcf_price for s in mc.samples])
    fair = summarize([s.fair_value for s in mc.samples])
    assert (dcf.p5, dcf.p25, dcf.p50, dcf.p75, dcf.p95, dcf.mean) == pytest.approx(
        (4.70, 10.06, 14.62, 19.60, 26.98, 15.04), abs=0.005
    )
    assert (
        fair.p5,
        fair.p25,
        fair.p50,
        fair.p75,
        fair.p95,
        fair.mean,
    ) == pytest.approx((8.27, 12.31, 15.65, 19.27, 24.59, 15.94), abs=0.005)
    assert mc.rejected == 0


def test_monte_carlo_probabilities(aurora: dict, mc) -> None:
    fair = [s.fair_value for s in mc.samples]
    assert share_below(fair, 14.5) == pytest.approx(0.409, abs=0.0005)
    assert share_below([s.equity_pre for s in mc.samples], 0) == pytest.approx(0.0004)
    post_money = [
        f * aurora["offering.shares_pre"] + aurora["offering.raise"] for f in fair
    ]
    assert share_below(post_money, 1.4e9) == pytest.approx(0.350, abs=0.0005)


def test_same_seed_same_simulation(aurora: dict) -> None:
    first = simulate(aurora, draws=200, seed=7, rho=0.5)
    assert first == simulate(aurora, draws=200, seed=7, rho=0.5)
    assert first != simulate(aurora, draws=200, seed=8, rho=0.5)


def test_correlation_widens_the_distribution(aurora: dict) -> None:
    """Drivers that move together do not cancel out."""
    spread = [
        statistics.stdev(s.fair_value for s in simulate(aurora, 2000, 1, rho).samples)
        for rho in (0.0, 1.0)
    ]
    assert spread[1] > spread[0]


def test_triangular() -> None:
    assert triangular(0.0, 1.0, 2.0, 4.0) == 1.0
    assert triangular(1.0, 1.0, 2.0, 4.0) == 4.0
    assert triangular(1 / 3, 1.0, 2.0, 4.0) == pytest.approx(2.0)  # the mode
    assert triangular(0.5, 3.0, 3.0, 3.0) == 3.0
    draws = [triangular((i + 0.5) / 10_000, 1.0, 2.0, 4.0) for i in range(10_000)]
    assert statistics.mean(draws) == pytest.approx(7 / 3, abs=1e-3)
    # Reversed ends (a bear value numerically above the bull) work alike.
    assert triangular(0.0, 0.12, 0.08, 0.056) == 0.12


def test_bear_and_bull_must_bracket_the_base() -> None:
    with pytest.raises(InvalidAnswers, match="either side"):
        resolve({"simulation.bear.customers.churn": 0.05}, PRESETS)


# -- the warnings catalogue (§24) -----------------------------------------------------


def _codes(v: dict, with_pricing: bool = True) -> set[str]:
    valuation = value(v)
    pricing = price_ipo(v, valuation) if with_pricing else None
    return {f.code for f in findings(v, PRESETS, valuation, pricing)}


def test_worked_example_raises_only_the_range_move(aurora: dict) -> None:
    assert _codes(aurora) == {"V011"}


def test_rate_error_blocks_before_valuing(aurora: dict) -> None:
    near = {**aurora, "rates.r2_override": 0.03}
    errors = rate_errors(near)
    assert [(e.code, e.severity) for e in errors] == [("V001", Severity.ERROR)]
    assert rate_errors(aurora) == []


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"rates.terminal_growth": 0.045}, "V002"),
        ({"rates.r1_override": 0.09}, "V003"),
        ({"rates.horizon": 5}, "V004"),
        ({"rates.horizon": 5}, "V005"),
        ({"costs.cac_paid": 900_000.0}, "V006"),
        ({"costs.cac_paid": 900_000.0}, "V007"),
        ({"people.elasticity": 0.3}, "V008"),
        ({"costs.cac_paid": 900_000.0}, "V009"),
        ({"investors.target_coverage": 10.0}, "V010"),
        ({"management.min_market_cap": 1.6e9}, "V012"),
        ({"management.max_dilution": 0.1}, "V013"),
        ({"investors.hype": 8}, "V014"),
        ({"index.min_free_float": 0.3}, "V015"),
        ({"investors.comps_multiple": 30.0}, "V017"),
        ({"capital.nol": 5e9}, "V019"),
        ({"people.headcount": 3000}, "V020"),
        ({"management.min_net_proceeds": 400e6}, "V021"),
    ],
)
def test_each_warning_fires(aurora: dict, changes: dict, code: str) -> None:
    assert code in _codes(_values(**changes))


def test_rejected_draws_are_reported(aurora: dict) -> None:
    close = _values(**{"rates.terminal_growth": 0.075})  # r2 − g of 1-5 points
    valuation = value(close)
    mc = simulate(close, draws=300, seed=1, rho=0.5)
    assert mc.rejected > 0
    assert "V018" in {f.code for f in findings(close, PRESETS, valuation, mc=mc)}
