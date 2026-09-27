"""Normative parameter tiers for ``pm-mm-bot``.

This module is the single source of truth for *which* knobs exist and *where*
they may be set. Everything else — the CLI scope splitter, the YAML config
loader, the merge layer, and ``main.py`` — reads its key lists from here, so
the tiers cannot drift between the command line and the config file.

Two tiers (docs-design/EduMatcher-mm-bot-multi.md §3):

* **Tier 1 — gateway-wide.** One value for the whole process: the gateway
  identity, the two ZMQ endpoints, the session/shutdown timeouts, logging.
  There is nothing per-symbol to express for these.
* **Tier 2 — symbol-scoped.** May differ per symbol: strategy, spread, size,
  and the per-symbol timers.
"""

from __future__ import annotations

from typing import Any

from edumatcher.mm_bot.pricer import QuotePricer, available_strategies

#: Tier-2 keys, in the order they are presented to operators.
TIER2_KEYS: tuple[str, ...] = (
    "strategy",
    "gap",
    "qty",
    "max_position",
    "drift_ticks",
    "tif",
    "reissue_delay_ms",
    "heartbeat_interval_sec",
    "bootstrap_timeout_sec",
    "cancel_timeout_sec",
    "qlegs_reconcile_interval_sec",
    "initial_min",
    "initial_max",
    "retreat_ticks",
    "behind_ticks",
    "min_cover_qty",
    "fade_ticks",
    "fade_sec",
)

#: Tier-2 keys read only by the ``passive`` strategy; every other strategy
#: ignores them.
PASSIVE_KEYS: tuple[str, ...] = (
    "retreat_ticks",
    "behind_ticks",
    "min_cover_qty",
    "fade_ticks",
    "fade_sec",
)

#: Tier-1 keys settable under the config file's ``gateway:`` block.
GATEWAY_KEYS: tuple[str, ...] = (
    "label",
    "id_suffix",
    "engine_pull",
    "engine_pub",
    "startup_session_timeout_sec",
    "shutdown_timeout_sec",
)

#: Tier-1 keys settable under the config file's ``logging:`` block. The YAML
#: names are deliberately shorter than the CLI's (``level`` not ``log_level``)
#: because the block already says "logging"; LOGGING_KEY_TO_DEST maps them
#: back to the argparse destinations.
LOGGING_KEYS: tuple[str, ...] = ("level", "target", "file", "failover_timeout_sec")

LOGGING_KEY_TO_DEST: dict[str, str] = {
    "level": "log_level",
    "target": "log_target",
    "file": "log_file",
    "failover_timeout_sec": "log_failover_timeout",
}

TIER2_DEFAULTS: dict[str, Any] = {
    "strategy": "symmetric",
    "gap": 0.10,
    "qty": 500,
    "max_position": None,
    "drift_ticks": 3,
    "tif": "DAY",
    "reissue_delay_ms": 200,
    "heartbeat_interval_sec": 5.0,
    "bootstrap_timeout_sec": 1.0,
    "cancel_timeout_sec": 1.0,
    "qlegs_reconcile_interval_sec": 15.0,
    "initial_min": None,
    "initial_max": None,
    # passive strategy (docs/user-guide/100-mm-bot.md, "The passive strategy")
    "retreat_ticks": 5,
    "behind_ticks": 1,
    "min_cover_qty": 1,
    "fade_ticks": 2,
    "fade_sec": 3.0,
}

GATEWAY_DEFAULTS: dict[str, Any] = {
    "label": None,
    "id_suffix": "01",
    "engine_pull": "tcp://127.0.0.1:5555",
    "engine_pub": "tcp://127.0.0.1:5556",
    "startup_session_timeout_sec": 5.0,
    "shutdown_timeout_sec": 2.0,
}

TIF_CHOICES: tuple[str, ...] = ("DAY", "GTC")
LOG_TARGET_CHOICES: tuple[str, ...] = ("server", "stdout", "file")
LOG_LEVEL_CHOICES: tuple[str, ...] = (
    "CRITICAL",
    "ERROR",
    "WARNING",
    "INFO",
    "DEBUG",
)


