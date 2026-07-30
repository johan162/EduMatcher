"""CLI entrypoint for pm-dc-gwy."""

from __future__ import annotations

import argparse
import logging

from edumatcher.config import ENGINE_CONFIG_FILE
from edumatcher.dc_gateway.config import (
    DcGatewayConfig,
    load_default_dc_gateway_config,
    load_dc_gateway_config,
)
from edumatcher.dc_gateway.gateway import DcGateway
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler

_CLIENT_NAME = "pm-dc-gwy"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EduMatcher drop-copy TCP gateway (external DC1 access to :5557)"
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-dc-gwy")
    parser.add_argument("--bind", help="TCP bind address override")
    parser.add_argument("--port", type=int, help="TCP bind port override")
    parser.add_argument(
        "--engine-dc-pub",
        default=None,
        help=(
            "Engine drop-copy PUB socket address (default: value from config, "
            "then tcp://127.0.0.1:5557)"
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


def _resolve_config(args: argparse.Namespace) -> DcGatewayConfig:
    cfg_path = ENGINE_CONFIG_FILE
    cfg = load_dc_gateway_config(cfg_path)

    bind_address = str(args.bind) if args.bind else cfg.bind_address
    port = int(args.port) if args.port else cfg.port
    drop_copy_pub_addr = (
        str(args.engine_dc_pub) if args.engine_dc_pub else cfg.drop_copy_pub_addr
    )

    return DcGatewayConfig(
        name=cfg.name,
        bind_address=bind_address,
        port=port,
        drop_copy_pub_addr=drop_copy_pub_addr,
        heartbeat_interval_sec=cfg.heartbeat_interval_sec,
        idle_timeout_sec=cfg.idle_timeout_sec,
        max_client_queue=cfg.max_client_queue,
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-dc-gwy with log level %s", logging.getLevelName(log_level))
    log.info("using engine config %s", ENGINE_CONFIG_FILE)

    try:
        config = _resolve_config(args)
    except Exception as exc:
        log.error("failed to resolve configuration: %s", exc)
        parser.error(str(exc))

    log.debug(
        "resolved dc-gateway config: bind=%s port=%s drop_copy_pub=%s",
        config.bind_address,
        config.port,
        config.drop_copy_pub_addr,
    )

    gateway = DcGateway(config)
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
    "load_default_dc_gateway_config",
]
