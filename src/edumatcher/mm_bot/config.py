"""Optional YAML config-file support for ``pm-mm-bot``.

A config file lets a bot's full parameter set — symbol, strategy, gap,
timeouts, and so on — live in a version-controlled file instead of a long
CLI invocation. Every key mirrors a ``main.py`` CLI flag by its long-form
name with dashes replaced by underscores (e.g. ``--drift-ticks`` ->
``drift_ticks``); an explicit CLI flag always overrides the same key from
the file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Keys the config file may set — every one mirrors an existing CLI flag's
# argparse ``dest`` name and is applied as an argparse default, so an
# unrecognized key is almost certainly a typo rather than a new feature.
_ALLOWED_KEYS = {
    "symbol",
    "symbols",
    "label",
    "id_suffix",
    "strategy",
    "gap",
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


def load_config_file(path: Path) -> dict[str, Any]:
    """Load and validate a ``pm-mm-bot`` YAML config file.

    Returns a dict of argparse-default overrides. Raises ``ValueError`` if
    the file cannot be parsed, is not a mapping, or contains an unknown key.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"config file {path} is not valid YAML: {exc}") from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"config file {path} must contain a YAML mapping")

    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise ValueError(
            f"config file {path} has unknown key(s): {', '.join(sorted(unknown))}"
        )

    if "symbols" in raw:
        raw["symbols"] = _normalize_symbols_value(raw["symbols"], path)

    return raw


def _normalize_symbols_value(value: Any, path: Path) -> str:
    """Coerce a config file's ``symbols`` key to the CLI's comma-string form.

    ``main.py`` treats ``args.symbols`` as a single comma-separated string
    (matching ``pm-ai-trader --symbols``, and identical whether it came from
    ``--symbols`` on the command line or from this file) so this is the one
    place a YAML-native ``symbols: [AAPL, MSFT]`` list gets flattened to
    that shape; a plain ``symbols: AAPL,MSFT`` string is accepted as-is.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ",".join(value)
    raise ValueError(
        f"config file {path}: 'symbols' must be a comma-separated string "
        "or a list of strings"
    )
