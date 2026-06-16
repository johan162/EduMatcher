"""Parser for risk level specs: NAME:STATIC_PCT[:DYNAMIC_PCT]."""

from __future__ import annotations

from dataclasses import dataclass

from .defaults import DEFAULT_DYNAMIC_BAND_PCT


@dataclass(frozen=True)
class RiskLevelSpec:
    name: str
    static_pct: float
    dynamic_pct: float


def parse_risk_level_spec(raw: str) -> RiskLevelSpec:
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) not in (2, 3):
        raise ValueError(
            f"Invalid risk-level spec '{raw}': expected NAME:STATIC_PCT[:DYNAMIC_PCT]"
        )

    name = parts[0].upper()
    if not name:
        raise ValueError("Risk level name cannot be empty")

    try:
        static_pct = float(parts[1])
    except ValueError as exc:
        raise ValueError(f"Invalid static_pct in risk-level spec '{raw}'") from exc
    if not (0 < static_pct < 1):
        raise ValueError(f"Risk static_pct must be in (0, 1): '{raw}'")

    dynamic_pct = DEFAULT_DYNAMIC_BAND_PCT
    if len(parts) == 3 and parts[2] != "":
        try:
            dynamic_pct = float(parts[2])
        except ValueError as exc:
            raise ValueError(f"Invalid dynamic_pct in risk-level spec '{raw}'") from exc
    if not (0 < dynamic_pct < 1):
        raise ValueError(f"Risk dynamic_pct must be in (0, 1): '{raw}'")

    return RiskLevelSpec(name=name, static_pct=static_pct, dynamic_pct=dynamic_pct)
