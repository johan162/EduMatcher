"""Monte Carlo over the scenario drivers (design §12).

Each driver is triangular on (bear, base, bull). The operating drivers share
one "execution" factor through a Gaussian copula; the market and rate
drivers are drawn independently. The draw order is fixed, so a seed always
gives the same simulation.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

from edumatcher.valuation.fields import DRIVER_KEYS, OPERATING_DRIVERS
from edumatcher.valuation.model.rates import stage_rates
from edumatcher.valuation.model.scenarios import try_value
from edumatcher.valuation.model.valuation import rate_inputs

#: A draw with r2 − g below this is rejected: the terminal value explodes.
MIN_RATE_GAP = 0.02
_PHI = NormalDist().cdf


@dataclass(frozen=True)
class Sample:
    dcf_price: float
    fair_value: float
    equity_pre: float  # DCF equity before the IPO


@dataclass(frozen=True)
class MonteCarlo:
    samples: tuple[Sample, ...]
    rejected: int  # draws redrawn: r2 − g too small, or no valid company


@dataclass(frozen=True)
class Summary:
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    mean: float
    sd: float


def triangular(u: float, bear: float, base: float, bull: float) -> float:
    """Inverse CDF of the triangle from bear (u = 0) through base to bull (u = 1)."""
    if bull == bear:
        return base
    m = (base - bear) / (bull - bear)
    q = math.sqrt(u * m) if u < m else 1 - math.sqrt((1 - u) * (1 - m))
    return bear + q * (bull - bear)


def simulate(v: Mapping[str, Any], draws: int, seed: int, rho: float) -> MonteCarlo:
    rng = random.Random(seed)
    samples: list[Sample] = []
    rejected = 0
    while len(samples) < draws:
        z = rng.gauss(0, 1)
        drawn: dict[str, float] = {}
        for key in DRIVER_KEYS:
            if key in OPERATING_DRIVERS:
                u = _PHI(math.sqrt(rho) * z + math.sqrt(1 - rho) * rng.gauss(0, 1))
            else:
                u = rng.random()
            drawn[key] = triangular(
                u, v[f"simulation.bear.{key}"], v[key], v[f"simulation.bull.{key}"]
            )
        values = {**v, **drawn}
        r2 = stage_rates(rate_inputs(values))[1].rate
        result = (
            try_value(values)
            if r2 - values["rates.terminal_growth"] >= MIN_RATE_GAP
            else None
        )
        if result is None:
            rejected += 1
            continue
        samples.append(Sample(result.dcf_price, result.fair_value, result.equity_pre))
    return MonteCarlo(tuple(samples), rejected)


def summarize(values: Sequence[float]) -> Summary:
    """Percentiles by nearest rank below: the value at index ⌊p·(n − 1)⌋."""
    xs = sorted(values)
    p5, p25, p50, p75, p95 = (
        xs[int(p * (len(xs) - 1))] for p in (0.05, 0.25, 0.50, 0.75, 0.95)
    )
    return Summary(p5, p25, p50, p75, p95, statistics.mean(xs), statistics.stdev(xs))


def share_below(values: Sequence[float], threshold: float) -> float:
    return sum(1 for x in values if x < threshold) / len(values)
