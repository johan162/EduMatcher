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

#: The eleven industries of FTSE Russell's Industry Classification Benchmark,
#: by the first two digits of an ICB code. Nasdaq's Nordic exchanges use ICB.
ICB_INDUSTRIES = {
    "10": "Technology",
    "15": "Telecommunications",
    "20": "Health Care",
    "30": "Financials",
    "35": "Real Estate",
    "40": "Consumer Discretionary",
    "45": "Consumer Staples",
    "50": "Industrials",
    "55": "Basic Materials",
    "60": "Energy",
    "65": "Utilities",
}
#: The industry classifications a market's offering document may use.
CLASSIFICATIONS = ("ICB", "SIC")


@dataclass(frozen=True)
class Preset:
    """Defaults for one business model. Percentages are fractions."""

    name: str
    description: str
    sic_code: str  # US Standard Industrial Classification (the S-1)
    icb_code: str  # ICB subsector, 8 digits (Nasdaq Stockholm)
    icb_name: str
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
    execution_premium: float
    useful_life: float
    ebit_margin_band: tuple[float, float]
    revenue_per_employee_band: tuple[float, float]  # year N, US dollars at US pay

    @property
    def industry(self) -> str:
        """The ICB industry the preset belongs to, e.g. Technology."""
        return ICB_INDUSTRIES[self.icb_code[:2]]


@dataclass(frozen=True)
class FilerThresholds:
    """SEC filer-status thresholds for the S-1 cover (design §4)."""

    egc_revenue: float
    src_public_float: float
    src_revenue: float
    src_public_float_alt: float


@dataclass(frozen=True)
class Market:
    """Where the company lists: currency, legal and regulatory framing, and
    the defaults that follow from it (--market)."""

    name: str
    description: str
    currency: str
    fx: float  # local currency per US dollar; presets are in US dollars
    salary_level: float  # loaded cost relative to the (US) presets
    company_name: str
    incorporation: str
    lead_underwriter: str
    document: str  # the offering document: "S-1" or "Prospectus"
    classification: str  # the industry code its cover shows: ICB or SIC
    regulator: str
    listing_venue: str
    risk_free: float
    erp: float
    tax_rate: float
    inflation: float
    terminal_growth: float
    gross_spread: float
    target_price: float
    max_above_range: float


@dataclass(frozen=True)
class Presets:
    markets: dict[str, Market]
    market_structures: dict[str, float]
    sectors: dict[str, Preset]
    filer_thresholds: FilerThresholds


def _market(name: str, raw: Any) -> Market:
    if not isinstance(raw, dict):
        raise ValueError(f"market {name!r} must be a mapping")
    expected = {f.name for f in dataclasses.fields(Market)} - {"name"}
    if set(raw) != expected:
        missing = sorted(expected - set(raw))
        unknown = sorted(set(raw) - expected)
        raise ValueError(f"market {name!r}: missing {missing}, unknown {unknown}")
    text = {"description", "currency", "company_name", "incorporation",
            "lead_underwriter", "document", "classification", "regulator",
            "listing_venue"}  # fmt: skip
    values: dict[str, Any] = {
        k: str(v) if k in text else float(v) for k, v in raw.items()
    }
    if values["classification"] not in CLASSIFICATIONS:
        raise ValueError(f"market {name!r}: classification must be ICB or SIC")
    return Market(name=name, **values)


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
    fewest, most = (float(x) for x in raw["revenue_per_employee_band"])
    text = {"description", "sic_code", "icb_code", "icb_name", "customer_means"}
    values: dict[str, Any] = {
        key: str(value) if key in text else float(value)
        for key, value in raw.items()
        if key not in ("staff_split", "ebit_margin_band", "revenue_per_employee_band")
    }
    code = values["icb_code"]
    if len(code) != 8 or not code.isdigit() or code[:2] not in ICB_INDUSTRIES:
        raise ValueError(f"preset {name!r}: icb_code must be an 8-digit ICB code")
    return Preset(
        name=name,
        staff_split=(shares[0], shares[1], shares[2], shares[3]),
        ebit_margin_band=(low, high),
        revenue_per_employee_band=(fewest, most),
        **values,
    )


def load_presets(path: Path | None = None) -> Presets:
    """Read *path*, or the bundled ``presets.yaml`` when it is None."""
    if path is None:
        text = files("edumatcher.valuation").joinpath("presets.yaml").read_text("utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    sections = {"filer_thresholds", "market_structures", "markets", "sectors"}
    if not isinstance(raw, dict) or set(raw) != sections:
        raise ValueError(f"presets need exactly {', '.join(sorted(sections))}")
    structures = {str(k): float(v) for k, v in raw["market_structures"].items()}
    sectors = {str(k): _preset(str(k), v) for k, v in raw["sectors"].items()}
    markets = {str(k): _market(str(k), v) for k, v in raw["markets"].items()}
    if not sectors:
        raise ValueError("presets define no sectors")
    thresholds = raw["filer_thresholds"]
    expected = {f.name for f in dataclasses.fields(FilerThresholds)}
    if not isinstance(thresholds, dict) or set(thresholds) != expected:
        raise ValueError(f"filer_thresholds need exactly {', '.join(sorted(expected))}")
    return Presets(
        markets=markets,
        market_structures=structures,
        sectors=sectors,
        filer_thresholds=FilerThresholds(
            **{k: float(v) for k, v in thresholds.items()}
        ),
    )
