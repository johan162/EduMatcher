"""CLI entry point for ``pm-md-gwy`` (CALF market data gateway)."""

from __future__ import annotations

import argparse
import logging

from edumatcher.config import (
    COMPILED_CONFIG_FILE,
    INDEX_PUB_CONNECT_ADDR,
)
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway.gateway import MarketDataGateway
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler

_CLIENT_NAME = "pm-md-gwy"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EduMatcher CALF market data gateway",
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-md-gwy")
    parser.add_argument("--bind", help="TCP bind address override")
    parser.add_argument("--port", type=int, help="TCP bind port override")
    parser.add_argument(
        "--engine-pub",
        default=None,
        help="Engine PUB socket address (overrides config; default: tcp://127.0.0.1:5556)",
    )
    parser.add_argument(
        "--index-pub",
        default=INDEX_PUB_CONNECT_ADDR,
        help="Index PUB socket address (default: tcp://127.0.0.1:5558)",
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
        help="Increase log verbosity (-v: INFO, -vv: DEBUG)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce log output to warnings/errors",
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


def _resolve_config(
    args: argparse.Namespace,
) -> tuple[MarketDataGatewayConfig, set[str]]:
    from edumatcher.config_artifact import load_compiled_config

    compiled = load_compiled_config()
    cfg = (
        MarketDataGatewayConfig() if compiled is None else compiled.market_data_gateway
    )

    bind_address = str(args.bind) if args.bind else cfg.bind_address
    port = int(args.port) if args.port else cfg.port
    engine_pub_addr = str(args.engine_pub) if args.engine_pub else cfg.engine_pub_addr
    index_pub_addr = str(args.index_pub) if args.index_pub else cfg.index_pub_addr

    # An empty symbol set is not a harmless default: it disables per-symbol
    # SUB validation *and* omits SYMBOLS= from every WELCOME, so a client is
    # left with no instrument universe and no clue why. Both ways of ending up
    # there used to be silent; they are now loud.
    #
    # The symbols come from the same compiled artifact as the gateway's own
    # settings, so the two can no longer describe different exchanges.
    known_symbols: set[str] = set()
    if compiled is None:
        log.warning(
            "no compiled configuration at %s — starting with no known symbols, "
            "so SUB symbol validation is disabled and WELCOME will carry no "
            "SYMBOLS= list. Run pm-config-deploy to install one.",
            COMPILED_CONFIG_FILE,
        )
    else:
        known_symbols = set(compiled.engine.symbols)
        if not known_symbols:
            log.warning(
                "the compiled configuration defines no symbols — WELCOME will "
                "carry no SYMBOLS= list"
            )

    return (
        MarketDataGatewayConfig(
            enabled=cfg.enabled,
            name=cfg.name,
            bind_address=bind_address,
            port=port,
            engine_pub_addr=engine_pub_addr,
            index_pub_addr=index_pub_addr,
            heartbeat_interval_sec=cfg.heartbeat_interval_sec,
            idle_timeout_sec=cfg.idle_timeout_sec,
            replay_window_sec=cfg.replay_window_sec,
            max_connections=cfg.max_connections,
            max_messages_per_second=cfg.max_messages_per_second,
            max_symbols_per_client=cfg.max_symbols_per_client,
            max_client_queue=cfg.max_client_queue,
            depth_levels=cfg.depth_levels,
        ),
        known_symbols,
    )


def main() -> None:
    from edumatcher.config_artifact import report_deployment

    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-md-gwy with log level %s", logging.getLevelName(log_level))
    report_deployment(log)

    try:
        config, known_symbols = _resolve_config(args)
    except Exception as exc:
        log.error("failed to resolve configuration: %s", exc)
        parser.error(str(exc))

    if not config.enabled:
        log.warning("market_data_gateway.enabled=false; exiting")
        log.info("market_data_gateway.enabled=false; exiting")
        return

    log.debug(
        "resolved md-gateway config: bind=%s port=%s engine_pub=%s index_pub=%s known_symbols=%d",
        config.bind_address,
        config.port,
        config.engine_pub_addr,
        config.index_pub_addr,
        len(known_symbols),
    )
    gateway = MarketDataGateway(config=config, known_symbols=known_symbols)
    try:
        gateway.run()
    except Exception as exc:
        log.error("fatal runtime error: %s", exc)
        raise
    finally:
        gateway.close()


__all__ = ["main", "_build_parser", "_resolve_config", "_configure_logging"]
