"""The warnings catalogue (design §24): what deserves a sentence in the report.

V016 (invalid ticker) is not here: resolve() refuses such a ticker outright.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from edumatcher.valuation.model.forecast import unit_economics
from edumatcher.valuation.model.montecarlo import MonteCarlo
from edumatcher.valuation.model.offering import Outcome, Pricing
from edumatcher.valuation.model.rates import stage_rates
from edumatcher.valuation.model.valuation import Valuation, rate_inputs
from edumatcher.valuation.presets import Presets

#: Plausible revenue per employee in year N (V020), in the profile's currency.
REVENUE_PER_EMPLOYEE = (150_000, 800_000)


class Severity(Enum):
    ERROR = "error"  # the valuation cannot be computed
    WARN = "warning"
    INFO = "info"
    RESULT = "result"  # the deal is postponed


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str


def rate_errors(v: Mapping[str, Any]) -> list[Finding]:
    """V001, checked before valuing: the terminal value needs r2 well above g."""
    r2 = stage_rates(rate_inputs(v))[1].rate
    g = v["rates.terminal_growth"]
    if r2 - g < 0.01:
        return [
            Finding(
                "V001",
                Severity.ERROR,
                f"the stage-2 rate {r2:.2%} is less than 1 point above terminal "
                f"growth {g:.2%}; the terminal value is undefined or explosive",
            )
        ]
    return []


def findings(
    v: Mapping[str, Any],
    presets: Presets,
    valuation: Valuation,
    pricing: Pricing | None = None,
    mc: MonteCarlo | None = None,
) -> list[Finding]:
    """Every catalogue entry that applies, in code order."""
    out: list[Finding] = []

    def add(code: str, severity: Severity, message: str) -> None:
        out.append(Finding(code, severity, message))

    years, dcf = valuation.years, valuation.dcf
    horizon = len(years) - 1
    g, r1, r2 = v["rates.terminal_growth"], valuation.stage1.rate, valuation.stage2.rate

    if g > v["rates.risk_free"]:
        add(
            "V002", Severity.WARN, f"terminal growth {g:.2%} exceeds the risk-free rate"
        )
    if r1 < r2:
        add(
            "V003", Severity.WARN, "years 1-5 are discounted less than the mature years"
        )
    if dcf.tv_share > 0.75:
        add(
            "V004",
            Severity.WARN,
            f"{dcf.tv_share:.0%} of the value lies beyond year {horizon}",
        )
    tail_growth = years[horizon].revenue_growth
    if tail_growth > g + 0.03:
        add(
            "V005",
            Severity.WARN,
            f"revenue still grows {tail_growth:.1%} after the horizon; extend it",
        )
    for t in sorted({1, min(5, horizon), horizon}):  # years 1, 5 and N (§6.4)
        year = years[t - 1]
        economics = unit_economics(year, v["customers.churn"])
        if economics.ltv_to_cac < 1:
            add(
                "V006",
                Severity.WARN,
                f"year {year.t}: a customer is worth less than it costs to win",
            )
        if economics.payback_months > 36:
            add(
                "V007",
                Severity.WARN,
                f"year {year.t}: acquisition cost takes "
                f"{economics.payback_months:.0f} months to earn back",
            )
    low, high = presets.sectors[v["company.sector"]].ebit_margin_band
    margin = years[horizon - 1].ebit_margin
    if not low <= margin <= high:
        add(
            "V008",
            Severity.WARN,
            f"year-{horizon} EBIT margin {margin:.1%} is outside the sector's "
            f"{low:.0%}-{high:.0%}",
        )
    if valuation.equity_pre < 0:
        add("V009", Severity.WARN, "the plan does not earn its cost of capital")

    if pricing is not None:
        listing = pricing.listing
        if pricing.outcome is Outcome.THIN_BOOK:
            add(
                "V010",
                Severity.WARN,
                f"priced on a {pricing.coverage:.1f}× book, below the "
                f"{v['investors.target_coverage']:g}× target",
            )
        if pricing.range_moved and pricing.outcome is not Outcome.POSTPONED:
            low_, high_ = pricing.price_range
            add(
                "V011",
                Severity.INFO,
                f"the management floor moved the range to {low_:.2f}-{high_:.2f}",
            )
        if pricing.outcome is Outcome.POSTPONED:
            add("V012", Severity.RESULT, f"IPO postponed: {pricing.reason}")
        if listing is not None:
            if listing.dilution > v["management.max_dilution"]:
                add(
                    "V013",
                    Severity.WARN,
                    f"dilution {listing.dilution:.1%} exceeds management's "
                    f"{v['management.max_dilution']:.0%}",
                )
            if listing.free_float < v["index.min_free_float"]:
                add(
                    "V015",
                    Severity.WARN,
                    f"free float {listing.free_float:.1%} is below the index "
                    f"minimum {v['index.min_free_float']:.0%}",
                )
            minimum = v["management.min_net_proceeds"]
            if minimum is not None and listing.net_proceeds < minimum:
                add(
                    "V021",
                    Severity.WARN,
                    "net proceeds fall short of management's minimum",
                )
    if v["investors.hype"] >= 7:
        add("V014", Severity.WARN, "the pricing leans on sentiment (hype ≥ 7)")
    comps = valuation.comps_price
    if comps <= 0 or abs(valuation.dcf_price / comps - 1) > 0.5:
        add(
            "V017",
            Severity.WARN,
            f"DCF {valuation.dcf_price:.2f} and comparables {comps:.2f} differ "
            "by more than 50%",
        )
    if mc is not None and mc.rejected / (len(mc.samples) + mc.rejected) > 0.01:
        add(
            "V018",
            Severity.WARN,
            f"{mc.rejected} Monte Carlo draws were rejected; the rate ranges "
            "come too close to terminal growth",
        )
    if years[horizon - 1].nol > 0:
        add("V019", Severity.INFO, "tax losses are still unused at the horizon")
    per_employee = years[horizon - 1].revenue_per_employee
    if not REVENUE_PER_EMPLOYEE[0] <= per_employee <= REVENUE_PER_EMPLOYEE[1]:
        add(
            "V020",
            Severity.WARN,
            f"year-{horizon} revenue per employee {per_employee:,.0f} is implausible",
        )
    return sorted(out, key=lambda f: f.code)
