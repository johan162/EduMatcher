"""Entry point for pm-mm-bot — autonomous market-maker bot."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.mm_bot.config import load_config_file

log = logging.getLogger(__name__)

_CLIENT_NAME = "pm-mm-bot"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EduMatcher autonomous market-maker bot"
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-mm-bot")
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=(
            "YAML file supplying any of these flags by long name "
            "(dashes as underscores); an explicit CLI flag overrides the "
            "same key from the file"
        ),
    )
    parser.add_argument(
        "--symbol",
        help="Instrument to make a market in (e.g. AAPL) — required unless "
        "--symbols or --config supplies one or more symbols",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help=(
            "Comma-separated symbols to make markets in from one process "
            "(e.g. AAPL,MSFT) — mutually exclusive with --symbol; each "
            "symbol runs through the same startup/failure-isolation checks "
            "independently (see docs-design/EduMatcher-MM-Bot-review.md "
            "§5a)"
        ),
    )
    parser.add_argument(
        "--label",
        default=None,
        help=(
            "Override the gateway-ID symbol segment (default: the single "
            "--symbol, or SYM1_SYM2_... derived from --symbols) — mainly "
            "useful to keep a multi-symbol gateway ID short"
        ),
    )
    parser.add_argument(
        "--strategy",
        default="symmetric",
        help="Pricing strategy (default: symmetric)",
    )
    parser.add_argument(
        "--gap",
        type=float,
        default=0.10,
        help="Total spread in price units (default: 0.10)",
    )
    parser.add_argument(
        "--qty", type=int, default=500, help="Quote size on each leg (default: 500)"
    )
    parser.add_argument(
        "--id-suffix",
        default="01",
        help="Running number for gateway ID (default: 01)",
    )
    parser.add_argument(
        "--drift-ticks",
        type=int,
        default=3,
        help="Reprice when mid moves by this many ticks (default: 3)",
    )
    parser.add_argument(
        "--reissue-delay-ms",
        type=int,
        default=200,
        help="Milliseconds to wait after fill before re-issuing (default: 200)",
    )
    parser.add_argument(
        "--tif",
        choices=["DAY", "GTC"],
        default="DAY",
        help="Time-in-force for quote legs (default: DAY)",
    )
    parser.add_argument(
        "--heartbeat-interval-sec",
        type=float,
        default=5.0,
        help="Periodic live-quote check interval (default: 5.0)",
    )
    parser.add_argument(
        "--startup-session-timeout-sec",
        type=float,
        default=5.0,
        help="Max wait for first session.state event (default: 5.0)",
    )
    parser.add_argument(
        "--bootstrap-timeout-sec",
        type=float,
        default=1.0,
        help="Max wait for QBOOT reply (default: 1.0)",
    )
    parser.add_argument(
        "--cancel-timeout-sec",
        type=float,
        default=1.0,
        help="Max wait for cancel confirmation (default: 1.0)",
    )
    parser.add_argument(
        "--shutdown-timeout-sec",
        type=float,
        default=2.0,
        help="Max wait for cancel on shutdown (default: 2.0)",
    )
    parser.add_argument(
        "--qlegs-reconcile-interval-sec",
        type=float,
        default=15.0,
        help="Interval for QLEGS snapshot reconciliation (default: 15.0)",
    )
    parser.add_argument(
        "--initial_min",
        type=float,
        default=None,
        help="Lower bound for random bootstrap reference price",
    )
    parser.add_argument(
        "--initial_max",
        type=float,
        default=None,
        help="Upper bound for random bootstrap reference price",
    )
    parser.add_argument(
        "--engine-pull",
        default="tcp://127.0.0.1:5555",
        help="Engine PUSH/PULL address",
    )
    parser.add_argument(
        "--engine-pub",
        default="tcp://127.0.0.1:5556",
        help="Engine PUB address",
    )
    parser.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level override (default: WARNING)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v: INFO + bot debug prints, -vv: DEBUG)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce output to warnings/errors",
    )
    parser.add_argument(
        "--log-target",
        choices=["server", "stdout", "file"],
        default=None,
        help=(
            "Where this process's own operational log records go: "
            "server (default, auto-detected pm-log-srv), stdout, or file"
        ),
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Operational log file path — required when --log-target file",
    )
    parser.add_argument(
        "--log-failover-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Grace window before falling back to a local log file once "
            "pm-log-srv becomes unreachable (default: 30, from config)"
        ),
    )
    return parser


def _configure_logging(args: argparse.Namespace) -> int:
    log_level = getattr(args, "log_level", None)
    verbose = getattr(args, "verbose", 0)
    quiet = getattr(args, "quiet", False)

    if log_level:
        level_name = str(log_level).upper()
        level = getattr(logging, level_name, logging.WARNING)
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.WARNING

    client_config = load_default_log_client_config()
    server_config = load_default_log_server_config()
    failover_timeout = getattr(args, "log_failover_timeout", None)
    handler = resolve_handler(
        log_target=getattr(args, "log_target", None),
        log_file=getattr(args, "log_file", None),
        client_name=_CLIENT_NAME,
        instance=None,
        host=resolve_host_default(),
        port=server_config.port,
        connect_timeout_sec=client_config.connect_timeout_sec,
        failover_timeout_sec=(
            failover_timeout
            if failover_timeout is not None
            else client_config.failover_timeout_sec
        ),
        failover_dir=client_config.failover_dir,
    )
    logging.basicConfig(level=level, format=_LOG_FORMAT, handlers=[handler])
    return int(level)


def main(argv: list[str] | None = None) -> None:
    """Main entry point for pm-mm-bot."""
    cli_args = argv if argv is not None else sys.argv[1:]
    parser = _build_parser()

    # First pass: only to find --config, before applying its values as
    # parser defaults below. A bare parse (no config-file defaults in play
    # yet) is enough for this — argparse ignores --symbol being unset here.
    config_path = parser.parse_known_args(cli_args)[0].config
    file_values: dict[str, object] = {}
    if config_path is not None:
        try:
            file_values = load_config_file(Path(config_path))
        except ValueError as exc:
            log.error("invalid config file: %s", exc)
            raise SystemExit(1)
        parser.set_defaults(**file_values)

    # Detect both the "--gap 0.10" and "--gap=0.10" forms. A gap pinned by
    # the config file counts the same as one pinned on the CLI — either way
    # the user (not the built-in 0.10 default) chose it, so the MM-obligation
    # auto-derivation in bot.py must not override it.
    gap_was_explicit = "gap" in file_values or any(
        arg == "--gap" or arg.startswith("--gap=") for arg in cli_args
    )

    args = parser.parse_args(argv)
    if args.symbol and args.symbols:
        parser.error("--symbol and --symbols are mutually exclusive")
    if not args.symbol and not args.symbols:
        parser.error("--symbol or --symbols is required (directly or via --config)")

    log_level = _configure_logging(args)
    log.info("starting pm-mm-bot with log level %s", logging.getLevelName(log_level))

    from edumatcher.mm_bot.pricer import QuotePricer

    # Validate bootstrap range
    try:
        QuotePricer.validate_bootstrap_range(args.initial_min, args.initial_max)
    except ValueError as exc:
        log.error("invalid bootstrap range: %s", exc)
        raise

    # Validate positive timeouts and intervals
    positive_checks = [
        ("--startup-session-timeout-sec", args.startup_session_timeout_sec),
        ("--bootstrap-timeout-sec", args.bootstrap_timeout_sec),
        ("--cancel-timeout-sec", args.cancel_timeout_sec),
        ("--shutdown-timeout-sec", args.shutdown_timeout_sec),
        ("--heartbeat-interval-sec", args.heartbeat_interval_sec),
        ("--qlegs-reconcile-interval-sec", args.qlegs_reconcile_interval_sec),
    ]
    for flag, value in positive_checks:
        if value <= 0:
            log.error(
                "invalid startup value: %s must be positive (got %s)", flag, value
            )
            raise SystemExit(1)
    if args.reissue_delay_ms < 0:
        log.error(
            "invalid startup value: --reissue-delay-ms must be non-negative (got %s)",
            args.reissue_delay_ms,
        )
        raise SystemExit(1)

    symbol_list = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else [args.symbol.upper()]
    )
    if not symbol_list:
        parser.error("--symbols must contain at least one non-empty symbol")

    # The gateway ID's symbol segment: a single --symbol keeps today's
    # MM_<SYMBOL>_<suffix> form unchanged; multiple --symbols derives
    # SYM1_SYM2_..._<suffix> unless --label shortens it explicitly.
    label = args.label if args.label else "_".join(symbol_list)
    gateway_id = f"MM_{label}_{args.id_suffix}"
    bot_verbose = bool(args.verbose >= 1 or log_level <= logging.DEBUG)
    log.info(
        "resolved mm_bot config gateway_id=%s symbols=%s strategy=%s gap=%s qty=%s "
        "tif=%s",
        gateway_id,
        ",".join(symbol_list),
        args.strategy,
        args.gap,
        args.qty,
        args.tif,
    )
    log.debug(
        "timeouts heartbeat=%s startup_session=%s bootstrap=%s cancel=%s shutdown=%s qlegs=%s",
        args.heartbeat_interval_sec,
        args.startup_session_timeout_sec,
        args.bootstrap_timeout_sec,
        args.cancel_timeout_sec,
        args.shutdown_timeout_sec,
        args.qlegs_reconcile_interval_sec,
    )

    from edumatcher.mm_bot.bot import MMBot

    try:
        bot = MMBot(
            gateway_id=gateway_id,
            symbols=symbol_list,
            strategy=args.strategy,
            gap=args.gap,
            gap_was_explicit=gap_was_explicit,
            qty=args.qty,
            drift_ticks=args.drift_ticks,
            reissue_delay_ms=args.reissue_delay_ms,
            tif=args.tif,
            heartbeat_interval_sec=args.heartbeat_interval_sec,
            startup_session_timeout_sec=args.startup_session_timeout_sec,
            bootstrap_timeout_sec=args.bootstrap_timeout_sec,
            cancel_timeout_sec=args.cancel_timeout_sec,
            shutdown_timeout_sec=args.shutdown_timeout_sec,
            qlegs_reconcile_interval_sec=args.qlegs_reconcile_interval_sec,
            initial_min=args.initial_min,
            initial_max=args.initial_max,
            engine_pull=args.engine_pull,
            engine_pub=args.engine_pub,
            verbose=bot_verbose,
        )
    except Exception as exc:
        log.error("failed to create mm_bot runtime: %s", exc)
        raise SystemExit(1)
    try:
        rc = bot.run()
        log.info("pm-mm-bot exiting with code %s", rc)
        raise SystemExit(rc)
    except KeyboardInterrupt:
        log.info("keyboard interrupt received; shutting down mm_bot")
        bot.shutdown()
        raise SystemExit(0)
