"""
pm-monitor — the health collector behind the operator dashboard.

Usage:
  poetry run pm-monitor [--log-level LEVEL] [-v|-vv] [-q]
                        [--log-target server|stdout|file] [--log-file PATH]

Every long-running pm-* process PUSHes a ``health.beacon`` every
``monitor.beacon_interval_sec``; pm-monitor keeps the latest state of each
and PUBlishes a ``health.snapshot`` once a second for the dashboard bridge.
See docs-design/EduMatcher-Operator-Dashboard.md §9.

Configuration comes from the ``monitor:`` section of the deployed artifact
(there are no flags for it): ``bind_address``, ``pull_port`` (beacons in,
default 5610) and ``pub_port`` (snapshots out, default 5611).
``EDUMATCHER_GATEWAY_BIND_HOST`` overrides ``bind_address``. With
``monitor.enabled: false`` pm-monitor refuses to start (exit 2).

The trading date in the snapshot follows the engine's session timezone
(``engine.locale.session_timezone``), as pm-stats does, so "today" means the
same day everywhere.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sqlite3
import sys
import time

import zmq

from edumatcher.config import ENGINE_PUB_ADDR, METRICS_DB_FILE
from edumatcher.health import HealthReporter
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.monitor.collector import Monitor
from edumatcher.monitor.config import MonitorConfig
from edumatcher.monitor.host import HostSampler, default_files
from edumatcher.monitor.store import (
    IncompatibleStoreError,
    MetricsStore,
    StoreLockedError,
)
from edumatcher.stats.trading_day import resolve_timezone

_CLIENT_NAME = "pm-monitor"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EduMatcher health collector for the operator dashboard"
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, _CLIENT_NAME)
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
    if args.log_level:
        level = int(getattr(logging, str(args.log_level).upper(), logging.WARNING))
    elif args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    client_config = load_default_log_client_config()
    server_config = load_default_log_server_config()
    handler = resolve_handler(
        log_target=args.log_target,
        log_file=args.log_file,
        client_name=_CLIENT_NAME,
        instance=None,
        host=resolve_host_default(),
        port=server_config.port,
        connect_timeout_sec=client_config.connect_timeout_sec,
        failover_timeout_sec=(
            args.log_failover_timeout
            if args.log_failover_timeout is not None
            else client_config.failover_timeout_sec
        ),
        failover_dir=client_config.failover_dir,
    )
    logging.basicConfig(level=level, format=_LOG_FORMAT, handlers=[handler])
    return level


def main() -> None:
    from edumatcher.config_artifact import load_compiled_config, report_deployment
    from edumatcher.engine.config_loader import DEFAULT_SESSION_TIMEZONE

    parser = build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-monitor with log level %s", logging.getLevelName(log_level))
    report_deployment(log)

    compiled = load_compiled_config()
    config = MonitorConfig() if compiled is None else compiled.monitor
    if not config.enabled:
        parser.exit(
            2,
            f"{parser.prog}: monitoring is disabled (monitor.enabled: false in "
            "the deployed configuration); enable it and redeploy to run "
            "pm-monitor\n",
        )
    session_tz_name = (
        DEFAULT_SESSION_TIMEZONE
        if compiled is None
        else compiled.engine.locale.session_timezone
    )
    session_tz = resolve_timezone(session_tz_name)
    if session_tz is None:
        parser.error(
            f"engine config locale.session_timezone: unknown timezone {session_tz_name!r}"
        )
    log.info("session timezone %s", session_tz_name)

    roles = (
        {}
        if compiled is None
        else {gw: cfg.role.value for gw, cfg in compiled.engine.fix_gateways.items()}
    )
    log_db = None if compiled is None else compiled.log_server.db_path
    try:
        store = MetricsStore(
            METRICS_DB_FILE,
            session_tz_name,
            raw_hours=config.retention.raw_hours,
            minute_days=config.retention.minute_days,
        )
    except (StoreLockedError, IncompatibleStoreError, sqlite3.Error, OSError) as exc:
        log.error("cannot open %s: %s", METRICS_DB_FILE, exc)
        sys.exit(1)
    try:
        monitor = Monitor(
            config,
            session_tz,
            engine_pub_addr=ENGINE_PUB_ADDR,
            roles=roles,
            host_sampler=HostSampler(default_files(log_db)),
            store=store,
        )
    except zmq.ZMQError as exc:
        store.close(time.time())
        log.error(
            "cannot bind pm-monitor sockets (pull_port %d, pub_port %d): %s",
            config.pull_port,
            config.pub_port,
            exc,
        )
        sys.exit(1)
    # Installed here rather than in run() so tests that drive run() directly
    # keep pytest's own handlers.
    signal.signal(signal.SIGINT, lambda *_: monitor.stop())
    signal.signal(signal.SIGTERM, lambda *_: monitor.stop())
    # Beacons to the monitor's own PULL: config.host is where every process on
    # this machine reaches pm-monitor, so it reaches itself the same way.
    reporter = HealthReporter.start_from_compiled_config(_CLIENT_NAME)
    if reporter is not None:
        monitor.attach_reporter(reporter)
    try:
        monitor.run()
    except Exception as exc:
        log.error("fatal runtime error: %s", exc)
        raise
    finally:
        monitor.close()


if __name__ == "__main__":
    main()
