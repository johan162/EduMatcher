"""Entry point for pm-mm-bot — autonomous market-maker bot."""

from __future__ import annotations

import argparse
import logging
import sys

log = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EduMatcher autonomous market-maker bot"
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-mm-bot")
    parser.add_argument(
        "--symbol", required=True, help="Instrument to make a market in (e.g. AAPL)"
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
    return parser.parse_args(argv)


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

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stdout,
    )
    return int(level)


def main(argv: list[str] | None = None) -> None:
    """Main entry point for pm-mm-bot."""
    cli_args = argv if argv is not None else sys.argv[1:]
    # Detect both the "--gap 0.10" and "--gap=0.10" forms.
    gap_was_explicit = any(
        arg == "--gap" or arg.startswith("--gap=") for arg in cli_args
    )
    args = _parse_args(argv)
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
            print(f"ERROR: {flag} must be positive", file=sys.stderr)
            raise SystemExit(1)
    if args.reissue_delay_ms < 0:
        log.error(
            "invalid startup value: --reissue-delay-ms must be non-negative (got %s)",
            args.reissue_delay_ms,
        )
        print("ERROR: --reissue-delay-ms must be non-negative", file=sys.stderr)
        raise SystemExit(1)

    symbol = args.symbol.upper()
    gateway_id = f"MM_{symbol}_{args.id_suffix}"
    bot_verbose = bool(args.verbose >= 1 or log_level <= logging.DEBUG)
    log.info(
        "resolved mm_bot config gateway_id=%s symbol=%s gap=%s qty=%s tif=%s",
        gateway_id,
        symbol,
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
            symbol=symbol,
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
