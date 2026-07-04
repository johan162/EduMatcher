"""Layer 3 — Semantic / cross-field consistency checks (M001–M016).

This layer works directly on the raw YAML mapping so that every problem is
reported independently, even when several fields are wrong at once.  It does
not build the typed EngineConfig: the CLI only runs this layer once Layer 2
reports zero schema errors, so the raw values are already well-formed enough
to reason about.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edumatcher.cverifier.helpers import (
    all_gateway_ids,
    gateway_ids_by_role,
    symbol_cfg_by_upper_name,
)
from edumatcher.cverifier.models import CheckResult, Severity

_TIME_FIELDS = (
    "pre_open",
    "opening_auction_start",
    "continuous_start",
    "closing_auction_start",
    "closing_auction_end",
)


def check(raw: dict[str, Any], path: Path) -> list[CheckResult]:  # noqa: ARG001
    """Run Layer 3 semantic checks."""
    results: list[CheckResult] = []
    _check_mm_obligation_symbols(raw, results)
    _check_mm_seeds(raw, results)
    _check_sessions_schedule(raw, results)
    _check_enforce_flags(raw, results)
    _check_indices(raw, results)
    _check_combos(raw, results)
    _check_admin_gateway(raw, results)
    _check_post_trade_admin(raw, results)
    _check_balf_gateway_semantic(raw, results)
    _check_api_gateway_semantic(raw, results)
    return results


# ---------------------------------------------------------------------------
# MM seed checks
# ---------------------------------------------------------------------------


def _check_mm_seeds(raw: dict[str, Any], results: list[CheckResult]) -> None:
    mm_gateways = gateway_ids_by_role(raw, "MARKET_MAKER")
    all_ids = all_gateway_ids(raw)
    gateways_by_role: dict[str, str] = {}
    gateways = raw.get("gateways")
    if isinstance(gateways, dict):
        alf = gateways.get("alf")
        if isinstance(alf, list):
            for gw in alf:
                if not isinstance(gw, dict):
                    continue
                gw_id = gw.get("id")
                if not isinstance(gw_id, str) or not gw_id.strip():
                    continue
                gateways_by_role[gw_id.strip().upper()] = str(
                    gw.get("role", "TRADER")
                ).upper()

    symbols = raw.get("symbols", {})
    if not isinstance(symbols, dict):
        return

    # M003 only applies when MM obligations are actually configured.
    mm_obligation_defaults = raw.get("mm_obligation_defaults")
    mm_max_spread: int | None = None
    if isinstance(mm_obligation_defaults, dict) and mm_obligation_defaults:
        try:
            mm_max_spread = int(mm_obligation_defaults.get("mm_max_spread_ticks", 10))
        except (TypeError, ValueError):
            mm_max_spread = 10

    for sym_raw, cfg in symbols.items():
        sym = str(sym_raw).upper()
        if not isinstance(cfg, dict):
            cfg = {}

        mm_quotes = cfg.get("market_maker_quotes") or []
        if not isinstance(mm_quotes, list):
            mm_quotes = []

        # M001: MM gateway present but symbol has no seeds
        if mm_gateways and not mm_quotes:
            gw_list = ", ".join(mm_gateways)
            results.append(
                CheckResult(
                    code="M001",
                    severity=Severity.ERROR,
                    message=(
                        f"Symbol '{sym}' has no market_maker_quotes entry for "
                        f"MARKET_MAKER gateway(s) {gw_list}."
                    ),
                    suggestion=(
                        "Add a bid/ask seed quote or the engine will reject startup. "
                        "Run pm-config-gen with --seed-mm to generate placeholder seeds."
                    ),
                    path=f"symbols.{sym}.market_maker_quotes",
                )
            )

        for i, quote in enumerate(mm_quotes):
            if not isinstance(quote, dict):
                continue

            gw_id_raw = quote.get("gateway_id")
            if gw_id_raw:
                gw_id = str(gw_id_raw).strip().upper()
                # M002: seed references unknown gateway
                if gw_id not in all_ids:
                    results.append(
                        CheckResult(
                            code="M002",
                            severity=Severity.WARN,
                            message=(
                                f"Symbol '{sym}': market_maker_quotes gateway_id "
                                f"'{gw_id}' is not listed in gateways.alf."
                            ),
                            suggestion=(
                                "Either add the gateway or remove the seed entry."
                            ),
                            path=f"symbols.{sym}.market_maker_quotes[{i}].gateway_id",
                        )
                    )
                elif gw_id not in mm_gateways:
                    role = gateways_by_role.get(gw_id, "TRADER")
                    results.append(
                        CheckResult(
                            code="M020",
                            severity=Severity.ERROR,
                            message=(
                                f"Symbol '{sym}': market_maker_quotes gateway_id "
                                f"'{gw_id}' has role {role}, not MARKET_MAKER."
                            ),
                            suggestion=(
                                "Point this quote seed to a MARKET_MAKER gateway or "
                                "change the gateway role to MARKET_MAKER."
                            ),
                            path=f"symbols.{sym}.market_maker_quotes[{i}].gateway_id",
                        )
                    )

            # M003: spread exceeds MM max spread ticks
            if mm_max_spread is not None:
                bid = quote.get("bid_price")
                ask = quote.get("ask_price")
                tick_decimals = cfg.get("tick_decimals", 2)
                if bid is not None and ask is not None:
                    try:
                        spread_price = float(ask) - float(bid)
                        tick_size = 10 ** (-int(tick_decimals))
                        spread_ticks = round(spread_price / tick_size)
                        if spread_ticks > mm_max_spread:
                            results.append(
                                CheckResult(
                                    code="M003",
                                    severity=Severity.WARN,
                                    message=(
                                        f"Symbol '{sym}': market_maker_quotes[{i}] spread "
                                        f"({spread_ticks} ticks) exceeds mm_max_spread_ticks "
                                        f"({mm_max_spread})."
                                    ),
                                    suggestion=(
                                        "The seed quote would be immediately rejected. "
                                        "Narrow the spread or raise mm_max_spread_ticks."
                                    ),
                                    path=f"symbols.{sym}.market_maker_quotes[{i}]",
                                )
                            )
                    except (TypeError, ValueError):
                        pass


def _check_mm_obligation_symbols(
    raw: dict[str, Any], results: list[CheckResult]
) -> None:
    symbols = symbol_cfg_by_upper_name(raw)
    mm_defaults = raw.get("mm_obligation_defaults")
    if not isinstance(mm_defaults, dict):
        return
    sym_overrides = mm_defaults.get("symbols")
    if not isinstance(sym_overrides, dict):
        return

    for sym_raw in sym_overrides:
        sym = str(sym_raw).upper()
        if sym not in symbols:
            results.append(
                CheckResult(
                    code="M019",
                    severity=Severity.ERROR,
                    message=(
                        "mm_obligation_defaults.symbols references unknown symbol "
                        f"'{sym}'."
                    ),
                    suggestion=(
                        f"Add symbol '{sym}' under symbols, or remove the override entry."
                    ),
                    path=f"mm_obligation_defaults.symbols.{sym}",
                )
            )


# ---------------------------------------------------------------------------
# Sessions / schedule
# ---------------------------------------------------------------------------


def _check_sessions_schedule(raw: dict[str, Any], results: list[CheckResult]) -> None:
    sessions_enabled = bool(raw.get("sessions_enabled", False))
    schedule = raw.get("schedule")

    # M004: sessions enabled but no schedule
    if sessions_enabled and not isinstance(schedule, dict):
        results.append(
            CheckResult(
                code="M004",
                severity=Severity.ERROR,
                message=(
                    "sessions_enabled is true but no schedule is defined. "
                    "The engine will wait indefinitely in CLOSED state."
                ),
                suggestion=("Add a schedule section or set sessions_enabled: false."),
                path="schedule",
            )
        )

    # M005: sessions disabled but schedule present
    if not sessions_enabled and isinstance(schedule, dict):
        results.append(
            CheckResult(
                code="M005",
                severity=Severity.WARN,
                message=(
                    "A schedule section is present but sessions_enabled is false. "
                    "The schedule will be ignored."
                ),
                suggestion=(
                    "Set sessions_enabled: true or remove the schedule section."
                ),
                path="sessions_enabled",
            )
        )

    # M006: schedule times out of order
    if isinstance(schedule, dict):
        _check_schedule_order(schedule, results)


def _parse_hhmm(t: Any) -> int | None:
    """Return minutes since midnight or None on parse error."""
    if not isinstance(t, str):
        return None
    parts = t.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except ValueError:
        pass
    return None


def _check_schedule_order(schedule: dict[str, Any], results: list[CheckResult]) -> None:
    times = []
    for field in _TIME_FIELDS:
        val = schedule.get(field)
        t = _parse_hhmm(val)
        if t is not None:
            times.append((field, t, str(val)))

    for i in range(len(times) - 1):
        name_a, t_a, v_a = times[i]
        name_b, t_b, v_b = times[i + 1]
        if t_a >= t_b:
            results.append(
                CheckResult(
                    code="M006",
                    severity=Severity.WARN,
                    message=(
                        f"Schedule times are out of order: "
                        f"{name_a}={v_a} >= {name_b}={v_b}."
                    ),
                    suggestion=(
                        "Expected order: pre_open < opening_auction_start < "
                        "continuous_start < closing_auction_start < closing_auction_end."
                    ),
                    path="schedule",
                )
            )


# ---------------------------------------------------------------------------
# Enforce flags
# ---------------------------------------------------------------------------


def _check_enforce_flags(raw: dict[str, Any], results: list[CheckResult]) -> None:
    enforce_collars = raw.get("enforce_collars", True)
    enforce_cb = raw.get("enforce_circuit_breakers", True)

    rc = raw.get("risk_controls", {})
    has_collar_levels = False
    if isinstance(rc, dict):
        levels = rc.get("levels", {})
        if isinstance(levels, dict):
            for level_cfg in levels.values():
                if isinstance(level_cfg, dict) and level_cfg.get("collar"):
                    has_collar_levels = True
                    break

    # M007: enforce_collars=false but collars configured
    if not enforce_collars and has_collar_levels:
        results.append(
            CheckResult(
                code="M007",
                severity=Severity.WARN,
                message=(
                    "enforce_collars is false but risk_controls defines collar levels. "
                    "Collars are configured but inactive."
                ),
                suggestion=(
                    "Set enforce_collars: true to activate them, or remove the "
                    "risk_controls.levels collar entries."
                ),
                path="enforce_collars",
            )
        )

    cb_defaults = raw.get("circuit_breaker_defaults")
    has_cb_levels = isinstance(cb_defaults, dict) and bool(cb_defaults.get("levels"))

    # M008: enforce_circuit_breakers=false but CB configured
    if not enforce_cb and has_cb_levels:
        results.append(
            CheckResult(
                code="M008",
                severity=Severity.WARN,
                message=(
                    "enforce_circuit_breakers is false but circuit_breaker_defaults "
                    "defines levels. Circuit breakers are configured but inactive."
                ),
                suggestion="Set enforce_circuit_breakers: true to activate them.",
                path="enforce_circuit_breakers",
            )
        )


# ---------------------------------------------------------------------------
# Index checks
# ---------------------------------------------------------------------------


def _get_symbol_names(raw: dict[str, Any]) -> set[str]:
    return set(symbol_cfg_by_upper_name(raw))


def _check_indices(raw: dict[str, Any], results: list[CheckResult]) -> None:
    indices = raw.get("indices")
    if indices is None:
        return
    if not isinstance(indices, list):
        return

    symbol_cfgs = symbol_cfg_by_upper_name(raw)
    symbol_names = set(symbol_cfgs)

    # M011: more than 5 indices
    if len(indices) > 5:
        excess = len(indices) - 5
        results.append(
            CheckResult(
                code="M011",
                severity=Severity.ERROR,
                message=(
                    f"{len(indices)} indices are defined but only 5 are supported."
                ),
                suggestion=f"Remove {excess} index entries.",
                path="indices",
            )
        )

    for idx in indices:
        if not isinstance(idx, dict):
            continue
        idx_id = str(idx.get("id", "?"))
        constituents = idx.get("constituents") or []
        if not isinstance(constituents, list):
            continue
        for sym_raw in constituents:
            sym = str(sym_raw).upper()
            # M009: constituent not in symbols
            if sym not in symbol_names:
                results.append(
                    CheckResult(
                        code="M009",
                        severity=Severity.ERROR,
                        message=(
                            f"Index '{idx_id}': constituent '{sym}' is not listed "
                            "in the symbols section."
                        ),
                        suggestion=(
                            f"Add '{sym}' to symbols or remove it from the index constituents."
                        ),
                        path=f"indices[id={idx_id}].constituents",
                    )
                )
            else:
                sym_cfg = symbol_cfgs.get(sym, {})
                if sym_cfg.get("outstanding_shares") is None:
                    results.append(
                        CheckResult(
                            code="M010",
                            severity=Severity.WARN,
                            message=(
                                f"Index '{idx_id}': constituent '{sym}' has no outstanding_shares."
                            ),
                            suggestion=(
                                "This field is required for cap-weighted index calculation. "
                                f"Add outstanding_shares to symbol '{sym}'."
                            ),
                            path=f"symbols.{sym}.outstanding_shares",
                        )
                    )


# ---------------------------------------------------------------------------
# Combo checks
# ---------------------------------------------------------------------------


def _check_combos(raw: dict[str, Any], results: list[CheckResult]) -> None:
    combos = raw.get("market_maker_combos")
    if not isinstance(combos, list):
        return

    symbol_names = _get_symbol_names(raw)

    for n, combo in enumerate(combos):
        if not isinstance(combo, dict):
            continue

        # M012: GTC tif
        tif = combo.get("tif", "DAY")
        if str(tif).upper() == "GTC":
            results.append(
                CheckResult(
                    code="M012",
                    severity=Severity.WARN,
                    message=(f"market_maker_combos[{n}] uses tif: GTC."),
                    suggestion=(
                        "On engine restart, GTC combo seeds may collide with persisted "
                        "orders from a previous session. Use tif: DAY unless you explicitly "
                        "manage persisted state."
                    ),
                    path=f"market_maker_combos[{n}].tif",
                )
            )

        legs = combo.get("legs") or []
        if not isinstance(legs, list):
            continue
        for j, leg in enumerate(legs):
            if not isinstance(leg, dict):
                continue
            leg_sym = leg.get("symbol")
            if leg_sym is not None and str(leg_sym).upper() not in symbol_names:
                results.append(
                    CheckResult(
                        code="M015",
                        severity=Severity.ERROR,
                        message=(
                            f"market_maker_combos[{n}].legs[{j}]: symbol "
                            f"'{leg_sym}' is not listed in the symbols section."
                        ),
                        suggestion=(
                            "Add the symbol to the symbols section or correct the combo leg."
                        ),
                        path=f"market_maker_combos[{n}].legs[{j}].symbol",
                    )
                )


# ---------------------------------------------------------------------------
# Admin gateway
# ---------------------------------------------------------------------------


def _check_admin_gateway(raw: dict[str, Any], results: list[CheckResult]) -> None:
    admin_gateways = gateway_ids_by_role(raw, "ADMIN")
    if not admin_gateways:
        results.append(
            CheckResult(
                code="M013",
                severity=Severity.WARN,
                message="No gateway has role: ADMIN.",
                suggestion=(
                    "Without an admin gateway, halt, resume, kill-switch, and emergency "
                    "commands cannot be issued at runtime. Add a gateway with role: ADMIN:\n"
                    "    - id: OPS01\n"
                    "      role: ADMIN\n"
                    "      disconnect_behaviour: LEAVE_ALL"
                ),
                path="gateways.alf",
            )
        )

    # C010: LEAVE_ALL on non-ADMIN gateways
    gateways = raw.get("gateways", {})
    if not isinstance(gateways, dict):
        return
    alf = gateways.get("alf", [])
    if not isinstance(alf, list):
        return
    for n, gw in enumerate(alf):
        if not isinstance(gw, dict):
            continue
        role = str(gw.get("role", "TRADER")).upper()
        disconnect = str(gw.get("disconnect_behaviour", "")).upper()
        gw_id = str(gw.get("id", "?"))
        if disconnect == "LEAVE_ALL" and role != "ADMIN":
            results.append(
                CheckResult(
                    code="C010",
                    severity=Severity.WARN,
                    message=(
                        f"Gateway '{gw_id}' has disconnect_behaviour: LEAVE_ALL but "
                        f"role {role}."
                    ),
                    suggestion=(
                        "LEAVE_ALL is typically reserved for ADMIN gateways. "
                        "TRADER and MARKET_MAKER gateways usually use CANCEL_ALL "
                        "or CANCEL_QUOTES_ONLY to prevent stale orders after disconnection."
                    ),
                    path=f"gateways.alf[{n}].disconnect_behaviour",
                )
            )


def _check_post_trade_admin(raw: dict[str, Any], results: list[CheckResult]) -> None:
    post_trade = raw.get("post_trade_gateway")
    if post_trade is None:
        return
    admin_gateways = gateway_ids_by_role(raw, "ADMIN")
    if not admin_gateways:
        results.append(
            CheckResult(
                code="M016",
                severity=Severity.WARN,
                message=(
                    "post_trade_gateway is configured but no ADMIN gateway exists."
                ),
                suggestion=(
                    "RALF admin commands (replay, etc.) will be unavailable. "
                    "Add a gateway with role: ADMIN."
                ),
                path="post_trade_gateway",
            )
        )


def _check_balf_gateway_semantic(
    raw: dict[str, Any], results: list[CheckResult]
) -> None:
    """Semantic cross-field checks for the balf_gateway section (M017–M018)."""
    section = raw.get("balf_gateway")
    if section is None or not isinstance(section, dict):
        return

    # M017 — heartbeat timeout should exceed heartbeat interval
    interval_raw = section.get("heartbeat_interval_sec")
    timeout_raw = section.get("heartbeat_timeout_sec")
    if interval_raw is not None and timeout_raw is not None:
        try:
            f_interval = float(interval_raw)
            f_timeout = float(timeout_raw)
            if f_timeout <= f_interval:
                results.append(
                    CheckResult(
                        code="M017",
                        severity=Severity.WARN,
                        message=(
                            f"balf_gateway.heartbeat_timeout_sec ({f_timeout}) must be "
                            f"greater than heartbeat_interval_sec ({f_interval})."
                        ),
                        suggestion=(
                            "Set heartbeat_timeout_sec to at least 2\u00d7 "
                            "heartbeat_interval_sec so a single missed heartbeat "
                            "triggers the timeout."
                        ),
                        path="balf_gateway.heartbeat_timeout_sec",
                    )
                )
        except (TypeError, ValueError):
            pass  # type errors already reported by layer 2

    # M018 — port collision with other gateway sections
    balf_port = section.get("port")
    if not isinstance(balf_port, int) or isinstance(balf_port, bool):
        return

    _BALF_PORT_PEERS = (
        ("post_trade_gateway", "pm-ralf-gwy"),
        ("market_data_gateway", "pm-md-gwy"),
    )
    for peer_key, peer_name in _BALF_PORT_PEERS:
        peer = raw.get(peer_key)
        if not isinstance(peer, dict):
            continue
        peer_port = peer.get("port")
        if (
            isinstance(peer_port, int)
            and not isinstance(peer_port, bool)
            and peer_port == balf_port
        ):
            results.append(
                CheckResult(
                    code="M018",
                    severity=Severity.ERROR,
                    message=(
                        f"balf_gateway.port ({balf_port}) conflicts with "
                        f"{peer_key}.port ({peer_port})."
                    ),
                    suggestion=(
                        f"Each gateway process must bind to a unique TCP port. "
                        f"Change balf_gateway.port or {peer_key}.port ({peer_name})."
                    ),
                    path="balf_gateway.port",
                )
            )


def _check_api_gateway_semantic(
    raw: dict[str, Any], results: list[CheckResult]
) -> None:
    """Cross-field checks for api_gateway/api_gateways sections."""

    has_named = isinstance(raw.get("api_gateways"), dict)
    has_legacy = isinstance(raw.get("api_gateway"), dict)
    if has_named and has_legacy:
        results.append(
            CheckResult(
                code="M021",
                severity=Severity.WARN,
                message=(
                    "Both 'api_gateways' and legacy 'api_gateway' are configured. "
                    "The runtime loader prioritizes 'api_gateways'."
                ),
                suggestion=(
                    "Use only 'api_gateways' for clarity, or remove 'api_gateways' "
                    "if you intentionally run the single legacy block."
                ),
                path="api_gateways",
            )
        )

    known_gateway_ids = all_gateway_ids(raw)
    if not known_gateway_ids:
        return

    for path, gateway_id in _iter_api_gateway_credential_ids(raw):
        if gateway_id not in known_gateway_ids:
            results.append(
                CheckResult(
                    code="M022",
                    severity=Severity.ERROR,
                    message=(
                        f"API gateway credential gateway_id '{gateway_id}' is not "
                        "defined in gateways.alf."
                    ),
                    suggestion=(
                        f"Add gateway '{gateway_id}' under gateways.alf or update "
                        "the credential to an existing ALF gateway id."
                    ),
                    path=path,
                )
            )


def _iter_api_gateway_credential_ids(raw: dict[str, Any]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []

    legacy = raw.get("api_gateway")
    if isinstance(legacy, dict):
        creds = legacy.get("credentials")
        if isinstance(creds, list):
            for index, cred in enumerate(creds):
                if not isinstance(cred, dict):
                    continue
                gateway = cred.get("gateway_id")
                if gateway is None:
                    continue
                gateway_id = str(gateway).strip().upper()
                if gateway_id:
                    items.append(
                        (f"api_gateway.credentials[{index}].gateway_id", gateway_id)
                    )

    named = raw.get("api_gateways")
    if isinstance(named, dict):
        for name, section in named.items():
            if not isinstance(section, dict):
                continue
            entry = str(name).strip() or str(name)
            creds = section.get("credentials")
            if not isinstance(creds, list):
                continue
            for index, cred in enumerate(creds):
                if not isinstance(cred, dict):
                    continue
                gateway = cred.get("gateway_id")
                if gateway is None:
                    continue
                gateway_id = str(gateway).strip().upper()
                if gateway_id:
                    items.append(
                        (
                            f"api_gateways.{entry}.credentials[{index}].gateway_id",
                            gateway_id,
                        )
                    )

    return items
