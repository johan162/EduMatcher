"""Argparse builder for pm-config-gen CLI."""

from __future__ import annotations

import argparse

from edumatcher.config_gen.defaults import (
    DEFAULT_CB_WINDOW_NS,
    DEFAULT_MM_MIN_QTY,
    DEFAULT_MM_SPREAD_TICKS,
    DEFAULT_SCHEDULE,
    DEFAULT_SNAPSHOT_INTERVAL_SEC,
    DEFAULT_TICK_DECIMALS,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-config-gen",
        description=(
            "Generate a parser-compatible engine_config.yaml from concise CLI inputs."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-config-gen")

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
        help="NAME:SHIFT_PCT[:HALT_MINS[:RESUMPTION_MODE]] entries. RESUMPTION_MODE is AUCTION (default) or CONTINUOUS.",
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
        help="Emit a top-level api_gateways section for pm-api-gwy.",
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

    # ── BALF gateway ──────────────────────────────────────────────────────────
    parser.add_argument(
        "--balf-gateway",
        action="store_true",
        help="Emit a top-level balf_gateway section for pm-balf-gwy.",
    )
    parser.add_argument(
        "--balf-name",
        default=None,
        metavar="NAME",
        help="balf_gateway.name override.",
    )
    parser.add_argument(
        "--balf-bind-address",
        default=None,
        metavar="ADDR",
        help="balf_gateway.bind_address override.",
    )
    parser.add_argument(
        "--balf-port",
        type=int,
        default=None,
        metavar="N",
        help="balf_gateway.port override (> 0).",
    )
    parser.add_argument(
        "--balf-heartbeat-interval-sec",
        type=int,
        default=None,
        metavar="N",
        help="balf_gateway.heartbeat_interval_sec override (> 0).",
    )
    parser.add_argument(
        "--balf-heartbeat-timeout-sec",
        type=int,
        default=None,
        metavar="N",
        help="balf_gateway.heartbeat_timeout_sec override (> 0).",
    )
    parser.add_argument(
        "--balf-idle-timeout-sec",
        type=int,
        default=None,
        metavar="N",
        help="balf_gateway.idle_timeout_sec override (> 0).",
    )
    parser.add_argument(
        "--balf-auth-timeout-sec",
        type=int,
        default=None,
        metavar="N",
        help="balf_gateway.auth_timeout_sec override (> 0).",
    )
    parser.add_argument(
        "--balf-max-connections",
        type=int,
        default=None,
        metavar="N",
        help="balf_gateway.max_connections override (> 0).",
    )
    parser.add_argument(
        "--balf-max-client-queue",
        type=int,
        default=None,
        metavar="N",
        help="balf_gateway.max_client_queue override (> 0).",
    )
    parser.add_argument(
        "--balf-max-messages-per-second",
        type=int,
        default=None,
        metavar="N",
        help="balf_gateway.max_messages_per_second override (> 0).",
    )
    parser.add_argument(
        "--balf-max-errors-before-disconnect",
        type=int,
        default=None,
        metavar="N",
        help="balf_gateway.max_errors_before_disconnect override (> 0).",
    )
    parser.add_argument(
        "--balf-error-window-sec",
        type=int,
        default=None,
        metavar="N",
        help="balf_gateway.error_window_sec override (> 0).",
    )
    parser.add_argument(
        "--balf-duplicate-session-policy",
        default=None,
        choices=["REJECT_NEW", "EVICT_OLD"],
        help="balf_gateway.duplicate_session_policy override.",
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
        "--combo",
        action="append",
        default=[],
        metavar="COMBO_SPEC",
        help=(
            "Seed a market-maker combo order: ID:TYPE:TIF:SYM/SIDE/TYPE/QTY[/PRICE[/STOP[/SMP]]],...\n"
            "Example: SEED-PAIR:AON:DAY:AAPL/BUY/LIMIT/100/20950,MSFT/SELL/LIMIT/50/41550\n"
            "Can be repeated."
        ),
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
