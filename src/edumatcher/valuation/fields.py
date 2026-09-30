"""Every question pm-valuation asks, with its default and its help text.

Design §19.3–19.4. A field's default is one of three kinds, which is also the
provenance the report shows for it:

``Const``       a fixed default                              → "default"
``FromPreset``  an attribute of the chosen sector preset      → "preset"
``FromMarket``  an attribute of the chosen market (--market) → "default"
``Rule``        computed from other fields                    → "derived"

The student's own answer always wins ("you"). Percentages are fractions.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any

from edumatcher.valuation.model.valuation import FORECAST_KEYS, comps_pre_money
from edumatcher.valuation.presets import Market, Preset, Presets

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

    @property
    def market(self) -> Market:
        return self.presets.markets[self.values["company.market"]]

    def money(self, attr: str) -> float:
        """A money attribute of the preset (in US dollars) in the market's
        currency. Pay and revenue per employee both follow the market's salary
        level, so staff cost stays the same share of revenue: a cheaper market
        employs more people, not more profitably."""
        per_person = attr in ("loaded_cost", "revenue_per_employee")
        level = self.market.salary_level if per_person else 1.0
        return float(getattr(self.preset, attr)) * self.market.fx * level


@dataclass(frozen=True)
class Const:
    value: Any


@dataclass(frozen=True)
class FromPreset:
    attr: str


@dataclass(frozen=True)
class FromMarket:
    attr: str


@dataclass(frozen=True)
class Rule:
    fn: Callable[[Ctx], Any]
    depends: tuple[str, ...]


Default = Const | FromPreset | FromMarket | Rule

#: Choices that come from the presets file rather than from the catalogue.
SECTORS = "sectors"
MARKET_STRUCTURES = "market_structures"
MARKETS = "markets"
INTEREST_LEVELS = ("very_low", "low", "medium", "high", "very_high")


class Level(IntEnum):
    """How much of the interview is shown (F3, --level); each level adds fields."""

    BEGINNER = 1
    INTERMEDIATE = 2
    ADVANCED = 3
    EXPERT = 4


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
    choices: tuple[str, ...] | str | None = None  # or SECTORS / MARKETS / …
    pattern: str | None = None  # full-match regex for text
    optional: bool = False  # None ("not given") is a valid value
    level: Level = Level.EXPERT  # the lowest level that shows the field
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
    "company.market",
)


def _shares_pre(ctx: Ctx) -> float:
    return _round_to(comps_pre_money(ctx.values) / ctx.market.target_price, 1e6)


def _raise(ctx: Ctx) -> float:
    return _round_to(0.20 * comps_pre_money(ctx.values), 25e6 * ctx.market.fx)


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
    # -- 1 Company (the cover of the offering document) --------------------
    _F(
        "company.name",
        1,
        "Company name",
        Unit.TEXT,
        FromMarket("company_name"),
        "The registrant's legal name: the company filing to go public, as on "
        "the cover of its offering document. In Sweden that is the "
        "prospectus, and the name ends in AB (aktiebolag, 'share company', "
        "like Inc.). In the US it is the S-1, the registration statement "
        "filed with the SEC before an IPO.",
        level=Level.BEGINNER,
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
        level=Level.INTERMEDIATE,
    ),
    _F(
        "company.sector",
        1,
        "Sector preset",
        Unit.CHOICE,
        Const("b2b_saas"),
        "The business model. The preset supplies every value marked 'preset' "
        "(market size, price per customer, customer losses, costs, risk "
        "measures and how similar companies are valued), chosen to fit "
        "together. b2b_saas: business software on annual subscriptions; "
        "consumer_subscription: a paid app or media service; "
        "online_marketplace: a platform taking a cut of each sale; "
        "fintech_payments: payment processing for merchants; "
        "deep_tech_hardware: hardware plus service for enterprises.",
        choices=SECTORS,
        level=Level.BEGINNER,
    ),
    _F(
        "company.sic_code",
        1,
        "SIC code",
        Unit.TEXT,
        FromPreset("sic_code"),
        "The US Standard Industrial Classification code, shown on the S-1 "
        "cover in the US market only. Display only.",
        level=Level.ADVANCED,
    ),
    _F(
        "company.incorporation",
        1,
        "Incorporated in",
        Unit.TEXT,
        FromMarket("incorporation"),
        "Where the company is incorporated (registered as a legal person): "
        "Sweden for an AB, often Delaware for a US company. Display only.",
        level=Level.ADVANCED,
    ),
    _F(
        "company.currency",
        1,
        "Currency",
        Unit.TEXT,
        FromMarket("currency"),
        "The currency of every amount; it follows the market (SEK or USD). A "
        "billion ('bn') is 1,000 million: a miljard, not a biljon. You may "
        "also type 'md' or 'mdr' for miljard and 'mkr' for miljoner. The "
        "model itself works in any currency.",
        level=Level.ADVANCED,
    ),
    _F(
        "company.fiscal_year_end",
        1,
        "Fiscal year end",
        Unit.TEXT,
        Const("December 31"),
        "Display only.",
        level=Level.ADVANCED,
    ),
    _F(
        "company.dual_class",
        1,
        "Dual-class shares",
        Unit.BOOL,
        Const(False),
        "A second share class gives the founders more votes per share than "
        "public investors, so they keep control. Institutions (pension and "
        "investment funds) see a governance risk, so their orders in the book"
        " (the orders the banks collect before setting the price) fall by 5%."
        " Many stock-market indices, lists of shares that index funds must "
        "buy, exclude such companies (page 10).",
        level=Level.INTERMEDIATE,
    ),
    _F(
        "company.lead_underwriter",
        1,
        "Lead underwriter",
        Unit.TEXT,
        FromMarket("lead_underwriter"),
        "The investment bank that organises the IPO, markets the shares and "
        "runs the book (collects investors' orders). Display only.",
        level=Level.ADVANCED,
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
        "What the money raised will be spent on, as the offering document " "must say.",
        level=Level.ADVANCED,
    ),
    _F(
        "company.market",
        1,
        "Market",
        Unit.CHOICE,
        Const("se"),
        "Where the company lists, and so the rules and defaults it follows. "
        "'se': a Swedish IPO. An aktiebolag (AB, a Swedish limited company) "
        "lists on Nasdaq Stockholm with a prospectus approved by "
        "Finansinspektionen, the Swedish financial regulator; amounts in SEK. "
        "'us': a US IPO registered with the SEC on Form S-1; amounts in USD. "
        "It is best chosen at the start with --market: every money default "
        "follows its currency.",
        choices=MARKETS,
        level=Level.BEGINNER,
    ),
    # -- 2 Market ----------------------------------------------------------
    _F(
        "market.tam",
        2,
        "Total addressable market",
        M,
        FromPreset("tam"),
        "Total addressable market (TAM): all yearly spending on this kind of "
        "product, by every customer everywhere, today. It is the size of the "
        "whole industry, not the company's revenue. It is estimated top-down "
        "(industry reports) or bottom-up (possible customers × price). The "
        "company's growth is limited by the part it can serve (SAM) and the "
        "share of that it can win.",
        lo=1e6,
        hi=1e14,
        level=Level.BEGINNER,
    ),
    _F(
        "market.tam_growth",
        2,
        "TAM growth, year 1",
        P,
        FromPreset("tam_growth"),
        "How fast the whole market grows next year. The rate falls in a "
        "straight line to the terminal growth rate (the growth assumed for "
        "ever after the forecast) by the end of the forecast horizon (the "
        "last year forecast one by one, year 10 by default), because no "
        "market can outgrow the economy for ever.",
        lo=-0.5,
        hi=1.0,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "market.sam_share",
        2,
        "SAM share of TAM",
        P,
        FromPreset("sam_share"),
        "Serviceable addressable market (SAM): the part of the TAM this "
        "product can actually serve, given its regions, customer segments, "
        "language and price point. A product sold only in English to mid-"
        "sized firms might serve 20-30% of its TAM. SAM × the maximum share "
        "of SAM is the most revenue the company can ever reach.",
        lo=0.001,
        hi=1.0,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "market.structure",
        2,
        "Market structure",
        Unit.CHOICE,
        Const("competitive"),
        "How contested the market is. It sets the largest share of the SAM "
        "the company can realistically win: fragmented 5% (many small "
        "rivals), competitive 8%, oligopoly 15% (a few large players), "
        "dominant 30% (close to a monopoly). That ceiling decides how long "
        "fast growth can last before it flattens.",
        choices=MARKET_STRUCTURES,
        level=Level.BEGINNER,
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
        "The ceiling on market share, set directly instead of through the "
        "market structure. Customer growth follows an S-curve: fast while the"
        " company is small, slowing as it approaches this ceiling. It is one "
        "of the inputs with the largest effect on value, because it limits "
        "how big the company can ever get.",
        lo=0.001,
        hi=1.0,
        level=Level.EXPERT,
    ),
    # -- 3 Customers & pricing ---------------------------------------------
    _F(
        "customers.last_fy_revenue",
        3,
        "Last FY revenue",
        M,
        FromPreset("revenue_last_fy"),
        "Revenue in the last completed fiscal (financial) year, year 0: the "
        "starting point of the forecast. If you give only revenue or only the"
        " number of customers, the model derives the other from the average "
        "revenue per customer (ARPU, below).",
        lo=1,
        hi=1e13,
        inverse=Rule(
            lambda c: _REVENUE_TO_RUN_RATE * c["customers.now"] * c["customers.arpu"],
            ("customers.now", "customers.arpu"),
        ),
        inverse_when="customers.now",
        level=Level.BEGINNER,
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
        "on the sector: an account, a subscriber, a buyer, a merchant. "
        "Compared with the most customers the market allows, it shows how far"
        " along its S-curve the company already is.",
        lo=1,
        hi=1e10,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "customers.arpu",
        3,
        "ARPU per year",
        M,
        FromPreset("arpu"),
        "Average revenue per user: yearly revenue divided by the average "
        "number of customers. For business software it is the annual contract"
        " value; for a marketplace it is the fee the platform keeps (the take"
        " rate), not the value of what the buyer bought. Revenue = customers "
        "× ARPU.",
        lo=0.01,
        hi=1e9,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "customers.arpu_growth",
        3,
        "ARPU growth, year 1",
        P,
        Const(0.05),
        "How much ARPU rises next year, from price increases and from selling"
        " more to existing customers (upselling). It fades to general "
        "inflation by the end of the horizon. Because the market is measured "
        "in money, a faster-rising ARPU also lowers the number of customers "
        "the market can hold.",
        lo=-0.5,
        hi=1.0,
        level=Level.ADVANCED,
    ),
    _F(
        "customers.churn",
        3,
        "Annual churn",
        P,
        FromPreset("churn"),
        "The share of customers lost each year. At 8% the average customer "
        "stays 1 / 0.08 = 12.5 years; at 35% (typical for consumer apps) less"
        " than 3. Churn sets a customer's lifetime value, the profit it "
        "brings before leaving: ARPU × gross margin (the share of revenue "
        "left after the direct cost of serving customers) / churn. Business "
        "software often churns 5-15% a year.",
        lo=0.001,
        hi=0.99,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "customers.growth_y1",
        3,
        "Customer growth, year 1",
        P,
        FromPreset("customer_growth_y1"),
        "Net growth in customers next year: customers won minus customers "
        "lost, as a share of today's base. Growth then slows by itself as the"
        " company fills its reachable market (the S-curve). It is a scenario "
        "driver: one of the inputs the report varies between a pessimistic "
        "('bear') and an optimistic ('bull') value to show how uncertain the "
        "valuation is.",
        lo=-0.5,
        hi=5.0,
        level=Level.BEGINNER,
    ),
    # -- 4 People ------------------------------------------------------------
    _F(
        "people.headcount",
        4,
        "Headcount",
        Unit.COUNT,
        Rule(
            lambda c: max(
                1,
                round(c["customers.last_fy_revenue"] / c.money("revenue_per_employee")),
            ),
            ("customers.last_fy_revenue", "company.sector", "company.market"),
        ),
        "Employees today. The default assumes the preset's revenue per "
        "employee. Staff are the largest cost of a young technology company.",
        lo=1,
        hi=1e7,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "people.loaded_cost",
        4,
        "Loaded cost per employee",
        M,
        FromPreset("loaded_cost"),
        "The full yearly cost of one employee: salary plus benefits, payroll "
        "taxes, office space and equipment, often 1.3-1.5 times the salary "
        "itself. It rises with wage inflation. Headcount × loaded cost is the"
        " staff cost, split into research and development (R&D), sales and "
        "marketing, general and administrative (G&A: finance, legal, "
        "management) and operations.",
        lo=1,
        hi=1e7,
        level=Level.INTERMEDIATE,
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
        level=Level.ADVANCED,
    ),
    _F(
        "people.headcount_mode",
        4,
        "Headcount growth",
        Unit.CHOICE,
        Const("follow_revenue"),
        "How staff numbers grow. 'follow_revenue' grows headcount by a "
        "fraction of revenue growth (the elasticity), never slower than the "
        "floor, so revenue per employee rises and profit margins widen as the"
        " company grows: this is called operating leverage. 'explicit' "
        "ignores revenue and moves in a straight line from a year-1 hiring "
        "rate to the floor rate in the last forecast year.",
        choices=("follow_revenue", "explicit"),
        level=Level.ADVANCED,
    ),
    _F(
        "people.elasticity",
        4,
        "Headcount elasticity",
        Unit.NUMBER,
        Const(0.6),
        "Staff growth per unit of revenue growth, in 'follow_revenue' mode. "
        "At 0.6, revenue growing 50% needs 30% more staff. Below 1, revenue "
        "per employee rises and margins widen as the company scales "
        "(operating leverage). Staff are most of the cost, so this input "
        "often tops the report's tornado chart, which ranks inputs by how far"
        " changing each one alone moves the value.",
        lo=0.0,
        hi=3.0,
        level=Level.INTERMEDIATE,
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
        level=Level.ADVANCED,
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
        level=Level.ADVANCED,
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
        level=Level.EXPERT,
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
        level=Level.EXPERT,
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
        level=Level.EXPERT,
    ),
    _F(
        "people.split_ops",
        4,
        "Staff share: operations",
        P,
        Rule(lambda c: c.preset.staff_split[3], ("company.sector",)),
        "Support and service operations staff. Their cost is part of the cost"
        " of revenue: the direct cost of delivering the product to customers.",
        lo=0.0,
        hi=1.0,
        level=Level.EXPERT,
    ),
    # -- 5 Costs -------------------------------------------------------------
    _F(
        "costs.infra_fixed",
        5,
        "Infrastructure, fixed",
        M,
        FromPreset("infra_fixed"),
        "Yearly hosting and platform cost that does not depend on the number "
        "of customers. It is part of the cost of revenue (the direct cost of "
        "delivering the product), and it rises with inflation.",
        lo=0,
        hi=1e12,
        level=Level.ADVANCED,
    ),
    _F(
        "costs.infra_per_customer",
        5,
        "Infrastructure per customer",
        M,
        FromPreset("infra_per_customer"),
        "Yearly cost of serving one more customer: hosting, storage, support "
        "tools; for hardware, the unit cost of the delivered equipment. It is"
        " part of the cost of revenue, so it lowers the gross margin. It "
        "rises with inflation.",
        lo=0,
        hi=1e9,
        level=Level.ADVANCED,
    ),
    _F(
        "costs.other_cogs_pct",
        5,
        "Other cost of revenue",
        P,
        FromPreset("other_cogs_pct"),
        "Payment fees, third-party licences and app-store fees, as a share of"
        " revenue. Part of the cost of revenue, so it lowers the gross "
        "margin.",
        lo=0.0,
        hi=0.95,
        level=Level.ADVANCED,
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
        "Paid customer acquisition cost: the marketing spend (advertising, "
        "campaigns, referral fees) needed to win one new customer. Sales "
        "staff are not included; they are in headcount. A customer should "
        "bring in several times what it cost to win (lifetime value above 3 ×"
        " the full acquisition cost is a common rule). A scenario driver.",
        lo=0,
        hi=1e9,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "costs.cac_growth",
        5,
        "Acquisition cost growth",
        P,
        Const(0.03),
        "How fast the cost of winning a customer rises each year. The easiest"
        " customers are won first; later ones need more marketing, and rivals"
        " bid up advertising prices. Rising acquisition cost is one reason "
        "growth becomes expensive as a company matures, and it lowers the "
        "value of fast growth.",
        lo=-0.5,
        hi=1.0,
        level=Level.ADVANCED,
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
        level=Level.ADVANCED,
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
        level=Level.ADVANCED,
    ),
    _F(
        "costs.public_company",
        5,
        "Public-company cost",
        M,
        Const(3e6),
        "What being listed costs each year: audit, directors' and officers' "
        "insurance, investor relations, listing fees, compliance and "
        "quarterly reporting. It is a cost the company did not have while "
        "private, part of general and administrative expenses. The default is"
        " 3 m USD (30 m SEK) a year, growing with inflation.",
        lo=0,
        hi=1e10,
        level=Level.ADVANCED,
    ),
    _F(
        "costs.sbc_pct",
        5,
        "Stock-based compensation",
        P,
        Const(0.12),
        "Stock-based compensation: shares and options (rights to buy shares "
        "later at a fixed price) given to employees as pay, as a share of "
        "staff cost. No cash leaves the company, but it is a real cost: every"
        " new share dilutes the existing owners, who then own a smaller slice"
        " of the company. This model counts it as an expense.",
        lo=0.0,
        hi=1.0,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "costs.inflation",
        5,
        "General inflation",
        P,
        FromMarket("inflation"),
        "General price inflation. It escalates fixed costs, and ARPU growth "
        "fades to it. The Riksbank and the US Federal Reserve both aim for "
        "about 2% a year.",
        lo=-0.05,
        hi=0.5,
        level=Level.ADVANCED,
    ),
    # -- 6 Capital & tax -----------------------------------------------------
    _F(
        "capital.capex_pct",
        6,
        "Capex",
        P,
        FromPreset("capex_pct"),
        "Capital expenditure (capex): cash spent on long-lived equipment "
        "(servers, hardware, fit-outs), as a share of revenue. The income "
        "statement (the yearly profit-and-loss account) spreads its cost over"
        " the equipment's life as depreciation, but the cash leaves at once, "
        "so it lowers free cash flow (the cash left after all spending, which"
        " the valuation is built on) now.",
        lo=0.0,
        hi=1.0,
        level=Level.ADVANCED,
    ),
    _F(
        "capital.useful_life",
        6,
        "Useful life",
        Unit.YEARS,
        Const(4),
        "Years over which capex is depreciated, straight line: equipment "
        "bought for 4 m with a 4-year life costs 1 m a year in the income "
        "statement. Depreciation is not a cash payment; it spreads the cash "
        "already spent. A longer life raises reported profit early on, but "
        "does not change the cash spent or the free cash flow.",
        lo=1,
        hi=50,
        level=Level.ADVANCED,
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
        "Property, plant and equipment (PP&E): what the company's long-lived "
        "equipment is worth on its balance sheet (the list of what it owns "
        "and owes) today, at cost less depreciation so far. Capex adds to it "
        "each year and depreciation (PP&E ÷ useful life) wears it down. The "
        "default is the level the capex schedule settles at: capex × useful "
        "life ÷ 2.",
        lo=0,
        hi=1e13,
        level=Level.ADVANCED,
    ),
    _F(
        "capital.nwc_pct",
        6,
        "Net working capital",
        P,
        FromPreset("nwc_pct"),
        "Net working capital: cash tied up in running the business, as a "
        "share of revenue: money customers owe plus inventory, minus money "
        "owed to suppliers and customers' prepayments. When it is positive, "
        "growth absorbs cash. When it is negative, as when customers pay a "
        "year in advance, growth releases cash. Business software is often "
        "around -5%.",
        lo=-1.0,
        hi=1.0,
        level=Level.ADVANCED,
    ),
    _F(
        "capital.tax_rate",
        6,
        "Tax rate",
        P,
        FromMarket("tax_rate"),
        "Corporate income tax on operating profit (EBIT: earnings before "
        "interest and taxes): 20.6% in Sweden, about 25% in the US (federal "
        "plus state). A young company pays none while it makes losses, and "
        "those losses then shelter its first profits. After the forecast it "
        "pays the full rate, which matters most for the terminal value: the "
        "value of all years after the forecast.",
        lo=0.0,
        hi=0.9,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "capital.nol",
        6,
        "Tax losses carried forward",
        M,
        Const(0.0),
        "Net operating losses from past years that can be set against future "
        "profits, so no tax is paid until they are used up. Young companies "
        "often carry large losses, and ignoring them undervalues the company."
        " The forecast's own early losses are added to this balance.",
        lo=0,
        hi=1e13,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "capital.cash",
        6,
        "Cash",
        M,
        Const(0.0),
        "Cash on the balance sheet before the IPO. The discounted cash flow "
        "valuation (DCF: future cash flows converted into today's money) "
        "values the business itself, its enterprise value. Cash is not part "
        "of the business, so it is added separately to reach the value of the"
        " shares: equity value = enterprise value + cash − debt.",
        lo=0,
        hi=1e13,
        level=Level.BEGINNER,
    ),
    _F(
        "capital.debt",
        6,
        "Debt",
        M,
        Const(0.0),
        "Financial debt (loans, bonds) before the IPO. The DCF values the "
        "business for lenders and owners together; lenders are paid first, so"
        " debt is subtracted to reach the value of the shares (equity value ="
        " enterprise value + cash − debt).",
        lo=0,
        hi=1e13,
        level=Level.BEGINNER,
    ),
    # -- 7 Discount rates ----------------------------------------------------
    _F(
        "rates.risk_free",
        7,
        "Risk-free rate",
        P,
        FromMarket("risk_free"),
        "The return on a riskless investment: the yield (yearly return) on a "
        "long-dated government bond, the Swedish or US 10-year bond. It is "
        "the starting point of every discount rate: the yearly return "
        "investors require, used to turn future cash into today's money. The "
        "default is a recent round figure: set today's value. A higher rate "
        "lowers every value.",
        lo=-0.05,
        hi=0.3,
        level=Level.BEGINNER,
    ),
    _F(
        "rates.erp",
        7,
        "Equity risk premium",
        P,
        FromMarket("erp"),
        "Equity risk premium: the extra yearly return investors demand for "
        "holding shares in general instead of government bonds, because "
        "shares can fall. Surveys put it at about 5-6% (Sweden 5.6% in PwC's "
        "2026 study). It is multiplied by the beta (next field: how strongly "
        "the stock moves with the market), so it matters most for high-beta "
        "companies.",
        lo=0.0,
        hi=0.3,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "rates.beta_stage1",
        7,
        "Beta, years 1-5",
        Unit.NUMBER,
        FromPreset("beta_stage1"),
        "Beta measures how strongly a stock moves with the whole market: 1 "
        "moves with it, 1.5 moves 50% more, up and down. Young companies have"
        " high betas. Cost of equity (the return shareholders require) = "
        "risk-free rate + beta × equity risk premium: the capital asset "
        "pricing model (CAPM). The model uses two stages: years 1-5 (young, "
        "risky) and year 6 on (established).",
        lo=0.0,
        hi=5.0,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "rates.beta_stage2",
        7,
        "Beta, year 6 on",
        Unit.NUMBER,
        FromPreset("beta_stage2"),
        "The beta once the company is mature (year 6 onwards). Established "
        "companies behave more like the market as a whole, so their beta "
        "drifts toward 1. It also applies to the terminal value, so it has a "
        "large effect on value. A scenario driver.",
        lo=0.0,
        hi=5.0,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "rates.size_premium_1",
        7,
        "Size premium, years 1-5",
        P,
        Const(0.015),
        "Extra return investors demand from small, thinly traded companies, "
        "on top of the CAPM. Small companies fail more often and their shares"
        " are harder to sell quickly, so investors want to be paid more for "
        "holding them. Added to the stage-1 (years 1-5) cost of equity; 1-3% "
        "is a common range.",
        lo=0.0,
        hi=0.2,
        level=Level.ADVANCED,
    ),
    _F(
        "rates.size_premium_2",
        7,
        "Size premium, year 6 on",
        P,
        Const(0.005),
        "The size premium from year 6 onwards. By then the company is larger "
        "and its shares easier to trade, so the premium is usually smaller "
        "than in stage 1. It is part of the stage-2 rate, which also "
        "discounts the terminal value, so small changes here move value "
        "noticeably.",
        lo=0.0,
        hi=0.2,
        level=Level.ADVANCED,
    ),
    _F(
        "rates.execution_premium",
        7,
        "Execution premium",
        P,
        Const(0.03),
        "Stage 1 only: the extra return demanded for the risk that the plan "
        "simply does not happen. Products slip, customers do not come, key "
        "people leave. It is why the first five years get their own, higher "
        "rate; once the company is mature (stage 2) it falls away. A scenario"
        " driver.",
        lo=0.0,
        hi=0.5,
        level=Level.ADVANCED,
    ),
    _F(
        "rates.debt_ratio",
        7,
        "Target debt ratio D/V",
        P,
        Const(0.0),
        "Debt as a share of total capital (debt plus equity) that the company"
        " aims for. With debt, the discount rate becomes a weighted average "
        "cost of capital (WACC) of the cost of equity and the after-tax cost "
        "of debt. Most growth IPOs have no debt, so the default is 0%.",
        lo=0.0,
        hi=0.9,
        level=Level.EXPERT,
    ),
    _F(
        "rates.cost_of_debt",
        7,
        "Cost of debt",
        P,
        Rule(lambda c: c["rates.risk_free"] + 0.03, ("rates.risk_free",)),
        "The interest rate the company pays on its debt, before tax. Interest"
        " is tax-deductible, so the model uses it after tax: cost × (1 − tax "
        "rate). It is weighted with the cost of equity by the target debt "
        "ratio into the WACC. Used only when that ratio is above 0; the "
        "default is the risk-free rate plus 3%.",
        lo=0.0,
        hi=0.5,
        level=Level.EXPERT,
    ),
    _F(
        "rates.stage1_years",
        7,
        "Stage-1 years",
        Unit.YEARS,
        Const(5),
        "Years discounted at the higher stage-1 rate (the risky growth "
        "phase); later years use the stage-2 rate. Each year's discount "
        "factor (the multiplier that turns a future amount into today's "
        "money) is the product of all earlier years' rates, so later years "
        "still carry the stage-1 discount.",
        lo=1,
        hi=20,
        level=Level.EXPERT,
    ),
    _F(
        "rates.horizon",
        7,
        "Forecast horizon",
        Unit.YEARS,
        Const(10),
        "Years forecast explicitly, one by one, before the terminal value "
        "takes over. It should be long enough for growth to settle near the "
        "terminal growth rate; the model warns if revenue is still growing "
        "much faster than that at the end.",
        lo=2,
        hi=50,
        level=Level.EXPERT,
    ),
    _F(
        "rates.terminal_growth",
        7,
        "Terminal growth",
        P,
        FromMarket("terminal_growth"),
        "Growth of the cash flows for ever after the forecast horizon. "
        "Because it lasts for ever it has a large effect on value, and it "
        "must stay well below the stage-2 rate. Keep it at or below the risk-"
        "free rate: no company outgrows the economy for ever. Long-run growth"
        " plus inflation is about 2-3%.",
        lo=-0.05,
        hi=0.1,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "rates.ronic_spread",
        7,
        "RONIC spread",
        P,
        Const(0.02),
        "RONIC is the return on new invested capital: the yearly profit "
        "earned on money the company reinvests to keep growing after the "
        "forecast. The spread is how far it exceeds the stage-2 rate. If new "
        "capital earns only its cost (spread 0), growing creates no value at "
        "all. A larger spread makes growth cheaper and the terminal value "
        "higher.",
        lo=-0.1,
        hi=0.5,
        level=Level.EXPERT,
    ),
    _F(
        "rates.r1_override",
        7,
        "Override rate, years 1-5",
        P,
        Const(None),
        "Enter the stage-1 discount rate (the first five years) directly, "
        "instead of building it up from the risk-free rate, beta × the "
        "equity risk premium, and the size and execution premia. Beta "
        "measures how strongly the stock swings with the whole market; a "
        "premium (plural premia) is extra return demanded for one particular"
        " risk. Useful to test a rate you have from elsewhere.",
        lo=0.001,
        hi=1.0,
        optional=True,
        level=Level.EXPERT,
    ),
    _F(
        "rates.r2_override",
        7,
        "Override rate, year 6 on",
        P,
        Const(None),
        "Enter the stage-2 discount rate (year 6 onwards) directly, instead "
        "of building it up from the risk-free rate, beta (how strongly the "
        "stock swings with the whole market) × the equity risk premium, and "
        "the size premium (extra return demanded for a smaller company). The"
        " terminal value, all cash flows after the forecast, is discounted at"
        " this rate too.",
        lo=0.001,
        hi=1.0,
        optional=True,
        level=Level.EXPERT,
    ),
    _F(
        "rates.mid_year",
        7,
        "Mid-year convention",
        Unit.BOOL,
        Const(False),
        "Discount each year's cash flow as if it arrived in the middle of the"
        " year, not at the end, since cash comes in all year round. It raises"
        " value by about half a year of discounting. Off by default, so the "
        "tables match hand calculations.",
        level=Level.EXPERT,
    ),
    # -- 8 Offering ----------------------------------------------------------
    _F(
        "offering.shares_pre",
        8,
        "Pre-IPO shares (fully diluted)",
        Unit.COUNT,
        Rule(_shares_pre, _PRE_MONEY_DEPENDS),
        "Shares outstanding before the IPO, fully diluted: options and "
        "convertible shares are counted as if already turned into shares. "
        "Companies split their stock before listing (divide each share into "
        "several) so the price lands at a usual level; the default aims at "
        "about 100 SEK or 20 USD. The share count changes the price per "
        "share, not the company's value.",
        lo=1,
        hi=1e12,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "offering.raise",
        8,
        "Primary raise (gross)",
        M,
        Rule(_raise, _PRE_MONEY_DEPENDS),
        "Primary raise: new money for the company, before fees, from selling "
        "newly issued shares. At a fair price, the raise neither creates nor "
        "destroys value; only the fees do. Fair value per share is the "
        "model's estimate: a blend of the DCF and the comparables valuation "
        "(what similar listed companies are worth per unit of revenue). "
        "Default: 20% of the comparables valuation.",
        lo=1,
        hi=1e13,
        level=Level.BEGINNER,
    ),
    _F(
        "offering.secondary_shares",
        8,
        "Secondary shares",
        Unit.COUNT,
        Const(0),
        "Existing shares sold by current holders (founders, venture funds) in"
        " the offering; the money goes to them, not to the company. They make"
        " the offer larger, so more demand is needed to cover it, and add to "
        "the free float (the shares anyone can trade), but do not change the "
        "company's value or its share count.",
        lo=0,
        hi=1e12,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "offering.gross_spread",
        8,
        "Gross spread",
        P,
        FromMarket("gross_spread"),
        "The underwriters' fee, as a share of the money raised. The "
        "underwriters are the investment banks that organise, market and "
        "guarantee the offering. About 7% is customary for mid-sized US IPOs;"
        " European IPOs, Swedish ones included, pay roughly half that "
        "(default 3%). It is a cost to the company and lowers the value per "
        "share.",
        lo=0.0,
        hi=0.2,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "offering.other_expenses",
        8,
        "Other offering expenses",
        M,
        Rule(
            lambda c: 2e6 * c.market.fx + 0.01 * c["offering.raise"],
            ("offering.raise", "company.market"),
        ),
        "Legal, audit, printing, registration and listing fees for the "
        "offering, paid by the company whatever the price. The default is 2 m"
        " USD (20 m SEK) plus 1% of the raise. Like the underwriters' spread,"
        " these costs reduce the value per share: they are the only way "
        "raising money at a fair price costs existing owners anything.",
        lo=0,
        hi=1e11,
        level=Level.ADVANCED,
    ),
    _F(
        "offering.ipo_discount",
        8,
        "IPO discount",
        P,
        Const(0.15),
        "How far below fair value the price range (the indicative range "
        "published before investors order) is set. The offer price, what IPO "
        "buyers pay, is then chosen from the orders. The discount rewards "
        "investors for buying an untested stock and leaves room for the price"
        " to rise on the first day. 10-15% is typical.",
        lo=0.0,
        hi=0.6,
        level=Level.BEGINNER,
    ),
    _F(
        "offering.min_discount",
        8,
        "Minimum IPO discount",
        P,
        Const(0.05),
        "The smallest discount to fair value at which the bankers will still "
        "launch the deal. Below it, buying the IPO offers investors no reward"
        " for the risk of an untested stock, and the book would fail. If "
        "management's minimum valuation pushes the price range that high, the"
        " IPO is postponed.",
        lo=0.0,
        hi=0.6,
        level=Level.EXPERT,
    ),
    _F(
        "offering.max_above_range",
        8,
        "Maximum price above the range",
        P,
        FromMarket("max_above_range"),
        "How far above the top of the price range the deal may be priced. "
        "In Sweden, as in the rest of the EU, the prospectus states the top "
        "of the range as the maximum price; pricing above it needs a "
        "supplement that lets investors withdraw their orders, so the default "
        "is 0%. In the US a deal may price about 20% outside the filed range "
        "without re-filing (SEC Rule 430A).",
        lo=0.0,
        hi=1.0,
        level=Level.EXPERT,
    ),
    _F(
        "offering.lockup_days",
        8,
        "Lock-up",
        Unit.DAYS,
        Const(180),
        "Days after the IPO during which existing holders (founders, staff, "
        "venture investors) promise not to sell. 180 days is customary. A "
        "longer lock-up reassures institutions and lifts demand a little; "
        "when it ends, many shares may come to market at once (the overhang).",
        lo=0,
        hi=1095,
        level=Level.ADVANCED,
    ),
    _F(
        "offering.lockup_coverage",
        8,
        "Lock-up coverage",
        P,
        Const(1.0),
        "Share of the pre-IPO shares covered by the lock-up. Locked-up shares"
        " cannot be sold, so they are not free float until the lock-up ends. "
        "Shares not locked up are free float from the first day: they make "
        "the stock easier to trade and to include in an index, but can also "
        "be sold into the first day's market.",
        lo=0.0,
        hi=1.0,
        level=Level.ADVANCED,
    ),
    _F(
        "offering.cornerstone",
        8,
        "Cornerstone commitment",
        M,
        Const(0.0),
        "Money committed by anchor (cornerstone) investors before the "
        "offering is launched, at whatever price is set. It makes the book "
        "safer from the start and is common in Hong Kong and the Nordics. "
        "Cornerstone investors receive their shares first.",
        lo=0,
        hi=1e12,
        level=Level.ADVANCED,
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
        level=Level.EXPERT,
    ),
    _F(
        "offering.retail_tranche",
        8,
        "Retail tranche",
        P,
        Const(0.10),
        "Share (tranche: portion) of the offer reserved for private (retail) "
        "investors; institutions receive the rest. If retail investors order "
        "less, institutions take the difference, and the other way round. A "
        "larger retail tranche spreads ownership widely; institutions are "
        "seen as more stable long-term holders.",
        lo=0.0,
        hi=1.0,
        level=Level.ADVANCED,
    ),
    # -- 9 Investors & sentiment ---------------------------------------------
    _F(
        "investors.inst_interest",
        9,
        "Institutional interest",
        Unit.CHOICE,
        Const("medium"),
        "Feedback from 'testing the waters': meetings with funds before the "
        "launch. How warm are they? From very_low to very_high it scales "
        "institutional demand from 0.3 to 2.2 times (medium = 1). It is the "
        "biggest single lever on the book, and it is judgement, not "
        "calculation.",
        choices=INTEREST_LEVELS,
        level=Level.BEGINNER,
    ),
    _F(
        "investors.n_institutions",
        9,
        "Institutions in the book",
        Unit.COUNT,
        Const(40),
        "How many institutions put in orders. Together with the average order"
        " it sets the size of the institutional book at fair value.",
        lo=0,
        hi=10_000,
        level=Level.ADVANCED,
    ),
    _F(
        "investors.avg_ticket",
        9,
        "Average institutional order",
        M,
        Rule(lambda c: 0.05 * c["offering.raise"], ("offering.raise",)),
        "The typical institutional order, at fair value. The default is 5% of"
        " the raise.",
        lo=0,
        hi=1e12,
        level=Level.ADVANCED,
    ),
    _F(
        "investors.retail_interest",
        9,
        "Retail interest",
        Unit.CHOICE,
        Const("medium"),
        "How keen private investors are, from very_low to very_high (0.3 to "
        "2.2 times retail demand). Retail money is a small part of most "
        "books, but it reacts strongly to hype.",
        choices=INTEREST_LEVELS,
        level=Level.BEGINNER,
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
        level=Level.ADVANCED,
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
        level=Level.ADVANCED,
    ),
    _F(
        "investors.hype",
        9,
        "Hype factor",
        Unit.NUMBER,
        Const(3),
        "0-10: press and social-media excitement around the listing. It "
        "swells retail demand (3.5 times at 10), nudges institutions, and "
        "makes retail buyers less sensitive to price. It also adds to the "
        "expected first-day pop: the rise from the offer price during the "
        "first day of trading. Hype is not value: it moves the book, not the "
        "fair value.",
        lo=0,
        hi=10,
        level=Level.BEGINNER,
    ),
    _F(
        "investors.target_coverage",
        9,
        "Target coverage",
        Unit.RATIO,
        Const(3.0),
        "How many times over the bankers want the offering covered by orders:"
        " 3 means orders for three times the shares on offer. The deal is "
        "priced at the highest price that still meets this target. "
        "Oversubscription leaves investors unfilled, and their buying on the "
        "first day supports the price.",
        lo=1,
        hi=50,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "investors.comps_multiple",
        9,
        "Comparable EV / NTM revenue",
        Unit.RATIO,
        FromPreset("comps_ev_revenue"),
        "Enterprise value divided by next year's revenue (NTM: next twelve "
        "months) for comparable listed companies. Young companies without "
        "profits are valued on revenue. Multiplied by the company's own next-"
        "year revenue, it gives the comparables valuation. It moves with "
        "market fashion. A scenario driver.",
        lo=0,
        hi=200,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "investors.dcf_weight",
        9,
        "DCF weight",
        P,
        Const(0.7),
        "How much the DCF counts in fair value; the comparables method gets "
        "the rest. The DCF reflects your own forecast of cash flows; "
        "comparables reflect what the market pays for similar companies "
        "today, mood included. Bankers look at both. Set it to 100% to see "
        "pure intrinsic value (value from the company's own cash flows "
        "alone), or 0% to price like the market.",
        lo=0.0,
        hi=1.0,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "investors.inst_elasticity",
        9,
        "Institutional price elasticity",
        Unit.NUMBER,
        Const(3.0),
        "How sharply institutions cut their orders as the offer price rises "
        "toward what they think the shares are worth: demand at price P is "
        "proportional to (fair value ÷ P) to the power of this number. A "
        "higher value makes demand fall off faster at higher prices, so the "
        "book supports a lower offer price.",
        lo=0,
        hi=20,
        level=Level.EXPERT,
    ),
    # -- 10 Index --------------------------------------------------------------
    _F(
        "index.min_cap",
        10,
        "Minimum market cap",
        M,
        Const(500e6),
        "Index rule: the company's full market capitalisation (share price × "
        "all shares) must be at least this. Indices want companies large "
        "enough to matter to their tracking funds. Checked at the offer "
        "price; size rules are never relaxed.",
        lo=0,
        hi=1e13,
        level=Level.ADVANCED,
    ),
    _F(
        "index.min_free_float",
        10,
        "Minimum free float",
        P,
        Const(0.15),
        "Index rule: the share of all shares that is freely tradable (free "
        "float). Shares locked up or held by cornerstones do not count. "
        "Indices want stocks that funds can actually buy without moving the "
        "price. The exchange may relax this rule to 10%.",
        lo=0.0,
        hi=1.0,
        level=Level.ADVANCED,
    ),
    _F(
        "index.min_ff_cap",
        10,
        "Minimum free-float cap",
        M,
        Const(150e6),
        "Index rule: the value of the freely tradable shares (free-float "
        "shares × price) must be at least this. Index funds weight their "
        "members by free-float value, so a company with a small float would "
        "get a weight too small to matter. Checked at the offer price; never "
        "relaxed.",
        lo=0,
        hi=1e13,
        level=Level.ADVANCED,
    ),
    _F(
        "index.seasoning_days",
        10,
        "Seasoning",
        Unit.DAYS,
        Const(63),
        "Index rule: trading days after listing before a new stock can join, "
        "so that it first has a price history and the first-day swings have "
        "settled. 63 trading days is about three months. The exchange may "
        "waive it, bringing inclusion forward to 10 days.",
        lo=0,
        hi=1000,
        level=Level.ADVANCED,
    ),
    _F(
        "index.fast_entry_cap",
        10,
        "Fast-entry market cap",
        M,
        Const(5e9),
        "Index rule: IPOs at least this large (full market cap) skip the "
        "seasoning period and join after a short delay, because an index that"
        " left out such a large company would no longer represent the market."
        " Fast entry gives the strongest index boost to demand in the book.",
        lo=0,
        hi=1e14,
        level=Level.EXPERT,
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
        level=Level.EXPERT,
    ),
    _F(
        "index.allow_multi_class",
        10,
        "Multiple share classes allowed",
        Unit.BOOL,
        Const(False),
        "Index rule: whether companies with several share classes (dual-"
        "class) are eligible. The exchange may agree to admit them.",
        level=Level.ADVANCED,
    ),
    _F(
        "index.relax",
        10,
        "Exchange may relax",
        Unit.CHOICE,
        Const("none"),
        "Which index rules the exchange is willing to loosen for this "
        "listing: seasoning, float, multi-class, or all. The report shows the"
        " verdict with and without it. Inclusion brings buying from index "
        "funds, so better prospects raise institutional demand in the book.",
        choices=("none", "seasoning", "float", "multi_class", "all"),
        level=Level.ADVANCED,
    ),
    _F(
        "index.passive_aum",
        10,
        "Passive assets tracking the index",
        M,
        Const(None),
        "Optional: money in index funds (passive funds that simply hold every"
        " share in the index) tracking this index. With the index's free-"
        "float market cap below, it estimates the forced buying by index "
        "funds when the stock joins: its weight in the index × these assets.",
        lo=0,
        hi=1e14,
        optional=True,
        level=Level.EXPERT,
    ),
    _F(
        "index.index_ff_cap",
        10,
        "Index free-float market cap",
        M,
        Const(None),
        "Optional: the combined free-float value of all current index "
        "members. The new stock's weight in the index is its own free-float "
        "value divided by this total plus its own. Index funds must then buy "
        "that weight × the passive assets tracking the index.",
        lo=0,
        hi=1e15,
        optional=True,
        level=Level.EXPERT,
    ),
    # -- 11 Management -----------------------------------------------------------
    _F(
        "management.last_round",
        11,
        "Last private round, post-money",
        M,
        Const(None),
        "The post-money valuation at the last private (venture) funding "
        "round: the price paid per share then × all shares after that round. "
        "Founders and venture investors hate an IPO below it (a 'down "
        "round'), so by default it becomes management's minimum market cap.",
        lo=0,
        hi=1e14,
        optional=True,
        level=Level.BEGINNER,
    ),
    _F(
        "management.min_market_cap",
        11,
        "Minimum market cap",
        M,
        Rule(lambda c: c["management.last_round"], ("management.last_round",)),
        "The lowest valuation (market capitalisation after the IPO) the CEO "
        "and CFO will accept. If it forces the price range up so far that the"
        " bankers' discount to fair value disappears, the IPO is postponed. "
        "Defaults to the last private round.",
        lo=0,
        hi=1e14,
        optional=True,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "management.max_dilution",
        11,
        "Maximum dilution",
        P,
        Const(0.25),
        "The largest share of the company, after the IPO, that management "
        "will give to new investors: new shares ÷ all shares after the IPO. "
        "Dilution is the price of new money: existing owners keep a smaller "
        "slice of a company with more cash. The report warns if the offering "
        "exceeds it.",
        lo=0.0,
        hi=1.0,
        level=Level.INTERMEDIATE,
    ),
    _F(
        "management.min_net_proceeds",
        11,
        "Minimum net proceeds",
        M,
        Const(None),
        "Optional: the least cash the company must receive, after the "
        "underwriters' spread and other expenses, for the IPO to be worth "
        "doing, for example to fund the next years of the plan. The report "
        "warns if the offering falls short.",
        lo=0,
        hi=1e13,
        optional=True,
        level=Level.ADVANCED,
    ),
    # -- 12 Simulation -----------------------------------------------------------
    _F(
        "simulation.mode",
        12,
        "Mode",
        Unit.CHOICE,
        Const("both"),
        "'deterministic' computes fixed cases: the bear (pessimistic), base "
        "and bull (optimistic) scenarios, the tornado chart and the "
        "sensitivity grids (value over pairs of inputs). 'montecarlo' "
        "simulates thousands of possible companies, each with its inputs "
        "drawn at random, and shows the spread of fair values. 'both' shows "
        "the two side by side.",
        choices=("deterministic", "montecarlo", "both"),
        level=Level.INTERMEDIATE,
    ),
    _F(
        "simulation.draws",
        12,
        "Monte Carlo draws",
        Unit.COUNT,
        Const(10_000),
        "Number of simulated companies in the Monte Carlo. More draws give "
        "smoother, steadier results but take longer; 10,000 takes a few "
        "seconds.",
        lo=100,
        hi=1e6,
        level=Level.ADVANCED,
    ),
    _F(
        "simulation.seed",
        12,
        "Random seed",
        Unit.COUNT,
        Const(42),
        "The same seed gives the same simulation. Change it to see how much "
        "the results move by chance alone.",
        lo=0,
        hi=2**31 - 1,
        level=Level.ADVANCED,
    ),
    _F(
        "simulation.rho",
        12,
        "Execution correlation ρ",
        Unit.NUMBER,
        Const(0.5),
        "How strongly the operating drivers (inputs about the business "
        "itself: growth, churn, prices, costs) move together in the Monte "
        "Carlo (0-1). Good and bad news cluster: a company that grows fast "
        "usually also keeps its customers. At 0 each is drawn independently; "
        "at 1 they move in step. The comparable multiple and the rate inputs "
        "are always drawn independently.",
        lo=0.0,
        hi=1.0,
        level=Level.ADVANCED,
    ),
]


def _relative(fn: Callable[[float], float], key: str) -> Rule:
    return Rule(lambda c: fn(c[key]), (key,))


def _driver_fields() -> list[FieldSpec]:
    """Bear and bull values of each scenario driver (§11.1), all expert."""
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
                    f"The {case} value of '{base.label}': the "
                    f"{'pessimistic' if case == 'bear' else 'optimistic'} end of "
                    f"its plausible range. The {case} scenario sets every driver "
                    "to this end at once, and the tornado moves this driver "
                    "alone to it. The Monte Carlo draws it between the bear and "
                    "bull values, with your base answer as the most likely value.",
                    lo=base.lo,
                    hi=base.hi,
                    level=Level.EXPERT,
                )
            )
    return out


FIELDS: tuple[FieldSpec, ...] = (*_CATALOGUE, *_driver_fields())
BY_KEY: Mapping[str, FieldSpec] = {spec.key: spec for spec in FIELDS}
