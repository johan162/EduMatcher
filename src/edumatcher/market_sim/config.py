"""``market_sim.yaml``: the market model's parameters.

Deployed next to the engine configuration (``pm-config-deploy`` copies the
``market_sim.yaml`` that sits beside the source ``engine_config.yaml``), so the
engine configuration itself is untouched::

    version: 1
    seed: 1                    # one seed for the whole model
    step_sec: 1.0              # simulated seconds per model step
    overnight_fraction: 0.2    # overnight variance as a fraction of a day's
    defaults:                  # for every symbol, unless its sector or entry says otherwise
      vol: 0.30                # annual volatility
      drift: 0.05              # annual drift
      jump_rate: 0.05          # jumps per trading day
      jump_mean: 0.0           # mean log jump size
      jump_std: 0.04           # log jump size standard deviation
      beta_market: 0.5         # loading on the market factor
      beta_sector: 0.4         # loading on the sector factor
    sectors:
      TECH: {vol: 0.35, beta_market: 0.6, beta_sector: 0.45}
    symbols:
      AAPL: {sector: TECH, vol: 0.28, initial: 150.0}
    news:                      # random news; every key optional, a rate of 0 = none
      rate_symbol: 6.0         # symbol news per trading day, whole exchange
      rate_sector: 0.5
      rate_market: 0.3
      rumour_share: 0.3        # share that starts as a rumour
      rumour_confirm: 0.6      # chance a rumour is confirmed rather than retracted
      rumour_delay_min: 0.02   # trading days before a rumour resolves (uniform)
      rumour_delay_max: 0.15

A symbol of the engine configuration missing here gets the defaults (sector
``OTHER``); a symbol here that the engine does not list is an error. With no
``initial``, a symbol starts at the engine's previous close.
"""

from __future__ import annotations

import difflib
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from edumatcher.market_sim.model import SymbolParams
from edumatcher.market_sim.news import NewsConfig
from edumatcher.market_sim.sectors import PROFILES, SECTOR_OF, sector_for

SCHEMA_VERSION = 1
FILE_NAME = "market_sim.yaml"
DEFAULT_SECTOR = "OTHER"

#: parameter -> (low, high), inclusive
_RANGES: dict[str, tuple[float, float]] = {
    "vol": (0.0, 3.0),
    "drift": (-1.0, 1.0),
    "jump_rate": (0.0, 10.0),
    "jump_mean": (-1.0, 1.0),
    "jump_std": (0.0, 1.0),
    "beta_market": (0.0, 1.0),
    "beta_sector": (0.0, 1.0),
}
_TOP = {
    "version",
    "seed",
    "step_sec",
    "overnight_fraction",
    "defaults",
    "sectors",
    "symbols",
    "news",
}
_NEWS_RANGES: dict[str, tuple[float, float]] = {
    "rate_symbol": (0.0, 1000.0),
    "rate_sector": (0.0, 100.0),
    "rate_market": (0.0, 100.0),
    "rumour_share": (0.0, 1.0),
    "rumour_confirm": (0.0, 1.0),
    "rumour_delay_min": (0.0, 10.0),
    "rumour_delay_max": (0.0, 10.0),
}


class SimConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SimConfig:
    seed: int
    step_sec: float
    overnight_fraction: float
    params: dict[str, SymbolParams]
    #: explicit starting values; the rest start at the engine's previous close
    initial: dict[str, float]
    news: NewsConfig = NewsConfig()


def _unknown(where: str, keys: set[str], allowed: set[str]) -> None:
    for key in sorted(keys - allowed):
        close = difflib.get_close_matches(key, sorted(allowed), n=1)
        hint = f" (did you mean {close[0]!r}?)" if close else ""
        raise SimConfigError(f"{where}: unknown key {key!r}{hint}")


