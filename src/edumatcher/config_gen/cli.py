"""pm-config-gen — generate engine_config.yaml from high-level CLI inputs."""

from __future__ import annotations

import argparse
import math
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile

from edumatcher.engine.config_loader import load_engine_config
from edumatcher.models.participant import ParticipantRole

from edumatcher.config_gen.builder import ConfigBuilder, ConfigSpec
from edumatcher.config_gen.builder import ApiCredentialSpec, ApiGatewaySpec
from edumatcher.config_gen.builder import BalfGatewaySpec
from edumatcher.config_gen.builder import ComboLegSpec, ComboSpec
from edumatcher.config_gen.builder import IndexSpec
from edumatcher.config_gen.builder import MarketDataGatewaySpec
from edumatcher.config_gen.builder import PostTradeGatewaySpec
from edumatcher.config_gen.cb_spec import CbSpec, parse_cb_spec
from edumatcher.config_gen.defaults import (
    DEFAULT_API_GATEWAY_ENGINE_AUTH_SEC,
    DEFAULT_API_GATEWAY_ENGINE_REPLY_SEC,
    DEFAULT_API_GATEWAY_HOST,
    DEFAULT_API_GATEWAY_LOG_LEVEL,
    DEFAULT_API_GATEWAY_PORT,
    DEFAULT_API_GATEWAY_RATE_LIMIT_BURST,
    DEFAULT_API_GATEWAY_RATE_LIMIT_WRITES_PER_SECOND,
    DEFAULT_API_GATEWAY_STATS_DB,
    DEFAULT_API_GATEWAY_WAIT_ACK_SEC,
    DEFAULT_BALF_GATEWAY_AUTH_TIMEOUT_SEC,
    DEFAULT_BALF_GATEWAY_BIND_ADDRESS,
    DEFAULT_BALF_GATEWAY_DUPLICATE_SESSION_POLICY,
    DEFAULT_BALF_GATEWAY_ERROR_WINDOW_SEC,
    DEFAULT_BALF_GATEWAY_HEARTBEAT_INTERVAL_SEC,
    DEFAULT_BALF_GATEWAY_HEARTBEAT_TIMEOUT_SEC,
    DEFAULT_BALF_GATEWAY_IDLE_TIMEOUT_SEC,
    DEFAULT_BALF_GATEWAY_MAX_CLIENT_QUEUE,
    DEFAULT_BALF_GATEWAY_MAX_CONNECTIONS,
    DEFAULT_BALF_GATEWAY_MAX_ERRORS_BEFORE_DISCONNECT,
    DEFAULT_BALF_GATEWAY_MAX_MESSAGES_PER_SECOND,
    DEFAULT_BALF_GATEWAY_NAME,
    DEFAULT_BALF_GATEWAY_PORT,
    DEFAULT_INDEX_BASE_VALUE,
    DEFAULT_INDEX_PUBLISH_INTERVAL_SEC,
    DEFAULT_MARKET_DATA_GATEWAY_BIND_ADDRESS,
    DEFAULT_MARKET_DATA_GATEWAY_DEPTH_LEVELS,
    DEFAULT_MARKET_DATA_GATEWAY_HEARTBEAT_INTERVAL_SEC,
    DEFAULT_MARKET_DATA_GATEWAY_IDLE_TIMEOUT_SEC,
    DEFAULT_MARKET_DATA_GATEWAY_MAX_CLIENT_QUEUE,
    DEFAULT_MARKET_DATA_GATEWAY_MAX_SYMBOLS_PER_CLIENT,
    DEFAULT_MARKET_DATA_GATEWAY_NAME,
    DEFAULT_MARKET_DATA_GATEWAY_PORT,
    DEFAULT_MARKET_DATA_GATEWAY_REPLAY_WINDOW_SEC,
    DEFAULT_POST_TRADE_GATEWAY_ALLOWED_ROLES,
    DEFAULT_POST_TRADE_GATEWAY_BIND_ADDRESS,
    DEFAULT_POST_TRADE_GATEWAY_HEARTBEAT_INTERVAL_SEC,
    DEFAULT_POST_TRADE_GATEWAY_IDLE_TIMEOUT_SEC,
    DEFAULT_POST_TRADE_GATEWAY_MAX_CLIENT_QUEUE,
    DEFAULT_POST_TRADE_GATEWAY_NAME,
    DEFAULT_POST_TRADE_GATEWAY_PORT,
    DEFAULT_POST_TRADE_GATEWAY_REPLAY_RETENTION_SEC,
)
from edumatcher.config_gen.gateway_spec import GatewaySpec, parse_gateway_spec
from edumatcher.config_gen.renderer import render_yaml
from edumatcher.config_gen.risk_spec import parse_risk_level_spec
from edumatcher.config_gen.symbol_spec import SymbolOverride
from edumatcher.config_gen.symbol_spec import parse_symbol_opts
from edumatcher.config_gen.warnings import evaluate_diagnostics


from edumatcher.config_gen.cli_parser import build_parser
from edumatcher.config_gen.cli_comments import build_default_engine_field_comment_lines


