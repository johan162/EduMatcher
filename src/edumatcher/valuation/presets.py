"""Load and validate the sector presets (``presets.yaml``, design §5)."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

#: Order of the staff split everywhere in the model.
STAFF_SPLIT_KEYS = ("rnd", "snm", "gna", "ops")


@dataclass(frozen=True)
class Preset:
    """Defaults for one business model. Percentages are fractions."""

    name: str
    description: str
    sic_code: str
    customer_means: str
    revenue_last_fy: float
    arpu: float
    churn: float
    customer_growth_y1: float
    tam: float
    tam_growth: float
    sam_share: float
    infra_fixed: float
    infra_per_customer: float
    other_cogs_pct: float
    revenue_per_employee: float
    loaded_cost: float
    staff_split: tuple[float, float, float, float]
    cac_arpu_multiple: float
    capex_pct: float
    nwc_pct: float
    beta_stage1: float
    beta_stage2: float
    comps_ev_revenue: float
    ebit_margin_band: tuple[float, float]


@dataclass(frozen=True)
class FilerThresholds:
    """SEC filer-status thresholds for the S-1 cover (design §4)."""

    egc_revenue: float
    src_public_float: float
    src_revenue: float
    src_public_float_alt: float


@dataclass(frozen=True)
class Presets:
    market_structures: dict[str, float]
    sectors: dict[str, Preset]
    filer_thresholds: FilerThresholds


def _preset(name: str, raw: Any) -> Preset:
    if not isinstance(raw, dict):
        raise ValueError(f"preset {name!r} must be a mapping")
    expected = {f.name for f in dataclasses.fields(Preset)} - {"name"}
    if set(raw) != expected:
        missing = sorted(expected - set(raw))
        unknown = sorted(set(raw) - expected)
        raise ValueError(f"preset {name!r}: missing {missing}, unknown {unknown}")
    split = raw["staff_split"]
    if not isinstance(split, dict) or set(split) != set(STAFF_SPLIT_KEYS):
        raise ValueError(f"preset {name!r}: staff_split needs {STAFF_SPLIT_KEYS}")
    shares = tuple(float(split[k]) for k in STAFF_SPLIT_KEYS)
    if abs(sum(shares) - 1) > 1e-9:
        raise ValueError(f"preset {name!r}: staff_split must sum to 1")
    low, high = (float(x) for x in raw["ebit_margin_band"])
    text = {"description", "sic_code", "customer_means"}
    values: dict[str, Any] = {
        key: str(value) if key in text else float(value)
        for key, value in raw.items()
        if key not in ("staff_split", "ebit_margin_band")
    }
    return Preset(
        name=name,
        staff_split=(shares[0], shares[1], shares[2], shares[3]),
        ebit_margin_band=(low, high),
        **values,
    )


def load_presets(path: Path | None = None) -> Presets:
    """Read *path*, or the bundled ``presets.yaml`` when it is None."""
    if path is None:
        text = files("edumatcher.valuation").joinpath("presets.yaml").read_text("utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    sections = {"filer_thresholds", "market_structures", "sectors"}
    if not isinstance(raw, dict) or set(raw) != sections:
        raise ValueError(f"presets need exactly {', '.join(sorted(sections))}")
    structures = {str(k): float(v) for k, v in raw["market_structures"].items()}
    sectors = {str(k): _preset(str(k), v) for k, v in raw["sectors"].items()}
    if not sectors:
        raise ValueError("presets define no sectors")
    thresholds = raw["filer_thresholds"]
    expected = {f.name for f in dataclasses.fields(FilerThresholds)}
    if not isinstance(thresholds, dict) or set(thresholds) != expected:
        raise ValueError(f"filer_thresholds need exactly {', '.join(sorted(expected))}")
    return Presets(
        market_structures=structures,
        sectors=sectors,
        filer_thresholds=FilerThresholds(
            **{k: float(v) for k, v in thresholds.items()}
        ),
    )
