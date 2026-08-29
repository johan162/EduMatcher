"""Build a :class:`ConfigView` from a raw ``engine_config.yaml`` mapping.

Everything here is defensive.  A section that is missing, ``None`` or the
wrong type degrades to "not shown" rather than raising, because the most
likely moment somebody reaches for a viewer is when the config is broken and
they want to see what is actually in it.  Diagnosis belongs to
``pm-cverifier``; a viewer that crashes on a bad file has failed at exactly
the moment it was needed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from edumatcher.config import (
    EDUMATCHER_ENGINE_BIND_HOST,
    EDUMATCHER_INDEX_BIND_HOST,
    resolve_gateway_bind_host,
)
from edumatcher.gateway_ports import (
    DEFAULT_API_GATEWAY_PORT,
    LOG_SERVER_EXTRA_PORTS,
    SINGLETON_GATEWAYS,
    effective_port,
    resolved_fixed_listeners,
)

from edumatcher.config_show.model import (
    ApiGateway,
    CBLevel,
    Combo,
    ConfigView,
    Credential,
    Index,
    Listener,
    Participant,
    RiskLevel,
    Schedule,
    Source,
    Symbol,
)

#: Top-level keys the viewer understands.  Anything else is surfaced in the
#: unrecognised-keys panel under ``--all`` -- a typo'd section is invisible in
#: a plain YAML read and this is the cheapest place to catch one.
KNOWN_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "sessions_enabled",
        "enforce_collars",
        "enforce_circuit_breakers",
        "enforce_mm_obligation",
        "country",
        "snapshot_interval_sec",
        "engine_tuning",
        "mm_obligation_defaults",
        "risk_controls",
        "circuit_breaker_defaults",
        "gateways",
        "alf_gateway",
        "balf_gateway",
        "post_trade_gateway",
        "market_data_gateway",
        "dc_gateway",
        "log_server",
        "api_gateways",
        "api_gateway",
        "symbols",
        "market_maker_combos",
        "indices",
        "schedule",
    }
)


def _as_dict(obj: Any) -> dict[str, Any]:
    return obj if isinstance(obj, dict) else {}


def _as_list(obj: Any) -> list[Any]:
    return obj if isinstance(obj, list) else []


def _as_int(obj: Any) -> int | None:
    return obj if isinstance(obj, int) and not isinstance(obj, bool) else None


def _as_float(obj: Any) -> float | None:
    if isinstance(obj, bool):
        return None
    return float(obj) if isinstance(obj, (int, float)) else None


def _as_str(obj: Any, default: str = "") -> str:
    return obj if isinstance(obj, str) else default


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------
def resolve_source(explicit: str | None, default_path: Path) -> Source:
    """Work out which file to read and record how we got there.

    Showing *why* a path was chosen matters more than it looks: the single
    most common confusion with this config is editing a file in the source
    tree while a process reads one from ``EDUMATCHER_DATA_DIR``.
    """
    if explicit:
        path, via = Path(explicit).expanduser(), "--file"
    elif os.environ.get("EDUMATCHER_DATA_DIR"):
        path, via = default_path, "EDUMATCHER_DATA_DIR"
    else:
        path, via = default_path, "data directory"

    try:
        stat = path.stat()
        return Source(path, True, stat.st_size, stat.st_mtime, via)
    except OSError:
        return Source(path, False, 0, 0.0, via)


# ---------------------------------------------------------------------------
# Listeners
# ---------------------------------------------------------------------------
def _listeners(raw: dict[str, Any]) -> tuple[Listener, ...]:
    out: list[Listener] = []

    # Sockets that never appear in the YAML, and so are invisible without us.
    for fixed in resolved_fixed_listeners():
        out.append(
            Listener(
                port=fixed.port,
                proto=fixed.proto,
                process=fixed.process,
                function=fixed.function,
                # The engine trio and the index pair are the only listeners
                # whose bind host comes from the environment alone; report
                # what they will actually bind, not the compiled-in default.
                bind=(
                    EDUMATCHER_INDEX_BIND_HOST
                    if fixed.process == "pm-index"
                    else EDUMATCHER_ENGINE_BIND_HOST
                ),
                origin=fixed.origin,
                enabled=True,
                section=fixed.env_var or "config.py",
            )
        )

    for spec in SINGLETON_GATEWAYS:
        section = raw.get(spec.key)
        if not isinstance(section, dict):
            continue
        # A section present with no port: still binds, on the runtime default.
        port = effective_port(section, spec.default_port)
        if port is None:
            continue
        # Same resolution the gateway itself performs, so the panel matches
        # the running process even when EDUMATCHER_GATEWAY_BIND_HOST is set.
        bind = resolve_gateway_bind_host(
            section.get("bind_address") or section.get("host")
        )
        enabled = section.get("enabled", True) is not False
        origin = "configured" if "port" in section else "default"
        out.append(
            Listener(
                port,
                spec.proto,
                spec.process,
                spec.function,
                bind,
                origin,
                enabled,
                spec.key,
            )
        )

        if (
            spec.key == "log_server"
            and section.get("pubsub_enabled", True) is not False
        ):
            for extra in LOG_SERVER_EXTRA_PORTS:
                eport = effective_port(section, extra.default_port, key=extra.field)
                if eport is None:
                    continue
                out.append(
                    Listener(
                        eport,
                        extra.proto,
                        spec.process,
                        extra.function,
                        bind,
                        "configured" if extra.field in section else "default",
                        enabled,
                        f"{spec.key}.{extra.field}",
                    )
                )

    for name, section in _as_dict(raw.get("api_gateways")).items():
        if not isinstance(section, dict):
            continue
        port = effective_port(section, DEFAULT_API_GATEWAY_PORT)
        if port is None:
            continue
        out.append(
            Listener(
                port,
                "HTTP",
                "pm-api-gwy",
                f"REST API — {name}",
                resolve_gateway_bind_host(section.get("host")),
                "configured" if "port" in section else "default",
                section.get("enabled", True) is not False,
                f"api_gateways.{name}",
            )
        )

    out.sort(key=lambda listener: (listener.port, listener.process))
    return tuple(out)


# ---------------------------------------------------------------------------
# Participants and credentials
# ---------------------------------------------------------------------------
def _participants(raw: dict[str, Any]) -> tuple[Participant, ...]:
    out: list[Participant] = []
    for entry in _as_list(_as_dict(raw.get("gateways")).get("alf")):
        if not isinstance(entry, dict):
            continue
        out.append(
            Participant(
                gid=str(entry.get("id", "?")),
                role=_as_str(entry.get("role"), "—"),
                disconnect=_as_str(entry.get("disconnect_behaviour"), "—"),
                quote_policy=(
                    entry.get("quote_refresh_policy")
                    if isinstance(entry.get("quote_refresh_policy"), str)
                    else None
                ),
                description=_as_str(entry.get("description")),
            )
        )
    return tuple(out)


def _api_gateways(raw: dict[str, Any], roles: dict[str, str]) -> tuple[ApiGateway, ...]:
    sections = _as_dict(raw.get("api_gateways"))
    if not sections and isinstance(raw.get("api_gateway"), dict):
        sections = {"default": raw["api_gateway"]}  # legacy single-instance form

    out: list[ApiGateway] = []
    for name, section in sections.items():
        if not isinstance(section, dict):
            continue
        creds: list[Credential] = []
        for cred in _as_list(section.get("credentials")):
            if not isinstance(cred, dict):
                continue
            gid = cred.get("gateway_id")
            creds.append(
                Credential(
                    api_key=_as_str(cred.get("api_key")),
                    gateway_id=gid if isinstance(gid, str) else None,
                    description=_as_str(cred.get("description")),
                    owner_gateway=str(name),
                    role=roles.get(str(gid), "READ-ONLY" if gid is None else "?"),
                )
            )
        out.append(
            ApiGateway(
                name=str(name),
                enabled=section.get("enabled", True) is not False,
                host=_as_str(section.get("host"), "127.0.0.1"),
                port=effective_port(section, DEFAULT_API_GATEWAY_PORT)
                or DEFAULT_API_GATEWAY_PORT,
                swagger=section.get("swagger_enabled", False) is True,
                log_level=_as_str(section.get("log_level"), "—"),
                stats_db=_as_str(section.get("stats_db"), "—"),
                order_retention_sec=_as_int(section.get("order_retention_sec")),
                rate_limit=_as_dict(section.get("rate_limit")),
                timeouts=_as_dict(section.get("timeouts")),
                credentials=tuple(creds),
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Instruments and risk
# ---------------------------------------------------------------------------
def _symbols(raw: dict[str, Any]) -> tuple[Symbol, ...]:
    mm_symbols = _as_dict(_as_dict(raw.get("mm_obligation_defaults")).get("symbols"))
    out: list[Symbol] = []
    for name, section in _as_dict(raw.get("symbols")).items():
        section = _as_dict(section)
        quotes = [
            q
            for q in _as_list(section.get("market_maker_quotes"))
            if isinstance(q, dict)
        ]
        level = section.get("level")
        out.append(
            Symbol(
                name=str(name),
                tick_decimals=_as_int(section.get("tick_decimals")),
                level=level if isinstance(level, str) else None,
                last_buy=_as_float(section.get("last_buy_price")),
                last_sell=_as_float(section.get("last_sell_price")),
                outstanding=_as_int(section.get("outstanding_shares")),
                quote_makers=tuple(str(q.get("gateway_id", "?")) for q in quotes),
                collar_override=_as_dict(section.get("collar")) or None,
                cb_override=_as_dict(section.get("circuit_breaker")) or None,
                mm_override=_as_dict(mm_symbols.get(str(name))) or None,
            )
        )
    return tuple(out)


def _risk(
    raw: dict[str, Any], symbols: tuple[Symbol, ...]
) -> tuple[tuple[RiskLevel, ...], str | None]:
    controls = _as_dict(raw.get("risk_controls"))
    default_level = controls.get("default_level")
    default_name = default_level if isinstance(default_level, str) else None

    # A symbol with no explicit level inherits default_level, so the counts
    # shown beside each band have to resolve that inheritance, not just count
    # the literal 'level:' keys in the file.
    counts: dict[str, int] = {}
    for symbol in symbols:
        key = symbol.level or default_name
        if key:
            counts[key] = counts.get(key, 0) + 1

    out: list[RiskLevel] = []
    for name, body in _as_dict(controls.get("levels")).items():
        collar = _as_dict(_as_dict(body).get("collar"))
        out.append(
            RiskLevel(
                name=str(name),
                static_band_pct=_as_float(collar.get("static_band_pct")),
                dynamic_band_pct=_as_float(collar.get("dynamic_band_pct")),
                is_default=(name == default_name),
                n_symbols=counts.get(str(name), 0),
            )
        )
    return tuple(out), default_name


def _circuit_breakers(
    raw: dict[str, Any],
) -> tuple[tuple[CBLevel, ...], int | None, dict[str, Any]]:
    section = _as_dict(raw.get("circuit_breaker_defaults"))
    levels = tuple(
        CBLevel(
            name=str(name),
            price_shift_pct=_as_float(_as_dict(body).get("price_shift_pct")),
            halt_duration_ns=_as_int(_as_dict(body).get("halt_duration_ns")),
        )
        for name, body in _as_dict(section.get("levels")).items()
    )
    return (
        levels,
        _as_int(section.get("reference_window_ns")),
        _as_dict(section.get("reopening")),
    )


# ---------------------------------------------------------------------------
def build_view(raw: Any, source: Source) -> ConfigView:
    """Turn a parsed YAML document into the read-only view model."""
    raw = _as_dict(raw)

    participants = _participants(raw)
    roles = {p.gid: p.role for p in participants}
    symbols = _symbols(raw)
    risk_levels, default_level = _risk(raw, symbols)
    cb_levels, cb_window, cb_reopening = _circuit_breakers(raw)
    mm_defaults = _as_dict(raw.get("mm_obligation_defaults"))
    schedule = _as_dict(raw.get("schedule"))

    return ConfigView(
        source=source,
        flags={
            "sessions_enabled": raw.get("sessions_enabled"),
            "enforce_collars": raw.get("enforce_collars"),
            "enforce_circuit_breakers": raw.get("enforce_circuit_breakers"),
            # The per-section flag wins; the bare top-level key is the legacy
            # spelling and only applies when the section omits it.
            "enforce_mm_obligation": mm_defaults.get(
                "enforce_mm_obligation", raw.get("enforce_mm_obligation")
            ),
            "country": raw.get("country"),
        },
        listeners=_listeners(raw),
        participants=participants,
        api_gateways=_api_gateways(raw, roles),
        symbols=symbols,
        risk_levels=risk_levels,
        default_risk_level=default_level,
        cb_levels=cb_levels,
        cb_reference_window_ns=cb_window,
        cb_reopening=cb_reopening,
        mm_defaults={k: v for k, v in mm_defaults.items() if k != "symbols"},
        mm_symbol_overrides=_as_dict(mm_defaults.get("symbols")),
        combos=tuple(
            Combo(
                combo_id=str(c.get("combo_id", "?")),
                combo_type=_as_str(c.get("combo_type"), "—"),
                tif=_as_str(c.get("tif"), "—"),
                legs=tuple(
                    leg for leg in _as_list(c.get("legs")) if isinstance(leg, dict)
                ),
            )
            for c in _as_list(raw.get("market_maker_combos"))
            if isinstance(c, dict)
        ),
        indices=tuple(
            Index(
                idx_id=str(i.get("id", "?")),
                description=_as_str(i.get("description")),
                base_value=i.get("base_value"),
                publish_interval_sec=i.get("publish_interval_sec"),
                constituents=tuple(str(s) for s in _as_list(i.get("constituents"))),
            )
            for i in _as_list(raw.get("indices"))
            if isinstance(i, dict)
        ),
        schedule=Schedule(
            pre_open=schedule.get("pre_open"),
            opening_auction_start=schedule.get("opening_auction_start"),
            continuous_start=schedule.get("continuous_start"),
            closing_auction_start=schedule.get("closing_auction_start"),
            closing_auction_end=schedule.get("closing_auction_end"),
        ),
        tuning=_as_dict(raw.get("engine_tuning")),
        gateway_sections={
            spec.key: _as_dict(raw[spec.key])
            for spec in SINGLETON_GATEWAYS
            if isinstance(raw.get(spec.key), dict)
        },
        unknown_keys=tuple(sorted(k for k in raw if k not in KNOWN_TOP_LEVEL)),
    )
