"""pm-config-gen — generate engine_config.yaml from high-level CLI inputs."""

from __future__ import annotations

import argparse
import math
import sys
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from edumatcher.engine.config_loader import load_engine_config
from edumatcher.models.participant import ParticipantRole

from edumatcher.config_gen.builder import ConfigBuilder, ConfigSpec
from edumatcher.config_gen.builder import ApiCredentialSpec, ApiGatewaySpec
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
    DEFAULT_CB_WINDOW_NS,
    DEFAULT_INDEX_BASE_VALUE,
    DEFAULT_INDEX_PUBLISH_INTERVAL_SEC,
    DEFAULT_MARKET_DATA_GATEWAY_BIND_ADDRESS,
    DEFAULT_MARKET_DATA_GATEWAY_HEARTBEAT_INTERVAL_SEC,
    DEFAULT_MARKET_DATA_GATEWAY_IDLE_TIMEOUT_SEC,
    DEFAULT_MARKET_DATA_GATEWAY_MAX_CLIENT_QUEUE,
    DEFAULT_MARKET_DATA_GATEWAY_MAX_SYMBOLS_PER_CLIENT,
    DEFAULT_MARKET_DATA_GATEWAY_NAME,
    DEFAULT_MARKET_DATA_GATEWAY_PORT,
    DEFAULT_MARKET_DATA_GATEWAY_REPLAY_WINDOW_SEC,
    DEFAULT_MM_MIN_QTY,
    DEFAULT_MM_SPREAD_TICKS,
    DEFAULT_POST_TRADE_GATEWAY_ALLOWED_ROLES,
    DEFAULT_POST_TRADE_GATEWAY_BIND_ADDRESS,
    DEFAULT_POST_TRADE_GATEWAY_HEARTBEAT_INTERVAL_SEC,
    DEFAULT_POST_TRADE_GATEWAY_IDLE_TIMEOUT_SEC,
    DEFAULT_POST_TRADE_GATEWAY_MAX_CLIENT_QUEUE,
    DEFAULT_POST_TRADE_GATEWAY_NAME,
    DEFAULT_POST_TRADE_GATEWAY_PORT,
    DEFAULT_POST_TRADE_GATEWAY_REPLAY_RETENTION_SEC,
    DEFAULT_SNAPSHOT_INTERVAL_SEC,
    DEFAULT_SCHEDULE,
    DEFAULT_TICK_DECIMALS,
)
from edumatcher.config_gen.gateway_spec import GatewaySpec, parse_gateway_spec
from edumatcher.config_gen.renderer import render_yaml
from edumatcher.config_gen.risk_spec import parse_risk_level_spec
from edumatcher.config_gen.symbol_spec import SymbolOverride
from edumatcher.config_gen.symbol_spec import parse_symbol_opts
from edumatcher.config_gen.warnings import evaluate_diagnostics


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-config-gen",
        description=(
            "Generate a parser-compatible engine_config.yaml from concise CLI inputs."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        metavar="SYM",
        help="One or more symbols.",
    )
    parser.add_argument(
        "--gateways",
        nargs="+",
        required=True,
        metavar="GW_SPEC",
        help="One or more gateway specs (ID[:ROLE[:DISCONNECT]]).",
    )
    parser.add_argument(
        "--symbol-opts",
        action="append",
        default=[],
        metavar="SYMBOL:KEY=VALUE[,KEY=VALUE]",
        help="Per-symbol overrides. Can be repeated.",
    )
    parser.add_argument(
        "--symbol-static-band",
        action="append",
        default=[],
        metavar="SYM:PCT",
        help="Per-symbol collar static band pct in (0,1). Can be repeated.",
    )
    parser.add_argument(
        "--symbol-dynamic-band",
        action="append",
        default=[],
        metavar="SYM:PCT",
        help="Per-symbol collar dynamic band pct in (0,1). Can be repeated.",
    )
    parser.add_argument(
        "--symbol-risk-level",
        action="append",
        default=[],
        metavar="SYM:LEVEL",
        help="Per-symbol risk level key override. Can be repeated.",
    )
    parser.add_argument(
        "--outstanding-shares",
        action="append",
        default=[],
        metavar="SYM:N",
        help="Per-symbol outstanding shares (positive integer). Can be repeated.",
    )

    sess_group = parser.add_mutually_exclusive_group()
    sess_group.add_argument(
        "--sessions-enabled",
        dest="sessions_enabled",
        action="store_true",
        help="Enable scheduler-driven sessions.",
    )
    sess_group.add_argument(
        "--no-sessions-enabled",
        dest="sessions_enabled",
        action="store_false",
        help="Disable scheduler-driven sessions.",
    )
    parser.set_defaults(sessions_enabled=False)

    parser.add_argument(
        "--snapshot-interval",
        type=float,
        default=DEFAULT_SNAPSHOT_INTERVAL_SEC,
        metavar="SECS",
        help="Snapshot interval seconds (> 0).",
    )

    parser.add_argument(
        "--no-collars",
        action="store_true",
        help="Set enforce_collars: false.",
    )
    parser.add_argument(
        "--no-circuit-breakers",
        action="store_true",
        help="Set enforce_circuit_breakers: false.",
    )

    parser.add_argument(
        "--static-band",
        type=float,
        default=None,
        metavar="PCT",
        help="DEFAULT static band pct in (0,1).",
    )
    parser.add_argument(
        "--dynamic-band",
        type=float,
        default=None,
        metavar="PCT",
        help="DEFAULT dynamic band pct in (0,1).",
    )

    parser.add_argument(
        "--risk-level",
        action="append",
        default=[],
        metavar="LEVEL_SPEC",
        help="Repeatable NAME:STATIC_PCT[:DYNAMIC_PCT]",
    )

    parser.add_argument(
        "--cb-levels",
        nargs="+",
        default=None,
        metavar="CB_SPEC",
        help="NAME:SHIFT_PCT[:HALT_MINS] entries.",
    )
    parser.add_argument(
        "--cb-window-ns",
        type=int,
        default=DEFAULT_CB_WINDOW_NS,
        metavar="NS",
        help="CB reference window nanoseconds.",
    )

    parser.add_argument(
        "--mm-spread-ticks",
        type=int,
        default=DEFAULT_MM_SPREAD_TICKS,
        metavar="N",
        help="Global MM max spread ticks.",
    )
    parser.add_argument(
        "--mm-min-qty",
        type=int,
        default=DEFAULT_MM_MIN_QTY,
        metavar="N",
        help="Global MM min qty.",
    )

    mm_group = parser.add_mutually_exclusive_group()
    mm_group.add_argument(
        "--enforce-mm-obligations",
        dest="enforce_mm_obligations",
        action="store_true",
        help="Enable MM obligations globally.",
    )
    mm_group.add_argument(
        "--no-enforce-mm-obligations",
        dest="enforce_mm_obligations",
        action="store_false",
        help="Disable MM obligations globally.",
    )
    parser.set_defaults(enforce_mm_obligations=False)

    parser.add_argument(
        "--tick-decimals",
        type=int,
        default=DEFAULT_TICK_DECIMALS,
        metavar="N",
        help="Default symbol tick decimals.",
    )
    parser.add_argument(
        "--seed-last-prices",
        action="store_true",
        help="Emit last_buy_price/last_sell_price null placeholders.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Deterministic RNG seed for generated training values.",
    )
    parser.add_argument(
        "--seed-mm-mid-range",
        default=None,
        metavar="MIN:MAX",
        help=(
            "Seed MM quotes from a random midpoint in the inclusive MIN:MAX range, "
            "rounded to the symbol tick grid."
        ),
    )
    parser.add_argument(
        "--seed-last-prices-from-mm",
        action="store_true",
        help=(
            "When seeding MM quotes, set last_buy_price/last_sell_price to the same "
            "midpoint used for the generated quote."
        ),
    )

    parser.add_argument(
        "--post-trade-gateway",
        action="store_true",
        help="Emit a top-level post_trade_gateway section for pm-ralf-gwy.",
    )
    parser.add_argument(
        "--post-trade-name",
        default=None,
        metavar="NAME",
        help="post_trade_gateway.name override.",
    )
    parser.add_argument(
        "--post-trade-bind-address",
        default=None,
        metavar="ADDR",
        help="post_trade_gateway.bind_address override.",
    )
    parser.add_argument(
        "--post-trade-port",
        type=int,
        default=None,
        metavar="N",
        help="post_trade_gateway.port override (> 0).",
    )
    parser.add_argument(
        "--post-trade-replay-retention-sec",
        type=int,
        default=None,
        metavar="N",
        help="post_trade_gateway.replay_retention_sec override (> 0).",
    )
    parser.add_argument(
        "--post-trade-heartbeat-interval-sec",
        type=int,
        default=None,
        metavar="N",
        help="post_trade_gateway.heartbeat_interval_sec override (> 0).",
    )
    parser.add_argument(
        "--post-trade-idle-timeout-sec",
        type=int,
        default=None,
        metavar="N",
        help="post_trade_gateway.idle_timeout_sec override (> 0).",
    )
    parser.add_argument(
        "--post-trade-max-client-queue",
        type=int,
        default=None,
        metavar="N",
        help="post_trade_gateway.max_client_queue override (> 0).",
    )
    parser.add_argument(
        "--post-trade-allowed-roles",
        nargs="+",
        default=None,
        metavar="ROLE",
        help="post_trade_gateway.allowed_roles override (default: CLEARING DROP_COPY AUDIT).",
    )

    parser.add_argument(
        "--market-data-gateway",
        action="store_true",
        help="Emit a top-level market_data_gateway section for pm-md-gwy.",
    )
    parser.add_argument(
        "--market-data-enabled",
        dest="market_data_enabled",
        action="store_true",
        default=None,
        help="Set market_data_gateway.enabled: true.",
    )
    parser.add_argument(
        "--market-data-disabled",
        dest="market_data_enabled",
        action="store_false",
        default=None,
        help="Set market_data_gateway.enabled: false.",
    )
    parser.add_argument(
        "--market-data-name",
        default=None,
        metavar="NAME",
        help="market_data_gateway.name override.",
    )
    parser.add_argument(
        "--market-data-bind-address",
        default=None,
        metavar="ADDR",
        help="market_data_gateway.bind_address override.",
    )
    parser.add_argument(
        "--market-data-port",
        type=int,
        default=None,
        metavar="N",
        help="market_data_gateway.port override (> 0).",
    )
    parser.add_argument(
        "--market-data-heartbeat-interval-sec",
        type=int,
        default=None,
        metavar="N",
        help="market_data_gateway.heartbeat_interval_sec override (> 0).",
    )
    parser.add_argument(
        "--market-data-idle-timeout-sec",
        type=int,
        default=None,
        metavar="N",
        help="market_data_gateway.idle_timeout_sec override (> 0).",
    )
    parser.add_argument(
        "--market-data-replay-window-sec",
        type=int,
        default=None,
        metavar="N",
        help="market_data_gateway.replay_window_sec override (> 0).",
    )
    parser.add_argument(
        "--market-data-max-symbols-per-client",
        type=int,
        default=None,
        metavar="N",
        help="market_data_gateway.max_symbols_per_client override (> 0).",
    )
    parser.add_argument(
        "--market-data-max-client-queue",
        type=int,
        default=None,
        metavar="N",
        help="market_data_gateway.max_client_queue override (> 0).",
    )

    parser.add_argument(
        "--api-gateway",
        action="store_true",
        help="Emit a top-level api_gateways section for pm-api-gateway.",
    )
    parser.add_argument(
        "--api-gateway-name",
        default="default",
        metavar="NAME",
        help="Name for the generated api_gateways entry when using a single API gateway.",
    )
    parser.add_argument(
        "--api-gateway-instance",
        action="append",
        default=[],
        metavar="NAME:GATEWAY[,GATEWAY...][:PORT]",
        help=(
            "Repeatable named API gateway process. Generates credentials only for "
            "the listed gateway IDs and optionally overrides port."
        ),
    )
    parser.add_argument(
        "--api-gateway-enabled",
        dest="api_gateway_enabled",
        action="store_true",
        default=None,
        help="Set api_gateway.enabled: true.",
    )
    parser.add_argument(
        "--api-gateway-disabled",
        dest="api_gateway_enabled",
        action="store_false",
        default=None,
        help="Set api_gateway.enabled: false.",
    )
    parser.add_argument(
        "--api-gateway-host",
        default=None,
        metavar="ADDR",
        help="api_gateway.host override.",
    )
    parser.add_argument(
        "--api-gateway-port",
        type=int,
        default=None,
        metavar="N",
        help="api_gateway.port override (> 0).",
    )
    parser.add_argument(
        "--api-gateway-swagger-enabled",
        dest="api_gateway_swagger_enabled",
        action="store_true",
        default=None,
        help="Set api_gateway.swagger_enabled: true.",
    )
    parser.add_argument(
        "--api-gateway-swagger-disabled",
        dest="api_gateway_swagger_enabled",
        action="store_false",
        default=None,
        help="Set api_gateway.swagger_enabled: false.",
    )
    parser.add_argument(
        "--api-gateway-log-level",
        default=None,
        choices=["debug", "info", "warning", "error"],
        help="api_gateway.log_level override.",
    )
    parser.add_argument(
        "--api-gateway-stats-db",
        default=None,
        metavar="PATH",
        help="api_gateway.stats_db override.",
    )
    parser.add_argument(
        "--api-key",
        action="append",
        default=[],
        metavar="KEY:GATEWAY_ID[:DESCRIPTION]",
        help=(
            "Explicit api_gateways credential for single-instance generation. Use GATEWAY_ID=null for a read-only "
            "market-data key. Can be repeated."
        ),
    )
    api_key_group = parser.add_mutually_exclusive_group()
    api_key_group.add_argument(
        "--api-gateway-generate-keys",
        dest="api_gateway_generate_keys",
        action="store_true",
        default=None,
        help="Generate one API key for each configured ALF gateway when api_gateway is emitted.",
    )
    api_key_group.add_argument(
        "--no-api-gateway-generate-keys",
        dest="api_gateway_generate_keys",
        action="store_false",
        default=None,
        help="Do not auto-generate API keys for ALF gateways.",
    )
    parser.add_argument(
        "--api-gateway-readonly-key",
        action="store_true",
        help="Generate an additional read-only API key with gateway_id: null.",
    )
    parser.add_argument(
        "--api-gateway-rate-limit-writes-per-second",
        type=int,
        default=None,
        metavar="N",
        help="api_gateway.rate_limit.writes_per_second override (> 0).",
    )
    parser.add_argument(
        "--api-gateway-rate-limit-burst",
        type=int,
        default=None,
        metavar="N",
        help="api_gateway.rate_limit.burst override (> 0).",
    )
    parser.add_argument(
        "--api-gateway-engine-auth-sec",
        type=float,
        default=None,
        metavar="SECS",
        help="api_gateway.timeouts.engine_auth_sec override (> 0).",
    )
    parser.add_argument(
        "--api-gateway-engine-reply-sec",
        type=float,
        default=None,
        metavar="SECS",
        help="api_gateway.timeouts.engine_reply_sec override (> 0).",
    )
    parser.add_argument(
        "--api-gateway-wait-ack-sec",
        type=float,
        default=None,
        metavar="SECS",
        help="api_gateway.timeouts.wait_ack_sec override (> 0).",
    )

    sched_group = parser.add_mutually_exclusive_group()
    sched_group.add_argument(
        "--schedule",
        dest="schedule",
        action="store_true",
        default=None,
        help="Force emit schedule section.",
    )
    sched_group.add_argument(
        "--no-schedule",
        dest="schedule",
        action="store_false",
        default=None,
        help="Suppress schedule section.",
    )

    parser.add_argument(
        "--pre-open", default=DEFAULT_SCHEDULE["pre_open"], metavar="HH:MM"
    )
    parser.add_argument(
        "--opening-auction",
        default=DEFAULT_SCHEDULE["opening_auction_start"],
        metavar="HH:MM",
    )
    parser.add_argument(
        "--continuous",
        default=DEFAULT_SCHEDULE["continuous_start"],
        metavar="HH:MM",
    )
    parser.add_argument(
        "--closing-auction",
        default=DEFAULT_SCHEDULE["closing_auction_start"],
        metavar="HH:MM",
    )
    parser.add_argument(
        "--closing-end",
        default=DEFAULT_SCHEDULE["closing_auction_end"],
        metavar="HH:MM",
    )

    parser.add_argument(
        "--index",
        action="append",
        default=[],
        metavar="ID[:DESCRIPTION]",
        help=(
            "Define an index (repeatable, up to 5). "
            "ID is alphanumeric; DESCRIPTION is optional text after the first colon."
        ),
    )
    parser.add_argument(
        "--index-constituents",
        action="append",
        default=[],
        metavar="ID:SYM[,SYM,...]",
        help="Constituent symbols for an index. Can be repeated.",
    )
    parser.add_argument(
        "--index-base-value",
        action="append",
        default=[],
        metavar="ID:VALUE",
        help="Override base_value for an index (default: 1000.0). Can be repeated.",
    )
    parser.add_argument(
        "--index-interval",
        action="append",
        default=[],
        metavar="ID:SECS",
        help="Override publish_interval_sec for an index (default: 1.0). Can be repeated.",
    )
    parser.add_argument(
        "--index-history-file",
        action="append",
        default=[],
        metavar="ID:PATH",
        help="Override history_file path for an index. Can be repeated.",
    )
    parser.add_argument(
        "--index-state-file",
        action="append",
        default=[],
        metavar="ID:PATH",
        help="Override state_file path for an index. Can be repeated.",
    )

    parser.add_argument(
        "--output", default=None, metavar="FILE", help="Output file path."
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing output file."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print only, do not write."
    )
    parser.add_argument(
        "--comment-default-config-fields",
        action="store_true",
        help=(
            "Add a header comment block listing defaultable engine_config fields "
            "and their default values."
        ),
    )

    return parser


