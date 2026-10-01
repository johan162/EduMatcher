"""YAML config-file support for ``pm-mm-bot``.

Two file shapes are accepted.

**Schema version 1** (``version: 1``) is the structured form. It separates
gateway-wide settings from per-symbol ones, so one file can say "AAPL quotes
0.10 wide in 500 lots, TSLA quotes 0.50 wide in 100 lots with inventory
skew"::

    version: 1
    gateway:
      label: TECH
      id_suffix: "01"
    defaults:
      gap: 0.10
      qty: 500
    symbols:
      AAPL: {}
      TSLA:
        gap: 0.50
        strategy: inventory_skew
        max_position: 5000

**The legacy flat form** is the original shape: one mapping of CLI flag
names (dashes as underscores), every one of them gateway-wide. It still
loads, and is reported through the same :class:`FileConfig` structure so
nothing downstream has to know which shape it came from.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from edumatcher.mm_bot.params import GATEWAY_KEYS, LOGGING_KEYS, TIER2_KEYS

SCHEMA_VERSION = 1

_V1_TOP_LEVEL_KEYS = {"version", "gateway", "logging", "defaults", "symbols"}

# CLI-style logging dest names, recognised only to give a better error than
# "unknown key" when they turn up outside the ``logging:`` block.
_LOGGING_DEST_HINTS = {"log_level", "log_target", "log_file", "log_failover_timeout"}

# Keys the *legacy flat* config file may set — every one mirrors an existing
# CLI flag's argparse ``dest`` name and is applied as an argparse default, so
# an unrecognized key is almost certainly a typo rather than a new feature.
_ALLOWED_KEYS = {
    "symbol",
    "symbols",
    "label",
    "id_suffix",
    "strategy",
    "gap",
    "max_position",
    "qty",
    "drift_ticks",
    "reissue_delay_ms",
    "tif",
    "heartbeat_interval_sec",
    "startup_session_timeout_sec",
    "bootstrap_timeout_sec",
    "cancel_timeout_sec",
    "shutdown_timeout_sec",
    "qlegs_reconcile_interval_sec",
    "initial_min",
    "initial_max",
    "engine_pull",
    "engine_pub",
}


@dataclass(frozen=True)
class FileConfig:
    """A loaded config file, normalised to the two-tier shape.

    ``symbols`` maps SYMBOL -> that symbol's Tier-2 overrides, in file
    order. A legacy flat file lands its Tier-2 keys in ``defaults`` and
    contributes empty override blocks, which is why nothing downstream
    needs to branch on the file's shape.
    """

    gateway: dict[str, Any] = field(default_factory=dict)
    logging: dict[str, Any] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    symbols: dict[str, dict[str, Any]] = field(default_factory=dict)


EMPTY_FILE_CONFIG = FileConfig()


def load_bot_config(path: Path, symbols_required: bool = True) -> FileConfig:
    """Load a config file in either supported shape.

    The discriminator is structural as well as declared: ``version:``, a
    ``symbols:`` mapping, or any v1-only block selects the structured
    loader. A legacy flat file has ``symbols`` as a string or list of
    strings and never has ``gateway:``/``logging:``/``defaults:``.
    """
    raw = _read_yaml_mapping(path)
    if raw is None:
        return EMPTY_FILE_CONFIG
    if _looks_like_v1(raw):
        return _load_v1(raw, path, symbols_required)
    return _from_legacy_flat(load_config_file(path))


def load_config_file(path: Path) -> dict[str, Any]:
    """Load and validate a *legacy flat* ``pm-mm-bot`` YAML config file.

    Returns a dict of argparse-default overrides. Raises ``ValueError`` if
    the file cannot be parsed, is not a mapping, or contains an unknown key.
    """
    raw = _read_yaml_mapping(path)
    if raw is None:
        return {}

    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise ValueError(
            f"config file {path} has unknown key(s): {', '.join(sorted(unknown))}"
        )

    if "symbols" in raw:
        raw["symbols"] = _normalize_symbols_value(raw["symbols"], path)

    return raw


def _read_yaml_mapping(path: Path) -> dict[str, Any] | None:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"config file {path} is not valid YAML: {exc}") from exc

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"config file {path} must contain a YAML mapping")
    return raw


def _looks_like_v1(raw: dict[str, Any]) -> bool:
    if "version" in raw:
        return True
    if isinstance(raw.get("symbols"), dict):
        return True
    return any(key in raw for key in ("gateway", "logging", "defaults"))


def _from_legacy_flat(values: dict[str, Any]) -> FileConfig:
    names: list[str] = []
    symbols_value = values.get("symbols")
    symbol_value = values.get("symbol")
    if isinstance(symbols_value, str) and symbols_value.strip():
        names = [s.strip().upper() for s in symbols_value.split(",") if s.strip()]
    elif isinstance(symbol_value, str) and symbol_value.strip():
        names = [symbol_value.strip().upper()]

    return FileConfig(
        gateway={key: values[key] for key in GATEWAY_KEYS if key in values},
        defaults={key: values[key] for key in TIER2_KEYS if key in values},
        symbols={name: {} for name in names},
    )


def _load_v1(
    raw: dict[str, Any], path: Path, symbols_required: bool = True
) -> FileConfig:
    _reject_unknown(raw, _V1_TOP_LEVEL_KEYS, path, "")

    version = raw.get("version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"config file {path}: unsupported version {version!r} "
            f"(this build understands version {SCHEMA_VERSION})"
        )

    gateway = _load_block(raw.get("gateway"), set(GATEWAY_KEYS), path, "gateway")
    if "id_suffix" in gateway and not isinstance(gateway["id_suffix"], str):
        raise ValueError(
            f"config file {path}: gateway.id_suffix must be a string — quote "
            'it (e.g. "01") so YAML does not read it as a number'
        )

    return FileConfig(
        gateway=gateway,
        logging=_load_block(raw.get("logging"), set(LOGGING_KEYS), path, "logging"),
        defaults=_load_block(raw.get("defaults"), set(TIER2_KEYS), path, "defaults"),
        symbols=(
            _load_symbols(raw.get("symbols"), path)
            if symbols_required or raw.get("symbols") is not None
            else {}
        ),
    )


def _load_symbols(raw: Any, path: Path) -> dict[str, dict[str, Any]]:
    if raw is None:
        raise ValueError(f"config file {path}: a 'symbols:' block is required")

    symbols: dict[str, dict[str, Any]] = {}
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError(
                    f"config file {path}: 'symbols' list entries must be "
                    f"non-empty strings (got {entry!r})"
                )
            symbols[entry.strip().upper()] = {}
    elif isinstance(raw, dict):
        for name, block in raw.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError(
                    f"config file {path}: symbol names must be non-empty "
                    f"strings (got {name!r})"
                )
            key = name.strip().upper()
            symbols[key] = _load_block(block, set(TIER2_KEYS), path, f"symbols.{key}")
    else:
        raise ValueError(
            f"config file {path}: 'symbols' must be a mapping of symbol "
            "blocks or a list of symbol names"
        )

    if not symbols:
        raise ValueError(f"config file {path}: 'symbols' must name at least one symbol")
    return symbols


def _load_block(
    block: Any, allowed: set[str], path: Path, where: str
) -> dict[str, Any]:
    if block is None:
        return {}
    if not isinstance(block, dict):
        raise ValueError(f"config file {path}: '{where}' must be a mapping")
    _reject_unknown(block, allowed, path, where)
    return dict(block)


def _reject_unknown(
    block: dict[str, Any], allowed: set[str], path: Path, where: str
) -> None:
    for key in block:
        if key in allowed:
            continue
        misplaced = _misplaced_hint(str(key), where)
        if misplaced is not None:
            raise ValueError(f"config file {path}: {misplaced}")
        match = difflib.get_close_matches(str(key), sorted(allowed), n=1)
        suffix = f" (did you mean '{match[0]}'?)" if match else ""
        location = f" under {where}" if where else ""
        raise ValueError(f"config file {path}: unknown key '{key}'{location}{suffix}")


def _misplaced_hint(key: str, where: str) -> str | None:
    """Point a misplaced-but-real key at its block instead of calling it unknown."""
    if where == "gateway":
        if key in TIER2_KEYS:
            return (
                f"'{key}' is a per-symbol setting; move it under 'defaults:' "
                "or into a symbol's own block"
            )
        return None
    if key in GATEWAY_KEYS:
        return f"'{key}' is a gateway-wide setting; move it under 'gateway:'"
    if key in _LOGGING_DEST_HINTS:
        return f"'{key}' is a logging setting; move it under 'logging:'"
    return None


def _normalize_symbols_value(value: Any, path: Path) -> str:
    """Coerce a legacy flat file's ``symbols`` key to the CLI's comma-string form.

    ``main.py`` treats a legacy ``symbols`` value as a single comma-separated
    string (matching ``pm-ai-trader --symbols``), so this is the one place a
    YAML-native ``symbols: [AAPL, MSFT]`` list gets flattened to that shape;
    a plain ``symbols: AAPL,MSFT`` string is accepted as-is.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ",".join(value)
    raise ValueError(
        f"config file {path}: 'symbols' must be a comma-separated string "
        "or a list of strings"
    )
