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
from edumatcher.config_gen.builder import MarketDataGatewaySpec
from edumatcher.config_gen.builder import PostTradeGatewaySpec
from edumatcher.config_gen.cb_spec import CbSpec, parse_cb_spec
from edumatcher.config_gen.defaults import (
    DEFAULT_CB_WINDOW_NS,
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
            "  Boolean. Default: true.",
            "  true  = engine starts CLOSED and pm-scheduler drives session transitions.",
            "  false = engine starts in CONTINUOUS and scheduler transitions are ignored.",
            "",
        ]
    )

    # enforce_collars
    lines.extend(
        [
            "enforce_collars: true",
            "  Boolean. Default: true. Set false to disable price-collar checks globally.",
            "",
        ]
    )

    # enforce_circuit_breakers
    lines.extend(
        [
            "enforce_circuit_breakers: true",
            "  Boolean. Default: true. Set false to disable circuit-breaker halts globally.",
            "",
        ]
    )

    # snapshot_interval_sec
    lines.extend(
        [
            "snapshot_interval_sec: 0.5",
            "  Numeric seconds. Default: 0.5. Must be > 0.",
            "  Throttles book.<SYMBOL> snapshot publications per symbol.",
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
            "      halt_duration_ns:",
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
            "        stop_price:",
            "        smp_action: NONE",
            "      - symbol: MSFT",
            "        side: SELL",
            "        order_type: LIMIT",
            "        quantity: 50",
            "        price: 41550",
            "        stop_price:",
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

    # schedule
    lines.extend(
        [
            "schedule:",
            'pre_open: "09:00"',
            'opening_auction_start: "09:25"',
            'continuous_start: "09:30"',
            'closing_auction_start: "16:00"',
            'closing_auction_end: "16:05"',
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
            "enforce_mm_obligation:",
            "  Boolean. Default: false.",
            "mm_max_spread_ticks:",
            "  Positive integer. Default: 10.",
            "mm_min_qty:",
            "  Positive integer. Default: 100.",
            "symbols:",
            "  Optional per-symbol override mapping. Each entry supports the same three",
            "  fields: enforce_mm_obligation, mm_max_spread_ticks, mm_min_qty.",
            "  Symbol keys are uppercased. Each symbol must be present in symbols:.",
            "  Effective policy resolves most-specific-first: gateway mm_obligations >",
            "  mm_obligation_defaults.symbols > gateway flat fields >",
            "  mm_obligation_defaults flat fields > built-in defaults.",
            "",
        ]
    )

    lines.extend(
        [
            "risk_controls entries",
            "" + "-" * 21,
            "default_level:",
            "  Optional string. Must reference a key in risk_controls.levels.",
            "levels:",
            "  Mapping of named level configs. Level names are uppercased.",
            "levels.<NAME>.collar:",
            "  Optional mapping with static_band_pct and dynamic_band_pct in (0, 1).",
            "  Defaults when a collar is active: static_band_pct=0.20, dynamic_band_pct=0.02.",
            "  Collar precedence: symbols.<SYM>.collar > symbols.<SYM>.level >",
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
            "reference_window_ns:",
            "  Integer nanoseconds. Default: 300000000000 (5 minutes).",
            "levels:",
            "  Non-empty mapping of named threshold levels. Applies to every symbol that",
            "  does not define its own circuit_breaker section. Symbol-level",
            "  circuit_breaker.levels entries merge over these defaults field by field.",
            "levels.<NAME>.price_shift_pct:",
            "  Required float in (0, 1). Halt triggers when a fill moves this far from",
            "  the rolling reference price.",
            "levels.<NAME>.halt_duration_ns:",
            "  Positive integer nanoseconds, or null for a rest-of-day halt.",
            "  Default: null. Built-in defaults: L1=300000000000 (5m), L2=900000000000",
            "  (15m), L3=null.",
            "levels.<NAME>.resumption_mode:",
            "  AUCTION | CONTINUOUS. Default: AUCTION.",
            "  AUCTION runs an uncross before returning to continuous matching.",
            "  CONTINUOUS resumes matching immediately.",
            "  Built-in default ladder: L1=7%/5m, L2=13%/15m, L3=20%/rest-of-day.",
            "",
        ]
    )

    lines.extend(
        [
            "gateways.alf entries",
            "" + "-" * 20,
            "id:",
            "  Required string. Gateway ids are uppercased by the parser.",
            "description:",
            "  Optional string. Null is accepted and treated as an empty string.",
            "role:",
            "  TRADER | MARKET_MAKER | ADMIN. Default: TRADER.",
            "disconnect_behaviour:",
            "  CANCEL_QUOTES_ONLY | CANCEL_ALL | LEAVE_ALL. Default: CANCEL_QUOTES_ONLY.",
            "quote_refresh_policy:",
            "  INACTIVATE_ON_ANY_FILL | INACTIVATE_ON_FULL_FILL | NEVER_INACTIVATE.",
            "  Default: INACTIVATE_ON_ANY_FILL.",
            "enforce_mm_obligation:",
            "  Boolean. Defaults from mm_obligation_defaults.enforce_mm_obligation.",
            "mm_max_spread_ticks:",
            "  Positive integer. Defaults from mm_obligation_defaults.mm_max_spread_ticks.",
            "mm_min_qty:",
            "  Positive integer. Defaults from mm_obligation_defaults.mm_min_qty.",
            "mm_obligations:",
            "  Optional per-symbol mapping. Inside this mapping use max_spread_ticks and",
            "  min_qty, not mm_max_spread_ticks and mm_min_qty.",
            "",
        ]
    )

    lines.extend(
        [
            "symbols entries",
            "" + "-" * 15,
            "tick_decimals:",
            "  Integer 0..8. Default: 2.",
            "level:",
            "  Optional named risk level from risk_controls.levels. If omitted, inherits",
            "  risk_controls.default_level when that default is configured.",
            "last_buy_price / last_sell_price:",
            "  Optional numbers used to seed last buy/sell references before any trades or",
            "  persisted book_stats.json values exist.",
            "outstanding_shares:",
            "  Optional integer. Useful for statistics and external index-style consumers.",
            "  When omitted, defaults to null.",
            "collar:",
            "  Optional mapping. Values override inherited risk_controls level fields.",
            "  static_band_pct and dynamic_band_pct must both be in (0, 1).",
            "circuit_breaker:",
            "  Optional mapping. Level keys are arbitrary names. Symbol-level levels merge",
            "  field by field over circuit_breaker_defaults, so a level may override only",
            "  halt_duration_ns or resumption_mode and inherit price_shift_pct from the",
            "  defaults. After merging, every level must have price_shift_pct in (0, 1).",
            "  halt_duration_ns may be null, meaning halt for the rest of the trading day.",
            "  reference_window_ns may also be set here to override the default window.",
            "market_maker_quotes:",
            "  Optional list unless any gateway has role MARKET_MAKER. If MARKET_MAKER",
            "  gateways exist, every configured symbol must define at least one quote seed.",
            "  gateway_id must reference a configured MARKET_MAKER gateway.",
            "",
        ]
    )

    lines.extend(
        [
            "market_maker_quotes entries (under symbols.<SYM>.market_maker_quotes)",
            "" + "-" * 68,
            "gateway_id:",
            "  Required string. Uppercased. Must reference a MARKET_MAKER gateway.",
            "quote_id:",
            "  Optional string. Empty string is treated as absent; engine auto-generates.",
            "bid_price / ask_price:",
            "  Required numbers (display price). bid_price must be less than ask_price.",
            "  Converted to integer ticks by the engine using tick_decimals.",
            "bid_qty / ask_qty:",
            "  Required positive integers.",
            "tif:",
            "  DAY | GTC | ATO | ATC. Default: DAY.",
            "  Prefer DAY for seeds — GTC seeds can duplicate on restart if",
            "  gtc_orders.json still contains the previous session's orders.",
            "seed_once:",
            "  Boolean. Default: true. When true, injection is skipped if",
            "  book_stats.json already has history for this symbol.",
            "",
        ]
    )

    lines.extend(
        [
            "market_maker_combos entries",
            "" + "-" * 27,
            "combo_id:",
            "  Required non-empty string.",
            "combo_type:",
            "  AON. Default: AON.",
            "tif:",
            "  DAY | GTC | ATO | ATC. Default: DAY.",
            "legs:",
            "  Required list with 2..10 entries. Symbols must be configured and unique",
            "  within the combo.",
            "leg.symbol:",
            "  Required string. Must reference a configured symbol. Uppercased. Must be",
            "  unique within the combo.",
            "leg.side:",
            "  BUY | SELL.",
            "leg.order_type:",
            "  MARKET | LIMIT | STOP | STOP_LIMIT | FOK | ICEBERG | IOC | TRAILING_STOP.",
            "leg.quantity:",
            "  Required integer quantity.",
            "leg.price:",
            "  Optional integer tick price used by priced order types (LIMIT, STOP_LIMIT,",
            "  FOK, ICEBERG, IOC). With tick_decimals: 2, display 209.50 = tick 20950.",
            "leg.stop_price:",
            "  Optional integer tick stop price used by stop order types (STOP, STOP_LIMIT,",
            "  TRAILING_STOP).",
            "leg.smp_action:",
            "  NONE | CANCEL_AGGRESSOR | CANCEL_RESTING | CANCEL_BOTH. Default: NONE.",
            "",
        ]
    )

    lines.extend(
        [
            "post_trade_gateway entries",
            "" + "-" * 27,
            "name:",
            "  Optional string. Default: 'ralf-gwy01'.",
            "bind_address:",
            "  Optional string. Default: '0.0.0.0'.",
            "port:",
            "  Optional integer. Default: 5580. Must be > 0.",
            "replay_retention_sec:",
            "  Optional integer seconds. Default: 86400. Must be > 0.",
            "heartbeat_interval_sec:",
            "  Optional integer seconds. Default: 1. Must be > 0.",
            "idle_timeout_sec:",
            "  Optional integer seconds. Default: 5. Must be > 0.",
            "max_client_queue:",
            "  Optional integer. Default: 10000. Must be > 0.",
            "allowed_roles:",
            "  Optional list of strings. Default: [CLEARING, DROP_COPY, AUDIT].",
            "",
        ]
    )

    lines.extend(
        [
            "market_data_gateway entries",
            "" + "-" * 28,
            "enabled:",
            "  Optional boolean. Default: true.",
            "name:",
            "  Optional string. Default: 'md-gwy01'.",
            "bind_address:",
            "  Optional string. Default: '0.0.0.0'.",
            "port:",
            "  Optional integer. Default: 5570. Must be > 0.",
            "heartbeat_interval_sec:",
            "  Optional integer seconds. Default: 1. Must be > 0.",
            "idle_timeout_sec:",
            "  Optional integer seconds. Default: 5. Must be > 0.",
            "replay_window_sec:",
            "  Optional integer seconds. Default: 30. Must be > 0.",
            "max_symbols_per_client:",
            "  Optional integer. Default: 200. Must be > 0.",
            "max_client_queue:",
            "  Optional integer. Default: 10000. Must be > 0.",
            "",
        ]
    )

    lines.extend(
        [
            "schedule entries",
            "" + "-" * 16,
            "Times are strings in HH:MM local server time. The scheduler uses any provided",
            "subset in trading-day order and falls back to built-in defaults if no usable",
            "schedule is present.",
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
    )

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