def _build_default_engine_field_comment_lines(config: dict[str, object]) -> list[str]:
    """Build comprehensive comment block for optional engine configuration fields.

    Mimics the sample YAML format with three sections:
    - Overview & top-level settings
    - Complete recognized configuration shape (all optional fields with examples)
    - Field notes and accepted values (detailed field documentation)
    """
    lines: list[str] = []

    # =========================================================================
    # Section 1: Header and overview
    # =========================================================================
    lines.extend(
        [
            "=============================================================================",
            "Complete Recognized Configuration Shape",
            "=============================================================================",
            "",
            "The following commented example lists optional top-level entries and nested",
            "fields recognized by the current engine and scheduler parsers. Leave entries",
            "commented unless you need them.",
            "",
        ]
    )

    # sessions_enabled
    lines.extend(
        [
            "sessions_enabled: true",
            "  Controls whether the scheduler owns session-state transitions.",
            "  true  = engine starts CLOSED and pm-scheduler drives the trading-day timeline.",
            "  false = engine starts in CONTINUOUS and ignores scheduler session transitions.",
            "",
        ]
    )

    # enforce_collars
    lines.extend(
        [
            "enforce_collars: true",
            "  Global switch for price-collar validation on incoming orders.",
            "",
        ]
    )

    # enforce_circuit_breakers
    lines.extend(
        [
            "enforce_circuit_breakers: true",
            "  Global switch for circuit-breaker halt detection and enforcement.",
            "",
        ]
    )

    # snapshot_interval_sec
    lines.extend(
        [
            "snapshot_interval_sec: 0.5",
            "  Minimum interval between published book snapshots for a dirty symbol.",
            "  Reduces outbound snapshot volume while preserving near-real-time updates.",
            "",
        ]
    )

    # mm_obligation_defaults
    lines.extend(
        [
            "mm_obligation_defaults:",
            "  enforce_mm_obligation: false",
            "  mm_max_spread_ticks: 10",
            "  mm_min_qty: 100",
            "  symbols:",
            "    AAPL:",
            "      enforce_mm_obligation: true",
            "      mm_max_spread_ticks: 8",
            "      mm_min_qty: 200",
            "",
        ]
    )

    # risk_controls
    lines.extend(
        [
            "risk_controls:",
            "  default_level: L2",
            "  levels:",
            "    L1:",
            "      collar:",
            "        static_band_pct: 0.30",
            "        dynamic_band_pct: 0.05",
            "    L2:",
            "      collar:",
            "        static_band_pct: 0.20",
            "        dynamic_band_pct: 0.02",
            "",
        ]
    )

    # circuit_breaker_defaults
    lines.extend(
        [
            "circuit_breaker_defaults:",
            "  reference_window_ns: 300000000000",
            "  levels:",
            "    L1:",
            "      price_shift_pct: 0.07",
            "      halt_duration_ns: 300000000000",
            "      resumption_mode: AUCTION",
            "    L2:",
            "      price_shift_pct: 0.13",
            "      halt_duration_ns: 900000000000",
            "      resumption_mode: AUCTION",
            "    L3:",
            "      price_shift_pct: 0.20",
            "      halt_duration_ns: null",
            "      resumption_mode: AUCTION",
            "",
        ]
    )

    # gateways
    lines.extend(
        [
            "gateways:",
            "  alf:",
            "    - id: TRADER01",
            "      description: Student workstation 1",
            "      role: TRADER",
            "      disconnect_behaviour: CANCEL_ALL",
            "      quote_refresh_policy: INACTIVATE_ON_ANY_FILL",
            "      enforce_mm_obligation: false",
            "      mm_max_spread_ticks: 10",
            "      mm_min_qty: 100",
            "      mm_obligations:",
            "        AAPL:",
            "          enforce_mm_obligation: true",
            "          max_spread_ticks: 6",
            "          min_qty: 300",
            "",
        ]
    )

    # symbols section
    lines.extend(
        [
            "symbols:",
            "  AAPL:",
            "    tick_decimals: 2",
            "    level: L2",
            "    last_buy_price: 209.50",
            "    last_sell_price: 210.50",
            "    outstanding_shares: 2600000000",
            "    collar:",
            "      static_band_pct: 0.20",
            "      dynamic_band_pct: 0.02",
            "    circuit_breaker:",
            "      reference_window_ns: 300000000000",
            "      levels:",
            "        L1:",
            "          price_shift_pct: 0.07",
            "          halt_duration_ns: 300000000000",
            "          resumption_mode: AUCTION",
            "        L2:",
            "          price_shift_pct: 0.13",
            "          halt_duration_ns: 900000000000",
            "          resumption_mode: CONTINUOUS",
            "        L3:",
            "          price_shift_pct: 0.20",
            "          halt_duration_ns:",
            "          resumption_mode: AUCTION",
            "    market_maker_quotes:",
            "      - gateway_id: MM01",
            "        quote_id: SEED-MM01-AAPL",
            "        bid_price: 209.00",
            "        ask_price: 211.00",
            "        bid_qty: 1000",
            "        ask_qty: 1000",
            "        tif: DAY",
            "        seed_once: true",
            "",
        ]
    )

    # market_maker_combos
    lines.extend(
        [
            "market_maker_combos:",
            "  - combo_id: SEED-PAIR-AAPL-MSFT",
            "    combo_type: AON",
            "    tif: DAY",
            "    legs:",
            "      - symbol: AAPL",
            "        side: BUY",
            "        order_type: LIMIT",
            "        quantity: 100",
            "        price: 20950",
            "        stop_price: null",
            "        smp_action: NONE",
            "      - symbol: MSFT",
            "        side: SELL",
            "        order_type: LIMIT",
            "        quantity: 50",
            "        price: 41550",
            "        stop_price: null",
            "        smp_action: NONE",
            "",
        ]
    )

    # post_trade_gateway
    lines.extend(
        [
            "post_trade_gateway:",
            "  name: ralf-gwy01",
            "  bind_address: 0.0.0.0",
            "  port: 5580",
            "  replay_retention_sec: 86400",
            "  heartbeat_interval_sec: 1",
            "  idle_timeout_sec: 5",
            "  max_client_queue: 10000",
            "  allowed_roles: [CLEARING, DROP_COPY, AUDIT]",
            "",
        ]
    )

    # market_data_gateway
    lines.extend(
        [
            "market_data_gateway:",
            "  enabled: true",
            "  name: md-gwy01",
            "  bind_address: 0.0.0.0",
            "  port: 5570",
            "  heartbeat_interval_sec: 1",
            "  idle_timeout_sec: 5",
            "  replay_window_sec: 30",
            "  max_symbols_per_client: 200",
            "  max_client_queue: 10000",
            "",
        ]
    )

    # indices
    lines.extend(
        [
            "indices:",
            "  - id: EDU100",
            "    description: Broad technology benchmark",
            "    base_value: 1000.0",
            "    publish_interval_sec: 1.0",
            "    history_file: data/indexes/EDU100_history.jsonl",
            "    state_file: data/indexes/EDU100_state.json",
            "    constituents: [AAPL, MSFT, TSLA]",
            "  - id: EDUFIN",
            "    description: Financial sector basket",
            "    base_value: 1000.0",
            "    publish_interval_sec: 1.0",
            "    history_file: data/indexes/EDUFIN_history.jsonl",
            "    state_file: data/indexes/EDUFIN_state.json",
            "    constituents: [JPM, BAC, GS]",
            "",
        ]
    )

    # api_gateways
    lines.extend(
        [
            "api_gateways:",
            "  desk:",
            "    enabled: true",
            "    host: 127.0.0.1",
            "    port: 8080",
            "    swagger_enabled: true",
            "    log_level: info",
            "    stats_db: data/stats.db",
            "    credentials:",
            "      - api_key: key-trader-demo",
            "        gateway_id: TRADER01",
            "        description: Demo trading client",
            "    rate_limit:",
            "      writes_per_second: 10",
            "      burst: 20",
            "    timeouts:",
            "      engine_auth_sec: 3.0",
            "      engine_reply_sec: 3.0",
            "      wait_ack_sec: 3.0",
            "  dashboards:",
            "    enabled: true",
            "    host: 127.0.0.1",
            "    port: 8081",
            "    credentials:",
            "      - api_key: key-dashboard-demo",
            "        gateway_id: null",
            "        description: Read-only dashboard client",
            "",
        ]
    )

    # schedule
    lines.extend(
        [
            "schedule:",
            '  pre_open: "09:00"',
            '  opening_auction_start: "09:25"',
            '  continuous_start: "09:30"',
            '  closing_auction_start: "16:00"',
            '  closing_auction_end: "16:05"',
            "",
        ]
    )

    # =========================================================================
    # Section 2: Field notes and accepted values
    # =========================================================================
    lines.extend(
        [
            "=============================================================================",
            "Field Notes and Accepted Values",
            "=============================================================================",
            "",
        ]
    )

    lines.extend(
        [
            "mm_obligation_defaults entries",
            "" + "-" * 30,
            "enforce_mm_obligation: false",
            "  Enables exchange-side market-maker compliance checks for quote width and size.",
            "mm_max_spread_ticks: 10",
            "  Maximum allowed bid-ask spread (in ticks) for obligated quotes.",
            "mm_min_qty: 100",
            "  Minimum displayed quantity required on each side of an obligated quote.",
            "symbols:",
            "  Per-symbol policy overrides when different instruments require different",
            "  quoting obligations. Keys must match configured symbols.",
            "  Effective precedence is: gateway mm_obligations >",
            "  mm_obligation_defaults.symbols > gateway flat fields >",
            "  mm_obligation_defaults flat fields > built-in defaults.",
            "",
        ]
    )

    lines.extend(
        [
            "risk_controls entries",
            "" + "-" * 21,
            "default_level: L2",
            "  Baseline risk profile applied to symbols that do not set a symbol-specific level.",
            "levels:",
            "  Named risk profile catalog used by symbols and by default_level.",
            "levels.<NAME>.collar:",
            "  Price-band configuration for order acceptance checks:",
            "  static_band_pct anchors to a session reference, dynamic_band_pct tracks live prices.",
            "levels.<NAME>.collar.static_band_pct: 0.20",
            "  Wider static guardrail around the reference price.",
            "levels.<NAME>.collar.dynamic_band_pct: 0.02",
            "  Tighter dynamic guardrail around near-live trading levels.",
            "  Precedence: symbols.<SYM>.collar > symbols.<SYM>.level >",
            "  risk_controls.default_level > built-in defaults.",
            "  Note: levels.<NAME>.circuit_breaker is not supported; use",
            "  circuit_breaker_defaults at the top level instead.",
            "",
        ]
    )

    lines.extend(
        [
            "circuit_breaker_defaults entries",
            "" + "-" * 33,
            "reference_window_ns: 300000000000",
            "  Lookback window used to compute the rolling reference price for halt triggers.",
            "levels:",
            "  Halt ladder definitions applied exchange-wide unless overridden per symbol.",
            "  Symbol-level circuit_breaker.levels entries merge field-by-field over defaults.",
            "levels.<NAME>.price_shift_pct:",
            "  Percent move from the rolling reference price required to trigger this halt level.",
            "levels.<NAME>.halt_duration_ns: null",
            "  Halt length for this level; null means halt remains active for the rest of day.",
            "  Built-in ladder values: L1=300000000000 (5m), L2=900000000000",
            "  (15m), L3=null.",
            "levels.<NAME>.resumption_mode: AUCTION",
            "  How trading resumes after the halt: AUCTION runs an uncross,",
            "  CONTINUOUS reopens matching immediately.",
            "  Built-in default ladder: L1=7%/5m, L2=13%/15m, L3=20%/rest-of-day.",
            "",
        ]
    )

    lines.extend(
        [
            "gateways.alf entries",
            "" + "-" * 20,
            "id:",
            "  Participant session identifier used for login, permissions, and routing.",
            "description: null",
            "  Operator-facing label for dashboards and diagnostics.",
            "role: TRADER",
            "  Permission profile: TRADER submits orders, MARKET_MAKER supplies quotes,",
            "  ADMIN can issue exchange control commands.",
            "disconnect_behaviour: CANCEL_QUOTES_ONLY",
            "  Cleanup action on disconnect to control stale exposure risk.",
            "quote_refresh_policy: INACTIVATE_ON_ANY_FILL",
            "  Determines when seeded quotes are inactivated after executions.",
            "enforce_mm_obligation: false",
            "  Gateway-level switch to enforce market-maker obligations for this participant.",
            "mm_max_spread_ticks: 10",
            "  Gateway-level quote spread cap used by obligation checks.",
            "mm_min_qty: 100",
            "  Gateway-level minimum quote size used by obligation checks.",
            "mm_obligations:",
            "  Per-symbol overrides for this gateway when obligations differ by instrument.",
            "  Use enforce_mm_obligation, max_spread_ticks, and min_qty inside this map.",
            "mm_obligations.<SYM>.enforce_mm_obligation: false",
            "  Per-symbol switch enabling/disabling obligation checks for this gateway.",
            "mm_obligations.<SYM>.max_spread_ticks: 10",
            "  Per-symbol spread cap in ticks.",
            "mm_obligations.<SYM>.min_qty: 100",
            "  Per-symbol minimum quote size.",
            "",
        ]
    )

    lines.extend(
        [
            "symbols entries",
            "" + "-" * 15,
            "tick_decimals: 2",
            "  Display precision and tick-size conversion for all prices of this symbol.",
            "level:",
            "  Symbol's assigned risk profile name from risk_controls.levels.",
            "  If omitted, the symbol inherits risk_controls.default_level.",
            "last_buy_price: null",
            "last_sell_price: null",
            "  Startup seed values for last-trade references before live or persisted history exists.",
            "outstanding_shares: null",
            "  Issued share count used by analytics, reporting, and index-style consumers.",
            "collar:",
            "  Symbol-specific collar override when this instrument needs tighter/looser bands.",
            "collar.static_band_pct: 0.20",
            "  Symbol-level static guardrail around reference price.",
            "collar.dynamic_band_pct: 0.02",
            "  Symbol-level dynamic guardrail around near-live prices.",
            "circuit_breaker:",
            "  Symbol-specific halt policy override layered on top of circuit_breaker_defaults.",
            "  Levels merge field-by-field, so each symbol can override only needed fields.",
            "circuit_breaker.reference_window_ns: 300000000000",
            "  Symbol-specific rolling reference window for halt detection.",
            "circuit_breaker.levels.<NAME>.price_shift_pct: 0.07",
            "  Percent move threshold that triggers halt level <NAME>.",
            "circuit_breaker.levels.<NAME>.halt_duration_ns: null",
            "  Halt duration for level <NAME>; null means rest-of-day.",
            "circuit_breaker.levels.<NAME>.resumption_mode: AUCTION",
            "  Trading resumption behavior for level <NAME>.",
            "  halt_duration_ns may be null for rest-of-day halts.",
            "  reference_window_ns can override the global rolling reference window.",
            "market_maker_quotes:",
            "  Startup quote seeds used to initialize liquidity for this symbol.",
            "  Required when MARKET_MAKER gateways are configured.",
            "  gateway_id must reference a configured MARKET_MAKER gateway.",
            "",
        ]
    )

    lines.extend(
        [
            "market_maker_quotes entries (under symbols.<SYM>.market_maker_quotes)",
            "" + "-" * 68,
            "gateway_id:",
            "  Market-maker session that owns and submits this seed quote.",
            "quote_id: null",
            "  External quote identifier for audit/reconciliation; auto-generated when omitted.",
            "bid_price / ask_price:",
            "  Initial two-sided quote prices used to seed the order book.",
            "  bid_price must be less than ask_price; engine converts display prices to ticks.",
            "bid_qty / ask_qty:",
            "  Initial displayed quantities for each side of the seeded quote.",
            "tif: DAY",
            "  Time-in-force policy for the seeded quote lifecycle.",
            "  Prefer DAY for seeds — GTC seeds can duplicate on restart if",
            "  gtc_orders.json still contains the previous session's orders.",
            "seed_once: true",
            "  Prevents re-injecting the same seed quote after restart when history already exists.",
            "",
        ]
    )

    lines.extend(
        [
            "market_maker_combos entries",
            "" + "-" * 27,
            "combo_id:",
            "  Stable identifier for this seeded multi-leg strategy.",
            "combo_type: AON",
            "  Execution rule for the combo (AON executes all legs together).",
            "tif: DAY",
            "  Time-in-force policy for the combo order.",
            "legs:",
            "  Ordered leg definitions that specify how the strategy is composed.",
            "  Requires 2..10 legs; symbols must be configured and unique per combo.",
            "leg.symbol:",
            "  Instrument traded by this leg; must reference a configured symbol.",
            "leg.side:",
            "  Direction of this leg within the strategy (BUY or SELL).",
            "leg.order_type:",
            "  Execution style for this leg (MARKET, LIMIT, STOP, etc.).",
            "leg.quantity:",
            "  Quantity contributed by this leg to each combo execution.",
            "leg.price:",
            "  Tick price used by priced order types (LIMIT, STOP_LIMIT, FOK, ICEBERG, IOC).",
            "  Example: with tick_decimals=2, display 209.50 is stored as tick 20950.",
            "leg.stop_price:",
            "  Trigger price in ticks for STOP, STOP_LIMIT, and TRAILING_STOP leg types.",
            "leg.smp_action: NONE",
            "  Self-match prevention behavior when this leg would cross own resting interest.",
            "",
        ]
    )

    lines.extend(
        [
            "post_trade_gateway entries",
            "" + "-" * 27,
            "name: ralf-gwy01",
            "  Service name used in logs, telemetry, and client diagnostics.",
            "bind_address: 0.0.0.0",
            "  Network interface/address the post-trade server listens on for incoming clients.",
            "port: 5580",
            "  TCP port clients connect to for fills, drop copy, and post-trade replay.",
            "replay_retention_sec: 86400",
            "  How long post-trade events are retained for client replay after reconnect.",
            "heartbeat_interval_sec: 1",
            "  Keepalive interval used to prove connection liveness to clients.",
            "idle_timeout_sec: 5",
            "  Disconnect threshold when a client is silent for too long.",
            "max_client_queue: 10000",
            "  Per-client outbound backlog limit before applying backpressure/disconnect logic.",
            "allowed_roles: [CLEARING, DROP_COPY, AUDIT]",
            "  Roles authorized to subscribe to this gateway's post-trade data stream.",
            "",
        ]
    )

    lines.extend(
        [
            "market_data_gateway entries",
            "" + "-" * 28,
            "enabled: true",
            "  Master switch that enables or disables the market data gateway service.",
            "name: md-gwy01",
            "  Service name shown in logs, monitoring, and client banners.",
            "bind_address: 0.0.0.0",
            "  Network interface/address the market data server binds to.",
            "port: 5570",
            "  TCP port clients connect to for snapshots, deltas, and replay requests.",
            "heartbeat_interval_sec: 1",
            "  Keepalive cadence for market-data client sessions.",
            "idle_timeout_sec: 5",
            "  Session timeout when no traffic is received from a client.",
            "replay_window_sec: 30",
            "  In-memory replay horizon available to late/reconnecting clients.",
            "max_symbols_per_client: 200",
            "  Subscription safety limit to prevent a single client from over-consuming fanout.",
            "max_client_queue: 10000",
            "  Per-client outbound queue cap before overload handling is triggered.",
            "",
        ]
    )

    lines.extend(
        [
            "api_gateways entries",
            "" + "-" * 20,
            "api_gateways.<NAME>:",
            "  Named REST/WebSocket gateway process configuration.",
            "enabled: true",
            "  Master switch that lets pm-api-gateway start serving clients.",
            "host: 127.0.0.1",
            "  HTTP bind address used by uvicorn.",
            "port: 8080",
            "  HTTP listen port for REST and WebSocket clients.",
            "swagger_enabled: true",
            "  Enables /docs and /openapi.json when true.",
            "log_level: info",
            "  Uvicorn logging level: debug, info, warning, or error.",
            "stats_db: data/stats.db",
            "  SQLite stats database used by /history endpoints.",
            "credentials:",
            "  Bearer-token credentials accepted by REST and WebSocket auth.",
            "credentials[].gateway_id:",
            "  Must reference gateways.alf[].id for trading access; null means read-only.",
            "  A non-null gateway_id may appear in only one api_gateways entry.",
            "rate_limit.writes_per_second: 10",
            "  Per API-key write throughput for POST/PATCH/DELETE routes.",
            "rate_limit.burst: 20",
            "  Per API-key burst capacity for write routes.",
            "timeouts.engine_auth_sec: 3.0",
            "  Intended engine-auth handshake timeout setting.",
            "timeouts.engine_reply_sec: 3.0",
            "  Timeout for engine request/reply read endpoints.",
            "timeouts.wait_ack_sec: 3.0",
            "  Timeout for write endpoints using ?wait=ack.",
            "",
        ]
    )

    lines.extend(
        [
            "schedule entries",
            "" + "-" * 16,
            "pre_open: 09:00",
            "  Start of pre-open state, when participants can stage orders before opening auction.",
            "opening_auction_start: 09:25",
            "  Time the opening uncross begins and opening match logic takes over.",
            "continuous_start: 09:30",
            "  Transition from opening auction into continuous limit-order-book matching.",
            "closing_auction_start: 16:00",
            "  Time the closing auction phase begins and continuous matching stops.",
            "closing_auction_end: 16:05",
            "  End of closing auction and completion of the trading session timeline.",
            "  Times are HH:MM in local server time and are applied in trading-day order.",
            "",
        ]
    )

    lines.extend(
        [
            "indices entries",
            "" + "-" * 15,
            "id:",
            "  Alphanumeric index identifier used in messages, file names, and CALF subscriptions.",
            "description:",
            "  Human-readable label shown in operator output and diagnostics.",
            "base_value: 1000.0",
            "  Starting level that the divisor is calibrated to at launch.",
            "publish_interval_sec: 1.0",
            "  Throttle: minimum seconds between consecutive index.update broadcasts.",
            "history_file: data/indexes/<ID>_history.jsonl",
            "  Append-only JSONL file where pm-index records LEVEL, EOD, and CORP_ACTION entries.",
            "state_file: data/indexes/<ID>_state.json",
            "  JSON checkpoint file used to recover divisor and last prices across restarts.",
            "constituents:",
            "  Ordered list of symbol IDs included in this index; each must be configured in symbols.",
            "  Each constituent symbol must have outstanding_shares set.",
            "  Maximum 5 indices per exchange; maximum constituents per index limited by performance.",
            "",
        ]
    )

    return lines


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
    parser = _build_parser()
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
            api_gateways=_build_api_gateway_specs(args, gateways),
            indices=indices,
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
        _build_default_engine_field_comment_lines(config)
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
