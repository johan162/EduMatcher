"""WP1: presets, the field catalogue and default resolution (design §5, §19)."""

from pathlib import Path

import pytest

from edumatcher.valuation.fields import FIELDS, PAGES, Ctx, Rule
from edumatcher.valuation.model.valuation import FORECAST_KEYS, forecast_inputs, value
from edumatcher.valuation.presets import load_presets
from edumatcher.valuation.resolve import InvalidAnswers, Source, resolve

PRESETS = load_presets()

#: The ✎ answers of the worked example, design §18.1.
AURORA = {
    "company.name": "Aurora Metrics Inc.",
    "customers.last_fy_revenue": 90e6,
    "customers.now": 1800,
    "capital.ppe_start": 12e6,
    "capital.nol": 150e6,
    "capital.cash": 60e6,
    "offering.shares_pre": 80e6,
    "offering.secondary_shares": 5e6,
    "management.last_round": 1.4e9,
}


def test_every_field_is_documented() -> None:
    keys = [spec.key for spec in FIELDS]
    assert len(keys) == len(set(keys))
    for spec in FIELDS:
        assert spec.help.strip(), spec.key
        assert 1 <= spec.page <= len(PAGES), spec.key


@pytest.mark.parametrize("sector", sorted(PRESETS.sectors))
def test_all_defaults_resolve_to_a_coherent_company(sector: str) -> None:
    """Pressing Enter through the interview gives a sensible company (§5)."""
    resolved = resolve({"company.sector": sector}, PRESETS)
    assert set(resolved.values) == {spec.key for spec in FIELDS}

    v = value(resolved.values)
    low, high = PRESETS.sectors[sector].ebit_margin_band
    assert low <= v.years[9].ebit_margin <= high
    assert v.years[10].revenue_growth - resolved["rates.terminal_growth"] <= 0.03
    assert abs(v.dcf_price / v.comps_price - 1) <= 0.25


def test_sources_record_where_each_value_came_from() -> None:
    resolved = resolve(AURORA, PRESETS)
    assert resolved.sources["customers.now"] is Source.USER
    assert resolved.sources["company.sector"] is Source.DEFAULT
    assert resolved.sources["customers.arpu"] is Source.PRESET
    assert resolved.sources["people.headcount"] is Source.DERIVED


def test_worked_example_defaults() -> None:
    """The derived rows of design §18.1."""
    r = resolve(AURORA, PRESETS)
    assert r["company.ticker"] == "AURM"
    assert r["people.headcount"] == 450
    assert r["costs.cac_paid"] == 30_000
    assert r["market.p_max"] == 0.08
    assert r["offering.raise"] == 300e6
    assert r["offering.other_expenses"] == 5e6
    assert r["investors.avg_ticket"] == 15e6
    assert r["management.min_market_cap"] == 1.4e9
    assert r["rates.cost_of_debt"] == pytest.approx(0.0725)
    without_shares = {k: v for k, v in AURORA.items() if k != "offering.shares_pre"}
    assert resolve(without_shares, PRESETS)["offering.shares_pre"] == 74e6


def test_revenue_and_customers_derive_in_either_direction() -> None:
    arpu = PRESETS.sectors["b2b_saas"].arpu
    from_revenue = resolve({"customers.last_fy_revenue": 85e6}, PRESETS)
    assert from_revenue["customers.now"] == round(85e6 / (0.85 * arpu))
    assert from_revenue.sources["customers.last_fy_revenue"] is Source.USER

    from_customers = resolve({"customers.now": 2000}, PRESETS)
    assert from_customers["customers.last_fy_revenue"] == pytest.approx(
        0.85 * 2000 * arpu
    )
    assert from_customers.sources["customers.last_fy_revenue"] is Source.DERIVED


@pytest.mark.parametrize(
    ("name", "ticker"),
    [("Newco Inc.", "NEWC"), ("Aurora Metrics Inc.", "AURM"), ("AB", "NEWCO")],
)
def test_ticker_default(name: str, ticker: str) -> None:
    assert resolve({"company.name": name}, PRESETS)["company.ticker"] == ticker


@pytest.mark.parametrize(
    ("answers", "fragment"),
    [
        ({"customers.churn": 1.5}, "outside"),
        ({"customers.churn": "high"}, "must be a number"),
        ({"company.sector": "biotech"}, "not one of"),
        ({"company.ticker": "IPO-1"}, "does not match"),
        ({"no.such.field": 1}, "unknown field"),
        ({"people.split_rnd": 0.5}, "sum to"),
        ({"rates.stage1_years": 12}, "longer than the forecast horizon"),
        ({"company.dual_class": "yes"}, "yes/no"),
        # A derived value out of range needs an answer: bear churn = 0.7 × 1.5.
        ({"customers.churn": 0.7}, "derived; enter a value"),
    ],
)
def test_invalid_answers_are_reported(answers: dict, fragment: str) -> None:
    with pytest.raises(InvalidAnswers, match=fragment):
        resolve(answers, PRESETS)


def test_optional_fields_accept_none_and_required_do_not() -> None:
    assert resolve({"rates.r1_override": None}, PRESETS)["rates.r1_override"] is None
    with pytest.raises(InvalidAnswers, match="required"):
        resolve({"customers.churn": None}, PRESETS)


class _Recording(dict):
    """A mapping that remembers which keys were read."""

    def __init__(self, values: dict) -> None:
        super().__init__(values)
        self.read: set[str] = set()

    def __getitem__(self, key: str):
        self.read.add(key)
        return super().__getitem__(key)


def test_rules_read_only_what_they_declare() -> None:
    """A rule that reads an undeclared key would break the dependency order."""
    resolved = dict(resolve(AURORA, PRESETS).values)
    for spec in FIELDS:
        for rule in (spec.default, spec.inverse):
            if isinstance(rule, Rule):
                values = _Recording(resolved)
                rule.fn(Ctx(values, PRESETS))
                assert values.read <= set(rule.depends), spec.key


def test_forecast_keys_are_exactly_what_the_forecast_reads() -> None:
    values = _Recording(dict(resolve(AURORA, PRESETS).values))
    forecast_inputs(values)
    assert values.read == set(FORECAST_KEYS)


def test_bad_preset_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "presets.yaml"
    path.write_text(
        "filer_thresholds: {egc_revenue: 1, src_public_float: 1, src_revenue: 1, src_public_float_alt: 1}\nmarket_structures: {competitive: 0.08}\nsectors:\n  x: {arpu: 1}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing"):
        load_presets(path)