def _validate_basic_args(args: argparse.Namespace) -> None:
    if args.snapshot_interval <= 0:
        raise ValueError("--snapshot-interval must be > 0")
    if not (0 <= args.tick_decimals <= 8):
        raise ValueError("--tick-decimals must be in range 0..8")
    if args.mm_spread_ticks <= 0:
        raise ValueError("--mm-spread-ticks must be > 0")
    if args.mm_min_qty <= 0:
        raise ValueError("--mm-min-qty must be > 0")
    if args.cb_window_ns <= 0:
        raise ValueError("--cb-window-ns must be > 0")
    if args.post_trade_port is not None and args.post_trade_port <= 0:
        raise ValueError("--post-trade-port must be > 0")
    if args.market_data_port is not None and args.market_data_port <= 0:
        raise ValueError("--market-data-port must be > 0")
    if (
        args.post_trade_replay_retention_sec is not None
        and args.post_trade_replay_retention_sec <= 0
    ):
        raise ValueError("--post-trade-replay-retention-sec must be > 0")
    if (
        args.post_trade_heartbeat_interval_sec is not None
        and args.post_trade_heartbeat_interval_sec <= 0
    ):
        raise ValueError("--post-trade-heartbeat-interval-sec must be > 0")
    if (
        args.post_trade_idle_timeout_sec is not None
        and args.post_trade_idle_timeout_sec <= 0
    ):
        raise ValueError("--post-trade-idle-timeout-sec must be > 0")
    if (
        args.post_trade_max_client_queue is not None
        and args.post_trade_max_client_queue <= 0
    ):
        raise ValueError("--post-trade-max-client-queue must be > 0")
    if (
        args.market_data_heartbeat_interval_sec is not None
        and args.market_data_heartbeat_interval_sec <= 0
    ):
        raise ValueError("--market-data-heartbeat-interval-sec must be > 0")
    if (
        args.market_data_idle_timeout_sec is not None
        and args.market_data_idle_timeout_sec <= 0
    ):
        raise ValueError("--market-data-idle-timeout-sec must be > 0")
    if (
        args.market_data_replay_window_sec is not None
        and args.market_data_replay_window_sec <= 0
    ):
        raise ValueError("--market-data-replay-window-sec must be > 0")
    if (
        args.market_data_max_symbols_per_client is not None
        and args.market_data_max_symbols_per_client <= 0
    ):
        raise ValueError("--market-data-max-symbols-per-client must be > 0")
    if (
        args.market_data_max_client_queue is not None
        and args.market_data_max_client_queue <= 0
    ):
        raise ValueError("--market-data-max-client-queue must be > 0")
    if args.market_data_depth_levels is not None and args.market_data_depth_levels <= 0:
        raise ValueError("--market-data-depth-levels must be > 0")
    if args.api_gateway_port is not None and args.api_gateway_port <= 0:
        raise ValueError("--api-gateway-port must be > 0")
    if (
        args.api_gateway_rate_limit_writes_per_second is not None
        and args.api_gateway_rate_limit_writes_per_second <= 0
    ):
        raise ValueError("--api-gateway-rate-limit-writes-per-second must be > 0")
    if (
        args.api_gateway_rate_limit_burst is not None
        and args.api_gateway_rate_limit_burst <= 0
    ):
        raise ValueError("--api-gateway-rate-limit-burst must be > 0")
    if (
        args.api_gateway_engine_auth_sec is not None
        and args.api_gateway_engine_auth_sec <= 0
    ):
        raise ValueError("--api-gateway-engine-auth-sec must be > 0")
    if (
        args.api_gateway_engine_reply_sec is not None
        and args.api_gateway_engine_reply_sec <= 0
    ):
        raise ValueError("--api-gateway-engine-reply-sec must be > 0")
    if args.api_gateway_wait_ack_sec is not None and args.api_gateway_wait_ack_sec <= 0:
        raise ValueError("--api-gateway-wait-ack-sec must be > 0")

    if args.balf_port is not None and args.balf_port <= 0:
        raise ValueError("--balf-port must be > 0")
    if (
        args.balf_heartbeat_interval_sec is not None
        and args.balf_heartbeat_interval_sec <= 0
    ):
        raise ValueError("--balf-heartbeat-interval-sec must be > 0")
    if (
        args.balf_heartbeat_timeout_sec is not None
        and args.balf_heartbeat_timeout_sec <= 0
    ):
        raise ValueError("--balf-heartbeat-timeout-sec must be > 0")
    if args.balf_idle_timeout_sec is not None and args.balf_idle_timeout_sec <= 0:
        raise ValueError("--balf-idle-timeout-sec must be > 0")
    if args.balf_auth_timeout_sec is not None and args.balf_auth_timeout_sec <= 0:
        raise ValueError("--balf-auth-timeout-sec must be > 0")
    if args.balf_max_connections is not None and args.balf_max_connections <= 0:
        raise ValueError("--balf-max-connections must be > 0")
    if args.balf_max_client_queue is not None and args.balf_max_client_queue <= 0:
        raise ValueError("--balf-max-client-queue must be > 0")
    if (
        args.balf_max_messages_per_second is not None
        and args.balf_max_messages_per_second <= 0
    ):
        raise ValueError("--balf-max-messages-per-second must be > 0")
    if (
        args.balf_max_errors_before_disconnect is not None
        and args.balf_max_errors_before_disconnect <= 0
    ):
        raise ValueError("--balf-max-errors-before-disconnect must be > 0")
    if args.balf_error_window_sec is not None and args.balf_error_window_sec <= 0:
        raise ValueError("--balf-error-window-sec must be > 0")

    if args.static_band is not None and not (0 < args.static_band < 1):
        raise ValueError("--static-band must be in (0, 1)")
    if args.dynamic_band is not None and not (0 < args.dynamic_band < 1):
        raise ValueError("--dynamic-band must be in (0, 1)")

    if args.seed_mm_mid_range is not None:
        min_price, max_price = _parse_seed_mm_mid_range(args.seed_mm_mid_range)
        tick_size = 10 ** (-int(args.tick_decimals))
        min_steps = math.ceil(min_price / tick_size)
        max_steps = math.floor(max_price / tick_size)
        if min_steps > max_steps:
            raise ValueError(
                "--seed-mm-mid-range does not contain any prices on the configured tick grid"
            )
        if min_steps <= 1:
            raise ValueError(
                "--seed-mm-mid-range minimum must allow a positive bid after applying a one-tick spread"
            )

    if args.seed_last_prices_from_mm and args.seed_mm_mid_range is None:
        raise ValueError("--seed-last-prices-from-mm requires --seed-mm-mid-range")

    _validate_schedule_order(args)


def _parse_hhmm_to_minutes(value: str, flag_name: str) -> int:
    text = value.strip()
    parts = text.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"{flag_name} must be in HH:MM format, got '{value}'")
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"{flag_name} must be in HH:MM format, got '{value}'") from exc
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"{flag_name} must be a valid HH:MM time, got '{value}'")
    return hours * 60 + minutes


def _validate_schedule_order(args: argparse.Namespace) -> None:
    """Ensure the five schedule times are well-formed and strictly increasing.

    A schedule where e.g. --continuous is before --opening-auction would let
    the engine reach an inconsistent session state, so this is validated
    regardless of whether --sessions-enabled/--schedule end up emitting the
    section, matching the treatment of other argument sanity checks above.
    """
    ordered_flags = (
        ("--pre-open", args.pre_open),
        ("--opening-auction", args.opening_auction),
        ("--continuous", args.continuous),
        ("--closing-auction", args.closing_auction),
        ("--closing-end", args.closing_end),
    )
    parsed = [
        (flag_name, raw_value, _parse_hhmm_to_minutes(raw_value, flag_name))
        for flag_name, raw_value in ordered_flags
    ]
    for (flag_a, value_a, minutes_a), (flag_b, value_b, minutes_b) in zip(
        parsed, parsed[1:]
    ):
        if minutes_a >= minutes_b:
            raise ValueError(
                f"Schedule times must be strictly increasing: {flag_a} ({value_a}) "
                f"must be earlier than {flag_b} ({value_b})"
            )