def _number(where: str, value: Any, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SimConfigError(f"{where}: must be a number, got {value!r}")
    if not lo <= value <= hi:
        raise SimConfigError(f"{where}: must lie in [{lo}, {hi}], got {value}")
    return float(value)


def _params(where: str, raw: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SimConfigError(f"{where}: must be a mapping")
    _unknown(where, set(raw), allowed)
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _RANGES:
            out[key] = _number(f"{where}.{key}", value, *_RANGES[key])
        elif key == "sector":
            if not isinstance(value, str) or not value:
                raise SimConfigError(f"{where}.sector: must be a name")
            out[key] = value.upper()
        elif key == "initial":
            out[key] = _number(f"{where}.initial", value, 1e-9, 1e12)
    return out


def load_sim_config(path: Path, engine_symbols: set[str]) -> SimConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SimConfigError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SimConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise SimConfigError(f"{path} must contain a YAML mapping")
    where = str(path)
    _unknown(where, set(raw), _TOP)
    if raw.get("version") != SCHEMA_VERSION:
        raise SimConfigError(f"{where}: version must be {SCHEMA_VERSION}")
    seed = raw.get("seed", 1)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise SimConfigError(f"{where}: seed must be an integer >= 0")
    step_sec = _number(f"{where}: step_sec", raw.get("step_sec", 1.0), 0.01, 60.0)
    overnight = _number(
        f"{where}: overnight_fraction", raw.get("overnight_fraction", 0.2), 0.0, 5.0
    )
    defaults = _params(f"{where}: defaults", raw.get("defaults", {}), set(_RANGES))
    sectors_raw = raw.get("sectors", {})
    if not isinstance(sectors_raw, dict):
        raise SimConfigError(f"{where}: sectors must be a mapping")
    sectors = {
        str(name).upper(): _params(f"{where}: sectors.{name}", body, set(_RANGES))
        for name, body in sectors_raw.items()
    }
    symbols_raw = raw.get("symbols", {})
    if not isinstance(symbols_raw, dict):
        raise SimConfigError(f"{where}: symbols must be a mapping")
    unknown = sorted(
        str(s).upper() for s in symbols_raw if str(s).upper() not in engine_symbols
    )
    if unknown:
        raise SimConfigError(
            f"{where}: symbol(s) not in the engine configuration: {', '.join(unknown)}"
        )
    entries = {
        str(sym).upper(): _params(
            f"{where}: symbols.{sym}", body or {}, set(_RANGES) | {"sector", "initial"}
        )
        for sym, body in symbols_raw.items()
    }
    params: dict[str, SymbolParams] = {}
    initial: dict[str, float] = {}
    for sym in sorted(engine_symbols):
        entry = entries.get(sym, {})
        sector = entry.get("sector", DEFAULT_SECTOR)
        merged = {**defaults, **sectors.get(sector, {}), **entry}
        merged.pop("sector", None)
        start = merged.pop("initial", None)
        try:
            params[sym] = SymbolParams(sector=sector, **merged)
        except ValueError as exc:
            raise SimConfigError(f"{where}: {sym}: {exc}") from exc
        if start is not None:
            initial[sym] = start
    news_raw = raw.get("news", {})
    if not isinstance(news_raw, dict):
        raise SimConfigError(f"{where}: news must be a mapping")
    _unknown(f"{where}: news", set(news_raw), set(_NEWS_RANGES))
    news = NewsConfig(
        **{
            k: _number(f"{where}: news.{k}", v, *_NEWS_RANGES[k])
            for k, v in news_raw.items()
        }
    )
    if news.rumour_delay_min > news.rumour_delay_max:
        raise SimConfigError(f"{where}: news.rumour_delay_min exceeds rumour_delay_max")
    return SimConfig(int(seed), step_sec, overnight, params, initial, news)


def load_sectors(path: Path) -> dict[str, frozenset[str]]:
    """Sector membership from a deployed ``market_sim.yaml`` (empty without
    one): which symbols a SECTOR headline is about. Nothing secret."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, set[str]] = {}
    symbols = raw.get("symbols") if isinstance(raw, dict) else None
    for sym, body in (symbols or {}).items():
        if isinstance(body, dict) and isinstance(body.get("sector"), str):
            out.setdefault(body["sector"].upper(), set()).add(str(sym).upper())
    return {k: frozenset(v) for k, v in out.items()}


def generate_sim_config(engine_symbols: list[str], seed: int = 1) -> str:
    """A plausible ``market_sim.yaml`` for these symbols: each in its sector,
    with the sector's betas and a volatility spread around the sector's."""
    unknown = 0
    lines = [
        "# Generated by pm-market-sim --init. Edit freely; see the operator guide.",
        "version: 1",
        f"seed: {seed}",
        "step_sec: 1.0",
        "overnight_fraction: 0.2",
        "defaults: {vol: 0.30, drift: 0.05, jump_rate: 0.05, jump_mean: 0.0, "
        "jump_std: 0.04, beta_market: 0.5, beta_sector: 0.4}",
        "sectors:",
    ]
    for name, p in sorted(PROFILES.items()):
        lines.append(
            f"  {name}: {{vol: {p.vol}, beta_market: {p.beta_market}, "
            f"beta_sector: {p.beta_sector}}}"
        )
    lines.append("symbols:")
    for sym in sorted(engine_symbols):
        sector = sector_for(sym, unknown)
        if sym.upper() not in SECTOR_OF:
            unknown += 1
        # a fixed spread of 0.8x-1.25x around the sector's volatility
        spread = 0.8 + 0.45 * (zlib.crc32(sym.encode()) / 2**32)
        vol = round(PROFILES[sector].vol * spread, 3)
        lines.append(f"  {sym}: {{sector: {sector}, vol: {vol}}}")
    return "\n".join(lines) + "\n"
