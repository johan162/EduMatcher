"""Build the report (design §20) as plain data.

Every number is formatted here, once, so the terminal and Markdown views
cannot disagree.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from edumatcher.valuation.fields import FIELDS, PAGES
from edumatcher.valuation.model.bridge import dilution
from edumatcher.valuation.model.checks import Finding
from edumatcher.valuation.model.forecast import unit_economics
from edumatcher.valuation.model.index_rules import IndexVerdict, Path, passive_buying
from edumatcher.valuation.model.montecarlo import share_below, summarize
from edumatcher.valuation.model.offering import Listing, Outcome
from edumatcher.valuation.model.valuation import Valuation, offering
from edumatcher.valuation.pipeline import Run
from edumatcher.valuation.presets import Presets
from edumatcher.valuation.units import format_value

# ---------------------------------------------------------------------------
# The report as data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Table:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    align: str  # one character per column: "l" or "r"


@dataclass(frozen=True)
class Paragraph:
    text: str


@dataclass(frozen=True)
class Bullets:
    items: tuple[str, ...]


@dataclass(frozen=True)
class Code:
    text: str


Block = Table | Paragraph | Bullets | Code


@dataclass(frozen=True)
class Section:
    title: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Report:
    title: str
    verdict: str  # PROCEED, PROCEED (THIN BOOK) or POSTPONE
    sections: tuple[Section, ...]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _minus(text: str) -> str:
    return text.replace("-", "−")


def _m(x: float) -> str:
    """Money in millions, one decimal."""
    return _minus(f"{x / 1e6:,.1f}")


def _ps(x: float) -> str:
    """Money per share."""
    return _minus(f"{x:,.2f}")


def _pct(x: float, decimals: int = 1) -> str:
    return _minus(f"{x * 100:.{decimals}f}%")


def _n(x: float) -> str:
    return _minus(f"{x:,.0f}")


def _x(x: float) -> str:
    return f"{x:.2f}×"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]], align: str) -> Table:
    return Table(tuple(headers), tuple(tuple(r) for r in rows), align)


def _by_year(run: Run, rows: Sequence[tuple[str, str]], unit: str) -> Table:
    """One row per line item, one column per forecast year."""
    years = run.valuation.years[:-1]
    percent = {"gross_margin", "ebit_margin"}
    body = [
        (label, *(
            _pct(getattr(y, attr)) if attr in percent else _m(getattr(y, attr))
            for y in years
        ))
        for label, attr in rows
    ]  # fmt: skip
    return _table((unit, *(f"Y{y.t}" for y in years)), body, "l" + "r" * len(years))


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

_RISK_FACTORS = {
    "V002": "Our valuation assumes we grow faster than the risk-free rate for ever.",
    "V003": "Our valuation discounts our riskiest years less than our mature ones.",
    "V004": "A majority of our valuation depends on cash flows beyond our forecast "
    "horizon.",
    "V005": "Our growth may not have slowed by the end of the forecast; the "
    "terminal value may overstate how mature we will be.",
    "V006": "Our customers may be worth less than they cost us to acquire.",
    "V007": "It may take us more than three years to earn back what we spend to "
    "win a customer.",
    "V008": "Our long-term margin assumption lies outside what comparable "
    "companies achieve.",
    "V009": "Our business plan does not earn its cost of capital.",
    "V010": "Demand for our shares at the offer price was limited, and our share "
    "price may fall below it.",
    "V013": "Investors in this offering will experience substantial dilution.",
    "V014": "Our share price may be volatile and driven by sentiment rather than "
    "by our results.",
    "V015": "Our free float may be too small for index inclusion.",
    "V017": "The methods used to value us disagree widely.",
    "V018": "Our valuation relies on assumptions close to the limits of the model.",
    "V019": "We may never use part of our accumulated tax losses.",
    "V020": "Our hiring plan implies an unusual revenue per employee.",
    "V021": "The net proceeds may not be sufficient to fund our plans.",
}

_LEAVES_OUT = (
    "Real market data: every rate, multiple and preset is an assumption.",
    "Accounting detail: revenue recognition, leases and deferred taxes; loss "
    "carry-forwards are unlimited.",
    "Pre-revenue companies: the DCF is only as good as the customer model.",
    "Options and warrants beyond the fully diluted share count; the greenshoe.",
    "Demand multipliers and the first-day pop are calibrated heuristics, not "
    "finance theory: they show direction and causes, not a forecast.",
    "The real first-day price is found by the opening auction on EduMatcher.",
)


_NOT_LISTED = Paragraph("Not applicable: the IPO is postponed.")


def _verdict(run: Run) -> str:
    return {
        Outcome.PRICED: "PROCEED",
        Outcome.THIN_BOOK: "PROCEED (THIN BOOK)",
        Outcome.POSTPONED: "POSTPONE",
    }[run.pricing.outcome]


def _verdict_section(run: Run) -> Section:
    v, val, pr = run.resolved.values, run.valuation, run.pricing
    listing = pr.listing
    low, high = pr.price_range
    rows = [
        ("Fair value per share", _ps(val.fair_value)),
        ("Price range", f"{_ps(low)}–{_ps(high)}"),
    ]
    bullets = [
        f"Fair value {_ps(val.fair_value)} per share blends the DCF "
        f"({_ps(val.dcf_price)}) and comparables ({_ps(val.comps_price)}) at "
        f"{_pct(v['investors.dcf_weight'], 0)} / "
        f"{_pct(1 - v['investors.dcf_weight'], 0)}.",
        f"The range sits {_pct(v['offering.ipo_discount'], 0)} below fair value"
        + (", moved up by management's minimum valuation." if pr.range_moved else "."),
    ]
    if listing is None:
        bullets.append(f"The IPO is postponed: {pr.reason}.")
    else:
        assert pr.coverage is not None and pr.allocation is not None
        rows += [
            ("Offer price", _ps(listing.price)),
            ("Market capitalisation", f"{_m(listing.market_cap)} m"),
            ("Primary raise", f"{_m(listing.primary_shares * listing.price)} m"),
            ("Coverage", _x(pr.coverage)),
            ("Expected first-day pop", _pct(pr.pop or 0.0)),
        ]
        bullets += [
            f"Priced at {_ps(listing.price)}, {pr.position} the range: {pr.reason}. "
            f"The book is {_x(pr.coverage)} covered; institutions receive "
            f"{_pct(pr.allocation.institutional_fill, 0)} of what they asked for.",
            f"Market capitalisation {_m(listing.market_cap)} m; dilution "
            f"{_pct(listing.dilution)}.",
            f"Expected first-day pop {_pct(pr.pop or 0.0)} leaves "
            f"{_m(pr.money_left or 0.0)} m on the table.",
            f"Index: {_index_text(listing.index)}.",
        ]
        if run.mc is not None:
            fair = [s.fair_value for s in run.mc.samples]
            bullets.append(
                f"In {_pct(share_below(fair, listing.price), 0)} of the simulated "
                "companies, IPO buyers pay more than fair value."
            )
    if run.scenarios is not None and run.scenarios.tornado:
        top = run.scenarios.tornado[0]
        bullets.append(
            f"The biggest single uncertainty is {top.label.lower()}: it swings "
            f"fair value by {_ps(top.swing)} per share."
        )
    blocks: list[Block] = [
        Paragraph(f"**{_verdict(run)}**"),
        _table(("", ""), rows, "lr"),
        Bullets(tuple(bullets)),
    ]
    if run.findings:
        blocks.append(
            Bullets(
                tuple(
                    f"{f.code} ({f.severity.value}): {f.message}" for f in run.findings
                )
            )
        )
    return Section("Verdict", tuple(blocks))


def _index_text(verdict: IndexVerdict) -> str:
    if verdict.path is Path.NOT_ELIGIBLE:
        return "not eligible (" + ", ".join(verdict.failures) + ")"
    text = f"eligible {verdict.path.value}, trading day {verdict.day}"
    if verdict.waivers:
        text += " (waived: " + ", ".join(verdict.waivers) + ")"
    return text


def _s1_section(run: Run, presets: Presets) -> Section:
    v, listing = run.resolved.values, run.pricing.listing
    t = presets.filer_thresholds
    revenue = v["customers.last_fy_revenue"]
    egc = "yes" if revenue < t.egc_revenue else "no"
    rows = [
        ("Registrant", v["company.name"]),
        ("Proposed ticker", v["company.ticker"]),
        ("SIC code", v["company.sic_code"]),
        ("Incorporated in", v["company.incorporation"]),
        ("Fiscal year end", v["company.fiscal_year_end"]),
        ("Lead underwriter", v["company.lead_underwriter"]),
        (
            "Emerging growth company",
            f"{egc} (revenue {_m(revenue)} m vs {_m(t.egc_revenue)} m)",
        ),
    ]
    blocks: list[Block] = []
    if listing is None:
        rows.append(("Smaller reporting company", "not determined: no offer price"))
    else:
        public_float = listing.free_float_cap
        src = public_float < t.src_public_float or (
            revenue < t.src_revenue and public_float < t.src_public_float_alt
        )
        rows.append(
            ("Smaller reporting company",
             f"{'yes' if src else 'no'} (public float {_m(public_float)} m)")
        )  # fmt: skip
        price, spread = listing.price, v["offering.gross_spread"]
        secondary = v["offering.secondary_shares"]
        primary = listing.primary_shares * price
        blocks.append(
            _table(
                ("", "Per share", "Total"),
                [
                    ("Initial public offering price", _ps(price),
                     f"{_m(primary)} m primary + {_m(secondary * price)} m secondary"),
                    (f"Underwriting discount ({_pct(spread, 1)})", f"{price * spread:,.3f}",
                     f"{_m(primary * spread)} m + {_m(secondary * price * spread)} m"),
                    ("Proceeds to the company, before expenses",
                     f"{price * (1 - spread):,.3f}", f"{_m(primary * (1 - spread))} m"),
                    ("Proceeds to selling stockholders, before expenses",
                     f"{price * (1 - spread):,.3f}",
                     f"{_m(secondary * price * (1 - spread))} m"),
                ],
                "lrr",
            )
        )  # fmt: skip
    rows.append(("Use of proceeds", v["company.use_of_proceeds"]))
    return Section("S-1 cover", (_table(("", ""), rows, "ll"), *blocks))


def _assumptions_section(run: Run) -> Section:
    v, sources = run.resolved.values, run.resolved.sources
    rows = [
        (PAGES[spec.page - 1], spec.label, format_value(spec, v[spec.key]),
         sources[spec.key].value)
        for spec in FIELDS
    ]  # fmt: skip
    return Section(
        "Assumptions",
        (
            Paragraph("Every value the model used, and where it came from: you, "
                      "the sector preset, a rule over other answers, or a default."),
            _table(("Page", "Input", "Value", "Source"), rows, "llrl"),
        ),
    )  # fmt: skip


def _customers_section(run: Run) -> Section:
    rows = [
        (str(y.t), f"{y.tam / 1e9:,.1f} bn", f"{y.sam / 1e9:,.2f} bn",
         _n(y.max_customers), _n(y.customers_begin), _n(y.gross_adds),
         _n(y.churned), _n(y.customers_end), _pct(y.penetration), _n(y.arpu),
         _m(y.revenue), _pct(y.revenue_growth), _pct(y.share_of_sam))
        for y in run.valuation.years[:-1]
    ]  # fmt: skip
    headers = ("Year", "TAM", "SAM", "Max customers", "Begin", "Gross adds",
               "Churned", "End", "Penetration", "ARPU", "Revenue (m)", "Growth",
               "Share of SAM")  # fmt: skip
    return Section("Market and customers", (_table(headers, rows, "r" * 13),))


def _unit_economics_section(run: Run) -> Section:
    years = run.valuation.years
    horizon = len(years) - 1
    picks = sorted({1, min(5, horizon), horizon})
    ues = [unit_economics(years[t - 1], run.resolved["customers.churn"]) for t in picks]
    rows = [
        ("LTV (ARPU × GM / churn)", *(_n(u.ltv) for u in ues)),
        ("Full CAC (S&M / gross adds)", *(_n(u.cac_full) for u in ues)),
        ("LTV / CAC", *(f"{u.ltv_to_cac:.1f}" for u in ues)),
        ("CAC payback (months)", *(f"{u.payback_months:.1f}" for u in ues)),
    ]
    return Section(
        "Unit economics",
        (_table(("", *(f"Year {t}" for t in picks)), rows, "l" + "r" * len(picks)),),
    )


def _headcount_section(run: Run) -> Section:
    rows = [
        (str(y.t), _n(y.headcount), _pct(y.headcount_growth), _n(y.loaded_cost),
         _m(y.staff_cost), _m(y.staff_rnd), _m(y.staff_snm), _m(y.staff_gna),
         _m(y.staff_ops), _n(y.revenue_per_employee))
        for y in run.valuation.years[:-1]
    ]  # fmt: skip
    headers = ("Year", "Headcount", "Growth", "Loaded cost", "Staff cost (m)",
               "R&D", "S&M", "G&A", "Ops (COGS)", "Revenue / employee")  # fmt: skip
    return Section("Headcount", (_table(headers, rows, "r" * 10),))


def _income_section(run: Run, unit: str) -> Section:
    items = (
        ("Revenue", "revenue"), ("Infrastructure", "infrastructure"),
        ("Other COGS", "other_cogs"), ("Ops staff", "staff_ops"),
        ("Gross profit", "gross_profit"), ("Gross margin", "gross_margin"),
        ("R&D", "rnd"), ("S&M", "snm"),
        ("of which paid acquisition", "paid_acquisition"),
        ("G&A (incl. public-co cost)", "gna"), ("Stock-based comp.", "sbc"),
        ("EBITDA", "ebitda"), ("D&A", "da"), ("EBIT", "ebit"),
        ("EBIT margin", "ebit_margin"),
    )  # fmt: skip
    return Section("Income statement", (_by_year(run, items, unit),))


def _fcff_section(run: Run, unit: str) -> Section:
    items = (
        ("EBIT", "ebit"), ("NOL used", "nol_used"), ("NOL balance (end)", "nol"),
        ("Cash taxes", "taxes"), ("+ D&A", "da"), ("− Capex", "capex"),
        ("PP&E (end)", "ppe"), ("NWC (end)", "nwc"), ("− ΔNWC", "delta_nwc"),
        ("FCFF", "fcff"),
    )  # fmt: skip
    return Section("Taxes, reinvestment and FCFF", (_by_year(run, items, unit),))


def _rates_section(run: Run) -> Section:
    v, val = run.resolved.values, run.valuation
    erp = v["rates.erp"]
    after_tax_debt = v["rates.cost_of_debt"] * (1 - v["capital.tax_rate"])
    rows = [
        ("Risk-free rate", _pct(v["rates.risk_free"], 2), _pct(v["rates.risk_free"], 2)),
        ("β × equity risk premium",
         f"{v['rates.beta_stage1']:.2f} × {_pct(erp, 2)}",
         f"{v['rates.beta_stage2']:.2f} × {_pct(erp, 2)}"),
        ("Size premium", _pct(v["rates.size_premium_1"], 2), _pct(v["rates.size_premium_2"], 2)),
        ("Execution premium", _pct(v["rates.execution_premium"], 2), "—"),
        ("Cost of equity", _pct(val.stage1.cost_of_equity, 2), _pct(val.stage2.cost_of_equity, 2)),
        ("Debt D/V; after-tax cost of debt",
         f"{_pct(v['rates.debt_ratio'], 0)}; {_pct(after_tax_debt, 2)}",
         f"{_pct(v['rates.debt_ratio'], 0)}; {_pct(after_tax_debt, 2)}"),
        ("Discount rate",
         _pct(val.stage1.rate, 2) + (" (override)" if val.stage1.overridden else ""),
         _pct(val.stage2.rate, 2) + (" (override)" if val.stage2.overridden else "")),
    ]  # fmt: skip
    stage1 = int(v["rates.stage1_years"])
    return Section(
        "Discount rates",
        (_table(("", f"Years 1–{stage1}", f"Year {stage1 + 1} on"), rows, "lrr"),),
    )


def _dcf_section(run: Run, unit: str) -> Section:
    v, d = run.resolved.values, run.valuation.dcf
    horizon = len(d.rows)
    rows = [
        (str(r.t), str(r.stage), _pct(r.rate, 2), f"{r.discount_factor:.4f}",
         _m(r.fcff), _m(r.pv))
        for r in d.rows
    ]  # fmt: skip
    rows.append(("", "", "", "", f"Σ PV, years 1–{horizon}", _m(d.pv_explicit)))
    r2, g = run.valuation.stage2.rate, v["rates.terminal_growth"]
    tax = v["capital.tax_rate"]
    steps = [
        (f"EBIT year {horizon + 1}", _m(d.ebit_terminal)),
        (f"NOPAT = EBIT × (1 − {_pct(tax, 0)})", _m(d.nopat_terminal)),
        (f"RONIC = {_pct(r2, 2)} + {_pct(v['rates.ronic_spread'], 1)}", _pct(d.ronic, 2)),
        (f"Reinvestment rate = {_pct(g, 1)} / {_pct(d.ronic, 2)}", _pct(d.reinvestment_rate)),
        (f"FCFF year {horizon + 1} = NOPAT × (1 − reinvestment)", _m(d.fcff_terminal)),
        (f"Terminal value = FCFF / ({_pct(r2, 2)} − {_pct(g, 1)})", _m(d.terminal_value)),
        ("PV(terminal value)", _m(d.pv_terminal)),
        ("Enterprise value", _m(d.enterprise_value)),
        ("Terminal value share of EV", _pct(d.tv_share)),
        ("Implied EV / NTM revenue; EV / year-N EBIT",
         f"{run.valuation.ev_to_ntm_revenue:.1f}×; {run.valuation.ev_to_ebit_n:.1f}×"),
    ]  # fmt: skip
    return Section(
        "DCF",
        (
            _table(("Year", "Stage", "Rate", "Discount factor", f"FCFF ({unit})",
                    f"PV ({unit})"), rows, "rrrrrr"),
            Paragraph("Each discount factor is the product of every earlier "
                      "year's own rate, so stage-2 years still carry the stage-1 "
                      "discount."),
            _table(("Terminal value", unit), steps, "lr"),
        ),
    )  # fmt: skip


def _bridge_section(run: Run) -> Section:
    v, val = run.resolved.values, run.valuation
    offer = offering(v)
    costs = offer.gross_spread * offer.raise_gross + offer.other_expenses
    net_cash = v["capital.cash"] - v["capital.debt"]
    rows = [
        ("Enterprise value (DCF)", f"{_m(val.dcf.enterprise_value)} m"),
        ("+ cash − debt", f"{_m(net_cash)} m"),
        ("Equity value before the IPO", f"{_m(val.equity_pre)} m"),
        ("− gross spread × raise − other expenses", f"{_m(costs)} m"),
        ("÷ pre-IPO shares", f"{offer.shares_pre / 1e6:,.2f} m"),
        ("DCF value per share", _ps(val.dcf_price)),
        (f"Comparables: {v['investors.comps_multiple']:g}× NTM revenue = "
         f"{_m(val.comps_ev)} m EV", _ps(val.comps_price)),
        (f"Fair value = {_pct(v['investors.dcf_weight'], 0)} DCF + "
         f"{_pct(1 - v['investors.dcf_weight'], 0)} comparables", _ps(val.fair_value)),
    ]  # fmt: skip
    return Section(
        "Bridge and fair value",
        (
            _table(("", ""), rows, "lr"),
            Paragraph(
                "Why the raise cancels out: new shares at a fair price P bring in "
                "exactly what they are worth, so P = (E + R − fR − X) / (S + R/P) "
                "solves to P = (E − fR − X) / S. Raising money costs existing "
                "holders only the fees."
            ),
        ),
    )


def _scenarios_section(run: Run, unit: str) -> Section:
    s = run.scenarios
    assert s is not None

    def col(case: Valuation | None, fn: Callable[[Valuation], str]) -> str:
        return "invalid" if case is None else fn(case)

    cases = (s.bear, s.base, s.bull)
    rows = [
        ("r1 / r2", *(col(c, lambda c: f"{_pct(c.stage1.rate, 2)} / {_pct(c.stage2.rate, 2)}") for c in cases)),
        (f"Year-N revenue ({unit})", *(col(c, lambda c: _m(c.years[-2].revenue)) for c in cases)),
        ("Year-N EBIT margin", *(col(c, lambda c: _pct(c.years[-2].ebit_margin)) for c in cases)),
        (f"EV ({unit})", *(col(c, lambda c: _m(c.dcf.enterprise_value)) for c in cases)),
        ("DCF / comps per share", *(col(c, lambda c: f"{_ps(c.dcf_price)} / {_ps(c.comps_price)}") for c in cases)),
        ("Fair value per share", *(col(c, lambda c: _ps(c.fair_value)) for c in cases)),
    ]  # fmt: skip
    tornado = [
        (b.label, "invalid" if b.bear is None else _ps(b.bear),
         "invalid" if b.bull is None else _ps(b.bull), _ps(b.swing))
        for b in s.tornado
    ]  # fmt: skip
    blocks: list[Block] = [
        _table(("", "Bear", "Base", "Bull"), rows, "lrrr"),
        Paragraph("Tornado: fair value per share with one driver at a time at "
                  "its bear or bull value, widest swing first."),
        _table(("Driver", "Bear", "Bull", "Swing"), tornado, "lrrr"),
    ]  # fmt: skip
    for grid, title in (
        (s.rate2_growth, "r2 \\ g"),
        (s.rate1_customer_growth, "r1 \\ year-1 customer growth"),
    ):
        rows_g = [
            (_pct(r, 2), *("—" if c is None else _ps(c) for c in cells))
            for r, cells in zip(grid.rows, grid.cells)
        ]
        blocks.append(Paragraph(f"DCF value per share, {title}:"))
        blocks.append(
            _table((title, *(_pct(c, 1) for c in grid.cols)), rows_g, "r" * 6)
        )
    return Section("Scenarios, tornado and sensitivity", tuple(blocks))


def _histogram(values: Sequence[float]) -> str:
    low, high = min(values), max(values)
    width = next(
        w
        for w in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 1e9)
        if (high - low) / w <= 12
    )
    start = math.floor(low / width) * width
    bins = max(1, math.ceil((high - start) / width))
    counts = [0] * bins
    for x in values:
        counts[min(bins - 1, int((x - start) // width))] += 1
    top = max(counts)
    lines = ["Fair value per share          draws"]
    for i, count in enumerate(counts):
        lo = start + i * width
        bar = "#" * round(40 * count / top)
        lines.append(f"{lo:>7g} – {lo + width:<7g}|{bar:<40} {count:>6,}")
    return "\n".join(lines)


def _mc_section(run: Run) -> Section:
    mc, v, val = run.mc, run.resolved.values, run.valuation
    assert mc is not None
    dcf = summarize([s.dcf_price for s in mc.samples])
    fair_values = [s.fair_value for s in mc.samples]
    fair = summarize(fair_values)
    rows = [
        (name, *(_ps(x) for x in (s.p5, s.p25, s.p50, s.p75, s.p95, s.mean, s.sd)), _ps(base))
        for name, s, base in (("DCF value", dcf, val.dcf_price), ("Fair value", fair, val.fair_value))
    ]  # fmt: skip
    probabilities = []
    if run.pricing.listing is not None:
        price = run.pricing.listing.price
        probabilities.append((f"Fair value below the offer price {_ps(price)}",
                              _pct(share_below(fair_values, price))))  # fmt: skip
    probabilities.append(("DCF equity below zero",
                          _pct(share_below([s.equity_pre for s in mc.samples], 0.0), 2)))  # fmt: skip
    minimum = v["management.min_market_cap"]
    if minimum is not None:
        post = [f * v["offering.shares_pre"] + v["offering.raise"] for f in fair_values]
        probabilities.append((f"Intrinsic post-money value below management's {_m(minimum)} m",
                              _pct(share_below(post, minimum))))  # fmt: skip
    probabilities.append(("Rejected draws", _n(mc.rejected)))
    gap = 1 - fair.mean / val.fair_value
    return Section(
        f"Monte Carlo ({len(mc.samples):,} draws, ρ = {v['simulation.rho']:g}, "
        f"seed {v['simulation.seed']})",
        (
            _table(("Per share", "P5", "P25", "P50", "P75", "P95", "Mean", "SD",
                    "Deterministic base"), rows, "lrrrrrrrr"),
            Code(_histogram(fair_values)),
            _table(("Probability", ""), probabilities, "lr"),
            Paragraph(
                f"Deterministic vs Monte Carlo: the mean fair value "
                f"({_ps(fair.mean)}) is {_pct(abs(gap), 0)} "
                f"{'below' if gap > 0 else 'above'} the base case "
                f"({_ps(val.fair_value)}), the median {_ps(fair.p50)}. The base case "
                "is not the expected case: the driver ranges are skewed and value "
                "is non-linear in them."
            ),
        ),
    )  # fmt: skip


def _pricing_section(run: Run, unit: str) -> Section:
    pr = run.pricing
    low, high = pr.price_range
    text = (f"Midpoint fair value × (1 − IPO discount) = {_ps(pr.mid)}; first range "
            f"{_ps(pr.first_range[0])}–{_ps(pr.first_range[1])}.")  # fmt: skip
    if pr.floor_price is not None:
        text += f" Management's floor price is {_ps(pr.floor_price)}."
    if pr.range_moved:
        text += f" The floor moves the range to {_ps(low)}–{_ps(high)}."
    blocks: list[Block] = [Paragraph(text)]
    chosen = None if pr.listing is None else pr.listing.price
    if pr.book:
        rows = [
            (_ps(b.price) + (" ◀" if b.price == chosen else ""), _m(b.institutional),
             _m(b.retail), _m(b.cornerstone), _m(b.offer_value), _x(b.coverage))
            for b in pr.book
        ]  # fmt: skip
        blocks.append(_table(("Price", "Institutional", "Retail", "Cornerstone",
                              f"Offer ({unit})", "Coverage"), rows, "rrrrrr"))  # fmt: skip
    if pr.listing is None:
        blocks.append(Paragraph(f"**Postponed:** {pr.reason}."))
        return Section("Pricing", tuple(blocks))
    listing, alloc = pr.listing, pr.allocation
    assert alloc is not None
    results = [
        ("Offer price", f"{_ps(listing.price)} ({pr.position} the range; {pr.reason})"),
        ("Primary shares", _n(listing.primary_shares)),
        ("Post-money shares", _n(listing.post_shares)),
        ("Market capitalisation", f"{_m(listing.market_cap)} m"),
        ("Dilution", _pct(listing.dilution)),
        ("Net proceeds", f"{_m(listing.net_proceeds)} m"),
        ("Intrinsic value per share after the IPO",
         f"{_ps(listing.value_after_ipo)} ({_pct(listing.value_after_ipo / listing.price - 1)} for IPO buyers)"),
        ("Allocation: cornerstone / retail / institutional",
         f"{_m(alloc.cornerstone)} / {_m(alloc.retail)} / {_m(alloc.institutional)} m"),
        ("Fill: retail / institutional", f"{_pct(alloc.retail_fill)} / {_pct(alloc.institutional_fill)}"),
        ("Expected first-day pop; first-day close", f"{_pct(pr.pop or 0.0)}; {_ps(pr.first_day_close or 0.0)}"),
        ("Money left on the table", f"{_m(pr.money_left or 0.0)} m"),
    ]  # fmt: skip
    blocks.append(_table(("", ""), results, "lr"))
    return Section("Pricing", tuple(blocks))


def _dilution_section(run: Run) -> Section:
    v, listing = run.resolved.values, run.pricing.listing
    if listing is None:
        return Section("Capitalisation and dilution", (_NOT_LISTED,))
    d = dilution(
        listing.price, offering(v), cash=v["capital.cash"], ppe_0=v["capital.ppe_start"],
        nwc_0=v["capital.nwc_pct"] * v["customers.last_fy_revenue"], debt=v["capital.debt"],
    )  # fmt: skip
    rows = [
        ("Pre-IPO shares; post-money shares",
         f"{_n(v['offering.shares_pre'])}; {_n(listing.post_shares)}"),
        ("Net tangible book value per share before the offering", _ps(d.ntbv_pre_per_share)),
        ("Increase attributable to new investors", _ps(d.increase_per_share)),
        ("Net tangible book value per share after the offering", _ps(d.ntbv_post_per_share)),
        ("Dilution per share to new investors",
         f"{_ps(d.dilution_per_share)} ({_pct(d.dilution_pct)})"),
    ]  # fmt: skip
    return Section("Capitalisation and dilution", (_table(("", ""), rows, "lr"),))


def _index_section(run: Run) -> Section:
    v, listing = run.resolved.values, run.pricing.listing
    if listing is None:
        return Section("Lock-ups, free float and index", (_NOT_LISTED,))
    ok = "✓"
    checks = [
        ("Full market cap", f"{_m(listing.market_cap)} m", f"≥ {_m(v['index.min_cap'])} m",
         ok if listing.market_cap >= v["index.min_cap"] else "✗"),
        ("Free float", _pct(listing.free_float), f"≥ {_pct(v['index.min_free_float'], 0)}",
         ok if listing.free_float >= v["index.min_free_float"] else "✗"),
        ("Free-float market cap", f"{_m(listing.free_float_cap)} m", f"≥ {_m(v['index.min_ff_cap'])} m",
         ok if listing.free_float_cap >= v["index.min_ff_cap"] else "✗"),
        ("Fast entry", f"{_m(listing.market_cap)} m", f"≥ {_m(v['index.fast_entry_cap'])} m",
         ok if listing.market_cap >= v["index.fast_entry_cap"] else "✗"),
        ("Share classes", "dual" if v["company.dual_class"] else "single", "—",
         "✗" if v["company.dual_class"] and not v["index.allow_multi_class"] else ok),
    ]  # fmt: skip
    lines = [
        f"Verdict: {_index_text(listing.index)}.",
    ]
    if v["index.relax"] != "none":
        lines.append(
            f"Without the exchange's relaxations: {_index_text(listing.index_unrelaxed)}."
        )
    lines.append(
        f"The lock-up ({int(v['offering.lockup_days'])} days) releases "
        f"{_n(listing.locked_shares)} pre-IPO shares at expiry, "
        f"{listing.overhang:.1f}× the free float."
    )
    buying = passive_buying(
        listing.free_float_cap, v["index.index_ff_cap"], v["index.passive_aum"]
    )
    if buying is not None:
        lines.append(
            f"Index funds would have to buy about {_m(buying)} m at inclusion."
        )
    return Section(
        "Lock-ups, free float and index",
        (_table(("Check at the offer price", "Value", "Rule", ""), checks, "lrrl"),
         Bullets(tuple(lines))),
    )  # fmt: skip


def _risk_section(findings: Sequence[Finding]) -> Section:
    risks = tuple(_RISK_FACTORS[f.code] for f in findings if f.code in _RISK_FACTORS)
    if not risks:
        risks = (
            "No model warning fired; the usual risks of any new listing still apply.",
        )
    return Section("Risk factors", (Bullets(risks),))


def listing_args(ticker: str, listing: Listing) -> list[str]:
    """The pm-new-symbol arguments that list the priced IPO (§22)."""
    return ["--symbol", ticker,
            "--ipo-price", f"{listing.price:.2f}",
            "--outstanding-shares", str(int(listing.post_shares)),
            "--tick-decimals", "2"]  # fmt: skip


def _next_step_section(run: Run) -> Section:
    v, listing = run.resolved.values, run.pricing.listing
    if listing is None:
        return Section("Next step", (Paragraph("No listing: the IPO is postponed."),))
    args = listing_args(v["company.ticker"], listing)
    blocks: list[Block] = [Code(" ".join(["pm-new-symbol", *args]))]
    if listing.index.day is not None:
        blocks.append(Code(
            f"# on or after trading day {listing.index.day}:\n"
            f"pm-index-admin-cli --id OPS01 add --index <ID> --sym {v['company.ticker']} "
            f"--shares {int(listing.post_shares)} --price <last close>"
        ))  # fmt: skip
    return Section("Next step", tuple(blocks))


def build_report(run: Run, presets: Presets) -> Report:
    v = run.resolved.values
    unit = f"{v['company.currency']} m"
    sections = [
        _verdict_section(run),
        _s1_section(run, presets),
        _assumptions_section(run),
        _customers_section(run),
        _unit_economics_section(run),
        _headcount_section(run),
        _income_section(run, unit),
        _fcff_section(run, unit),
        _rates_section(run),
        _dcf_section(run, unit),
        _bridge_section(run),
    ]
    if run.scenarios is not None:
        sections.append(_scenarios_section(run, unit))
    if run.mc is not None:
        sections.append(_mc_section(run))
    sections += [
        _pricing_section(run, unit),
        _dilution_section(run),
        _index_section(run),
        _risk_section(run.findings),
        _next_step_section(run),
        Section("What this model leaves out", (Bullets(_LEAVES_OUT),)),
    ]
    numbered = tuple(
        Section(f"{i}. {section.title}", section.blocks)
        for i, section in enumerate(sections, start=1)
    )
    title = f"{v['company.name']} ({v['company.ticker']}) — IPO valuation"
    return Report(title, _verdict(run), numbered)


# ---------------------------------------------------------------------------
# Comparing two runs (the TUI's what-if loop)
# ---------------------------------------------------------------------------


def _headlines(run: Run) -> dict[str, float | None]:
    listing, pr = run.pricing.listing, run.pricing
    out: dict[str, float | None] = {
        "Fair value per share": run.valuation.fair_value,
        "DCF per share": run.valuation.dcf_price,
        "Comparables per share": run.valuation.comps_price,
        "Enterprise value (m)": run.valuation.dcf.enterprise_value / 1e6,
        "Offer price": None if listing is None else listing.price,
        "Coverage": pr.coverage,
        "Market cap (m)": None if listing is None else listing.market_cap / 1e6,
        "First-day pop (%)": None if pr.pop is None else pr.pop * 100,
    }
    if run.mc is not None:
        out["Monte Carlo median fair value"] = summarize(
            [s.fair_value for s in run.mc.samples]
        ).p50
    return out


def compare(previous: Run, current: Run) -> Section:
    """Headline numbers side by side with the change, and the inputs that changed."""
    before, after = _headlines(previous), _headlines(current)

    def cell(x: float | None) -> str:
        return "—" if x is None else _minus(f"{x:,.2f}")

    rows = [("Verdict", _verdict(previous), _verdict(current), "")]
    for name in after:
        b, a = before.get(name), after[name]
        delta = "" if a is None or b is None else _minus(f"{a - b:+,.2f}")
        rows.append((name, cell(b), cell(a), delta))
    changed = [
        (spec.label,
         format_value(spec, previous.resolved[spec.key]),
         format_value(spec, current.resolved[spec.key]))
        for spec in FIELDS
        if previous.resolved[spec.key] != current.resolved[spec.key]
    ]  # fmt: skip
    blocks: list[Block] = [_table(("", "Previous", "Now", "Change"), rows, "lrrr")]
    blocks.append(
        _table(("Input that changed", "Previous", "Now"), changed, "lrr")
        if changed
        else Paragraph("No input changed.")
    )
    return Section("Compared with the previous run", tuple(blocks))
