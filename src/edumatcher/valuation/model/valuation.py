"""Resolved answers in, the whole deterministic valuation (§6–§10) out.

This is the one place that maps field keys (``fields.py``) onto the model's
input dataclasses. The resolver uses it too: the default share count and raise
are derived from the comps valuation, which needs the forecast.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from edumatcher.valuation.model.bridge import Offering, fair_price
from edumatcher.valuation.model.comps import blend, comps_enterprise_value
from edumatcher.valuation.model.dcf import Dcf, dcf
from edumatcher.valuation.model.forecast import ForecastInputs, YearRow, forecast
from edumatcher.valuation.model.rates import RateInputs, StageRate, stage_rates

#: Every key forecast_inputs() reads; rules that run the forecast depend on them.
FORECAST_KEYS = (
    "rates.horizon",
    "rates.terminal_growth",
    "costs.inflation",
    "market.tam",
    "market.tam_growth",
    "market.sam_share",
    "market.p_max",
    "customers.last_fy_revenue",
    "customers.now",
    "customers.arpu",
    "customers.arpu_growth",
    "customers.churn",
    "customers.growth_y1",
    "people.headcount",
    "people.loaded_cost",
    "people.wage_inflation",
    "people.headcount_mode",
    "people.elasticity",
    "people.growth_y1",
    "people.growth_floor",
    "people.split_rnd",
    "people.split_snm",
    "people.split_gna",
    "people.split_ops",
    "costs.infra_fixed",
    "costs.infra_per_customer",
    "costs.other_cogs_pct",
    "costs.cac_paid",
    "costs.cac_growth",
    "costs.rnd_nonstaff_pct",
    "costs.gna_nonstaff_pct",
    "costs.public_company",
    "costs.sbc_pct",
    "capital.capex_pct",
    "capital.useful_life",
    "capital.ppe_start",
    "capital.nwc_pct",
    "capital.tax_rate",
    "capital.nol",
)


def forecast_inputs(v: Mapping[str, Any]) -> ForecastInputs:
    follows_revenue = v["people.headcount_mode"] == "follow_revenue"
    return ForecastInputs(
        horizon=int(v["rates.horizon"]),
        terminal_growth=v["rates.terminal_growth"],
        inflation=v["costs.inflation"],
        tam=v["market.tam"],
        tam_growth=v["market.tam_growth"],
        sam_share=v["market.sam_share"],
        p_max=v["market.p_max"],
        revenue_0=v["customers.last_fy_revenue"],
        customers_0=v["customers.now"],
        arpu=v["customers.arpu"],
        arpu_growth=v["customers.arpu_growth"],
        churn=v["customers.churn"],
        customer_growth_y1=v["customers.growth_y1"],
        headcount_0=v["people.headcount"],
        loaded_cost=v["people.loaded_cost"],
        wage_inflation=v["people.wage_inflation"],
        headcount_elasticity=v["people.elasticity"] if follows_revenue else None,
        headcount_growth_y1=v["people.growth_y1"],
        headcount_growth_floor=v["people.growth_floor"],
        staff_split=(
            v["people.split_rnd"],
            v["people.split_snm"],
            v["people.split_gna"],
            v["people.split_ops"],
        ),
        infra_fixed=v["costs.infra_fixed"],
        infra_per_customer=v["costs.infra_per_customer"],
        other_cogs_pct=v["costs.other_cogs_pct"],
        cac_paid=v["costs.cac_paid"],
        cac_growth=v["costs.cac_growth"],
        rnd_nonstaff_pct=v["costs.rnd_nonstaff_pct"],
        gna_nonstaff_pct=v["costs.gna_nonstaff_pct"],
        public_company=v["costs.public_company"],
        sbc_pct=v["costs.sbc_pct"],
        capex_pct=v["capital.capex_pct"],
        useful_life=v["capital.useful_life"],
        ppe_0=v["capital.ppe_start"],
        nwc_pct=v["capital.nwc_pct"],
        tax_rate=v["capital.tax_rate"],
        nol_0=v["capital.nol"],
    )


def rate_inputs(v: Mapping[str, Any]) -> RateInputs:
    return RateInputs(
        risk_free=v["rates.risk_free"],
        erp=v["rates.erp"],
        beta_stage1=v["rates.beta_stage1"],
        beta_stage2=v["rates.beta_stage2"],
        size_premium_1=v["rates.size_premium_1"],
        size_premium_2=v["rates.size_premium_2"],
        execution_premium=v["rates.execution_premium"],
        debt_ratio=v["rates.debt_ratio"],
        cost_of_debt=v["rates.cost_of_debt"],
        tax_rate=v["capital.tax_rate"],
        r1_override=v["rates.r1_override"],
        r2_override=v["rates.r2_override"],
    )


def offering(v: Mapping[str, Any]) -> Offering:
    return Offering(
        raise_gross=v["offering.raise"],
        gross_spread=v["offering.gross_spread"],
        other_expenses=v["offering.other_expenses"],
        shares_pre=v["offering.shares_pre"],
    )


def comps_pre_money(v: Mapping[str, Any]) -> float:
    """Pre-IPO equity at the comparables' multiple, before any offering costs."""
    ntm_revenue = forecast(forecast_inputs(v))[0].revenue
    ev = comps_enterprise_value(ntm_revenue, v["investors.comps_multiple"])
    net_cash: float = v["capital.cash"] - v["capital.debt"]
    return ev + net_cash


@dataclass(frozen=True)
class Valuation:
    years: tuple[YearRow, ...]  # N+1 rows; the last feeds the terminal value
    stage1: StageRate
    stage2: StageRate
    dcf: Dcf
    equity_pre: float  # DCF enterprise value + cash − debt
    dcf_price: float
    comps_ev: float
    comps_price: float
    fair_value: float
    ev_to_ntm_revenue: float  # the DCF's implied multiples, for comparison
    ev_to_ebit_n: float


def value(v: Mapping[str, Any]) -> Valuation:
    """The deterministic valuation of one fully resolved set of answers."""
    years = forecast(forecast_inputs(v))
    stage1, stage2 = stage_rates(rate_inputs(v))
    result = dcf(
        years,
        r1=stage1.rate,
        r2=stage2.rate,
        stage1_years=int(v["rates.stage1_years"]),
        terminal_growth=v["rates.terminal_growth"],
        ronic_spread=v["rates.ronic_spread"],
        tax_rate=v["capital.tax_rate"],
        mid_year=v["rates.mid_year"],
    )
    net_cash = v["capital.cash"] - v["capital.debt"]
    offer = offering(v)
    equity_pre = result.enterprise_value + net_cash
    comps_ev = comps_enterprise_value(years[0].revenue, v["investors.comps_multiple"])
    dcf_price = fair_price(equity_pre, offer)
    comps_price = fair_price(comps_ev + net_cash, offer)
    return Valuation(
        years=years,
        stage1=stage1,
        stage2=stage2,
        dcf=result,
        equity_pre=equity_pre,
        dcf_price=dcf_price,
        comps_ev=comps_ev,
        comps_price=comps_price,
        fair_value=blend(dcf_price, comps_price, v["investors.dcf_weight"]),
        ev_to_ntm_revenue=result.enterprise_value / years[0].revenue,
        ev_to_ebit_n=result.enterprise_value / years[-2].ebit,
    )
