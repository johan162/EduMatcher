"""CLI entry point for ``pm-md-gwy`` (CALF market data gateway)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from edumatcher.config import (
    ENGINE_CONFIG_FILE,
    INDEX_PUB_CONNECT_ADDR,
)
from edumatcher.engine.config_loader import load_engine_config
from edumatcher.md_gateway.config import (
    MarketDataGatewayConfig,
    load_market_data_gateway_config,
)
from edumatcher.md_gateway.gateway import MarketDataGateway

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EduMatcher CALF market data gateway",
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-md-gwy")
    parser.add_argument(
        "--config",
        "-c",
        default=str(ENGINE_CONFIG_FILE),
        help="Engine config YAML path (default: engine_config.yaml)",
    )
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
    return parser


def _configure_logging(args: argparse.Namespace) -> int:
    if args.log_level:
        level_name = str(args.log_level).upper()
        level = getattr(logging, level_name, logging.WARNING)
    elif args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    elif args.quiet:
        level = logging.WARNING
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    return int(level)


def _resolve_config(
    args: argparse.Namespace,
) -> tuple[MarketDataGatewayConfig, set[str]]:
    cfg_path = Path(str(args.config))
    cfg = load_market_data_gateway_config(cfg_path)

    bind_address = str(args.bind) if args.bind else cfg.bind_address
    port = int(args.port) if args.port else cfg.port
    engine_pub_addr = str(args.engine_pub) if args.engine_pub else cfg.engine_pub_addr
    index_pub_addr = str(args.index_pub) if args.index_pub else cfg.index_pub_addr

    known_symbols: set[str] = set()
    if cfg_path.exists():
        try:
            engine_cfg = load_engine_config(cfg_path)
            known_symbols = set(engine_cfg.symbols.keys())
        except Exception:
            # Gateway remains usable in permissive mode when config validation
            # fails for unrelated reasons; symbol checks are simply disabled.
            known_symbols = set()

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
    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-md-gwy with log level %s", logging.getLevelName(log_level))

    try:
        config, known_symbols = _resolve_config(args)
    except Exception as exc:
        parser.error(str(exc))

    if not config.enabled:
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
    finally:
        gateway.close()


__all__ = ["main", "_build_parser", "_resolve_config", "_configure_logging"]
