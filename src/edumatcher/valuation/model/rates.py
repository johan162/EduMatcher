"""Discount rates for the two DCF stages (design §7)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RateInputs:
    risk_free: float
    erp: float
    beta_stage1: float
    beta_stage2: float
    size_premium_1: float
    size_premium_2: float
    execution_premium: float  # stage 1 only: the risk that the plan never happens
    debt_ratio: float  # D/V
    cost_of_debt: float
    tax_rate: float
    r1_override: float | None
    r2_override: float | None


@dataclass(frozen=True)
class StageRate:
    """One stage's rate and the build-up behind it."""

    cost_of_equity: float
    rate: float  # the WACC, or the override
    overridden: bool


def _stage(cost_of_equity: float, inp: RateInputs, override: float | None) -> StageRate:
    if override is not None:
        return StageRate(cost_of_equity, override, overridden=True)
    after_tax_debt = inp.cost_of_debt * (1 - inp.tax_rate)
    wacc = (1 - inp.debt_ratio) * cost_of_equity + inp.debt_ratio * after_tax_debt
    return StageRate(cost_of_equity, wacc, overridden=False)


def stage_rates(inp: RateInputs) -> tuple[StageRate, StageRate]:
    """CAPM with premia for each stage, then the WACC."""
    ke1 = (
        inp.risk_free
        + inp.beta_stage1 * inp.erp
        + inp.size_premium_1
        + inp.execution_premium
    )
    ke2 = inp.risk_free + inp.beta_stage2 * inp.erp + inp.size_premium_2
    return _stage(ke1, inp, inp.r1_override), _stage(ke2, inp, inp.r2_override)
