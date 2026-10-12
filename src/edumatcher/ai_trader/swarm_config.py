"""``pm-ai-swarm --swarm swarm.yaml``: the swarm in one file.

Every key is optional; a command-line flag given explicitly wins over the
file, the file over the built-in default. Unknown keys and bad values are
rejected before anything starts::

    version: 1
    agents: {prefix: AI, start: 1, count: 500}
    workers: 0                 # 0 = min(cpus - 1, ceil(count / 100))
    budget: 1000               # order actions/s for the whole swarm; 0 = presets decide
    seed: 1000                 # agent i gets seed + i
    duration: 0                # seconds; 0 = until stopped
    composition:               # preset: weight (built-in name or preset file)
      noise-retail: 40
      scalper: 10
      my-preset.yaml: 5        # relative to this file
    symbols:                   # default: every deployed symbol
      include: []
      exclude: []
      per_agent: 10            # default: just enough to cover every symbol
    alf: {host: 127.0.0.1, port: 5565}
    logging: {level: INFO, target: file, file: swarm.log, failover_timeout: 30}

Composition weights may sum to anything positive: counts are rounded by
largest remainder so they add up to exactly ``count``, and agents are
interleaved so every worker's block gets the same mix.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from edumatcher.ai_trader.preset import (
    Preset,
    PresetError,
    builtin_presets,
    load_preset_file,
)

SCHEMA_VERSION = 1
_SECTIONS: dict[str, set[str] | None] = {
    "version": None,
    "agents": {"prefix", "start", "count"},
    "workers": None,
    "budget": None,
    "seed": None,
    "duration": None,
    "composition": None,
    "symbols": {"include", "exclude", "per_agent"},
    "alf": {"host", "port"},
    "logging": {"level", "target", "file", "failover_timeout"},
}
LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")
LOG_TARGETS = ("server", "stdout", "file")


class SwarmConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SwarmFile:
    """The file's settings under the CLI's argparse dest names."""

    values: dict[str, Any]
    #: preset reference -> weight, references resolved to presets
    composition: dict[str, tuple[Preset, float]] | None
    exclude_symbols: list[str]


def _unknown(where: str, keys: set[str], allowed: set[str]) -> None:
    for key in sorted(keys - allowed):
        close = difflib.get_close_matches(key, sorted(allowed), n=1)
        hint = f" (did you mean {close[0]!r}?)" if close else ""
        raise SwarmConfigError(f"{where}: unknown key {key!r}{hint}")


def _int(where: str, value: Any, lo: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < lo:
        raise SwarmConfigError(f"{where}: must be an integer >= {lo}, got {value!r}")
    return value


def _num(where: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise SwarmConfigError(f"{where}: must be a number >= 0, got {value!r}")
    return float(value)


def _str(where: str, value: Any, choices: tuple[str, ...] = ()) -> str:
    if not isinstance(value, str) or not value:
        raise SwarmConfigError(f"{where}: must be a non-empty string, got {value!r}")
    if choices and value not in choices:
        raise SwarmConfigError(f"{where}: must be one of {', '.join(choices)}")
    return value


def _symbols(where: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise SwarmConfigError(f"{where}: must be a list of symbols")
    return [v.upper() for v in value]


def resolve_preset(ref: str, base: Path) -> Preset:
    """A built-in preset name, or a preset YAML file relative to ``base``."""
    builtin = builtin_presets()
    if ref in builtin:
        return builtin[ref]
    if ref.endswith((".yaml", ".yml")):
        return load_preset_file(base / ref)
    raise PresetError(
        f"unknown preset {ref!r}; built-ins: {', '.join(sorted(builtin))}, "
        "or a .yaml preset file"
    )


def parse_composition(
    raw: Any, where: str, base: Path
) -> dict[str, tuple[Preset, float]]:
    if not isinstance(raw, dict) or not raw:
        raise SwarmConfigError(f"{where}: must map preset -> weight")
    out: dict[str, tuple[Preset, float]] = {}
    for ref, weight in raw.items():
        w = _num(f"{where}.{ref}", weight)
        if w <= 0:
            raise SwarmConfigError(f"{where}.{ref}: weight must be > 0")
        try:
            out[str(ref)] = (resolve_preset(str(ref), base), w)
        except PresetError as exc:
            raise SwarmConfigError(f"{where}: {exc}") from exc
    return out


def parse_presets_flag(raw: str) -> dict[str, tuple[Preset, float]]:
    """``--presets a,b`` (equal weights) or ``a:2,b:3``."""
    mapping: dict[str, float] = {}
    for item in (x.strip() for x in raw.split(",")):
        if not item:
            continue
        name, _, weight = item.partition(":")
        try:
            mapping[name.strip()] = float(weight) if weight else 1.0
        except ValueError:
            raise SwarmConfigError(f"--presets: bad weight in {item!r}") from None
    return parse_composition(mapping, "--presets", Path.cwd())


def composition_counts(weights: list[float], total: int) -> list[int]:
    """Largest-remainder rounding: counts that sum to exactly ``total``."""
    s = sum(weights)
    exact = [total * w / s for w in weights]
    counts = [int(x) for x in exact]
    order = sorted(range(len(weights)), key=lambda i: (counts[i] - exact[i], i))
    for i in order[: total - sum(counts)]:
        counts[i] += 1
    return counts


def interleave(counts: list[int]) -> list[int]:
    """Smooth weighted round robin: index sequence with exactly ``counts``,
    spread evenly so any contiguous block has the same mix."""
    total = sum(counts)
    current = [0] * len(counts)
    out: list[int] = []
    for _ in range(total):
        for i, c in enumerate(counts):
            current[i] += c
        pick = max(range(len(counts)), key=lambda i: (current[i], -i))
        current[pick] -= total
        out.append(pick)
    return out


def load_swarm_config(path: Path) -> SwarmFile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SwarmConfigError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SwarmConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise SwarmConfigError(f"{path} must contain a YAML mapping")
    where = str(path)
    _unknown(where, set(raw), set(_SECTIONS))
    if raw.get("version") != SCHEMA_VERSION:
        raise SwarmConfigError(f"{where}: version must be {SCHEMA_VERSION}")
    for section, allowed in _SECTIONS.items():
        if allowed is not None and section in raw:
            if not isinstance(raw[section], dict):
                raise SwarmConfigError(f"{where}: {section} must be a mapping")
            _unknown(f"{where}: {section}", set(raw[section]), allowed)

    v: dict[str, Any] = {}
    agents = raw.get("agents", {})
    if "prefix" in agents:
        v["prefix"] = _str(f"{where}: agents.prefix", agents["prefix"]).upper()
    if "start" in agents:
        v["start_index"] = _int(f"{where}: agents.start", agents["start"], 1)
    if "count" in agents:
        v["count"] = _int(f"{where}: agents.count", agents["count"], 1)
    if "workers" in raw:
        v["workers"] = _int(f"{where}: workers", raw["workers"], 0)
    if "budget" in raw:
        v["budget"] = _num(f"{where}: budget", raw["budget"])
    if "seed" in raw:
        v["seed_base"] = _int(f"{where}: seed", raw["seed"], 0)
    if "duration" in raw:
        v["duration"] = _num(f"{where}: duration", raw["duration"])
    symbols = raw.get("symbols", {})
    if "include" in symbols:
        v["symbols"] = ",".join(
            _symbols(f"{where}: symbols.include", symbols["include"])
        )
    if "per_agent" in symbols:
        v["symbols_per_agent"] = _int(
            f"{where}: symbols.per_agent", symbols["per_agent"], 0
        )
    exclude = (
        _symbols(f"{where}: symbols.exclude", symbols["exclude"])
        if "exclude" in symbols
        else []
    )
    alf = raw.get("alf", {})
    if "host" in alf:
        v["alf_host"] = _str(f"{where}: alf.host", alf["host"])
    if "port" in alf:
        v["alf_port"] = _int(f"{where}: alf.port", alf["port"], 1)
    logging_ = raw.get("logging", {})
    if "level" in logging_:
        v["log_level"] = _str(
            f"{where}: logging.level", str(logging_["level"]).upper(), LOG_LEVELS
        )
    if "target" in logging_:
        v["log_target"] = _str(
            f"{where}: logging.target", logging_["target"], LOG_TARGETS
        )
    if "file" in logging_:
        v["log_file"] = _str(f"{where}: logging.file", logging_["file"])
    if "failover_timeout" in logging_:
        v["log_failover_timeout"] = _num(
            f"{where}: logging.failover_timeout", logging_["failover_timeout"]
        )
    composition = (
        parse_composition(raw["composition"], f"{where}: composition", path.parent)
        if "composition" in raw
        else None
    )
    return SwarmFile(v, composition, exclude)