def _as_int(where: str, key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where}{key} must be an integer (got {value!r})")
    return value


def _as_float(where: str, key: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}{key} must be a number (got {value!r})")
    return float(value)


def _as_str(where: str, key: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}{key} must be a non-empty string (got {value!r})")
    return value.strip()


def validate_symbol_params(symbol: str, values: dict[str, Any]) -> dict[str, Any]:
    """Type-check and range-check one symbol's fully merged Tier-2 values.

    Returns the normalised values (``tif`` upper-cased, numbers coerced).
    Raises ``ValueError`` whose message names the symbol, so an operator
    reading a failure from a ten-symbol config knows which block to fix.
    """
    where = f"[{symbol}] "
    out = dict(values)

    strategy = _as_str(where, "strategy", out["strategy"])
    if strategy not in available_strategies():
        allowed = ", ".join(available_strategies())
        raise ValueError(f"{where}unknown strategy {strategy!r} (allowed: {allowed})")
    out["strategy"] = strategy

    gap = _as_float(where, "gap", out["gap"])
    if gap <= 0:
        raise ValueError(f"{where}gap must be positive (got {gap})")
    out["gap"] = gap

    qty = _as_int(where, "qty", out["qty"])
    if qty <= 0:
        raise ValueError(f"{where}qty must be positive (got {qty})")
    out["qty"] = qty

    drift_ticks = _as_int(where, "drift_ticks", out["drift_ticks"])
    if drift_ticks <= 0:
        raise ValueError(f"{where}drift_ticks must be positive (got {drift_ticks})")
    out["drift_ticks"] = drift_ticks

    tif = _as_str(where, "tif", out["tif"]).upper()
    if tif not in TIF_CHOICES:
        raise ValueError(
            f"{where}tif must be one of {', '.join(TIF_CHOICES)} (got {tif!r})"
        )
    out["tif"] = tif

    reissue_delay_ms = _as_int(where, "reissue_delay_ms", out["reissue_delay_ms"])
    if reissue_delay_ms < 0:
        raise ValueError(
            f"{where}reissue_delay_ms must be non-negative (got {reissue_delay_ms})"
        )
    out["reissue_delay_ms"] = reissue_delay_ms

    for key in (
        "heartbeat_interval_sec",
        "bootstrap_timeout_sec",
        "cancel_timeout_sec",
        "qlegs_reconcile_interval_sec",
    ):
        seconds = _as_float(where, key, out[key])
        if seconds <= 0:
            raise ValueError(f"{where}{key} must be positive (got {seconds})")
        out[key] = seconds

    max_position = out["max_position"]
    if max_position is not None:
        max_position = _as_int(where, "max_position", max_position)
        if max_position <= 0:
            raise ValueError(
                f"{where}max_position must be positive (got {max_position})"
            )
        out["max_position"] = max_position
    if strategy == "inventory_skew" and max_position is None:
        raise ValueError(
            f"{where}max_position is required when strategy inventory_skew "
            "is selected"
        )
    if strategy != "inventory_skew" and max_position is not None:
        raise ValueError(
            f"{where}max_position is only meaningful with strategy "
            f"inventory_skew (got strategy {strategy})"
        )

    for key, minimum in (
        ("retreat_ticks", 0),
        ("behind_ticks", 1),
        ("min_cover_qty", 1),
        ("fade_ticks", 0),
    ):
        count = _as_int(where, key, out[key])
        if count < minimum:
            raise ValueError(f"{where}{key} must be >= {minimum} (got {count})")
        out[key] = count

    fade_sec = _as_float(where, "fade_sec", out["fade_sec"])
    if fade_sec < 0:
        raise ValueError(f"{where}fade_sec must be non-negative (got {fade_sec})")
    out["fade_sec"] = fade_sec

    for key in ("initial_min", "initial_max"):
        if out[key] is not None:
            out[key] = _as_float(where, key, out[key])
    try:
        QuotePricer.validate_bootstrap_range(out["initial_min"], out["initial_max"])
    except ValueError as exc:
        raise ValueError(f"{where}{exc}") from None

    return out
