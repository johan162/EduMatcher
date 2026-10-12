"""market_sim.model: statistical properties (fixed seeds) and determinism."""

from __future__ import annotations

import math
import statistics

import pytest

from edumatcher.market_sim.model import (
    TRADING_DAYS_PER_YEAR,
    SymbolParams,
    ValueModel,
    intraday_variance,
)

N = 100_000
Z99 = 2.576


def _returns(model: ValueModel, sym: str, steps: int, dt: float) -> list[float]:
    out = []
    last = model.log_values[sym]
    for _ in range(steps):
        model.step(dt)
        out.append(model.log_values[sym] - last)
        last = model.log_values[sym]
    return out


def test_log_return_mean_and_variance() -> None:
    # A strong drift and whole-day steps, so the mean is many standard errors
    # away from zero and a lost drift term would fail the test.
    p = SymbolParams(
        "TECH", vol=0.3, drift=0.5, jump_rate=0.0, beta_market=0.0, beta_sector=0.0
    )
    dt = 1.0
    r = _returns(ValueModel({"A": p}, {"A": 100.0}, seed=1), "A", N, dt)
    var = p.vol**2 / TRADING_DAYS_PER_YEAR * dt
    mean = (p.drift / TRADING_DAYS_PER_YEAR - 0.5 * var / dt) * dt
    assert mean > 10 * math.sqrt(var / N)
    assert abs(statistics.fmean(r) - mean) < Z99 * math.sqrt(var / N)
    sample_var = statistics.variance(r)
    assert abs(sample_var - var) < Z99 * var * math.sqrt(2 / (N - 1))


def test_correlation_follows_the_betas() -> None:
    same = SymbolParams("TECH", jump_rate=0.0, beta_market=0.5, beta_sector=0.6)
    other = SymbolParams("ENERGY", jump_rate=0.0, beta_market=0.5, beta_sector=0.6)
    m = ValueModel(
        {"A": same, "B": same, "C": other},
        {"A": 10.0, "B": 20.0, "C": 30.0},
        seed=2,
    )
    rets: dict[str, list[float]] = {"A": [], "B": [], "C": []}
    last = dict(m.log_values)
    for _ in range(20_000):
        m.step(1 / 390)
        for s in rets:
            rets[s].append(m.log_values[s] - last[s])
        last = dict(m.log_values)
    assert statistics.correlation(rets["A"], rets["B"]) == pytest.approx(0.61, abs=0.05)
    assert statistics.correlation(rets["A"], rets["C"]) == pytest.approx(0.25, abs=0.05)


def test_jump_frequency() -> None:
    p = SymbolParams(
        "X", vol=0.0, drift=0.0, jump_rate=0.05, jump_mean=1.0, jump_std=0.0
    )
    m = ValueModel({"A": p}, {"A": 1.0}, seed=3)
    jumps = sum(round(m._jump("A", p, 1.0)) for _ in range(N))
    expected = 0.05 * N
    assert abs(jumps - expected) < Z99 * math.sqrt(expected)


def test_overnight_variance_is_a_fraction_of_a_day() -> None:
    p = SymbolParams("X", vol=0.3, jump_rate=0.0, beta_market=0.0, beta_sector=0.0)
    m = ValueModel({"A": p}, {"A": 50.0}, seed=4, overnight_fraction=0.2)
    r = []
    for _ in range(N):
        before = m.log_values["A"]
        m.overnight()
        r.append(m.log_values["A"] - before)
    day_var = p.vol**2 / TRADING_DAYS_PER_YEAR
    assert statistics.variance(r) / day_var == pytest.approx(0.2, rel=0.02)


def test_same_seed_same_path_and_streams_are_independent() -> None:
    p = SymbolParams("TECH")
    a = ValueModel({"A": p}, {"A": 100.0}, seed=9)
    b = ValueModel({"A": p, "B": p}, {"A": 100.0, "B": 50.0}, seed=9)
    for _ in range(500):
        a.step(1 / 390)
        b.step(1 / 390)
    assert a.value("A") == b.value("A")  # adding B does not move A
    c = ValueModel({"A": p}, {"A": 100.0}, seed=9, epoch=1)
    c.step(1 / 390)
    d = ValueModel({"A": p}, {"A": 100.0}, seed=9)
    d.step(1 / 390)
    assert c.value("A") != d.value("A")


def test_intraday_multiplier_has_mean_one() -> None:
    xs = [(i + 0.5) / 10_000 for i in range(10_000)]
    assert statistics.fmean(intraday_variance(x) for x in xs) == pytest.approx(
        1.0, abs=1e-3
    )
    assert intraday_variance(0.0) == pytest.approx(1.94, abs=0.01)
    assert intraday_variance(0.5) == pytest.approx(0.53, abs=0.01)


def test_shock_and_validation() -> None:
    m = ValueModel({"A": SymbolParams("X")}, {"A": 100.0}, seed=1)
    m.shock({"A": math.log(1.1), "NOPE": 1.0})
    assert m.value("A") == pytest.approx(110.0)
    with pytest.raises(ValueError, match="beta"):
        SymbolParams("X", beta_market=0.8, beta_sector=0.8)
    with pytest.raises(ValueError, match="initial value"):
        ValueModel({"A": SymbolParams("X")}, {}, seed=1)
