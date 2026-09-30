"""Every question pm-valuation asks, with its default and its help text.

Design §19.3–19.4. A field's default is one of three kinds, which is also the
provenance the report shows for it:

``Const``       a fixed default                              → "default"
``FromPreset``  an attribute of the chosen sector preset      → "preset"
``Rule``        computed from other fields                    → "derived"

The student's own answer always wins ("you"). Percentages are fractions.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from edumatcher.valuation.model.valuation import FORECAST_KEYS, comps_pre_money
from edumatcher.valuation.presets import Preset, Presets

PAGES = (
    "Company",
    "Market",
    "Customers & pricing",
    "People",
    "Costs",
    "Capital & tax",
    "Discount rates",
    "Offering",
    "Investors & sentiment",
    "Index",
    "Management",
    "Simulation",
)


class Unit(Enum):
    TEXT = "text"
    CHOICE = "choice"
    BOOL = "yes/no"
    MONEY = "money"
    COUNT = "count"
    PERCENT = "%"
    RATIO = "×"
    NUMBER = "number"
    YEARS = "years"
    DAYS = "days"


@dataclass(frozen=True)
class Ctx:
    """What a rule may read: the values resolved so far, and the presets."""

    values: Mapping[str, Any]
    presets: Presets

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    @property
    def preset(self) -> Preset:
        return self.presets.sectors[self.values["company.sector"]]


@dataclass(frozen=True)
class Const:
    value: Any


@dataclass(frozen=True)
class FromPreset:
    attr: str


@dataclass(frozen=True)
class Rule:
    fn: Callable[[Ctx], Any]
    depends: tuple[str, ...]


Default = Const | FromPreset | Rule

#: Choices that come from the presets file rather than from the catalogue.
SECTORS = "sectors"
MARKET_STRUCTURES = "market_structures"
INTEREST_LEVELS = ("very_low", "low", "medium", "high", "very_high")


@dataclass(frozen=True)
class FieldSpec:
    key: str
    page: int  # 1-based index into PAGES
    label: str
    unit: Unit
    default: Default
    help: str
    lo: float | None = None  # inclusive bounds for numbers
    hi: float | None = None
    choices: tuple[str, ...] | str | None = None  # or SECTORS / MARKET_STRUCTURES
    pattern: str | None = None  # full-match regex for text
    optional: bool = False  # None ("not given") is a valid value
    advanced: bool = False  # shown only with F3
    # Used instead of the default when the student answered inverse_when:
    # the other direction of a two-way rule such as revenue ↔ customers.
    inverse: Rule | None = None
    inverse_when: str | None = None


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

#: Last year's revenue relative to year-end customers × ARPU: the customer
#: base grew during the year, so the year earned less than its closing run rate.
_REVENUE_TO_RUN_RATE = 0.85
#: Pre-IPO share count is chosen (by a stock split) to land the price near this.
_TARGET_IPO_PRICE = 20.0
_CORPORATE_SUFFIXES = {"INC", "CORP", "CORPORATION", "LTD", "LLC", "PLC", "AB", "AG"}
_SYMBOL = r"[A-Z0-9._]{1,8}"  # the pm-new-symbol rule


def _ticker(ctx: Ctx) -> str:
    words = [
        w
        for w in re.sub(r"[^A-Z0-9 ]", " ", str(ctx["company.name"]).upper()).split()
        if w not in _CORPORATE_SUFFIXES
    ]
    if not words:
        return "NEWCO"
    if len(words) == 1:
        return words[0][:4]
    return words[0][:3] + words[1][0]


def _round_to(value: float, step: float) -> float:
    return max(step, round(value / step) * step)


_PRE_MONEY_DEPENDS = (
    *FORECAST_KEYS,
    "investors.comps_multiple",
    "capital.cash",
    "capital.debt",
)


def _shares_pre(ctx: Ctx) -> float:
    return _round_to(comps_pre_money(ctx.values) / _TARGET_IPO_PRICE, 1e6)


def _raise(ctx: Ctx) -> float:
    return _round_to(0.20 * comps_pre_money(ctx.values), 25e6)


# The bear and bull values of the scenario drivers (§11.1), relative to base.
_DRIVERS: tuple[tuple[str, Callable[[float], float], Callable[[float], float]], ...] = (
    ("customers.growth_y1", lambda b: b * 0.6, lambda b: b * 1.3),
    ("customers.churn", lambda b: b * 1.5, lambda b: b * 0.7),
    ("customers.arpu_growth", lambda b: b - 0.02, lambda b: b + 0.02),
    ("market.p_max", lambda b: b * 0.7, lambda b: b * 1.3),
    ("costs.cac_paid", lambda b: b * 1.3, lambda b: b * 0.8),
    ("people.elasticity", lambda b: b + 0.1, lambda b: b - 0.1),
    ("investors.comps_multiple", lambda b: b * 0.7, lambda b: b * 1.3),
    ("rates.execution_premium", lambda b: b + 0.03, lambda b: b - 0.02),
    ("rates.beta_stage2", lambda b: b + 0.3, lambda b: b - 0.2),
    ("rates.terminal_growth", lambda b: b - 0.005, lambda b: b + 0.005),
)

#: The scenario drivers of §11.1, in the order the Monte Carlo draws them.
DRIVER_KEYS = tuple(key for key, _, _ in _DRIVERS)
#: The operating drivers, which share the Monte Carlo "execution" factor.
OPERATING_DRIVERS = DRIVER_KEYS[:6]

# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

_F = FieldSpec
M = Unit.MONEY
P = Unit.PERCENT

_CATALOGUE: list[FieldSpec] = [
    # -- 1 Company (the S-1 cover page) ------------------------------------
    _F(
        "company.name",
        1,
        "Company name",
        Unit.TEXT,
        Const("Newco Inc."),
        "The registrant's legal name, as on the cover of the S-1.",
    ),
    _F(
        "company.ticker",
        1,
        "Proposed ticker",
        Unit.TEXT,
        Rule(_ticker, ("company.name",)),
        "The symbol it will trade under: 1-8 characters of A-Z, 0-9, '.' or "
        "'_', the same rule pm-new-symbol enforces.",
        pattern=_SYMBOL,
    ),
    _F(
        "company.sector",
        1,
        "Sector preset",
        Unit.CHOICE,
        Const("b2b_saas"),
        "The business model. It supplies every default marked 'preset', so a "
        "whole company can be built by pressing Enter.",
        choices=SECTORS,
    ),
    _F(
        "company.sic_code",
        1,
        "SIC code",
        Unit.TEXT,
        FromPreset("sic_code"),
        "Standard Industrial Classification code shown on the S-1 cover. "
        "Display only.",
    ),
    _F(
        "company.incorporation",
        1,
        "Incorporated in",
        Unit.TEXT,
        Const("Delaware"),
        "Where the company is incorporated. Display only.",
    ),
    _F(
        "company.currency",
        1,
        "Currency",
        Unit.TEXT,
        Const("USD"),
        "The currency of every amount. The model itself is currency-agnostic.",
    ),
    _F(
        "company.fiscal_year_end",
        1,
        "Fiscal year end",
        Unit.TEXT,
        Const("December 31"),
        "Display only.",
    ),
    _F(
        "company.dual_class",
        1,
        "Dual-class shares",
        Unit.BOOL,
        Const(False),
        "Founders keep extra votes through a second share class. Institutions "
        "discount the governance risk, and some indices exclude it.",
    ),
    _F(
        "company.lead_underwriter",
        1,
        "Lead underwriter",
        Unit.TEXT,
        Const("Fictive & Co."),
        "The bank running the book. Display only.",
    ),
    _F(
        "company.use_of_proceeds",
        1,
        "Use of proceeds",
        Unit.TEXT,
        Const(
            "General corporate purposes, including working capital, R&D and "
            "sales expansion"
        ),
        "What the money raised will be spent on, as the S-1 must say.",
    ),
    # -- 2 Market ----------------------------------------------------------
    _F(
        "market.tam",
        2,
        "Total addressable market",
        M,
        FromPreset("tam"),
        "TAM: all yearly spending on this kind of product, by everyone, " "today.",
        lo=1e6,
        hi=1e14,
    ),
    _F(
        "market.tam_growth",
        2,
        "TAM growth, year 1",
        P,
        FromPreset("tam_growth"),
        "How fast the whole market grows next year. It fades to the terminal "
        "growth rate by the end of the horizon, because no market outgrows "
        "the economy forever.",
        lo=-0.5,
        hi=1.0,
    ),
    _F(
        "market.sam_share",
        2,
        "SAM share of TAM",
        P,
        FromPreset("sam_share"),
        "Serviceable addressable market: the part of the TAM this product can "
        "actually serve (region, segment, language).",
        lo=0.001,
        hi=1.0,
    ),
    _F(
        "market.structure",
        2,
        "Market structure",
        Unit.CHOICE,
        Const("competitive"),
        "How contested the market is. It sets the largest share of the SAM "
        "the company can ever win.",
        choices=MARKET_STRUCTURES,
    ),
    _F(
        "market.p_max",
        2,
        "Maximum share of SAM",
        P,
        Rule(
            lambda c: c.presets.market_structures[c["market.structure"]],
            ("market.structure",),
        ),
        "The ceiling on market share. Customer growth slows as the company "
        "approaches it: the adoption S-curve.",
        lo=0.001,
        hi=1.0,
        advanced=True,
    ),
    # -- 3 Customers & pricing ---------------------------------------------
    _F(
        "customers.last_fy_revenue",
        3,
        "Last FY revenue",
        M,
        FromPreset("revenue_last_fy"),
        "Revenue in the last completed fiscal year (year 0).",
        lo=1,
        hi=1e13,
        inverse=Rule(
            lambda c: _REVENUE_TO_RUN_RATE * c["customers.now"] * c["customers.arpu"],
            ("customers.now", "customers.arpu"),
        ),
        inverse_when="customers.now",
    ),
    _F(
        "customers.now",
        3,
        "Customers now",
        Unit.COUNT,
        Rule(
            lambda c: round(
                c["customers.last_fy_revenue"]
                / (_REVENUE_TO_RUN_RATE * c["customers.arpu"])
            ),
            ("customers.last_fy_revenue", "customers.arpu"),
        ),
        "Paying customers at the end of year 0. What a 'customer' is depends "
        "on the sector: an account, a subscriber, a buyer, a merchant.",
        lo=1,
        hi=1e10,
    ),
    _F(
        "customers.arpu",
        3,
        "ARPU per year",
        M,
        FromPreset("arpu"),
        "Average revenue per customer per year. For SaaS, the annual contract "
        "value.",
        lo=0.01,
        hi=1e9,
    ),
    _F(
        "customers.arpu_growth",
        3,
        "ARPU growth, year 1",
        P,
        Const(0.05),
        "Price rises and upsell. Fades to inflation over the horizon.",
        lo=-0.5,
        hi=1.0,
    ),
    _F(
        "customers.churn",
        3,
        "Annual churn",
        P,
        FromPreset("churn"),
        "The share of customers lost each year. It caps customer lifetime "
        "value at ARPU × gross margin / churn.",
        lo=0.001,
        hi=0.99,
    ),
    _F(
        "customers.growth_y1",
        3,
        "Customer growth, year 1",
        P,
        FromPreset("customer_growth_y1"),
        "Net growth in customers next year. It calibrates how hard the "
        "company acquires; growth then slows by itself as the market "
        "saturates.",
        lo=-0.5,
        hi=5.0,
    ),
    # -- 4 People ------------------------------------------------------------
    _F(
        "people.headcount",
        4,
        "Headcount",
        Unit.COUNT,
        Rule(
            lambda c: max(
                1, round(c["customers.last_fy_revenue"] / c.preset.revenue_per_employee)
            ),
            ("customers.last_fy_revenue", "company.sector"),
        ),
        "Employees today. The default assumes the preset's revenue per " "employee.",
        lo=1,
        hi=1e7,
    ),
    _F(
        "people.loaded_cost",
        4,
        "Loaded cost per employee",
        M,
        FromPreset("loaded_cost"),
        "Salary plus benefits, payroll tax, office and equipment per person "
        "per year.",
        lo=1,
        hi=1e7,
    ),
    _F(
        "people.wage_inflation",
        4,
        "Wage inflation",
        P,
        Const(0.035),
        "Yearly rise of the loaded cost.",
        lo=-0.1,
        hi=0.5,
    ),
    _F(
        "people.headcount_mode",
        4,
        "Headcount growth",
        Unit.CHOICE,
        Const("follow_revenue"),
        "'follow_revenue' grows staff at a fraction of revenue growth "
        "(operating leverage); 'explicit' fades from a year-1 rate to the "
        "floor.",
        choices=("follow_revenue", "explicit"),
    ),
    _F(
        "people.elasticity",
        4,
        "Headcount elasticity",
        Unit.NUMBER,
        Const(0.6),
        "Staff growth per unit of revenue growth, in 'follow_revenue' mode. "
        "Below 1, revenue per employee rises as the company scales.",
        lo=0.0,
        hi=3.0,
    ),
    _F(
        "people.growth_y1",
        4,
        "Headcount growth, year 1",
        P,
        Const(0.25),
        "Only in 'explicit' mode: next year's hiring rate.",
        lo=-0.5,
        hi=3.0,
    ),
    _F(
        "people.growth_floor",
        4,
        "Headcount growth floor",
        P,
        Const(0.04),
        "The minimum yearly staff growth ('follow_revenue'), and the year-N "
        "rate ('explicit').",
        lo=-0.5,
        hi=1.0,
    ),
    _F(
        "people.split_rnd",
        4,
        "Staff share: R&D",
        P,
        Rule(lambda c: c.preset.staff_split[0], ("company.sector",)),
        "Engineers and product people. The four shares must sum to 100%.",
        lo=0.0,
        hi=1.0,
        advanced=True,
    ),
    _F(
        "people.split_snm",
        4,
        "Staff share: sales & marketing",
        P,
        Rule(lambda c: c.preset.staff_split[1], ("company.sector",)),
        "Sales and marketing staff.",
        lo=0.0,
        hi=1.0,
        advanced=True,
    ),
    _F(
        "people.split_gna",
        4,
        "Staff share: G&A",
        P,
        Rule(lambda c: c.preset.staff_split[2], ("company.sector",)),
        "Finance, legal, HR and management.",
        lo=0.0,
        hi=1.0,
        advanced=True,
    ),
    _F(
        "people.split_ops",
        4,
        "Staff share: operations",
        P,
        Rule(lambda c: c.preset.staff_split[3], ("company.sector",)),
        "Support and service operations; a cost of revenue.",
        lo=0.0,
        hi=1.0,
        advanced=True,
    ),
    # -- 5 Costs -------------------------------------------------------------
    _F(
        "costs.infra_fixed",
        5,
        "Infrastructure, fixed",
        M,
        FromPreset("infra_fixed"),
        "Yearly hosting and platform cost that does not depend on customers. "
        "Escalates with inflation.",
        lo=0,
        hi=1e12,
    ),
    _F(
        "costs.infra_per_customer",
        5,
        "Infrastructure per customer",
        M,
        FromPreset("infra_per_customer"),
        "Yearly cost of serving one more customer (for hardware: the unit "
        "cost delivered).",
        lo=0,
        hi=1e9,
    ),
    _F(
        "costs.other_cogs_pct",
        5,
        "Other cost of revenue",
        P,
        FromPreset("other_cogs_pct"),
        "Payment fees, third-party licences, app-store fees, as a share of " "revenue.",
        lo=0.0,
        hi=0.95,
    ),
    _F(
        "costs.cac_paid",
        5,
        "Paid acquisition cost per customer",
        M,
        Rule(
            lambda c: c.preset.cac_arpu_multiple * c["customers.arpu"],
            ("company.sector", "customers.arpu"),
        ),
        "Marketing spent to win one new customer, excluding sales staff (they "
        "are in headcount).",
        lo=0,
        hi=1e9,
    ),
    _F(
        "costs.cac_growth",
        5,
        "Acquisition cost growth",
        P,
        Const(0.03),
        "Customers get dearer to buy as the easy ones are won.",
        lo=-0.5,
        hi=1.0,
    ),
    _F(
        "costs.rnd_nonstaff_pct",
        5,
        "R&D, non-staff",
        P,
        Const(0.04),
        "Tools, licences and cloud for development, as a share of revenue.",
        lo=0.0,
        hi=1.0,
    ),
    _F(
        "costs.gna_nonstaff_pct",
        5,
        "G&A, non-staff",
        P,
        Const(0.03),
        "Rent, insurance and advisers, as a share of revenue.",
        lo=0.0,
        hi=1.0,
    ),
    _F(
        "costs.public_company",
        5,
        "Public-company cost",
        M,
        Const(3e6),
        "What being listed costs each year: audit, directors' insurance, "
        "investor relations, listing fees, compliance.",
        lo=0,
        hi=1e10,
    ),
    _F(
        "costs.sbc_pct",
        5,
        "Stock-based compensation",
        P,
        Const(0.12),
        "Equity paid to staff, as a share of staff cost. A real cost: the "
        "dilution happens whether or not cash changes hands.",
        lo=0.0,
        hi=1.0,
    ),
    _F(
        "costs.inflation",
        5,
        "General inflation",
        P,
        Const(0.025),
        "Escalates fixed costs; ARPU growth fades to it.",
        lo=-0.05,
        hi=0.5,
    ),
    # -- 6 Capital & tax -----------------------------------------------------
    _F(
        "capital.capex_pct",
        6,
        "Capex",
        P,
        FromPreset("capex_pct"),
        "Capital expenditure (equipment, capitalised hardware) as a share of "
        "revenue.",
        lo=0.0,
        hi=1.0,
    ),
    _F(
        "capital.useful_life",
        6,
        "Useful life",
        Unit.YEARS,
        Const(4),
        "Years over which capex is depreciated, straight line.",
        lo=1,
        hi=50,
    ),
    _F(
        "capital.ppe_start",
        6,
        "Opening PP&E",
        M,
        Rule(
            lambda c: c["capital.capex_pct"]
            * c["customers.last_fy_revenue"]
            * c["capital.useful_life"]
            / 2,
            ("capital.capex_pct", "customers.last_fy_revenue", "capital.useful_life"),
        ),
        "Property, plant and equipment on the balance sheet today. The "
        "default is the steady-state balance of the capex schedule.",
        lo=0,
        hi=1e13,
    ),
    _F(
        "capital.nwc_pct",
        6,
        "Net working capital",
        P,
        FromPreset("nwc_pct"),
        "Receivables and inventory minus payables and prepayments, as a share "
        "of revenue. Negative when customers pay in advance: growth then "
        "releases cash.",
        lo=-1.0,
        hi=1.0,
    ),
    _F(
        "capital.tax_rate",
        6,
        "Tax rate",
        P,
        Const(0.25),
        "Corporate income tax on profits.",
        lo=0.0,
        hi=0.9,
    ),
    _F(
        "capital.nol",
        6,
        "Tax losses carried forward",
        M,
        Const(0.0),
        "Past losses that shelter future profits from tax.",
        lo=0,
        hi=1e13,
    ),
    _F(
        "capital.cash",
        6,
        "Cash",
        M,
        Const(0.0),
        "Cash on the balance sheet before the IPO.",
        lo=0,
        hi=1e13,
    ),
    _F(
        "capital.debt",
        6,
        "Debt",
        M,
        Const(0.0),
        "Financial debt before the IPO.",
        lo=0,
        hi=1e13,
    ),
    # -- 7 Discount rates ----------------------------------------------------
    _F(
        "rates.risk_free",
        7,
        "Risk-free rate",
        P,
        Const(0.0425),
        "The long government bond yield. The default is a round number, not a "
        "quote: set today's value.",
        lo=-0.05,
        hi=0.3,
    ),
    _F(
        "rates.erp",
        7,
        "Equity risk premium",
        P,
        Const(0.05),
        "The extra return investors demand for holding equities over bonds.",
        lo=0.0,
        hi=0.3,
    ),
    _F(
        "rates.beta_stage1",
        7,
        "Beta, years 1-5",
        Unit.NUMBER,
        FromPreset("beta_stage1"),
        "Sensitivity to the market while young.",
        lo=0.0,
        hi=5.0,
    ),
    _F(
        "rates.beta_stage2",
        7,
        "Beta, year 6 on",
        Unit.NUMBER,
        FromPreset("beta_stage2"),
        "Sensitivity to the market once mature; drifts toward 1.",
        lo=0.0,
        hi=5.0,
    ),
    _F(
        "rates.size_premium_1",
        7,
        "Size premium, years 1-5",
        P,
        Const(0.015),
        "Extra return demanded of small, illiquid companies.",
        lo=0.0,
        hi=0.2,
    ),
    _F(
        "rates.size_premium_2",
        7,
        "Size premium, year 6 on",
        P,
        Const(0.005),
        "The size premium once the company is larger.",
        lo=0.0,
        hi=0.2,
    ),
    _F(
        "rates.execution_premium",
        7,
        "Execution premium",
        P,
        Const(0.03),
        "Stage 1 only: the risk that the plan simply does not happen. It is "
        "why the first five years get their own rate.",
        lo=0.0,
        hi=0.5,
    ),
    _F(
        "rates.debt_ratio",
        7,
        "Target debt ratio D/V",
        P,
        Const(0.0),
        "Debt as a share of capital; most growth IPOs have none.",
        lo=0.0,
        hi=0.9,
        advanced=True,
    ),
    _F(
        "rates.cost_of_debt",
        7,
        "Cost of debt",
        P,
        Rule(lambda c: c["rates.risk_free"] + 0.03, ("rates.risk_free",)),
        "The pre-tax interest rate; used only when D/V > 0.",
        lo=0.0,
        hi=0.5,
        advanced=True,
    ),
    _F(
        "rates.stage1_years",
        7,
        "Stage-1 years",
        Unit.YEARS,
        Const(5),
        "Years discounted at the stage-1 rate.",
        lo=1,
        hi=20,
        advanced=True,
    ),
    _F(
        "rates.horizon",
        7,
        "Forecast horizon",
        Unit.YEARS,
        Const(10),
        "Years forecast explicitly before the terminal value takes over.",
        lo=2,
        hi=50,
        advanced=True,
    ),
    _F(
        "rates.terminal_growth",
        7,
        "Terminal growth",
        P,
        Const(0.025),
        "Growth for ever after the horizon. Keep it at or below the "
        "risk-free rate: no company outgrows the economy for ever.",
        lo=-0.05,
        hi=0.1,
    ),
    _F(
        "rates.ronic_spread",
        7,
        "RONIC spread",
        P,
        Const(0.02),
        "Return on new capital above the stage-2 rate. At 0, growth creates "
        "no value.",
        lo=-0.1,
        hi=0.5,
        advanced=True,
    ),
    _F(
        "rates.r1_override",
        7,
        "Override rate, years 1-5",
        P,
        Const(None),
        "Enter the stage-1 rate directly; the build-up is then ignored.",
        lo=0.001,
        hi=1.0,
        optional=True,
        advanced=True,
    ),
    _F(
        "rates.r2_override",
        7,
        "Override rate, year 6 on",
        P,
        Const(None),
        "Enter the stage-2 rate directly; the build-up is then ignored.",
        lo=0.001,
        hi=1.0,
        optional=True,
        advanced=True,
    ),
    _F(
        "rates.mid_year",
        7,
        "Mid-year convention",
        Unit.BOOL,
        Const(False),
        "Discount each year's cash as if it arrived mid-year.",
        advanced=True,
    ),
    # -- 8 Offering ----------------------------------------------------------
    _F(
        "offering.shares_pre",
        8,
        "Pre-IPO shares (fully diluted)",
        Unit.COUNT,
        Rule(_shares_pre, _PRE_MONEY_DEPENDS),
        "Shares outstanding before the IPO, options included. Companies split "
        "their stock before listing so the price lands near 20; the default "
        "does the same.",
        lo=1,
        hi=1e12,
    ),
    _F(
        "offering.raise",
        8,
        "Primary raise (gross)",
        M,
        Rule(_raise, _PRE_MONEY_DEPENDS),
        "New money for the company, before fees. Default: 20% of the "
        "comparables valuation.",
        lo=1,
        hi=1e13,
    ),
    _F(
        "offering.secondary_shares",
        8,
        "Secondary shares",
        Unit.COUNT,
        Const(0),
        "Existing shares sold by current holders; the money goes "
        "to them, not the company.",
        lo=0,
        hi=1e12,
    ),
    _F(
        "offering.gross_spread",
        8,
        "Gross spread",
        P,
        Const(0.07),
        "The underwriters' fee, as a share of the money raised.",
        lo=0.0,
        hi=0.2,
    ),
    _F(
        "offering.other_expenses",
        8,
        "Other offering expenses",
        M,
        Rule(lambda c: 2e6 + 0.01 * c["offering.raise"], ("offering.raise",)),
        "Legal, audit, printing and listing fees.",
        lo=0,
        hi=1e11,
    ),
    _F(
        "offering.ipo_discount",
        8,
        "IPO discount",
        P,
        Const(0.15),
        "The deliberate discount to fair value that makes the deal attractive "
        "and leaves room for a first-day rise.",
        lo=0.0,
        hi=0.6,
    ),
    _F(
        "offering.min_discount",
        8,
        "Minimum IPO discount",
        P,
        Const(0.05),
        "Below this the bankers will not launch.",
        lo=0.0,
        hi=0.6,
        advanced=True,
    ),
    _F(
        "offering.lockup_days",
        8,
        "Lock-up",
        Unit.DAYS,
        Const(180),
        "Days existing holders may not sell after the IPO.",
        lo=0,
        hi=1095,
        advanced=True,
    ),
    _F(
        "offering.lockup_coverage",
        8,
        "Lock-up coverage",
        P,
        Const(1.0),
        "Share of pre-IPO shares under lock-up.",
        lo=0.0,
        hi=1.0,
        advanced=True,
    ),
    _F(
        "offering.cornerstone",
        8,
        "Cornerstone commitment",
        M,
        Const(0.0),
        "Money pre-committed by anchor investors before launch.",
        lo=0,
        hi=1e12,
        advanced=True,
    ),
    _F(
        "offering.cornerstone_lockin_days",
        8,
        "Cornerstone lock-in",
        Unit.DAYS,
        Const(180),
        "Days the cornerstones' shares are locked; they are not free float "
        "until then.",
        lo=0,
        hi=1095,
        advanced=True,
    ),
    _F(
        "offering.retail_tranche",
        8,
        "Retail tranche",
        P,
        Const(0.10),
        "Share of the offer reserved for retail investors.",
        lo=0.0,
        hi=1.0,
        advanced=True,
    ),
    # -- 9 Investors & sentiment ---------------------------------------------
    _F(
        "investors.inst_interest",
        9,
        "Institutional interest",
        Unit.CHOICE,
        Const("medium"),
        "Feedback from 'testing the waters' before launch: how warm are the " "funds?",
        choices=INTEREST_LEVELS,
    ),
    _F(
        "investors.n_institutions",
        9,
        "Institutions in the book",
        Unit.COUNT,
        Const(40),
        "How many institutions put in orders (book interest).",
        lo=0,
        hi=10_000,
    ),
    _F(
        "investors.avg_ticket",
        9,
        "Average institutional order",
        M,
        Rule(lambda c: 0.05 * c["offering.raise"], ("offering.raise",)),
        "The typical order size, at fair value.",
        lo=0,
        hi=1e12,
    ),
    _F(
        "investors.retail_interest",
        9,
        "Retail interest",
        Unit.CHOICE,
        Const("medium"),
        "How keen private investors are.",
        choices=INTEREST_LEVELS,
    ),
    _F(
        "investors.n_retail",
        9,
        "Retail applicants",
        Unit.COUNT,
        Const(20_000),
        "Private investors applying for shares.",
        lo=0,
        hi=1e8,
    ),
    _F(
        "investors.retail_application",
        9,
        "Average retail application",
        M,
        Const(2_500.0),
        "The typical retail order.",
        lo=0,
        hi=1e9,
    ),
    _F(
        "investors.hype",
        9,
        "Hype factor",
        Unit.NUMBER,
        Const(3),
        "0-10: press and social-media excitement. It swells retail demand and "
        "makes it less price-sensitive.",
        lo=0,
        hi=10,
    ),
    _F(
        "investors.target_coverage",
        9,
        "Target coverage",
        Unit.RATIO,
        Const(3.0),
        "Demand the bankers want per share offered. An oversubscribed book "
        "supports the aftermarket.",
        lo=1,
        hi=50,
    ),
    _F(
        "investors.comps_multiple",
        9,
        "Comparable EV / NTM revenue",
        Unit.RATIO,
        FromPreset("comps_ev_revenue"),
        "What listed peers trade at, per unit of next year's revenue.",
        lo=0,
        hi=200,
    ),
    _F(
        "investors.dcf_weight",
        9,
        "DCF weight",
        P,
        Const(0.7),
        "Weight of the DCF in fair value; the rest is comparables.",
        lo=0.0,
        hi=1.0,
    ),
    _F(
        "investors.inst_elasticity",
        9,
        "Institutional price elasticity",
        Unit.NUMBER,
        Const(3.0),
        "How sharply institutions cut orders as the price nears fair value.",
        lo=0,
        hi=20,
        advanced=True,
    ),
    # -- 10 Index --------------------------------------------------------------
    _F(
        "index.min_cap",
        10,
        "Minimum market cap",
        M,
        Const(500e6),
        "Index rule: full market capitalisation at least this.",
        lo=0,
        hi=1e13,
    ),
    _F(
        "index.min_free_float",
        10,
        "Minimum free float",
        P,
        Const(0.15),
        "Index rule: share of shares freely tradable.",
        lo=0.0,
        hi=1.0,
    ),
    _F(
        "index.min_ff_cap",
        10,
        "Minimum free-float cap",
        M,
        Const(150e6),
        "Index rule: value of the free float.",
        lo=0,
        hi=1e13,
    ),
    _F(
        "index.seasoning_days",
        10,
        "Seasoning",
        Unit.DAYS,
        Const(63),
        "Index rule: trading days after listing before inclusion.",
        lo=0,
        hi=1000,
    ),
    _F(
        "index.fast_entry_cap",
        10,
        "Fast-entry market cap",
        M,
        Const(5e9),
        "Index rule: IPOs at least this large enter early.",
        lo=0,
        hi=1e14,
    ),
    _F(
        "index.fast_entry_days",
        10,
        "Fast-entry delay",
        Unit.DAYS,
        Const(5),
        "Trading days before a fast entry.",
        lo=0,
        hi=1000,
    ),
    _F(
        "index.allow_multi_class",
        10,
        "Multiple share classes allowed",
        Unit.BOOL,
        Const(False),
        "Index rule for dual-class companies.",
    ),
    _F(
        "index.relax",
        10,
        "Exchange may relax",
        Unit.CHOICE,
        Const("none"),
        "Which index rules the exchange is willing to loosen for this listing.",
        choices=("none", "seasoning", "float", "multi_class", "all"),
    ),
    _F(
        "index.passive_aum",
        10,
        "Passive assets tracking the index",
        M,
        Const(None),
        "Optional: with the index's free-float cap below, estimates the "
        "forced buying by index funds at inclusion.",
        lo=0,
        hi=1e14,
        optional=True,
    ),
    _F(
        "index.index_ff_cap",
        10,
        "Index free-float market cap",
        M,
        Const(None),
        "Optional: the free-float value of all current constituents, which "
        "sets the new listing's weight in the index.",
        lo=0,
        hi=1e15,
        optional=True,
    ),
    # -- 11 Management -----------------------------------------------------------
    _F(
        "management.last_round",
        11,
        "Last private round, post-money",
        M,
        Const(None),
        "The valuation at the last venture round. Founders hate a 'down-round "
        "IPO' below it.",
        lo=0,
        hi=1e14,
        optional=True,
    ),
    _F(
        "management.min_market_cap",
        11,
        "Minimum market cap",
        M,
        Rule(lambda c: c["management.last_round"], ("management.last_round",)),
        "The lowest valuation the CEO and CFO will accept. Below it they "
        "postpone the IPO.",
        lo=0,
        hi=1e14,
        optional=True,
    ),
    _F(
        "management.max_dilution",
        11,
        "Maximum dilution",
        P,
        Const(0.25),
        "New shares as a share of all shares after the IPO.",
        lo=0.0,
        hi=1.0,
    ),
    _F(
        "management.min_net_proceeds",
        11,
        "Minimum net proceeds",
        M,
        Const(None),
        "Optional: the least cash the company must receive.",
        lo=0,
        hi=1e13,
        optional=True,
    ),
    # -- 12 Simulation -----------------------------------------------------------
    _F(
        "simulation.mode",
        12,
        "Mode",
        Unit.CHOICE,
        Const("both"),
        "Deterministic scenarios, Monte Carlo, or both side by side.",
        choices=("deterministic", "montecarlo", "both"),
    ),
    _F(
        "simulation.draws",
        12,
        "Monte Carlo draws",
        Unit.COUNT,
        Const(10_000),
        "Number of simulated companies.",
        lo=100,
        hi=1e6,
    ),
    _F(
        "simulation.seed",
        12,
        "Random seed",
        Unit.COUNT,
        Const(42),
        "The same seed gives the same simulation.",
        lo=0,
        hi=2**31 - 1,
    ),
    _F(
        "simulation.rho",
        12,
        "Execution correlation ρ",
        Unit.NUMBER,
        Const(0.5),
        "How strongly the operating drivers move together (0-1).",
        lo=0.0,
        hi=1.0,
    ),
]


def _relative(fn: Callable[[float], float], key: str) -> Rule:
    return Rule(lambda c: fn(c[key]), (key,))


def _driver_fields() -> list[FieldSpec]:
    """Bear and bull values of each scenario driver (§11.1), all advanced."""
    by_key = {spec.key: spec for spec in _CATALOGUE}
    out: list[FieldSpec] = []
    for key, bear, bull in _DRIVERS:
        base = by_key[key]
        for case, fn in (("bear", bear), ("bull", bull)):
            out.append(
                FieldSpec(
                    f"simulation.{case}.{key}",
                    12,
                    f"{base.label}: {case}",
                    base.unit,
                    _relative(fn, key),
                    f"The {case} value of '{base.label}', for the scenarios "
                    "and the Monte Carlo range.",
                    lo=base.lo,
                    hi=base.hi,
                    advanced=True,
                )
            )
    return out


FIELDS: tuple[FieldSpec, ...] = (*_CATALOGUE, *_driver_fields())
BY_KEY: Mapping[str, FieldSpec] = {spec.key: spec for spec in FIELDS}
