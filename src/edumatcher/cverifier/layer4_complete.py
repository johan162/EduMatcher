"""Layer 4 — Completeness and advisory checks (C001–C013)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from edumatcher.cverifier.helpers import gateway_ids_by_role
from edumatcher.cverifier.models import CheckResult, Severity

_DEFAULT_SNAPSHOT_INTERVAL_SEC = 0.5


def check(raw: dict[str, Any], path: Path) -> list[CheckResult]:  # noqa: ARG001
    """Run Layer 4 completeness checks."""
    results: list[CheckResult] = []
    _check_reference_prices(raw, results)
    _check_collar_completeness(raw, results)
    _check_cb_completeness(raw, results)
    _check_mm_obligation_completeness(raw, results)
    _check_snapshot_interval(raw, results)
    _check_index_constituents_prices(raw, results)
    _check_sessions_completeness(raw, results)
    _check_unused_risk_levels(raw, results)
    _check_index_paths(raw, results)
    return results


# ---------------------------------------------------------------------------
# C001 / C002 — Reference prices
# ---------------------------------------------------------------------------


def _check_reference_prices(raw: dict[str, Any], results: list[CheckResult]) -> None:
    symbols = raw.get("symbols", {})
    if not isinstance(symbols, dict):
        return

    any_has_price = False
    for sym_raw, cfg in symbols.items():
        sym = str(sym_raw).upper()
        if not isinstance(cfg, dict):
            cfg = {}
        has_buy = cfg.get("last_buy_price") is not None
        has_sell = cfg.get("last_sell_price") is not None
        if has_buy or has_sell:
            any_has_price = True
        # C002: only one price set
        if has_buy ^ has_sell:
            results.append(
                CheckResult(
                    code="C002",
                    severity=Severity.INFO,
                    message=(
                        f"Symbol '{sym}': only one of last_buy_price / last_sell_price is set."
                    ),
                    suggestion=(
                        "The engine uses whichever is present; consider setting both "
                        "for a more accurate midpoint reference."
                    ),
                    path=f"symbols.{sym}",
                )
            )

    # C001: no symbol has any reference price
    if not any_has_price and symbols:
        results.append(
            CheckResult(
                code="C001",
                severity=Severity.WARN,
                message="No symbol has a reference price (last_buy_price / last_sell_price).",
                suggestion=(
                    "Price collars, circuit breakers, and MM obligation checks all depend "
                    "on a reference price. Populate at least one of these per symbol "
                    "before starting the engine."
                ),
                path="symbols",
            )
        )


# ---------------------------------------------------------------------------
# C003 — Collars enforced but none configured
# ---------------------------------------------------------------------------


def _check_collar_completeness(raw: dict[str, Any], results: list[CheckResult]) -> None:
    enforce_collars = raw.get("enforce_collars", True)
    if not enforce_collars:
        return

    rc = raw.get("risk_controls", {})
    has_collar = False
    if isinstance(rc, dict):
        levels = rc.get("levels", {})
        if isinstance(levels, dict):
            for level_cfg in levels.values():
                if isinstance(level_cfg, dict) and level_cfg.get("collar"):
                    has_collar = True
                    break

    # Also check inline collars on symbols
    if not has_collar:
        symbols = raw.get("symbols", {})
        if isinstance(symbols, dict):
            for cfg in symbols.values():
                if isinstance(cfg, dict) and cfg.get("collar"):
                    has_collar = True
                    break

    if not has_collar:
        results.append(
            CheckResult(
                code="C003",
                severity=Severity.INFO,
                message=(
                    "enforce_collars is true but no symbol has an effective collar "
                    "(no risk_controls levels and no inline collar)."
                ),
                suggestion=(
                    "All orders will pass the collar check. Add a risk_controls.default_level "
                    "collar or set enforce_collars: false."
                ),
                path="risk_controls",
            )
        )


# ---------------------------------------------------------------------------
# C004 — CB enforced but no levels configured
# ---------------------------------------------------------------------------


def _check_cb_completeness(raw: dict[str, Any], results: list[CheckResult]) -> None:
    enforce_cb = raw.get("enforce_circuit_breakers", True)
    if not enforce_cb:
        return

    cb_defaults = raw.get("circuit_breaker_defaults")
    has_cb = isinstance(cb_defaults, dict) and bool(cb_defaults.get("levels"))
    if not has_cb:
        results.append(
            CheckResult(
                code="C004",
                severity=Severity.INFO,
                message=(
                    "enforce_circuit_breakers is true but circuit_breaker_defaults is "
                    "absent and no circuit breaker levels are defined."
                ),
                suggestion=(
                    "The built-in defaults (L1=7%, L2=13%, L3=20%) will be used. "
                    "Explicitly add circuit_breaker_defaults if you want different thresholds."
                ),
                path="circuit_breaker_defaults",
            )
        )


# ---------------------------------------------------------------------------
# C005 / C006 — MM obligation defaults
# ---------------------------------------------------------------------------


def _check_mm_obligation_completeness(
    raw: dict[str, Any], results: list[CheckResult]
) -> None:
    mm_gateways = gateway_ids_by_role(raw, "MARKET_MAKER")
    if not mm_gateways:
        return

    mm_defaults = raw.get("mm_obligation_defaults")
    if mm_defaults is None:
        gw = mm_gateways[0]
        results.append(
            CheckResult(
                code="C005",
                severity=Severity.WARN,
                message=(
                    f"MARKET_MAKER gateway '{gw}' is configured but mm_obligation_defaults "
                    "is absent."
                ),
                suggestion=(
                    "MM obligations will use built-in defaults (spread=10 ticks, qty=100). "
                    "Add mm_obligation_defaults if you want to enforce specific requirements."
                ),
                path="mm_obligation_defaults",
            )
        )
        return

    if isinstance(mm_defaults, dict):
        enforce = mm_defaults.get("enforce_mm_obligation", False)
        if not enforce:
            results.append(
                CheckResult(
                    code="C006",
                    severity=Severity.WARN,
                    message=(
                        "mm_obligation_defaults.enforce_mm_obligation is false. "
                        "Market-maker obligations are defined but not enforced."
                    ),
                    suggestion=(
                        "Set enforce_mm_obligation: true to activate enforcement."
                    ),
                    path="mm_obligation_defaults.enforce_mm_obligation",
                )
            )


# ---------------------------------------------------------------------------
# C007 / C012 — Snapshot interval
# ---------------------------------------------------------------------------


def _check_snapshot_interval(raw: dict[str, Any], results: list[CheckResult]) -> None:
    engine_tuning = raw.get("engine_tuning")
    path = "snapshot_interval_sec"
    if isinstance(engine_tuning, dict) and "snapshot_interval_sec" in engine_tuning:
        snap = engine_tuning.get(
            "snapshot_interval_sec", _DEFAULT_SNAPSHOT_INTERVAL_SEC
        )
        path = "engine_tuning.snapshot_interval_sec"
    else:
        snap = raw.get("snapshot_interval_sec", _DEFAULT_SNAPSHOT_INTERVAL_SEC)
    try:
        snap_f = float(snap)
    except (TypeError, ValueError):
        return

    if math.isclose(snap_f, _DEFAULT_SNAPSHOT_INTERVAL_SEC, rel_tol=0.0, abs_tol=1e-9):
        results.append(
            CheckResult(
                code="C007",
                severity=Severity.INFO,
                message=(
                    f"snapshot_interval_sec is at the default of {_DEFAULT_SNAPSHOT_INTERVAL_SEC} seconds."
                ),
                suggestion=(
                    "This is suitable for most deployments. Consider lowering for "
                    "latency-sensitive setups or raising for high-symbol-count configs."
                ),
                path=path,
            )
        )

    symbols = raw.get("symbols", {})
    n_symbols = len(symbols) if isinstance(symbols, dict) else 0
    if n_symbols > 20 and snap_f < 0.2:
        results.append(
            CheckResult(
                code="C012",
                severity=Severity.WARN,
                message=(
                    f"{n_symbols} symbols are defined with snapshot_interval_sec={snap_f}."
                ),
                suggestion=(
                    "At high symbol counts, very short snapshot intervals can generate "
                    "high ZMQ publish rates. Consider raising snapshot_interval_sec to 0.5 or higher."
                ),
                path=path,
            )
        )


# ---------------------------------------------------------------------------
# C008 — Index constituent reference prices
# ---------------------------------------------------------------------------


def _check_index_constituents_prices(
    raw: dict[str, Any], results: list[CheckResult]
) -> None:
    indices = raw.get("indices")
    if not isinstance(indices, list):
        return

    symbols = raw.get("symbols", {})
    if not isinstance(symbols, dict):
        return

    for idx in indices:
        if not isinstance(idx, dict):
            continue
        idx_id = str(idx.get("id", "?"))
        constituents = idx.get("constituents") or []
        if not isinstance(constituents, list):
            continue
        for sym_raw in constituents:
            sym = str(sym_raw).upper()
            sym_cfg = symbols.get(sym_raw) or symbols.get(sym)
            if not isinstance(sym_cfg, dict):
                continue
            has_price = (
                sym_cfg.get("last_buy_price") is not None
                or sym_cfg.get("last_sell_price") is not None
            )
            if not has_price:
                results.append(
                    CheckResult(
                        code="C008",
                        severity=Severity.WARN,
                        message=(
                            f"Index '{idx_id}' constituent '{sym}' has no reference price."
                        ),
                        suggestion=(
                            "pm-index requires at least one of last_buy_price / last_sell_price "
                            "to compute the initial index divisor."
                        ),
                        path=f"symbols.{sym}",
                    )
                )


# ---------------------------------------------------------------------------
# C009 — No sessions and no schedule (info)
# ---------------------------------------------------------------------------


def _check_sessions_completeness(
    raw: dict[str, Any], results: list[CheckResult]
) -> None:
    sessions_enabled = bool(raw.get("sessions_enabled", False))
    schedule = raw.get("schedule")
    if not sessions_enabled and not isinstance(schedule, dict):
        results.append(
            CheckResult(
                code="C009",
                severity=Severity.INFO,
                message=(
                    "sessions_enabled is false and no schedule is configured. "
                    "The exchange will start in CONTINUOUS state immediately."
                ),
                suggestion=(
                    "This is the expected setup for simple or always-on deployments. "
                    "No action required unless you want session-based trading phases."
                ),
                path="sessions_enabled",
            )
        )


# ---------------------------------------------------------------------------
# C011 — Unused risk levels
# ---------------------------------------------------------------------------


def _check_unused_risk_levels(raw: dict[str, Any], results: list[CheckResult]) -> None:
    rc = raw.get("risk_controls", {})
    if not isinstance(rc, dict):
        return
    levels = rc.get("levels", {})
    if not isinstance(levels, dict) or not levels:
        return

    defined = {str(k).strip().upper() for k in levels}
    used: set[str] = set()

    # default_level
    default_level = rc.get("default_level")
    if default_level:
        used.add(str(default_level).strip().upper())

    # per-symbol levels
    symbols = raw.get("symbols", {})
    if isinstance(symbols, dict):
        for cfg in symbols.values():
            if isinstance(cfg, dict) and cfg.get("level"):
                used.add(str(cfg["level"]).strip().upper())

    for level_name in defined:
        if level_name not in used:
            results.append(
                CheckResult(
                    code="C011",
                    severity=Severity.INFO,
                    message=(
                        f"risk_controls.levels.{level_name} is defined but no symbol uses it."
                    ),
                    suggestion=(
                        "If this level is not needed, remove it to keep the config tidy."
                    ),
                    path=f"risk_controls.levels.{level_name}",
                )
            )


# ---------------------------------------------------------------------------
# C013 — Index path parent directories
# ---------------------------------------------------------------------------


def _check_index_paths(raw: dict[str, Any], results: list[CheckResult]) -> None:
    indices = raw.get("indices")
    if not isinstance(indices, list):
        return

    for idx in indices:
        if not isinstance(idx, dict):
            continue
        idx_id = str(idx.get("id", "?"))
        for path_field in ("history_file", "state_file"):
            val = idx.get(path_field)
            if not val or not isinstance(val, str):
                continue
            parent = Path(val).parent
            if not parent.exists() and str(parent) not in (".", ""):
                results.append(
                    CheckResult(
                        code="C013",
                        severity=Severity.WARN,
                        message=(
                            f"Index '{idx_id}': {path_field} path '{val}' is under "
                            f"a directory that may not exist at startup."
                        ),
                        suggestion=(
                            "Create the directory before starting pm-index or "
                            "use an existing path."
                        ),
                        path=f"indices[id={idx_id}].{path_field}",
                    )
                )
