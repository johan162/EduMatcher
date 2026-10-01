"""Bear, base and bull cases, the tornado and two sensitivity grids (§11)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from edumatcher.valuation.fields import BY_KEY, DRIVER_KEYS
from edumatcher.valuation.model.valuation import Valuation, value


def case_values(v: Mapping[str, Any], case: str) -> dict[str, Any]:
    """*v* with every driver at its bear or bull value."""
    return {**v, **{key: v[f"simulation.{case}.{key}"] for key in DRIVER_KEYS}}


def try_value(v: Mapping[str, Any]) -> Valuation | None:
    """The valuation, or None where the inputs describe no valid company
    (customers already at the market cap, or r2 not above g)."""
    try:
        return value(v)
    except ValueError:
        return None


@dataclass(frozen=True)
class TornadoBar:
    key: str
    label: str
    bear: float | None  # fair value per share with only this driver at bear
    bull: float | None
    swing: float  # |bull − bear|; 0 when either side is invalid


@dataclass(frozen=True)
class Grid:
    """DCF value per share over two inputs; None where invalid."""

    row_key: str
    col_key: str
    rows: tuple[float, ...]
    cols: tuple[float, ...]
    cells: tuple[tuple[float | None, ...], ...]


@dataclass(frozen=True)
class Scenarios:
    bear: Valuation | None
    base: Valuation
    bull: Valuation | None
    tornado: tuple[TornadoBar, ...]  # widest swing first
    rate2_growth: Grid  # r2 × terminal growth
    rate1_customer_growth: Grid  # r1 × year-1 customer growth


def _bar(v: Mapping[str, Any], key: str) -> TornadoBar:
    ends = [
        try_value({**v, key: v[f"simulation.{case}.{key}"]})
        for case in ("bear", "bull")
    ]
    bear, bull = (None if e is None else e.fair_value for e in ends)
    swing = abs(bull - bear) if bear is not None and bull is not None else 0.0
    return TornadoBar(key, BY_KEY[key].label, bear, bull, swing)


def _grid(
    v: Mapping[str, Any],
    row_key: str,
    rows: tuple[float, ...],
    col_key: str,
    cols: tuple[float, ...],
) -> Grid:
    cells = tuple(
        tuple(
            None if (val := try_value({**v, row_key: r, col_key: c})) is None
            else val.dcf_price
            for c in cols
        )
        for r in rows
    )  # fmt: skip
    return Grid(row_key, col_key, rows, cols, cells)


def scenarios(v: Mapping[str, Any], base: Valuation) -> Scenarios:
    """Everything §11.2 reports. The grids move a rate through its override,
    so each row is exactly the rate it is labelled with."""
    r1, r2 = base.stage1.rate, base.stage2.rate
    g, g_c1 = v["rates.terminal_growth"], v["customers.growth_y1"]
    return Scenarios(
        bear=try_value(case_values(v, "bear")),
        base=base,
        bull=try_value(case_values(v, "bull")),
        tornado=tuple(
            sorted((_bar(v, key) for key in DRIVER_KEYS), key=lambda b: -b.swing)
        ),
        rate2_growth=_grid(
            v,
            "rates.r2_override",
            tuple(r2 + d for d in (-0.02, -0.01, 0.0, 0.01, 0.02)),
            "rates.terminal_growth",
            tuple(g + d for d in (-0.01, -0.005, 0.0, 0.005, 0.01)),
        ),
        rate1_customer_growth=_grid(
            v,
            "rates.r1_override",
            tuple(r1 + d for d in (-0.04, -0.02, 0.0, 0.02, 0.04)),
            "customers.growth_y1",
            tuple(g_c1 + d for d in (-0.2, -0.1, 0.0, 0.1, 0.2)),
        ),
    )
