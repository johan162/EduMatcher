"""Build the plain-English risk summary from the raw YAML dict."""

from __future__ import annotations

from typing import Any

from edumatcher.cverifier.models import RiskSummary

_DEFAULT_CB_LEVELS = {
    "L1": {"price_shift_pct": 0.07, "halt_duration_ns": 300_000_000_000},
    "L2": {"price_shift_pct": 0.13, "halt_duration_ns": 900_000_000_000},
    "L3": {"price_shift_pct": 0.20, "halt_duration_ns": None},
}
_NS_PER_MIN = 60_000_000_000


def build(raw: dict[str, Any]) -> RiskSummary:
    summary = RiskSummary()

    # Symbols
    symbols = raw.get("symbols", {})
    if isinstance(symbols, dict):
        summary.symbols = sorted(str(k).upper() for k in symbols)

    # Gateways
    gateways_raw = raw.get("gateways", {})
    if isinstance(gateways_raw, dict):
        alf = gateways_raw.get("alf", [])
        if isinstance(alf, list):
            for gw in alf:
                if isinstance(gw, dict) and gw.get("id"):
                    gw_id = str(gw["id"]).strip().upper()
                    role = str(gw.get("role", "TRADER")).upper()
                    summary.gateways[gw_id] = role
                    if role == "ADMIN" and summary.admin_gateway is None:
                        summary.admin_gateway = gw_id

    # Sessions
    summary.sessions_enabled = bool(raw.get("sessions_enabled", False))
    schedule = raw.get("schedule")
    if summary.sessions_enabled and isinstance(schedule, dict):
        pre = schedule.get("pre_open", "?")
        cont = schedule.get("continuous_start", "?")
        close = schedule.get("closing_auction_end", "?")
        summary.schedule_summary = f"pre-open {pre}, continuous {cont}, close {close}"
    elif summary.sessions_enabled:
        summary.schedule_summary = "enabled (no schedule)"
    else:
        summary.schedule_summary = "always CONTINUOUS"

    # Collars
    summary.collars_enforced = bool(raw.get("enforce_collars", True))
    rc = raw.get("risk_controls", {})
    collar_descs: list[str] = []
    if isinstance(rc, dict):
        levels = rc.get("levels", {})
        if isinstance(levels, dict):
            for level_name, level_cfg in levels.items():
                if isinstance(level_cfg, dict):
                    collar = level_cfg.get("collar")
                    if isinstance(collar, dict):
                        summary.collars_configured = True
                        sbp = collar.get("static_band_pct")
                        dbp = collar.get("dynamic_band_pct")
                        parts = []
                        if sbp is not None:
                            try:
                                parts.append(f"static={float(sbp):.0%}")
                            except (TypeError, ValueError):
                                pass
                        if dbp is not None:
                            try:
                                parts.append(f"dynamic={float(dbp):.0%}")
                            except (TypeError, ValueError):
                                pass
                        if parts:
                            collar_descs.append(f"{level_name}: {', '.join(parts)}")

    if summary.collars_enforced and summary.collars_configured:
        summary.collar_description = "; ".join(collar_descs)
    elif summary.collars_enforced and not summary.collars_configured:
        summary.collar_description = "enabled but no collar configured ⚠"
    else:
        summary.collar_description = "disabled"

    # Circuit breakers
    summary.circuit_breakers_enforced = bool(raw.get("enforce_circuit_breakers", True))
    cb_defaults = raw.get("circuit_breaker_defaults")
    cb_levels: dict[str, Any] = {}
    if isinstance(cb_defaults, dict) and isinstance(cb_defaults.get("levels"), dict):
        cb_levels = cb_defaults["levels"]
        summary.circuit_breakers_configured = True
    else:
        cb_levels = _DEFAULT_CB_LEVELS

    cb_parts = []
    for level_name, level_cfg in sorted(cb_levels.items()):
        if not isinstance(level_cfg, dict):
            continue
        psp = level_cfg.get("price_shift_pct")
        hd = level_cfg.get("halt_duration_ns")
        try:
            psp_str = f"{float(psp):.0%}" if psp is not None else "?"
        except (TypeError, ValueError):
            psp_str = str(psp)
        if hd is None:
            dur_str = "rest-of-day"
        else:
            try:
                mins = int(hd) // _NS_PER_MIN
                dur_str = f"{mins} min"
            except (TypeError, ValueError):
                dur_str = str(hd)
        cb_parts.append(f"{level_name}={psp_str} ({dur_str})")

    if summary.circuit_breakers_enforced:
        using = "" if summary.circuit_breakers_configured else " (built-in defaults)"
        summary.cb_description = ", ".join(cb_parts) + using
    else:
        summary.cb_description = "disabled"

    # MM obligations
    mm_defaults = raw.get("mm_obligation_defaults")
    if isinstance(mm_defaults, dict):
        summary.mm_obligations_enforced = bool(
            mm_defaults.get("enforce_mm_obligation", False)
        )
    else:
        summary.mm_obligations_enforced = False

    # Indices
    indices = raw.get("indices")
    if isinstance(indices, list):
        for idx in indices:
            if isinstance(idx, dict) and idx.get("id"):
                summary.indices.append(str(idx["id"]))

    return summary
