"""Presets: a named bundle of strategy x execution x tempo x risk.

A preset is a small YAML file. Built-ins live in ``ai_trader/presets/``;
users pass their own with ``--preset-file``. Unknown keys and out-of-range
values are rejected before an agent starts, naming the file and key.

Tempo (how often and how big) has four built-in values, the old profile
names: ``many-small``, ``aggressive``, ``cautious``, ``few-large``. A preset
may name one or give its own mapping.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, fields
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from edumatcher.ai_trader.execution import STYLES, SWEEP_TYPES, ExecutionSpec
from edumatcher.ai_trader.risk import RiskSpec
from edumatcher.ai_trader.strategies import STRATEGIES

SIZE_DISTRIBUTIONS = ("balanced", "small-heavy", "block-heavy")
PROTECTIONS = ("none", "stop", "stop_limit", "trailing", "bracket")


class PresetError(ValueError):
    pass


@dataclass(frozen=True)
class TempoSpec:
    decisions_per_min: float
    size_min: int
    size_max: int
    size_distribution: str = "balanced"

    def sample_qty(self, rng: random.Random) -> int:
        lo, hi = self.size_min, self.size_max
        if lo >= hi:
            return lo
        u = rng.random()
        if self.size_distribution == "small-heavy":
            u = u**2.0
        elif self.size_distribution == "block-heavy":
            u = 1.0 - (1.0 - u) ** 2.0
        else:
            return rng.randint(lo, hi)
        return max(lo, min(hi, lo + int(u * (hi - lo))))


TEMPOS: dict[str, TempoSpec] = {
    "many-small": TempoSpec(30.0, 1, 25, "small-heavy"),
    "aggressive": TempoSpec(20.0, 20, 120, "balanced"),
    "cautious": TempoSpec(6.0, 10, 60, "balanced"),
    "few-large": TempoSpec(2.0, 150, 700, "block-heavy"),
}


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    strategy: str
    strategy_params: dict[str, float]
    execution: ExecutionSpec
    tempo: TempoSpec
    risk: RiskSpec

    def make_strategy(self) -> Any:
        return STRATEGIES[self.strategy](**self.strategy_params)


_TOP_KEYS = {"name", "description", "strategy", "execution", "tempo", "risk"}
_STRATEGY_PARAMS = {
    "noise": {"urgency"},
    "trend": {"strength", "sample", "urgency"},
    "reversion": {"strength", "sample", "urgency"},
    "value": {"threshold", "bias_std", "redraw", "sample", "urgency", "rumour_shift"},
    "news": {"lag_sec", "lag_sigma", "half_life_sec", "threshold", "urgency", "move"},
}
#: Strategy parameters that are not in [0, 1]: (low, high).
_STRATEGY_RANGES = {
    "lag_sec": (0.0, 3600.0),
    "lag_sigma": (0.0, 3.0),
    "half_life_sec": (1.0, 86_400.0),
}


def _fail(source: str, msg: str) -> PresetError:
    return PresetError(f"{source}: {msg}")


def _mapping(source: str, key: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(source, f"{key} must be a mapping")
    return value


def _number(source: str, key: str, value: Any, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(source, f"{key} must be a number")
    if not lo <= float(value) <= hi:
        raise _fail(source, f"{key}={value} is outside [{lo}, {hi}]")
    return float(value)


def _integer(source: str, key: str, value: Any, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(source, f"{key} must be an integer")
    if not lo <= value <= hi:
        raise _fail(source, f"{key}={value} is outside [{lo}, {hi}]")
    return value


def _choice(source: str, key: str, value: Any, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise _fail(source, f"{key}={value!r}; allowed: {', '.join(allowed)}")
    return str(value)


def _unknown(source: str, section: str, raw: dict[str, Any], allowed: set[str]) -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise _fail(source, f"unknown key(s) in {section}: {', '.join(extra)}")


def parse_preset(raw: Any, source: str) -> Preset:
    top = _mapping(source, "preset", raw)
    _unknown(source, "preset", top, _TOP_KEYS)
    for key in ("name", "strategy", "execution", "tempo", "risk"):
        if key not in top:
            raise _fail(source, f"missing key: {key}")
    name = top["name"]
    if not isinstance(name, str) or not name.strip():
        raise _fail(source, "name must be a non-empty string")

    strat = _mapping(source, "strategy", top["strategy"])
    sname = _choice(source, "strategy.name", strat.get("name"), tuple(STRATEGIES))
    _unknown(source, "strategy", strat, {"name"} | _STRATEGY_PARAMS[sname])
    params: dict[str, float] = {}
    for key, value in strat.items():
        if key == "name":
            continue
        if key == "sample":
            params[key] = _integer(source, f"strategy.{key}", value, 1, 50)
        else:
            lo, hi = _STRATEGY_RANGES.get(key, (0.0, 1.0))
            params[key] = _number(source, f"strategy.{key}", value, lo, hi)

    ex = _mapping(source, "execution", top["execution"])
    _unknown(source, "execution", ex, {f.name for f in fields(ExecutionSpec)})
    ex_kwargs: dict[str, Any] = {}
    for key, value in ex.items():
        path = f"execution.{key}"
        if key in ("style", "child_style"):
            allowed = STYLES if key == "style" else ("passive", "marketable")
            ex_kwargs[key] = _choice(source, path, value, allowed)
        elif key == "sweep_type":
            ex_kwargs[key] = _choice(source, path, value, tuple(SWEEP_TYPES))
        elif key == "tif":
            ex_kwargs[key] = _choice(source, path, value, ("DAY", "GTC"))
        elif key in ("offset_ticks", "cross_ticks"):
            ex_kwargs[key] = _integer(source, path, value, 0, 1000)
        elif key == "slices":
            ex_kwargs[key] = _integer(source, path, value, 1, 1000)
        elif key == "horizon_sec":
            ex_kwargs[key] = _number(source, path, value, 1.0, 86_400.0)
        else:  # visible_fraction, urgency_cross, auction_participation
            ex_kwargs[key] = _number(source, path, value, 0.0, 1.0)
    execution = ExecutionSpec(**ex_kwargs)

    tempo_raw = top["tempo"]
    if isinstance(tempo_raw, str):
        tempo = TEMPOS.get(tempo_raw)
        if tempo is None:
            raise _fail(source, f"tempo={tempo_raw!r}; built-ins: {', '.join(TEMPOS)}")
    else:
        t = _mapping(source, "tempo", tempo_raw)
        _unknown(source, "tempo", t, {f.name for f in fields(TempoSpec)})
        for key in ("decisions_per_min", "size_min", "size_max"):
            if key not in t:
                raise _fail(source, f"missing key: tempo.{key}")
        tempo = TempoSpec(
            decisions_per_min=_number(
                source, "tempo.decisions_per_min", t["decisions_per_min"], 0.01, 600.0
            ),
            size_min=_integer(source, "tempo.size_min", t["size_min"], 1, 10_000_000),
            size_max=_integer(source, "tempo.size_max", t["size_max"], 1, 10_000_000),
            size_distribution=_choice(
                source,
                "tempo.size_distribution",
                t.get("size_distribution", "balanced"),
                SIZE_DISTRIBUTIONS,
            ),
        )
        if tempo.size_min > tempo.size_max:
            raise _fail(source, "tempo.size_min must not exceed tempo.size_max")

    rk = _mapping(source, "risk", top["risk"])
    _unknown(source, "risk", rk, {f.name for f in fields(RiskSpec)})
    rk_kwargs: dict[str, Any] = {}
    for key, value in rk.items():
        path = f"risk.{key}"
        if key == "max_position":
            rk_kwargs[key] = _integer(source, path, value, 1, 100_000_000)
        elif key == "max_live_orders_per_symbol":
            rk_kwargs[key] = _integer(source, path, value, 1, 100)
        elif key == "max_order_age_sec":
            rk_kwargs[key] = _number(source, path, value, 1.0, 86_400.0)
        elif key == "stale_price_ticks":
            rk_kwargs[key] = (
                None if value is None else _integer(source, path, value, 1, 1_000_000)
            )
        elif key == "protection":
            rk_kwargs[key] = _choice(source, path, value, PROTECTIONS)
        else:  # protection_pct
            rk_kwargs[key] = _number(source, path, value, 0.001, 0.5)
    risk = RiskSpec(**rk_kwargs)

    description = top.get("description", "")
    if not isinstance(description, str):
        raise _fail(source, "description must be a string")
    return Preset(
        name=name.strip(),
        description=description.strip(),
        strategy=sname,
        strategy_params=params,
        execution=execution,
        tempo=tempo,
        risk=risk,
    )


def load_preset_file(path: Path) -> Preset:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PresetError(f"{path}: {exc.strerror or exc}") from exc
    except yaml.YAMLError as exc:
        raise PresetError(f"{path}: invalid YAML: {exc}") from exc
    return parse_preset(raw, str(path))


def builtin_presets() -> dict[str, Preset]:
    out: dict[str, Preset] = {}
    root = resources.files("edumatcher.ai_trader") / "presets"
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".yaml"):
            raw = yaml.safe_load(entry.read_text(encoding="utf-8"))
            preset = parse_preset(raw, f"built-in {entry.name}")
            out[preset.name] = preset
    return out


def get_preset(name: str) -> Preset:
    presets = builtin_presets()
    if name not in presets:
        raise PresetError(
            f"unknown preset {name!r}; built-ins: {', '.join(sorted(presets))}"
        )
    return presets[name]
