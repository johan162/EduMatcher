"""Build the plain-English risk summary from the raw YAML dict."""

from __future__ import annotations

from typing import Any

from edumatcher.cverifier.models import RiskSummary
from edumatcher.engine.config_loader import EngineConfig
from edumatcher.models.participant import ParticipantRole

_DEFAULT_CB_LEVELS = {
    "L1": {"price_shift_pct": 0.07, "halt_duration_ns": 300_000_000_000},
    "L2": {"price_shift_pct": 0.13, "halt_duration_ns": 900_000_000_000},
    "L3": {"price_shift_pct": 0.20, "halt_duration_ns": None},
}
_NS_PER_MIN = 60_000_000_000

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri")
_WEEKEND_KEYS = ("sat", "sun")


def _summarize_schedule(schedule: dict[str, Any]) -> str:
    """One-line summary of which days have a schedule, for the risk report.

    Reads the raw (possibly invalid) YAML the same way the rest of this
    module does -- this is a best-effort summary for a human, not
    validation, so it tolerates a malformed block rather than erroring (the
    cverifier checks in layer3_semantic are what actually validates it).
    """
    has_weekdays = isinstance(schedule.get("weekdays"), dict)
    has_weekend = isinstance(schedule.get("weekend"), dict)
    scheduled_days = sum(
        1
        for key in (*_WEEKDAY_KEYS, *_WEEKEND_KEYS)
        if isinstance(schedule.get(key), dict)
        or (has_weekdays and key in _WEEKDAY_KEYS)
        or (has_weekend and key in _WEEKEND_KEYS)
    )
    parts = [f"{scheduled_days} of 7 days scheduled"]
    if isinstance(schedule.get("holidays"), dict):
        parts.append("holidays overridden")
    return ", ".join(parts)


def _pct(fraction: float) -> str:
    """A fraction as a percentage, without rounding 0.025 to "2%"."""
    return f"{fraction * 100:.4f}".rstrip("0").rstrip(".") + "%"


def _duration(halt_ns: int | None) -> str:
    if halt_ns is None:
        return "rest-of-day"
    if halt_ns % _NS_PER_MIN == 0:
        return f"{halt_ns // _NS_PER_MIN} min"
    return f"{halt_ns / 1_000_000_000:g} s"


def _per_symbol(items: list[tuple[str, str]], n_symbols: int) -> str:
    """``k of N symbols (AAPL, MSFT: <setting>; 40 symbols: <setting>)``.

    Symbols sharing a setting are grouped; a group of more than three is
    counted rather than listed.
    """
    groups: dict[str, list[str]] = {}
    for symbol, setting in items:
        groups.setdefault(setting, []).append(symbol)
    parts = [
        f"{', '.join(syms) if len(syms) <= 3 else f'{len(syms)} symbols'}: {setting}"
        for setting, syms in groups.items()
    ]
    return f"{len(items)} of {n_symbols} symbols ({'; '.join(parts)})"


def _apply_engine(summary: RiskSummary, engine: EngineConfig) -> None:
    """Replace the collar, breaker and MM lines with what the engine applies.

    Collars and breakers are per symbol after the loader has merged levels,
    defaults and inline blocks. MM enforcement follows the engine's
    precedence for each market maker and symbol: gateway+symbol policy,
    then global symbol policy, then the participant's own flag (which
    already defaults to ``mm_obligation_defaults``).
    """
    symbols = sorted(engine.symbols)

    def collar_setting(sym: str) -> str | None:
        cfg = engine.symbols[sym]
        if cfg.collar is None:
            return None
        setting = (
            f"static {_pct(cfg.collar.static_band_pct)}, "
            f"dynamic {_pct(cfg.collar.dynamic_band_pct)}"
        )
        # The engine applies a collar only when it starts with a reference
        # price; without one in the file it depends on a previous run.
        if cfg.last_buy_price is None and cfg.last_sell_price is None:
            setting += ", no reference price in the file"
        return setting

    collared = [
        (sym, setting)
        for sym in symbols
        if (setting := collar_setting(sym)) is not None
    ]
    breakers = [
        (
            sym,
            ", ".join(
                f"{lvl.name}={_pct(lvl.price_shift_pct)} "
                f"({_duration(lvl.halt_duration_ns)})"
                for lvl in cb.levels
            ),
        )
        for sym in symbols
        if (cb := engine.symbols[sym].circuit_breaker) is not None
    ]
    summary.collared_symbols = [sym for sym, _ in collared]
    summary.circuit_breaker_symbols = [sym for sym, _ in breakers]
    summary.collars_configured = bool(collared)
    summary.circuit_breakers_configured = bool(breakers)
    if not summary.collars_enforced:
        summary.collar_description = "disabled"
    elif collared:
        summary.collar_description = _per_symbol(collared, len(symbols))
    else:
        summary.collar_description = "enabled but no collar configured ⚠"
    if not summary.circuit_breakers_enforced:
        summary.cb_description = "disabled"
    elif breakers:
        summary.cb_description = _per_symbol(breakers, len(symbols))
    else:
        summary.cb_description = "enabled but no circuit breaker configured ⚠"

    gateways: list[str] = []
    descriptions: list[str] = []
    for gw_id, participant in engine.participants.items():
        if participant.role is not ParticipantRole.MARKET_MAKER:
            continue
        enforced = 0
        for sym in symbols:
            policy = participant.mm_obligation_policies.get(
                sym
            ) or engine.global_symbol_mm_obligation_policies.get(sym)
            if (
                policy.enforce_mm_obligation
                if policy is not None
                else participant.enforce_mm_obligation
            ):
                enforced += 1
        if enforced:
            gateways.append(gw_id)
            descriptions.append(
                gw_id
                if enforced == len(symbols)
                else f"{gw_id} on {enforced} of {len(symbols)} symbols"
            )
    summary.mm_obligation_gateways = gateways
    summary.mm_obligations_enforced = bool(gateways)
    summary.mm_description = ", ".join(descriptions)
    summary.loaded = True


