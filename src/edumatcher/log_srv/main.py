"""CLI entry point for ``pm-log-srv`` (LALF centralized log server)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from edumatcher.config import ENGINE_CONFIG_FILE
from edumatcher.log_srv.config import LogServerConfig, load_log_server_config
from edumatcher.log_srv.server import LogServer

log = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EduMatcher centralized LALF log server",
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-log-srv")
    parser.add_argument("--host", help="TCP bind address override")
    parser.add_argument("--port", type=int, help="TCP bind port override")
    parser.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help="SQLite database path override (default: from config or data/log.db)",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Prune log_events rows older than N days (default: 30). "
            "Pass 0 to disable pruning (unbounded retention)."
        ),
    )
    parser.add_argument(
        "--max-message-bytes",
        type=int,
        default=None,
        metavar="N",
        help="Maximum LOG payload size before truncation (default: 65536)",
    )
    parser.add_argument(
        "--pub-port",
        type=int,
        default=None,
        metavar="PORT",
        help="LALF-PS ZeroMQ PUB bind port for log distribution (default: 5601)",
    )
    parser.add_argument(
        "--pull-port",
        type=int,
        default=None,
        metavar="PORT",
        help="LALF-PS ZeroMQ PULL bind port for subscriber control (default: 5602)",
    )
    parser.add_argument(
        "--no-pubsub",
        action="store_true",
        help="Disable the LALF-PS interface entirely (bind no ZeroMQ sockets)",
    )
    parser.add_argument(
        "--lease-sec",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Subscription lease TTL in seconds; a subscriber that stops "
            "sending log.renew is reaped after this long (default: 30)"
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
        choices=["stdout", "file"],
        default="stdout",
        help=(
            "Where this process's own operational log records go: "
            "stdout (default) or file. Never 'server' — pm-log-srv must "
            "not depend on itself over the network"
        ),
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Operational log file path — required when --log-target file",
    )
    return parser


def _configure_logging(args: argparse.Namespace) -> int:
    # pm-log-srv is the one pm-* process that never sends its own logging
    # to another pm-log-srv over LALF (docs-design/EduMatcher-log-srv.md
    # §7.6) — --log-target is restricted to stdout/file only, so this
    # function never touches TcpLogHandler or the network.
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

    log_target = getattr(args, "log_target", "stdout")
    if log_target == "file":
        log_file = getattr(args, "log_file", None)
        if not log_file:
            raise ValueError("--log-file is required when --log-target file")
        handler: logging.Handler = logging.FileHandler(log_file, encoding="utf-8")
    else:
        handler = logging.StreamHandler(stream=sys.stdout)

    logging.basicConfig(level=level, format=_LOG_FORMAT, handlers=[handler])
    return int(level)


def _resolve_config(args: argparse.Namespace) -> LogServerConfig:
    cfg_path = ENGINE_CONFIG_FILE
    cfg = load_log_server_config(cfg_path)

    bind_address = str(args.host) if args.host else cfg.bind_address
    port = int(args.port) if args.port else cfg.port
    db_path = Path(args.db) if args.db else cfg.db_path

    retention_days = cfg.retention_days
    if args.retention_days is not None:
        retention_days = None if args.retention_days == 0 else args.retention_days

    max_message_bytes = (
        int(args.max_message_bytes)
        if args.max_message_bytes is not None
        else cfg.max_message_bytes
    )

    pubsub_enabled = cfg.pubsub_enabled and not args.no_pubsub
    pub_port = int(args.pub_port) if args.pub_port else cfg.pub_port
    pull_port = int(args.pull_port) if args.pull_port else cfg.pull_port
    lease_sec = int(args.lease_sec) if args.lease_sec else cfg.lease_sec
    max_lease_sec = max(cfg.max_lease_sec, lease_sec)

    if pubsub_enabled and len({port, pub_port, pull_port}) != 3:
        raise ValueError(
            f"port ({port}), pub-port ({pub_port}) and pull-port ({pull_port}) "
            "must all be different"
        )

    return LogServerConfig(
        enabled=cfg.enabled,
        name=cfg.name,
        bind_address=bind_address,
        port=port,
        db_path=db_path,
        retention_days=retention_days,
        max_message_bytes=max_message_bytes,
        max_client_queue=cfg.max_client_queue,
        write_batch_size=cfg.write_batch_size,
        write_batch_interval_ms=cfg.write_batch_interval_ms,
        heartbeat_interval_sec=cfg.heartbeat_interval_sec,
        pubsub_enabled=pubsub_enabled,
        pub_port=pub_port,
        pull_port=pull_port,
        lease_sec=lease_sec,
        max_lease_sec=max_lease_sec,
        max_subscribers=cfg.max_subscribers,
        notify_interval_ms=cfg.notify_interval_ms,
        backfill_chunk_rows=cfg.backfill_chunk_rows,
        max_backfill_minutes=cfg.max_backfill_minutes,
        max_backfill_rows=cfg.max_backfill_rows,
        max_pending_rows=cfg.max_pending_rows,
        pub_sndhwm=cfg.pub_sndhwm,
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-log-srv with log level %s", logging.getLevelName(log_level))
    log.info("using engine config %s", ENGINE_CONFIG_FILE)

    try:
        config = _resolve_config(args)
    except Exception as exc:
        log.error("failed to resolve configuration: %s", exc)
        parser.error(str(exc))

    if not config.enabled:
        log.warning("log_server.enabled=false; exiting")
        return

    log.debug(
        "resolved log-srv config: bind=%s port=%s db=%s (cwd=%s) retention_days=%s "
        "max_message_bytes=%s pubsub=%s pub_port=%s pull_port=%s lease_sec=%s",
        config.bind_address,
        config.port,
        Path(config.db_path).resolve(),
        Path.cwd(),
        config.retention_days,
        config.max_message_bytes,
        config.pubsub_enabled,
        config.pub_port,
        config.pull_port,
        config.lease_sec,
    )

    server = LogServer(config=config)
    try:
        server.run()
    except Exception as exc:
        log.error("fatal runtime error: %s", exc)
        raise
    finally:
        server.close()


if __name__ == "__main__":
    main()


__all__ = ["main", "_build_parser", "_resolve_config", "_configure_logging"]
