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

    return raw