def build(raw: dict[str, Any], engine: EngineConfig | None = None) -> RiskSummary:
    """The Risk Summary for *raw*.

    With *engine* (the loader's EngineConfig for the same file) the collar,
    circuit-breaker and MM lines state what the engine applies, per symbol.
    Without it, they are a best-effort reading of the YAML.
    """
    summary = RiskSummary()

    # Symbols
    symbols = raw.get("symbols", {})
    if isinstance(symbols, dict):
        summary.symbols = sorted(str(k).upper() for k in symbols)

    # Gateways
    participants = raw.get("participants", [])
    if isinstance(participants, list):
        for gw in participants:
            if isinstance(gw, dict) and gw.get("id"):
                gw_id = str(gw["id"]).strip().upper()
                role = str(gw.get("role", "TRADER")).upper()
                summary.gateways[gw_id] = role
                if role == "ADMIN" and summary.admin_gateway is None:
                    summary.admin_gateway = gw_id

    # Sessions
    summary.sessions_enabled = bool(raw.get("sessions_enabled", True))
    schedule = raw.get("schedule")
    if summary.sessions_enabled and isinstance(schedule, dict):
        summary.schedule_summary = _summarize_schedule(schedule)
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
                            except TypeError, ValueError, OverflowError:
                                pass
                        if dbp is not None:
                            try:
                                parts.append(f"dynamic={float(dbp):.0%}")
                            except TypeError, ValueError, OverflowError:
                                pass
                        if parts:
                            collar_descs.append(f"{level_name}: {', '.join(parts)}")

    if summary.collars_enforced and summary.collars_configured:
        summary.collar_description = "; ".join(collar_descs)
    elif summary.collars_enforced and not summary.collars_configured:
        summary.collar_description = "enabled but no collar configured ⚠"
    else:
        summary.collar_description = "disabled"

    # Order-size / notional caps. Read from the symbols, which is the only
    # scope that carries them — there is no level or global default.
    limit_descs: list[str] = []
    if isinstance(symbols, dict):
        for sym_name, sym_cfg in symbols.items():
            if not isinstance(sym_cfg, dict):
                continue
            limits = sym_cfg.get("order_limits")
            if not isinstance(limits, dict):
                continue
            parts = []
            qty = limits.get("max_order_qty")
            if qty is not None:
                parts.append(f"max qty {qty}")
            value = limits.get("max_order_value")
            if value is not None:
                parts.append(f"max value {value}")
            if parts:
                summary.order_limits_configured = True
                limit_descs.append(f"{str(sym_name).upper()}: {', '.join(parts)}")

    summary.order_limits_description = (
        "; ".join(limit_descs) if summary.order_limits_configured else "none configured"
    )

    # Circuit breakers
    summary.circuit_breakers_enforced = bool(raw.get("enforce_circuit_breakers", True))
    cb_defaults = raw.get("circuit_breaker_defaults")
    raw_symbols = raw.get("symbols")
    has_symbol_cb = isinstance(raw_symbols, dict) and any(
        isinstance(cfg, dict) and isinstance(cfg.get("circuit_breaker"), dict)
        for cfg in raw_symbols.values()
    )
    # The engine creates a breaker only from circuit_breaker_defaults or a
    # symbol's own circuit_breaker block; a block without levels gets the
    # built-in ladder.
    summary.circuit_breakers_configured = isinstance(cb_defaults, dict) or has_symbol_cb
    cb_levels: dict[str, Any] = _DEFAULT_CB_LEVELS
    if isinstance(cb_defaults, dict) and isinstance(cb_defaults.get("levels"), dict):
        cb_levels = cb_defaults["levels"]

    cb_parts = []
    for level_name, level_cfg in sorted(cb_levels.items()):
        if not isinstance(level_cfg, dict):
            continue
        psp = level_cfg.get("price_shift_pct")
        hd = level_cfg.get("halt_duration_ns")
        try:
            psp_str = f"{float(psp):.0%}" if psp is not None else "?"
        except TypeError, ValueError, OverflowError:
            psp_str = str(psp)
        if hd is None:
            dur_str = "rest-of-day"
        else:
            try:
                mins = int(hd) // _NS_PER_MIN
                dur_str = f"{mins} min"
            except TypeError, ValueError, OverflowError:
                dur_str = str(hd)
        cb_parts.append(f"{level_name}={psp_str} ({dur_str})")

    if summary.circuit_breakers_enforced and summary.circuit_breakers_configured:
        summary.cb_description = ", ".join(cb_parts)
    elif summary.circuit_breakers_enforced:
        summary.cb_description = "enabled but no circuit breaker configured ⚠"
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

    if engine is not None:
        _apply_engine(summary, engine)
    return summary