def _parse_seed_mm_mid_range(raw: str) -> tuple[float, float]:
    if ":" not in raw:
        raise ValueError(f"Invalid --seed-mm-mid-range '{raw}': expected MIN:MAX")

    min_raw, max_raw = raw.split(":", 1)
    try:
        min_price = float(min_raw.strip())
        max_price = float(max_raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"Invalid --seed-mm-mid-range '{raw}': MIN and MAX must be numbers"
        ) from exc

    if min_price <= 0 or max_price <= 0:
        raise ValueError("--seed-mm-mid-range values must be > 0")
    if min_price >= max_price:
        raise ValueError("--seed-mm-mid-range requires MIN < MAX")

    return (min_price, max_price)


def _parse_outstanding_shares(
    specs: list[str],
    allowed_symbols: set[str],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for raw in specs:
        if ":" not in raw:
            raise ValueError(f"Invalid --outstanding-shares '{raw}': expected SYM:N")
        sym_raw, val_raw = raw.split(":", 1)
        sym = sym_raw.strip().upper()
        if not sym:
            raise ValueError(
                f"Invalid --outstanding-shares '{raw}': symbol cannot be empty"
            )
        if sym not in allowed_symbols:
            raise ValueError(f"--outstanding-shares references unknown symbol '{sym}'")
        try:
            value = int(val_raw.strip())
        except ValueError:
            raise ValueError(
                f"--outstanding-shares '{raw}': value must be a positive integer"
            )
        if value <= 0:
            raise ValueError(f"--outstanding-shares '{raw}': value must be > 0")
        result[sym] = value
    return result


def _parse_symbol_band_specs(
    specs: list[str],
    allowed_symbols: set[str],
    flag_name: str,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw in specs:
        if ":" not in raw:
            raise ValueError(f"Invalid {flag_name} '{raw}': expected SYM:PCT")
        sym_raw, val_raw = raw.split(":", 1)
        sym = sym_raw.strip().upper()
        if not sym:
            raise ValueError(f"Invalid {flag_name} '{raw}': symbol cannot be empty")
        if sym not in allowed_symbols:
            raise ValueError(f"{flag_name} references unknown symbol '{sym}'")
        try:
            value = float(val_raw.strip())
        except ValueError:
            raise ValueError(f"{flag_name} '{raw}': value must be numeric")
        if not (0 < value < 1):
            raise ValueError(f"{flag_name} '{raw}': value must be in (0, 1)")
        result[sym] = value
    return result


def _parse_symbol_level_specs(
    specs: list[str],
    allowed_symbols: set[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in specs:
        if ":" not in raw:
            raise ValueError(f"Invalid --symbol-risk-level '{raw}': expected SYM:LEVEL")
        sym_raw, level_raw = raw.split(":", 1)
        sym = sym_raw.strip().upper()
        if not sym:
            raise ValueError(
                f"Invalid --symbol-risk-level '{raw}': symbol cannot be empty"
            )
        if sym not in allowed_symbols:
            raise ValueError(f"--symbol-risk-level references unknown symbol '{sym}'")
        level = level_raw.strip().upper()
        if not level:
            raise ValueError(
                f"Invalid --symbol-risk-level '{raw}': level cannot be empty"
            )
        result[sym] = level
    return result


def _parse_api_credentials(
    specs: list[str], allowed_gateways: set[str]
) -> tuple[ApiCredentialSpec, ...]:
    credentials: list[ApiCredentialSpec] = []
    seen_keys: set[str] = set()
    for raw in specs:
        parts = raw.split(":", 2)
        if len(parts) < 2:
            raise ValueError(
                f"Invalid --api-key '{raw}': expected KEY:GATEWAY_ID[:DESCRIPTION]"
            )
        api_key = parts[0].strip()
        gateway_raw = parts[1].strip()
        description = parts[2].strip() if len(parts) == 3 else ""
        if not api_key:
            raise ValueError(f"Invalid --api-key '{raw}': key cannot be empty")
        if api_key in seen_keys:
            raise ValueError(f"Duplicate --api-key value '{api_key}'")
        seen_keys.add(api_key)
        gateway_id = None if gateway_raw.lower() == "null" else gateway_raw.upper()
        if gateway_id is not None and gateway_id not in allowed_gateways:
            raise ValueError(f"--api-key references unknown gateway_id '{gateway_id}'")
        credentials.append(
            ApiCredentialSpec(
                api_key=api_key,
                gateway_id=gateway_id,
                description=description,
            )
        )
    return tuple(credentials)


def _parse_api_gateway_instance(
    raw: str, allowed_gateways: set[str]
) -> tuple[str, tuple[str, ...], int | None]:
    parts = raw.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(
            f"Invalid --api-gateway-instance '{raw}': expected NAME:GATEWAY[,GATEWAY...][:PORT]"
        )
    name = parts[0].strip()
    if not name:
        raise ValueError(
            f"Invalid --api-gateway-instance '{raw}': name cannot be empty"
        )

    gateway_ids = tuple(
        gateway_raw.strip().upper()
        for gateway_raw in parts[1].split(",")
        if gateway_raw.strip()
    )
    if not gateway_ids:
        raise ValueError(
            f"Invalid --api-gateway-instance '{raw}': at least one gateway ID is required"
        )
    for gateway_id in gateway_ids:
        if gateway_id not in allowed_gateways:
            raise ValueError(
                f"--api-gateway-instance '{raw}' references unknown gateway_id '{gateway_id}'"
            )

    port: int | None = None
    if len(parts) == 3 and parts[2].strip():
        try:
            port = int(parts[2].strip())
        except ValueError as exc:
            raise ValueError(
                f"Invalid --api-gateway-instance '{raw}': PORT must be an integer"
            ) from exc
        if port <= 0:
            raise ValueError(
                f"Invalid --api-gateway-instance '{raw}': PORT must be > 0"
            )
    return name, gateway_ids, port


def _parse_specs(args: argparse.Namespace) -> tuple[
    list[str],
    list[GatewaySpec],
    dict[str, tuple[float, float | None]],
    list[CbSpec],
    dict[str, SymbolOverride],
    list[str],
    dict[str, int],
    tuple[float, float] | None,
]:
    symbols = [s.upper() for s in args.symbols]

    gateways = [parse_gateway_spec(raw) for raw in args.gateways]

    risk_levels: dict[str, tuple[float, float | None]] = {}
    for raw in args.risk_level:
        spec = parse_risk_level_spec(raw)
        risk_levels[spec.name] = (spec.static_pct, spec.dynamic_pct)

    cb_levels: list[CbSpec] = []
    if args.cb_levels is not None:
        cb_levels = [parse_cb_spec(raw) for raw in args.cb_levels]

    symbol_overrides, symbol_opt_warnings = parse_symbol_opts(
        specs=args.symbol_opts,
        allowed_symbols=set(symbols),
    )

    symbol_static_bands = _parse_symbol_band_specs(
        specs=args.symbol_static_band,
        allowed_symbols=set(symbols),
        flag_name="--symbol-static-band",
    )
    for sym, static_band in symbol_static_bands.items():
        symbol_overrides.setdefault(sym, SymbolOverride()).static_band_pct = static_band

    symbol_dynamic_bands = _parse_symbol_band_specs(
        specs=args.symbol_dynamic_band,
        allowed_symbols=set(symbols),
        flag_name="--symbol-dynamic-band",
    )
    for sym, dynamic_band in symbol_dynamic_bands.items():
        symbol_overrides.setdefault(sym, SymbolOverride()).dynamic_band_pct = (
            dynamic_band
        )

    symbol_risk_levels = _parse_symbol_level_specs(
        specs=args.symbol_risk_level,
        allowed_symbols=set(symbols),
    )
    for sym, risk_level in symbol_risk_levels.items():
        symbol_overrides.setdefault(sym, SymbolOverride()).level = risk_level

    outstanding_shares = _parse_outstanding_shares(
        specs=args.outstanding_shares,
        allowed_symbols=set(symbols),
    )

    seed_mm_mid_range = (
        _parse_seed_mm_mid_range(args.seed_mm_mid_range)
        if args.seed_mm_mid_range is not None
        else None
    )

    return (
        symbols,
        gateways,
        risk_levels,
        cb_levels,
        symbol_overrides,
        symbol_opt_warnings,
        outstanding_shares,
        seed_mm_mid_range,
    )


def _resolve_emit_schedule(args: argparse.Namespace) -> bool:
    if args.schedule is None:
        return bool(args.sessions_enabled)
    return bool(args.schedule)


def _print_diagnostics(lines: list[str]) -> None:
    for line in lines:
        print(line, file=sys.stderr)


def _build_post_trade_gateway_spec(
    args: argparse.Namespace,
) -> PostTradeGatewaySpec | None:
    emit = any(
        value is not None
        for value in (
            args.post_trade_name,
            args.post_trade_bind_address,
            args.post_trade_port,
            args.post_trade_replay_retention_sec,
            args.post_trade_heartbeat_interval_sec,
            args.post_trade_idle_timeout_sec,
            args.post_trade_max_client_queue,
            args.post_trade_allowed_roles,
        )
    ) or bool(args.post_trade_gateway)

    if not emit:
        return None

    allowed_roles = tuple(
        role.upper()
        for role in (
            args.post_trade_allowed_roles or DEFAULT_POST_TRADE_GATEWAY_ALLOWED_ROLES
        )
    )

    return PostTradeGatewaySpec(
        name=str(args.post_trade_name or DEFAULT_POST_TRADE_GATEWAY_NAME),
        bind_address=str(
            args.post_trade_bind_address or DEFAULT_POST_TRADE_GATEWAY_BIND_ADDRESS
        ),
        port=int(args.post_trade_port or DEFAULT_POST_TRADE_GATEWAY_PORT),
        replay_retention_sec=int(
            args.post_trade_replay_retention_sec
            or DEFAULT_POST_TRADE_GATEWAY_REPLAY_RETENTION_SEC
        ),
        heartbeat_interval_sec=int(
            args.post_trade_heartbeat_interval_sec
            or DEFAULT_POST_TRADE_GATEWAY_HEARTBEAT_INTERVAL_SEC
        ),
        idle_timeout_sec=int(
            args.post_trade_idle_timeout_sec
            or DEFAULT_POST_TRADE_GATEWAY_IDLE_TIMEOUT_SEC
        ),
        max_client_queue=int(
            args.post_trade_max_client_queue
            or DEFAULT_POST_TRADE_GATEWAY_MAX_CLIENT_QUEUE
        ),
        allowed_roles=allowed_roles,
    )


def _build_market_data_gateway_spec(
    args: argparse.Namespace,
) -> MarketDataGatewaySpec | None:
    emit = any(
        value is not None
        for value in (
            args.market_data_enabled,
            args.market_data_name,
            args.market_data_bind_address,
            args.market_data_port,
            args.market_data_heartbeat_interval_sec,
            args.market_data_idle_timeout_sec,
            args.market_data_replay_window_sec,
            args.market_data_max_symbols_per_client,
            args.market_data_max_client_queue,
            args.market_data_depth_levels,
        )
    ) or bool(args.market_data_gateway)

    if not emit:
        return None

    enabled = (
        bool(args.market_data_enabled) if args.market_data_enabled is not None else True
    )

    return MarketDataGatewaySpec(
        enabled=enabled,
        name=str(args.market_data_name or DEFAULT_MARKET_DATA_GATEWAY_NAME),
        bind_address=str(
            args.market_data_bind_address or DEFAULT_MARKET_DATA_GATEWAY_BIND_ADDRESS
        ),
        port=int(args.market_data_port or DEFAULT_MARKET_DATA_GATEWAY_PORT),
        heartbeat_interval_sec=int(
            args.market_data_heartbeat_interval_sec
            or DEFAULT_MARKET_DATA_GATEWAY_HEARTBEAT_INTERVAL_SEC
        ),
        idle_timeout_sec=int(
            args.market_data_idle_timeout_sec
            or DEFAULT_MARKET_DATA_GATEWAY_IDLE_TIMEOUT_SEC
        ),
        replay_window_sec=int(
            args.market_data_replay_window_sec
            or DEFAULT_MARKET_DATA_GATEWAY_REPLAY_WINDOW_SEC
        ),
        max_symbols_per_client=int(
            args.market_data_max_symbols_per_client
            or DEFAULT_MARKET_DATA_GATEWAY_MAX_SYMBOLS_PER_CLIENT
        ),
        max_client_queue=int(
            args.market_data_max_client_queue
            or DEFAULT_MARKET_DATA_GATEWAY_MAX_CLIENT_QUEUE
        ),
        depth_levels=int(
            args.market_data_depth_levels or DEFAULT_MARKET_DATA_GATEWAY_DEPTH_LEVELS
        ),
    )


def _build_balf_gateway_spec(
    args: argparse.Namespace,
) -> BalfGatewaySpec | None:
    emit = any(
        value is not None
        for value in (
            args.balf_name,
            args.balf_bind_address,
            args.balf_port,
            args.balf_heartbeat_interval_sec,
            args.balf_heartbeat_timeout_sec,
            args.balf_idle_timeout_sec,
            args.balf_auth_timeout_sec,
            args.balf_max_connections,
            args.balf_max_client_queue,
            args.balf_max_messages_per_second,
            args.balf_max_errors_before_disconnect,
            args.balf_error_window_sec,
            args.balf_duplicate_session_policy,
        )
    ) or bool(args.balf_gateway)

    if not emit:
        return None

    return BalfGatewaySpec(
        name=str(args.balf_name or DEFAULT_BALF_GATEWAY_NAME),
        bind_address=str(args.balf_bind_address or DEFAULT_BALF_GATEWAY_BIND_ADDRESS),
        port=int(args.balf_port or DEFAULT_BALF_GATEWAY_PORT),
        heartbeat_interval_sec=int(
            args.balf_heartbeat_interval_sec
            or DEFAULT_BALF_GATEWAY_HEARTBEAT_INTERVAL_SEC
        ),
        heartbeat_timeout_sec=int(
            args.balf_heartbeat_timeout_sec
            or DEFAULT_BALF_GATEWAY_HEARTBEAT_TIMEOUT_SEC
        ),
        idle_timeout_sec=int(
            args.balf_idle_timeout_sec or DEFAULT_BALF_GATEWAY_IDLE_TIMEOUT_SEC
        ),
        auth_timeout_sec=int(
            args.balf_auth_timeout_sec or DEFAULT_BALF_GATEWAY_AUTH_TIMEOUT_SEC
        ),
        max_connections=int(
            args.balf_max_connections or DEFAULT_BALF_GATEWAY_MAX_CONNECTIONS
        ),
        max_client_queue=int(
            args.balf_max_client_queue or DEFAULT_BALF_GATEWAY_MAX_CLIENT_QUEUE
        ),
        max_messages_per_second=int(
            args.balf_max_messages_per_second
            or DEFAULT_BALF_GATEWAY_MAX_MESSAGES_PER_SECOND
        ),
        max_errors_before_disconnect=int(
            args.balf_max_errors_before_disconnect
            or DEFAULT_BALF_GATEWAY_MAX_ERRORS_BEFORE_DISCONNECT
        ),
        error_window_sec=int(
            args.balf_error_window_sec or DEFAULT_BALF_GATEWAY_ERROR_WINDOW_SEC
        ),
        duplicate_session_policy=str(
            args.balf_duplicate_session_policy
            or DEFAULT_BALF_GATEWAY_DUPLICATE_SESSION_POLICY
        ),
    )


def _build_api_gateway_specs(
    args: argparse.Namespace,
    gateways: list[GatewaySpec],
) -> tuple[ApiGatewaySpec, ...]:
    emit = any(
        value is not None
        for value in (
            args.api_gateway_enabled,
            args.api_gateway_host,
            args.api_gateway_port,
            args.api_gateway_swagger_enabled,
            args.api_gateway_log_level,
            args.api_gateway_stats_db,
            args.api_gateway_generate_keys,
            args.api_gateway_rate_limit_writes_per_second,
            args.api_gateway_rate_limit_burst,
            args.api_gateway_engine_auth_sec,
            args.api_gateway_engine_reply_sec,
            args.api_gateway_wait_ack_sec,
        )
    ) or bool(
        args.api_gateway
        or args.api_gateway_instance
        or args.api_key
        or args.api_gateway_readonly_key
    )

    if not emit:
        return ()

    allowed_gateways = {gateway.gateway_id for gateway in gateways}
    parsed_instances = [
        _parse_api_gateway_instance(raw, allowed_gateways)
        for raw in args.api_gateway_instance
    ]
    if parsed_instances and args.api_key:
        raise ValueError(
            "--api-key is only supported for single API gateway generation; "
            "use generated keys with --api-gateway-instance"
        )

    seen_names: set[str] = set()
    seen_gateway_ids: dict[str, str] = {}
    for name, gateway_ids, _port in parsed_instances:
        if name in seen_names:
            raise ValueError(f"duplicate --api-gateway-instance name '{name}'")
        seen_names.add(name)
        for gateway_id in gateway_ids:
            existing = seen_gateway_ids.get(gateway_id)
            if existing is not None:
                raise ValueError(
                    f"gateway_id '{gateway_id}' is assigned to both API gateway "
                    f"instances '{existing}' and '{name}'"
                )
            seen_gateway_ids[gateway_id] = name

    enabled = (
        bool(args.api_gateway_enabled) if args.api_gateway_enabled is not None else True
    )
    swagger_enabled = (
        bool(args.api_gateway_swagger_enabled)
        if args.api_gateway_swagger_enabled is not None
        else True
    )
    generate_keys = (
        bool(args.api_gateway_generate_keys)
        if args.api_gateway_generate_keys is not None
        else True
    )
    credentials = _parse_api_credentials(
        specs=args.api_key,
        allowed_gateways=allowed_gateways,
    )

    host = str(args.api_gateway_host or DEFAULT_API_GATEWAY_HOST)
    log_level = str(args.api_gateway_log_level or DEFAULT_API_GATEWAY_LOG_LEVEL)
    stats_db = str(args.api_gateway_stats_db or DEFAULT_API_GATEWAY_STATS_DB)
    generate_readonly_key = bool(args.api_gateway_readonly_key)
    rate_limit_writes_per_second = int(
        args.api_gateway_rate_limit_writes_per_second
        or DEFAULT_API_GATEWAY_RATE_LIMIT_WRITES_PER_SECOND
    )
    rate_limit_burst = int(
        args.api_gateway_rate_limit_burst or DEFAULT_API_GATEWAY_RATE_LIMIT_BURST
    )
    engine_auth_sec = float(
        args.api_gateway_engine_auth_sec or DEFAULT_API_GATEWAY_ENGINE_AUTH_SEC
    )
    engine_reply_sec = float(
        args.api_gateway_engine_reply_sec or DEFAULT_API_GATEWAY_ENGINE_REPLY_SEC
    )
    wait_ack_sec = float(
        args.api_gateway_wait_ack_sec or DEFAULT_API_GATEWAY_WAIT_ACK_SEC
    )

    def make_spec(
        *,
        name: str,
        port: int,
        gateway_ids: tuple[str, ...] = (),
        credentials: tuple[ApiCredentialSpec, ...] = (),
    ) -> ApiGatewaySpec:
        return ApiGatewaySpec(
            name=name,
            enabled=enabled,
            host=host,
            port=port,
            swagger_enabled=swagger_enabled,
            log_level=log_level,
            stats_db=stats_db,
            credentials=credentials,
            gateway_ids=gateway_ids,
            generate_keys=generate_keys,
            generate_readonly_key=generate_readonly_key,
            rate_limit_writes_per_second=rate_limit_writes_per_second,
            rate_limit_burst=rate_limit_burst,
            engine_auth_sec=engine_auth_sec,
            engine_reply_sec=engine_reply_sec,
            wait_ack_sec=wait_ack_sec,
        )

    base_port = int(args.api_gateway_port or DEFAULT_API_GATEWAY_PORT)
    if parsed_instances:
        return tuple(
            make_spec(
                name=name,
                port=port if port is not None else base_port + index,
                gateway_ids=gateway_ids,
            )
            for index, (name, gateway_ids, port) in enumerate(parsed_instances)
        )

    return (
        make_spec(
            name=str(args.api_gateway_name),
            port=base_port,
            credentials=credentials,
        ),
    )


def _parse_index_specs(args: argparse.Namespace) -> tuple[IndexSpec, ...]:
    """Parse all --index* flags and return a tuple of IndexSpec objects."""
    if not args.index:
        return ()

    allowed_symbols = {s.upper() for s in args.symbols}

    # ── --index ID[:DESCRIPTION] ────────────────────────────────────────────
    index_defs: dict[str, str] = {}  # ordered: id -> description
    for raw in args.index:
        if ":" in raw:
            idx_id_raw, description = raw.split(":", 1)
        else:
            idx_id_raw, description = raw, ""
        idx_id = idx_id_raw.strip().upper()
        if not idx_id:
            raise ValueError(f"Invalid --index '{raw}': id cannot be empty")
        if not idx_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                f"Invalid --index '{raw}': id must be alphanumeric "
                "(letters, digits, hyphens, underscores)"
            )
        if idx_id in index_defs:
            raise ValueError(f"Duplicate --index id '{idx_id}'")
        index_defs[idx_id] = description.strip() or f"Index {idx_id}"

    if len(index_defs) > 5:
        raise ValueError("--index: maximum 5 indices per exchange")

    # ── --index-constituents ID:SYM[,SYM,...] ───────────────────────────────
    index_constituents: dict[str, list[str]] = {}
    for raw in args.index_constituents:
        if ":" not in raw:
            raise ValueError(
                f"Invalid --index-constituents '{raw}': expected ID:SYM[,SYM,...]"
            )
        idx_id_raw, syms_raw = raw.split(":", 1)
        idx_id = idx_id_raw.strip().upper()
        if idx_id not in index_defs:
            raise ValueError(
                f"--index-constituents references unknown index '{idx_id}'"
            )
        syms = [s.strip().upper() for s in syms_raw.split(",") if s.strip()]
        if not syms:
            raise ValueError(
                f"--index-constituents '{raw}': at least one symbol required"
            )
        for sym in syms:
            if sym not in allowed_symbols:
                raise ValueError(
                    f"--index-constituents '{raw}': symbol '{sym}' is not in --symbols"
                )
        index_constituents[idx_id] = syms

    # ── --index-base-value ID:VALUE ──────────────────────────────────────────
    index_base_values: dict[str, float] = {}
    for raw in args.index_base_value:
        if ":" not in raw:
            raise ValueError(f"Invalid --index-base-value '{raw}': expected ID:VALUE")
        idx_id_raw, val_raw = raw.split(":", 1)
        idx_id = idx_id_raw.strip().upper()
        if idx_id not in index_defs:
            raise ValueError(f"--index-base-value references unknown index '{idx_id}'")
        try:
            value = float(val_raw.strip())
        except ValueError as exc:
            raise ValueError(
                f"--index-base-value '{raw}': value must be numeric"
            ) from exc
        if value <= 0:
            raise ValueError(f"--index-base-value '{raw}': value must be > 0")
        index_base_values[idx_id] = value

    # ── --index-interval ID:SECS ─────────────────────────────────────────────
    index_intervals: dict[str, float] = {}
    for raw in args.index_interval:
        if ":" not in raw:
            raise ValueError(f"Invalid --index-interval '{raw}': expected ID:SECS")
        idx_id_raw, val_raw = raw.split(":", 1)
        idx_id = idx_id_raw.strip().upper()
        if idx_id not in index_defs:
            raise ValueError(f"--index-interval references unknown index '{idx_id}'")
        try:
            value = float(val_raw.strip())
        except ValueError as exc:
            raise ValueError(
                f"--index-interval '{raw}': value must be numeric"
            ) from exc
        if value <= 0:
            raise ValueError(f"--index-interval '{raw}': value must be > 0")
        index_intervals[idx_id] = value

    # ── --index-history-file ID:PATH ─────────────────────────────────────────
    index_history_files: dict[str, str] = {}
    for raw in args.index_history_file:
        if ":" not in raw:
            raise ValueError(f"Invalid --index-history-file '{raw}': expected ID:PATH")
        idx_id_raw, path_raw = raw.split(":", 1)
        idx_id = idx_id_raw.strip().upper()
        if idx_id not in index_defs:
            raise ValueError(
                f"--index-history-file references unknown index '{idx_id}'"
            )
        path = path_raw.strip()
        if not path:
            raise ValueError(f"--index-history-file '{raw}': path cannot be empty")
        index_history_files[idx_id] = path

    # ── --index-state-file ID:PATH ───────────────────────────────────────────
    index_state_files: dict[str, str] = {}
    for raw in args.index_state_file:
        if ":" not in raw:
            raise ValueError(f"Invalid --index-state-file '{raw}': expected ID:PATH")
        idx_id_raw, path_raw = raw.split(":", 1)
        idx_id = idx_id_raw.strip().upper()
        if idx_id not in index_defs:
            raise ValueError(f"--index-state-file references unknown index '{idx_id}'")
        path = path_raw.strip()
        if not path:
            raise ValueError(f"--index-state-file '{raw}': path cannot be empty")
        index_state_files[idx_id] = path

    # ── Validate: every index must have at least one constituent ─────────────
    for idx_id in index_defs:
        if not index_constituents.get(idx_id):
            raise ValueError(
                f"Index '{idx_id}' has no constituents. "
                f"Use --index-constituents {idx_id}:SYM[,SYM,...]"
            )

    return tuple(
        IndexSpec(
            id=idx_id,
            description=index_defs[idx_id],
            constituents=tuple(index_constituents[idx_id]),
            base_value=index_base_values.get(idx_id, DEFAULT_INDEX_BASE_VALUE),
            publish_interval_sec=index_intervals.get(
                idx_id, DEFAULT_INDEX_PUBLISH_INTERVAL_SEC
            ),
            history_file=index_history_files.get(idx_id, ""),
            state_file=index_state_files.get(idx_id, ""),
        )
        for idx_id in index_defs
    )


def _tick_decimals_by_symbol(
    symbols: list[str],
    symbol_overrides: dict[str, SymbolOverride],
    default_tick_decimals: int,
) -> dict[str, int]:
    result: dict[str, int] = {}
    for sym in symbols:
        override = symbol_overrides.get(sym)
        result[sym] = (
            override.tick_decimals
            if override is not None and override.tick_decimals is not None
            else default_tick_decimals
        )
    return result


def _parse_leg_price(raw: str, tick_decimals: int, label: str) -> int:
    """Parse a combo leg price/stop_price.

    Accepts either a plain integer tick count (legacy, backward-compatible
    format, e.g. '20950') or a decimal display price (e.g. '209.50'), which
    is converted to ticks using the leg symbol's tick_decimals. A value is
    treated as decimal input only when it contains a '.'; this keeps every
    existing integer-only invocation working unchanged.
    """
    text = raw.strip()
    if "." in text:
        try:
            decimal_price = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(
                f"{label} must be an integer tick count or a decimal price"
            ) from exc
        tick_size = Decimal(1).scaleb(-tick_decimals)
        ticks = (decimal_price / tick_size).to_integral_value(rounding=ROUND_HALF_UP)
        return int(ticks)
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(
            f"{label} must be an integer tick count or a decimal price"
        ) from exc


def _parse_combo_specs(
    args: argparse.Namespace,
    allowed_symbols: set[str],
    tick_decimals_by_symbol: dict[str, int],
) -> list[ComboSpec]:
    """Parse all --combo flags and return a list of ComboSpec objects."""
    from edumatcher.models.combo import ComboType
    from edumatcher.models.order import Side, OrderType, SmpAction, TIF as TIFEnum

    combos: list[ComboSpec] = []
    seen_ids: set[str] = set()

    for raw in args.combo:
        parts = raw.split(":", 3)
        if len(parts) != 4:
            raise ValueError(
                f"Invalid --combo '{raw}': expected ID:TYPE:TIF:SYM/SIDE/TYPE/QTY[/PRICE[/STOP[/SMP]]],..."
            )
        combo_id, combo_type_raw, tif_raw, legs_raw = parts
        combo_id = combo_id.strip()
        if not combo_id:
            raise ValueError(f"Invalid --combo '{raw}': combo_id cannot be empty")
        if combo_id in seen_ids:
            raise ValueError(f"Duplicate --combo combo_id '{combo_id}'")
        seen_ids.add(combo_id)

        combo_type = combo_type_raw.strip().upper()
        try:
            ComboType(combo_type)
        except ValueError as exc:
            raise ValueError(
                f"Invalid --combo '{raw}': combo_type '{combo_type}' is invalid"
            ) from exc

        tif = tif_raw.strip().upper()
        try:
            TIFEnum(tif)
        except ValueError as exc:
            raise ValueError(
                f"Invalid --combo '{raw}': tif '{tif}' is invalid"
            ) from exc

        leg_specs_raw = [s.strip() for s in legs_raw.split(",") if s.strip()]
        if len(leg_specs_raw) < 2:
            raise ValueError(f"Invalid --combo '{raw}': at least 2 legs required")
        if len(leg_specs_raw) > 10:
            raise ValueError(f"Invalid --combo '{raw}': at most 10 legs supported")

        seen_leg_symbols: set[str] = set()
        legs: list[ComboLegSpec] = []
        for leg_raw in leg_specs_raw:
            fields = leg_raw.split("/")
            if len(fields) < 4:
                raise ValueError(
                    f"Invalid --combo '{raw}': leg '{leg_raw}' requires SYM/SIDE/TYPE/QTY"
                )
            sym = fields[0].strip().upper()
            side_str = fields[1].strip().upper()
            order_type_str = fields[2].strip().upper()
            try:
                qty = int(fields[3].strip())
            except ValueError as exc:
                raise ValueError(
                    f"Invalid --combo '{raw}': leg quantity must be an integer"
                ) from exc
            if qty <= 0:
                raise ValueError(f"Invalid --combo '{raw}': leg quantity must be > 0")

            price: int | None = None
            stop_price: int | None = None
            smp_action_str = "NONE"
            leg_tick_decimals = tick_decimals_by_symbol.get(
                sym, int(args.tick_decimals)
            )

            if len(fields) >= 5 and fields[4].strip().lower() not in ("", "null"):
                try:
                    price = _parse_leg_price(
                        fields[4],
                        leg_tick_decimals,
                        f"Invalid --combo '{raw}': leg price",
                    )
                except ValueError as exc:
                    raise ValueError(str(exc)) from exc
            if len(fields) >= 6 and fields[5].strip().lower() not in ("", "null"):
                try:
                    stop_price = _parse_leg_price(
                        fields[5],
                        leg_tick_decimals,
                        f"Invalid --combo '{raw}': leg stop_price",
                    )
                except ValueError as exc:
                    raise ValueError(str(exc)) from exc
            if len(fields) >= 7 and fields[6].strip():
                smp_action_str = fields[6].strip().upper()

            if sym not in allowed_symbols:
                raise ValueError(
                    f"Invalid --combo '{raw}': leg symbol '{sym}' not in --symbols"
                )
            if sym in seen_leg_symbols:
                raise ValueError(
                    f"Invalid --combo '{raw}': duplicate leg symbol '{sym}'"
                )
            seen_leg_symbols.add(sym)

            try:
                Side(side_str)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid --combo '{raw}': leg side '{side_str}' is invalid"
                ) from exc
            try:
                OrderType(order_type_str)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid --combo '{raw}': leg order_type '{order_type_str}' is invalid"
                ) from exc
            try:
                SmpAction(smp_action_str)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid --combo '{raw}': leg smp_action '{smp_action_str}' is invalid"
                ) from exc

            legs.append(
                ComboLegSpec(
                    symbol=sym,
                    side=side_str,
                    order_type=order_type_str,
                    quantity=qty,
                    price=price,
                    stop_price=stop_price,
                    smp_action=smp_action_str,
                )
            )

        combos.append(
            ComboSpec(
                combo_id=combo_id,
                combo_type=combo_type,
                tif=tif,
                legs=tuple(legs),
            )
        )

    return combos


