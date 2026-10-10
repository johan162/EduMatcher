"""The value model: correlated log-normal values with jumps. Pure and seeded.

For symbol *i*, one step of length Δ (in trading days) moves the log value by

    (μ_i − ½σ_i²u)Δ + σ_i√(uΔ)·(β_m Z_m + β_s Z_s + √(1 − β_m² − β_s²) Z_i) + J_i

with Z standard normals for the market, the symbol's sector and the symbol
itself, ``u`` the intraday volatility multiplier (U-shaped, mean 1 over the
day) and J the sum of a Poisson(λ_iΔ) number of normal log jumps. μ and σ are
annual (252 trading days); λ is per trading day. ``overnight`` adds one step
whose variance is ``overnight_fraction`` of a day's.

Every source of randomness is its own ``random.Random`` stream, seeded from
the model seed and the stream's name, so a symbol's path does not change when
another symbol is added and a restart can reseed reproducibly.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class SymbolParams:
    sector: str
    vol: float = 0.30  # annual volatility of the log value
    drift: float = 0.05  # annual drift
    jump_rate: float = 0.05  # jumps per trading day
    jump_mean: float = 0.0  # mean log jump
    jump_std: float = 0.04  # std of the log jump
    beta_market: float = 0.5
    beta_sector: float = 0.4

    def __post_init__(self) -> None:
        if self.beta_market**2 + self.beta_sector**2 > 1.0:
            raise ValueError("beta_market² + beta_sector² must not exceed 1")


def intraday_variance(fraction: float) -> float:
    """Variance multiplier at ``fraction`` (0..1) of the trading day: 1.94 at
    the open and the close, 0.53 midday, mean 1."""
    x = min(1.0, max(0.0, fraction))
    return (0.6 + 1.6 * (2 * x - 1) ** 2) / (17.0 / 15.0)


class ValueModel:
    def __init__(
        self,
        params: dict[str, SymbolParams],
        values: dict[str, float],
        seed: int,
        *,
        overnight_fraction: float = 0.2,
        epoch: int = 0,
    ) -> None:
        missing = sorted(set(params) - set(values))
        if missing:
            raise ValueError(f"no initial value for {', '.join(missing)}")
        self.params = dict(params)
        self.log_values = {s: math.log(values[s]) for s in params}
        self.overnight_fraction = overnight_fraction
        self.seed = seed
        self.reseed(epoch)

    def reseed(self, epoch: int) -> None:
        """Fresh streams for ``epoch`` (a restart continues from a new epoch)."""

        def stream(name: str) -> random.Random:
            return random.Random(f"{self.seed}:{epoch}:{name}")

        self._market = stream("market")
        self._sectors = {
            p.sector: stream(f"sector:{p.sector}") for p in self.params.values()
        }
        self._idio = {s: stream(f"symbol:{s}") for s in self.params}
        self._jumps = {s: stream(f"jump:{s}") for s in self.params}

    # --- stepping -------------------------------------------------------------
    def step(self, dt_days: float, day_fraction: float | None = None) -> None:
        """Advance every symbol by ``dt_days`` of trading time."""
        u = 1.0 if day_fraction is None else intraday_variance(day_fraction)
        self._advance(dt_days, u)

    def overnight(self) -> None:
        """The move between yesterday's close and today's open."""
        self._advance(self.overnight_fraction, 1.0, jumps=False)

    def _advance(self, dt: float, u: float, jumps: bool = True) -> None:
        z_market = self._market.gauss(0.0, 1.0)
        z_sector = {name: r.gauss(0.0, 1.0) for name, r in self._sectors.items()}
        for sym, p in self.params.items():
            var = (p.vol**2 / TRADING_DAYS_PER_YEAR) * u
            idio = math.sqrt(1.0 - p.beta_market**2 - p.beta_sector**2)
            z = (
                p.beta_market * z_market
                + p.beta_sector * z_sector[p.sector]
                + idio * self._idio[sym].gauss(0.0, 1.0)
            )
            move = (p.drift / TRADING_DAYS_PER_YEAR - 0.5 * var) * dt + math.sqrt(
                var * dt
            ) * z
            if jumps and p.jump_rate > 0:
                move += self._jump(sym, p, dt)
            self.log_values[sym] += move

    def _jump(self, sym: str, p: SymbolParams, dt: float) -> float:
        r = self._jumps[sym]
        # Poisson count by inversion: a step is short, so mostly zero.
        lam = p.jump_rate * dt
        k, prob, u = 0, math.exp(-lam), r.random()
        cdf = prob
        while u > cdf:
            k += 1
            prob *= lam / k
            cdf += prob
        return sum(r.gauss(p.jump_mean, p.jump_std) for _ in range(k))

    def shock(self, log_moves: dict[str, float]) -> None:
        """Apply news: an immediate move of the log value of some symbols."""
        for sym, move in log_moves.items():
            if sym in self.log_values:
                self.log_values[sym] += move

    # --- reading ----------------------------------------------------------------
    def value(self, symbol: str) -> float:
        return math.exp(self.log_values[symbol])

    def values(self) -> dict[str, float]:
        return {s: math.exp(lv) for s, lv in self.log_values.items()}
