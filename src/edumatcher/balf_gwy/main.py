"""CLI entry point for ``pm-balf-gwy``."""

from __future__ import annotations

import argparse
import logging

from edumatcher.balf_gwy.config import (
    BalfGatewayConfig,
    load_default_balf_gateway_config,
)
from edumatcher.balf_gwy.gateway import BalfGateway
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler

_CLIENT_NAME = "pm-balf-gwy"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EduMatcher BALF (Binary ALF) TCP gateway"
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-balf-gwy")
    parser.add_argument("--bind", help="TCP bind address override")
    parser.add_argument("--port", type=int, help="TCP bind port override")
    parser.add_argument(
        "--engine-host",
        default=None,
        help=(
            "Override engine host in ZMQ URLs "
            "(uses tcp://<host>:5555 and tcp://<host>:5556)"
        ),
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
) -> BalfGatewayConfig:
    cfg = load_default_balf_gateway_config()

    bind_address = str(args.bind) if args.bind else cfg.bind_address
    port = int(args.port) if args.port else cfg.port

    engine_pull_addr = cfg.engine_pull_addr
    engine_pub_addr = cfg.engine_pub_addr
    if args.engine_host:
        engine_pull_addr = f"tcp://{args.engine_host}:5555"
        engine_pub_addr = f"tcp://{args.engine_host}:5556"

    return BalfGatewayConfig(
        enabled=cfg.enabled,
        name=cfg.name,
        bind_address=bind_address,
        port=port,
        engine_pull_addr=engine_pull_addr,
        engine_pub_addr=engine_pub_addr,
        heartbeat_interval_sec=cfg.heartbeat_interval_sec,
        heartbeat_timeout_sec=cfg.heartbeat_timeout_sec,
        idle_timeout_sec=cfg.idle_timeout_sec,
        auth_timeout_sec=cfg.auth_timeout_sec,
        max_connections=cfg.max_connections,
        max_client_queue=cfg.max_client_queue,
        max_messages_per_second=cfg.max_messages_per_second,
        max_errors_before_disconnect=cfg.max_errors_before_disconnect,
        error_window_sec=cfg.error_window_sec,
        duplicate_session_policy=cfg.duplicate_session_policy,
        gateway_roles=cfg.gateway_roles,
    )


def main() -> None:
    from edumatcher.config_artifact import report_deployment

    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-balf-gwy with log level %s", logging.getLevelName(log_level))
    report_deployment(log)

    try:
        config = _resolve_config(args)
    except Exception as exc:
        log.error("failed to resolve configuration: %s", exc)
        parser.error(str(exc))

    if not config.enabled:
        log.warning("balf_gateway.enabled is false; refusing to start")
        parser.error("balf_gateway.enabled is false in config")

    log.debug(
        "resolved balf-gateway config: bind=%s port=%s engine_pull=%s engine_pub=%s",
        config.bind_address,
        config.port,
        config.engine_pull_addr,
        config.engine_pub_addr,
    )

    gateway = BalfGateway(config)
    try:
        gateway.run()
    except Exception as exc:
        log.error("fatal runtime error: %s", exc)
        raise
    finally:
        gateway.close()


__all__ = ["main", "_build_parser", "_configure_logging", "_resolve_config"]