def _write_output(output_path: Path, content: str, force: bool) -> None:
    if output_path.exists() and not force:
        raise FileExistsError("Output file already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def _validate_generated_when_possible(
    content: str, skip_validation: bool
) -> str | None:
    # With MM stubs bid/ask are null by design, so parser validation is expected to fail.
    if skip_validation:
        return None

    with NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        fh.write(content)
        tmp_path = Path(fh.name)

    try:
        load_engine_config(tmp_path)
    except Exception as exc:  # pragma: no cover - defensive
        return f"[WARN] Internal validation failed for generated config: {exc}"
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    return "[INFO] Generated config passed load_engine_config() validation."


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        _validate_basic_args(args)
        (
            symbols,
            gateways,
            risk_levels,
            cb_levels,
            symbol_overrides,
            symbol_opt_warnings,
            outstanding_shares,
            seed_mm_mid_range,
        ) = _parse_specs(args)
        indices = _parse_index_specs(args)
        tick_decimals_by_symbol = _tick_decimals_by_symbol(
            symbols, symbol_overrides, int(args.tick_decimals)
        )
        combos = _parse_combo_specs(
            args,
            allowed_symbols=set(symbols),
            tick_decimals_by_symbol=tick_decimals_by_symbol,
        )
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    has_mm_gateway = any(g.role == ParticipantRole.MARKET_MAKER for g in gateways)
    if seed_mm_mid_range is not None and not has_mm_gateway:
        print(
            "[ERROR] --seed-mm-mid-range requires at least one MARKET_MAKER gateway",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        spec = ConfigSpec(
            symbols=symbols,
            gateways=gateways,
            sessions_enabled=bool(args.sessions_enabled),
            snapshot_interval_sec=float(args.snapshot_interval),
            enforce_collars=not args.no_collars,
            enforce_circuit_breakers=not args.no_circuit_breakers,
            static_band_pct=args.static_band,
            dynamic_band_pct=args.dynamic_band,
            risk_levels=risk_levels,
            cb_levels=cb_levels,
            cb_window_ns=int(args.cb_window_ns),
            mm_spread_ticks=int(args.mm_spread_ticks),
            mm_min_qty=int(args.mm_min_qty),
            enforce_mm_obligations=bool(args.enforce_mm_obligations),
            emit_mm_defaults=has_mm_gateway,
            tick_decimals=int(args.tick_decimals),
            seed_last_prices=bool(args.seed_last_prices),
            random_seed=args.seed,
            seed_mm_mid_range=seed_mm_mid_range,
            seed_last_prices_from_mm=bool(args.seed_last_prices_from_mm),
            emit_schedule=_resolve_emit_schedule(args),
            pre_open=str(args.pre_open),
            opening_auction=str(args.opening_auction),
            continuous=str(args.continuous),
            closing_auction=str(args.closing_auction),
            closing_end=str(args.closing_end),
            symbol_overrides=symbol_overrides,
            outstanding_shares=outstanding_shares,
            post_trade_gateway=_build_post_trade_gateway_spec(args),
            market_data_gateway=_build_market_data_gateway_spec(args),
            balf_gateway=_build_balf_gateway_spec(args),
            api_gateways=_build_api_gateway_specs(args, gateways),
            indices=indices,
            combos=combos,
        )
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    output_path = Path(args.output) if args.output else None
    output_exists = bool(output_path and output_path.exists() and not args.force)

    diagnostics = evaluate_diagnostics(
        spec=spec,
        parsed_symbol_option_warnings=symbol_opt_warnings,
        raw_symbols=args.symbols,
        raw_gateways=args.gateways,
        output_exists=output_exists,
    )

    # Fatal if user requested file output but file exists and no --force.
    if output_exists:
        _print_diagnostics(diagnostics)
        raise SystemExit(1)

    config = ConfigBuilder(spec).build()
    cmd_line = "pm-config-gen " + " ".join(sys.argv[1:])
    default_config_field_comment_lines = (
        build_default_engine_field_comment_lines(config)
        if args.comment_default_config_fields
        else None
    )
    rendered = render_yaml(
        config=config,
        command=cmd_line,
        generated_version="1.1.0",
        generated_date=str(date.today()),
        default_engine_field_comments=default_config_field_comment_lines,
    )

    _print_diagnostics(diagnostics)

    validation_line = _validate_generated_when_possible(
        content=rendered,
        skip_validation=has_mm_gateway and seed_mm_mid_range is None,
    )
    if validation_line:
        print(validation_line, file=sys.stderr)

    if args.dry_run or output_path is None:
        print(rendered, end="")
        if not args.dry_run and output_path is None:
            print(
                "[INFO] No --output specified; YAML printed to stdout.",
                file=sys.stderr,
            )
        return

    _write_output(output_path=output_path, content=rendered, force=bool(args.force))
    print(f"[INFO] Wrote generated config to {output_path}", file=sys.stderr)

    if has_mm_gateway and seed_mm_mid_range is None:
        print(
            "[HINT] Fill all market_maker_quotes bid_price/ask_price values before "
            "starting pm-engine.",
            file=sys.stderr,
        )
    print(
        "[HINT] Validate with: poetry run python -c 'from pathlib import Path; "
        "from edumatcher.engine.config_loader import load_engine_config; "
        'print(load_engine_config(Path("engine_config.yaml")))\'',
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
