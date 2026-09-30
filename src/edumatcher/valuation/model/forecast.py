"""The operating forecast (design §6): customers, staff, costs, tax and FCFF."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ForecastInputs:
    """Year-0 facts and the drivers of the forecast. Percentages are fractions."""

    horizon: int  # N, years forecast explicitly; year N+1 feeds the terminal value
    terminal_growth: float  # g, which TAM growth fades to
    inflation: float  # which ARPU growth fades to, and fixed costs escalate with
    # §6.2 market
    tam: float
    tam_growth: float
    sam_share: float
    p_max: float
    # §6.3 customers
    revenue_0: float
    customers_0: float
    arpu: float
    arpu_growth: float
    churn: float
    customer_growth_y1: float
    # §6.5 people; headcount_elasticity None means the explicit growth path
    headcount_0: float
    loaded_cost: float
    wage_inflation: float
    headcount_elasticity: float | None
    headcount_growth_y1: float
    headcount_growth_floor: float
    staff_split: tuple[float, float, float, float]  # R&D, S&M, G&A, Ops
    # §6.6 costs
    infra_fixed: float
    infra_per_customer: float
    other_cogs_pct: float
    cac_paid: float
    cac_growth: float
    rnd_nonstaff_pct: float
    gna_nonstaff_pct: float
    public_company: float
    sbc_pct: float
    # §6.7-6.9 capital and tax
    capex_pct: float
    useful_life: float
    ppe_0: float
    nwc_pct: float
    tax_rate: float
    nol_0: float


@dataclass(frozen=True)
class YearRow:
    """One forecast year. Money is in the profile's currency, not millions."""

    t: int
    tam: float
    sam: float
    max_customers: float
    customers_begin: float
    gross_adds: float
    churned: float
    customers_end: float
    penetration: float
    arpu: float
    revenue: float
    revenue_growth: float
    share_of_sam: float
    headcount: float
    headcount_growth: float
    loaded_cost: float
    staff_cost: float
    staff_rnd: float
    staff_snm: float
    staff_gna: float
    staff_ops: float
    revenue_per_employee: float
    infrastructure: float
    other_cogs: float
    cogs: float
    gross_profit: float
    gross_margin: float
    paid_acquisition: float
    rnd: float
    snm: float
    gna: float
    sbc: float
    ebitda: float
    da: float
    ebit: float
    ebit_margin: float
    nol_used: float
    nol: float
    taxes: float
    capex: float
    ppe: float
    nwc: float
    delta_nwc: float
    fcff: float


@dataclass(frozen=True)
class UnitEconomics:
    """§6.4 — reported, not used in the valuation."""

    ltv: float
    cac_full: float
    ltv_to_cac: float
    payback_months: float


def fade(t: int, horizon: int) -> float:
    """0 in year 1, rising linearly to 1 in year N and after."""
    return (min(t, horizon) - 1) / (horizon - 1)


