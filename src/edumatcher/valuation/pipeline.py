"""One run of pm-valuation: answers in, every result the report needs out."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from edumatcher.valuation.model.checks import Finding, findings, rate_errors
from edumatcher.valuation.model.montecarlo import MonteCarlo, simulate
from edumatcher.valuation.model.offering import Pricing, price_ipo
from edumatcher.valuation.model.scenarios import Scenarios, scenarios
from edumatcher.valuation.model.valuation import Valuation, value
from edumatcher.valuation.presets import Presets
from edumatcher.valuation.resolve import Resolved, resolve


class CannotValue(ValueError):
    """The answers are valid one by one but describe no computable company."""


@dataclass(frozen=True)
class Run:
    answers: Mapping[str, Any]
    resolved: Resolved
    valuation: Valuation
    pricing: Pricing
    scenarios: Scenarios | None  # modes "deterministic" and "both"
    mc: MonteCarlo | None  # modes "montecarlo" and "both"
    findings: tuple[Finding, ...]


def run(
    answers: Mapping[str, Any], presets: Presets, deterministic_only: bool = False
) -> Run:
    """Resolve, value, price and simulate as the Simulation page asks.

    *deterministic_only* skips scenarios and Monte Carlo: what the live
    preview needs after every keystroke. Raises InvalidAnswers for bad
    answers and CannotValue for a company the model cannot value.
    """
    resolved = resolve(answers, presets)
    v = resolved.values
    errors = rate_errors(v)
    if errors:
        raise CannotValue(errors[0].message)
    try:
        valuation = value(v)
    except ValueError as exc:
        raise CannotValue(str(exc)) from exc
    pricing = price_ipo(v, valuation)
    mode = v["simulation.mode"]
    cases = (
        scenarios(v, valuation)
        if mode in ("deterministic", "both") and not deterministic_only
        else None
    )
    mc = (
        simulate(
            v,
            int(v["simulation.draws"]),
            int(v["simulation.seed"]),
            v["simulation.rho"],
        )
        if mode in ("montecarlo", "both") and not deterministic_only
        else None
    )
    return Run(
        answers=dict(answers),
        resolved=resolved,
        valuation=valuation,
        pricing=pricing,
        scenarios=cases,
        mc=mc,
        findings=tuple(findings(v, presets, valuation, pricing, mc)),
    )
