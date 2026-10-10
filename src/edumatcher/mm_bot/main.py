"""Entry point for pm-mm-bot — autonomous market-maker bot.

The command line is scoped by ``--symbol``: flags before the first one are
gateway-wide defaults, flags after one apply to that symbol alone. A
``--config`` file expresses the same thing without a long command line. See
../../../docs/books/participant-guide/part-3-market-making/030-the-market-maker-bot.md and docs-design/EduMatcher-mm-bot-multi.md for
the full grammar.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from edumatcher.config_artifact import ArtifactError, load_compiled_config
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.mm_bot.cli_scope import ScopeError, split_argv_scopes
from edumatcher.mm_bot.config import EMPTY_FILE_CONFIG, FileConfig, load_bot_config
from edumatcher.mm_bot.params import (
    GATEWAY_DEFAULTS,
    GATEWAY_KEYS,
    LOGGING_KEY_TO_DEST,
    PASSIVE_KEYS,
    TIER2_KEYS,
)
from edumatcher.mm_bot.resolve import NoSymbolsError, resolve_symbol_params

log = logging.getLogger(__name__)

_CLIENT_NAME = "pm-mm-bot"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


def build_parser() -> argparse.ArgumentParser:
    """Build the parser used for both the global scope and each symbol scope.

    Nearly every default is ``None`` rather than the documented value: that
    sentinel is what lets the merge layer tell "flag not given" from "given
    the same value as the default", which in turn is what makes
    ``gap_was_explicit`` exact. Built-in defaults are applied later, by
    ``mm_bot.params.TIER2_DEFAULTS``/``GATEWAY_DEFAULTS``.
    """
    parser = argparse.ArgumentParser(
        description="EduMatcher autonomous market-maker bot"
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-mm-bot")
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=(
            "YAML file supplying gateway-wide settings, shared defaults, and "
            "per-symbol overrides; a CLI flag in the same scope overrides the "
            "same key from the file"
        ),
    )
    parser.add_argument(
        "--symbol",
        help=(
            "Instrument to make a market in (e.g. AAPL). May be repeated: "
            "each per-symbol flag after it applies to that symbol until the "
            "next --symbol"
        ),
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help=(
            "Comma-separated symbols (e.g. AAPL,MSFT) that all share the same "
            "settings — shorthand for repeating --symbol with no per-symbol "
            "flags; mutually exclusive with --symbol"
        ),
    )
    parser.add_argument(
        "--all-symbols",
        action="store_true",
        help=(
            "Quote every symbol in the currently deployed configuration, all "
            "with the same settings; the gateway ID defaults to MM_ALL_<nn>. "
            "Mutually exclusive with --symbol, --symbols and a config file "
            "'symbols:' block"
        ),
    )
    parser.add_argument(
        "--label",
        default=None,
        help=(
            "Override the gateway-ID symbol segment (default: the single "
            "symbol, or SYM1_SYM2_... derived from every symbol) — mainly "
            "useful to keep a multi-symbol gateway ID short"
        ),
    )
    parser.add_argument(
        "--strategy",
        default=None,
        help="Pricing strategy (default: symmetric)",
    )
    parser.add_argument(
        "--gap",
        type=float,
        default=None,
        help="Total spread in price units (default: 0.10)",
    )
    parser.add_argument(
        "--max-position",
        type=int,
        default=None,
        help=(
            "Net position (either direction) at which inventory skewing "
            "saturates. Required when --strategy inventory_skew; unused "
            "by every other strategy"
        ),
    )
    parser.add_argument(
        "--retreat-ticks",
        type=int,
        default=None,
        help=(
            "passive strategy: how many ticks beyond its home price each side "
            "may step back to stay behind other traders (default: 5)"
        ),
    )
    parser.add_argument(
        "--behind-ticks",
        type=int,
        default=None,
        help=(
            "passive strategy: how many ticks behind other traders' best "
            "price a covered side quotes (default: 1)"
        ),
    )
    parser.add_argument(
        "--min-cover-qty",
        type=int,
        default=None,
        help=(
            "passive strategy: quantity other traders must show inside the "
            "retreat band before a side counts as covered (default: 1)"
        ),
    )
    parser.add_argument(
        "--fade-ticks",
        type=int,
        default=None,
        help=(
            "passive strategy: extra ticks a side steps back after it is "
            "filled; 0 disables fading (default: 2)"
        ),
    )
    parser.add_argument(
        "--fade-sec",
        type=float,
        default=None,
        help=(
            "passive strategy: seconds a fade lasts after a fill; 0 disables "
            "fading (default: 3.0)"
        ),
    )
    parser.add_argument(
        "--anchor-sim",
        type=float,
        default=None,
        metavar="W",
        help=(
            "Quote around pm-market-sim's true value: each model step closes "
            "this fraction (0-1) of the gap; 0 = off (default: 0)"
        ),
    )
    parser.add_argument(
        "--qty", type=int, default=None, help="Quote size on each leg (default: 500)"
    )
    parser.add_argument(
        "--id-suffix",
        default=None,
        help="Running number for gateway ID (default: 01)",
    )
    parser.add_argument(
        "--gateway-id",
        default=None,
        help=(
            "Use this exact gateway ID (e.g. MM01) instead of deriving "
            "MM_<label>_<id-suffix>; it must match a MARKET_MAKER gateway "
            "in the engine config"
        ),
    )
    parser.add_argument(
        "--drift-ticks",
        type=int,
        default=None,
        help=(
            "Reprice when mid moves by more than this many ticks; passive "
            "strategy: when a side's target price does (default: 3)"
        ),
    )
    parser.add_argument(
        "--reissue-delay-ms",
        type=int,
        default=None,
        help="Milliseconds to wait after fill before re-issuing (default: 200)",
    )
    parser.add_argument(
        "--tif",
        choices=["DAY", "GTC"],
        default=None,
        help="Time-in-force for quote legs (default: DAY)",
    )
    parser.add_argument(
        "--heartbeat-interval-sec",
        type=float,
        default=None,
        help="Periodic live-quote check interval (default: 5.0)",
    )
    parser.add_argument(
        "--startup-session-timeout-sec",
        type=float,
        default=None,
        help="Max wait to learn the session phase (default: 5.0)",
    )
    parser.add_argument(
        "--bootstrap-timeout-sec",
        type=float,
        default=None,
        help="Max wait for QBOOT reply (default: 1.0)",
    )
    parser.add_argument(
        "--cancel-timeout-sec",
        type=float,
        default=None,
        help="Max wait for cancel confirmation (default: 1.0)",
    )
    parser.add_argument(
        "--shutdown-timeout-sec",
        type=float,
        default=None,
        help="Max wait for cancel on shutdown (default: 2.0)",
    )
    parser.add_argument(
        "--qlegs-reconcile-interval-sec",
        type=float,
        default=None,
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
        default=None,
        help="Engine PUSH/PULL address (default: tcp://127.0.0.1:5555)",
    )
    parser.add_argument(
        "--engine-pub",
        default=None,
        help="Engine PUB address (default: tcp://127.0.0.1:5556)",
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


def _given(namespace: argparse.Namespace, keys: tuple[str, ...]) -> dict[str, Any]:
    """The subset of ``keys`` the operator actually supplied in this scope."""
    return {
        key: getattr(namespace, key)
        for key in keys
        if getattr(namespace, key, None) is not None
    }


def _parse_symbol_scopes(
    parser: argparse.ArgumentParser,
    scopes: list[tuple[str, list[str]]],
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    """Parse each ``--symbol`` scope into that symbol's Tier-2 overrides.

    A gateway-wide flag written inside a symbol scope is hoisted to the
    global scope rather than rejected — that ordering is what most existing
    single-symbol command lines already use, and there is only one gateway
    for it to apply to. It is logged so nobody is left believing it was
    scoped to the symbol it followed.
    """
    symbol_cli: list[tuple[str, dict[str, Any]]] = []
    hoisted: dict[str, Any] = {}
    gateway_dests = (*GATEWAY_KEYS, *LOGGING_KEY_TO_DEST.values())
    for symbol, scope_argv in scopes:
        scoped = parser.parse_args(scope_argv)
        if scoped.symbols is not None or scoped.config is not None:
            parser.error(
                "--symbols and --config are gateway-wide and cannot follow "
                f"--symbol {symbol}"
            )
        for key, value in _given(scoped, gateway_dests).items():
            log.warning(
                "%s is gateway-wide; the value given after --symbol %s "
                "applies to every symbol",
                key,
                symbol,
            )
            hoisted[key] = value
        # Verbosity is hoisted silently: nobody expects -v to be per-symbol,
        # so warning about it would be pure noise.
        hoisted["verbose"] = max(hoisted.get("verbose", 0), scoped.verbose)
        hoisted["quiet"] = hoisted.get("quiet", False) or scoped.quiet
        symbol_cli.append((symbol, _given(scoped, TIER2_KEYS)))
    return symbol_cli, hoisted


def _resolve_gateway_settings(
    args: argparse.Namespace,
    hoisted: dict[str, Any],
    file_config: FileConfig,
) -> None:
    """Write resolved Tier-1 settings back onto ``args``.

    Gateway-wide keys use the simple precedence — an explicit flag, then the
    config file's ``gateway:``/``logging:`` block, then the built-in default
    — because there is no per-symbol tier for them to compete with.
    """
    for key, default in GATEWAY_DEFAULTS.items():
        value = getattr(args, key, None)
        if value is None:
            value = hoisted.get(key)
        if value is None:
            value = file_config.gateway.get(key)
        if value is None:
            value = default
        setattr(args, key, value)

    for yaml_key, dest in LOGGING_KEY_TO_DEST.items():
        if getattr(args, dest, None) is None:
            setattr(args, dest, hoisted.get(dest, file_config.logging.get(yaml_key)))

    args.verbose = max(args.verbose, hoisted.get("verbose", 0))
    args.quiet = args.quiet or hoisted.get("quiet", False)


def _deployed_symbols(parser: argparse.ArgumentParser) -> list[str]:
    """The symbols of the deployed configuration, for ``--all-symbols``."""
    try:
        compiled = load_compiled_config()
    except ArtifactError as exc:
        log.error("cannot read the deployed configuration: %s", exc)
        raise SystemExit(1)
    if compiled is None:
        parser.error(
            "--all-symbols needs a deployed configuration; run pm-config-deploy"
        )
    symbols = list(compiled.engine.symbols)
    if not symbols:
        parser.error("the deployed configuration defines no symbols")
    return symbols


def _derive_gateway_id(
    args: argparse.Namespace, symbols: list[str], all_symbols: bool = False
) -> str:
    if args.gateway_id:
        return str(args.gateway_id)
    default_label = "ALL" if all_symbols else "_".join(symbols)
    label = args.label if args.label else default_label
    return f"MM_{label}_{args.id_suffix}"


def main(argv: list[str] | None = None) -> None:
    """Main entry point for pm-mm-bot."""
    cli_args = argv if argv is not None else sys.argv[1:]
    parser = build_parser()

    try:
        scopes = split_argv_scopes(cli_args)
    except ScopeError as exc:
        parser.error(str(exc))

    args = parser.parse_args(scopes.global_argv)

    file_config = EMPTY_FILE_CONFIG
    if args.config is not None:
        try:
            file_config = load_bot_config(
                Path(args.config), symbols_required=not args.all_symbols
            )
        except ValueError as exc:
            log.error("invalid config file: %s", exc)
            raise SystemExit(1)

    if scopes.symbol_argv and args.symbols:
        parser.error("--symbol and --symbols are mutually exclusive")

    if args.all_symbols and (scopes.symbol_argv or args.symbols or file_config.symbols):
        parser.error(
            "--all-symbols cannot be combined with --symbol, --symbols or a "
            "config file 'symbols:' block"
        )

    symbol_cli, hoisted = _parse_symbol_scopes(parser, scopes.symbol_argv)
    _resolve_gateway_settings(args, hoisted, file_config)

    if args.all_symbols:
        extra_symbols = _deployed_symbols(parser)
    elif args.symbols:
        extra_symbols = [
            s.strip().upper() for s in args.symbols.split(",") if s.strip()
        ]
    else:
        extra_symbols = []
    if args.symbols and not extra_symbols:
        parser.error("--symbols must contain at least one non-empty symbol")

    try:
        resolved = resolve_symbol_params(
            file_config,
            _given(args, TIER2_KEYS),
            symbol_cli,
            extra_symbols,
        )
    except NoSymbolsError as exc:
        parser.error(str(exc))
    except ValueError as exc:
        log.error("invalid configuration: %s", exc)
        raise SystemExit(1)

    for flag, value in (
        ("--startup-session-timeout-sec", args.startup_session_timeout_sec),
        ("--shutdown-timeout-sec", args.shutdown_timeout_sec),
    ):
        if value <= 0:
            log.error(
                "invalid startup value: %s must be positive (got %s)", flag, value
            )
            raise SystemExit(1)

    log_level = _configure_logging(args)
    log.info("starting pm-mm-bot with log level %s", logging.getLevelName(log_level))

    gateway_id = _derive_gateway_id(args, resolved.symbols, args.all_symbols)
    bot_verbose = bool(args.verbose >= 1 or log_level <= logging.DEBUG)
    log.info(
        "resolved mm_bot config gateway_id=%s symbols=%s",
        gateway_id,
        ",".join(resolved.symbols),
    )
    for symbol in resolved.symbols:
        params = resolved.params[symbol]
        log.info(
            "[%s] strategy=%s gap=%s qty=%s tif=%s drift_ticks=%s max_position=%s",
            symbol,
            params["strategy"],
            params["gap"],
            params["qty"],
            params["tif"],
            params["drift_ticks"],
            params["max_position"],
        )
        if params["strategy"] == "passive":
            log.info(
                "[%s] passive: %s",
                symbol,
                " ".join(f"{key}={params[key]}" for key in PASSIVE_KEYS),
            )

    from edumatcher.mm_bot.bot import MMBot

    primary = resolved.primary
    try:
        bot = MMBot(
            gateway_id=gateway_id,
            symbols=resolved.symbols,
            strategy=primary["strategy"],
            gap=primary["gap"],
            gap_was_explicit=primary["gap_was_explicit"],
            max_position=primary["max_position"],
            qty=primary["qty"],
            drift_ticks=primary["drift_ticks"],
            reissue_delay_ms=primary["reissue_delay_ms"],
            tif=primary["tif"],
            heartbeat_interval_sec=primary["heartbeat_interval_sec"],
            startup_session_timeout_sec=args.startup_session_timeout_sec,
            bootstrap_timeout_sec=primary["bootstrap_timeout_sec"],
            cancel_timeout_sec=primary["cancel_timeout_sec"],
            shutdown_timeout_sec=args.shutdown_timeout_sec,
            qlegs_reconcile_interval_sec=primary["qlegs_reconcile_interval_sec"],
            initial_min=primary["initial_min"],
            initial_max=primary["initial_max"],
            engine_pull=args.engine_pull,
            engine_pub=args.engine_pub,
            verbose=bot_verbose,
            overrides=resolved.params,
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
