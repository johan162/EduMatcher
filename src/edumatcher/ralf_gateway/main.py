"""CLI entrypoint for pm-ralf-gwy."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from edumatcher.config import ENGINE_CONFIG_FILE
from edumatcher.ralf_gateway.config import (
    RalfGatewayConfig,
    load_default_ralf_gateway_config,
    load_ralf_gateway_config,
)
from edumatcher.ralf_gateway.gateway import RalfGateway

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EduMatcher RALF dissemination gateway"
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-ralf-gwy")
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
        help="Engine PUB socket address (default: value from config, then tcp://127.0.0.1:5556)",
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
    )
    return int(level)


def _resolve_config(args: argparse.Namespace) -> RalfGatewayConfig:
    cfg_path = Path(str(args.config))
    cfg = load_ralf_gateway_config(cfg_path)

    bind_address = str(args.bind) if args.bind else cfg.bind_address
    port = int(args.port) if args.port else cfg.port
    engine_pub_addr = str(args.engine_pub) if args.engine_pub else cfg.engine_pub_addr

    return RalfGatewayConfig(
        name=cfg.name,
        bind_address=bind_address,
        port=port,
        engine_pub_addr=engine_pub_addr,
        replay_retention_sec=cfg.replay_retention_sec,
        heartbeat_interval_sec=cfg.heartbeat_interval_sec,
        idle_timeout_sec=cfg.idle_timeout_sec,
        max_client_queue=cfg.max_client_queue,
        allowed_roles=cfg.allowed_roles,
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-ralf-gwy with log level %s", logging.getLevelName(log_level))

    try:
        config = _resolve_config(args)
    except Exception as exc:
        log.error("failed to resolve configuration: %s", exc)
        parser.error(str(exc))

    log.debug(
        "resolved ralf-gateway config: bind=%s port=%s engine_pub=%s",
        config.bind_address,
        config.port,
        config.engine_pub_addr,
    )

    gateway = RalfGateway(config)
    try:
        gateway.run()
    except Exception as exc:
        log.error("fatal runtime error: %s", exc)
        raise
    finally:
        gateway.close()


__all__ = [
    "main",
    "_build_parser",
    "_configure_logging",
    "_resolve_config",
    "load_default_ralf_gateway_config",
]