def forecast(inp: ForecastInputs) -> tuple[YearRow, ...]:
    """Years 1..N+1. The calibration and every formula follow design §6."""
    if inp.horizon < 2:
        raise ValueError("the horizon must be at least 2 years")
    max_customers_1 = (
        inp.p_max
        * inp.tam
        * (1 + inp.tam_growth)
        * inp.sam_share
        / (inp.arpu * (1 + inp.arpu_growth))
    )
    if inp.customers_0 >= max_customers_1:
        raise ValueError(
            f"{inp.customers_0:,.0f} customers already reach the maximum market "
            f"share ({max_customers_1:,.0f} customers); raise the TAM, the SAM "
            "share or the market structure"
        )
    # §6.3: the acquisition intensity that gives exactly the year-1 growth.
    acquisition = (inp.customer_growth_y1 + inp.churn) / (
        1 - inp.customers_0 / max_customers_1
    )

    rows: list[YearRow] = []
    tam, arpu = inp.tam, inp.arpu
    customers, headcount = inp.customers_0, inp.headcount_0
    revenue_prev = inp.revenue_0
    ppe, nol = inp.ppe_0, inp.nol_0
    nwc_prev = inp.nwc_pct * inp.revenue_0
    for t in range(1, inp.horizon + 2):
        f = fade(t, inp.horizon)
        # §6.2 market
        tam *= 1 + inp.tam_growth + (inp.terminal_growth - inp.tam_growth) * f
        sam = inp.sam_share * tam
        # §6.3 customers and revenue
        arpu *= 1 + inp.arpu_growth + (inp.inflation - inp.arpu_growth) * f
        max_customers = inp.p_max * sam / arpu
        churned = inp.churn * customers
        # Logistic adds, clamped: never negative, and never more than fills the
        # market (a discrete logistic with a high rate would overshoot it).
        adds = min(
            max(0.0, acquisition * customers * (1 - customers / max_customers)),
            max(0.0, max_customers - customers + churned),
        )
        customers_end = customers + adds - churned
        average_customers = (customers + customers_end) / 2
        revenue = average_customers * arpu
        revenue_growth = revenue / revenue_prev - 1
        # §6.5 people
        if inp.headcount_elasticity is None:
            headcount_growth = (
                inp.headcount_growth_y1
                + (inp.headcount_growth_floor - inp.headcount_growth_y1) * f
            )
        else:
            headcount_growth = max(
                inp.headcount_growth_floor, inp.headcount_elasticity * revenue_growth
            )
        headcount *= 1 + headcount_growth
        loaded = inp.loaded_cost * (1 + inp.wage_inflation) ** t
        staff = headcount * loaded
        staff_rnd, staff_snm, staff_gna, staff_ops = (
            staff * share for share in inp.staff_split
        )
        # §6.6 operating costs
        escalation = (1 + inp.inflation) ** t
        infrastructure = (
            inp.infra_fixed + inp.infra_per_customer * average_customers
        ) * escalation
        other_cogs = inp.other_cogs_pct * revenue
        cogs = infrastructure + other_cogs + staff_ops
        gross_profit = revenue - cogs
        paid_acquisition = inp.cac_paid * (1 + inp.cac_growth) ** t * adds
        rnd = staff_rnd + inp.rnd_nonstaff_pct * revenue
        snm = staff_snm + paid_acquisition
        gna = (
            staff_gna + inp.gna_nonstaff_pct * revenue + inp.public_company * escalation
        )
        sbc = inp.sbc_pct * staff
        ebitda = gross_profit - rnd - snm - gna - sbc
        # §6.7 capex and depreciation on the opening balance
        capex = inp.capex_pct * revenue
        da = ppe / inp.useful_life
        ppe += capex - da
        ebit = ebitda - da
        # §6.9 tax with a loss carry-forward
        if ebit < 0:
            nol_used = 0.0
            nol += -ebit
        else:
            nol_used = min(nol, ebit)
            nol -= nol_used
        taxes = inp.tax_rate * max(0.0, ebit - nol_used)
        # §6.8 working capital
        nwc = inp.nwc_pct * revenue
        delta_nwc = nwc - nwc_prev
        # §6.10
        fcff = ebit - taxes + da - capex - delta_nwc

        rows.append(
            YearRow(
                t=t,
                tam=tam,
                sam=sam,
                max_customers=max_customers,
                customers_begin=customers,
                gross_adds=adds,
                churned=churned,
                customers_end=customers_end,
                penetration=customers_end / max_customers,
                arpu=arpu,
                revenue=revenue,
                revenue_growth=revenue_growth,
                share_of_sam=revenue / sam,
                headcount=headcount,
                headcount_growth=headcount_growth,
                loaded_cost=loaded,
                staff_cost=staff,
                staff_rnd=staff_rnd,
                staff_snm=staff_snm,
                staff_gna=staff_gna,
                staff_ops=staff_ops,
                revenue_per_employee=revenue / headcount,
                infrastructure=infrastructure,
                other_cogs=other_cogs,
                cogs=cogs,
                gross_profit=gross_profit,
                gross_margin=gross_profit / revenue,
                paid_acquisition=paid_acquisition,
                rnd=rnd,
                snm=snm,
                gna=gna,
                sbc=sbc,
                ebitda=ebitda,
                da=da,
                ebit=ebit,
                ebit_margin=ebit / revenue,
                nol_used=nol_used,
                nol=nol,
                taxes=taxes,
                capex=capex,
                ppe=ppe,
                nwc=nwc,
                delta_nwc=delta_nwc,
                fcff=fcff,
            )
        )
        customers, revenue_prev, nwc_prev = customers_end, revenue, nwc
    return tuple(rows)


def unit_economics(row: YearRow, churn: float) -> UnitEconomics:
    """LTV, fully loaded CAC and payback for one year (§6.4)."""
    monthly_gross_profit = row.arpu * row.gross_margin / 12
    ltv = row.arpu * row.gross_margin / churn
    # A saturated market adds no customers: every sales dollar is then wasted.
    cac_full = row.snm / row.gross_adds if row.gross_adds else math.inf
    return UnitEconomics(
        ltv=ltv,
        cac_full=cac_full,
        ltv_to_cac=ltv / cac_full,
        payback_months=cac_full / monthly_gross_profit,
    )
