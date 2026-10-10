"""pm-ai-trader: one AI trading agent.

Runs a worker hosting a single agent. The agent's behaviour comes from a
preset (strategy x execution x tempo x risk); see ``--list-presets``.

Usage examples:
  poetry run pm-ai-trader --id AI001 --preset noise-retail
  poetry run pm-ai-trader --id AI007 --preset trend-follower --symbols AAPL,MSFT
  poetry run pm-ai-trader --id AI009 --preset-file my-preset.yaml
"""

from __future__ import annotations

import argparse
import logging
import signal
from pathlib import Path

from edumatcher.ai_trader.preset import (
    Preset,
    PresetError,
    builtin_presets,
    get_preset,
    load_preset_file,
)
from edumatcher.ai_trader.transport import AlfTransport
from edumatcher.ai_trader.worker import AgentSpec, Worker
from edumatcher.alf_gwy.config import load_default_alf_gateway_config
from edumatcher.config import EDUMATCHER_ENGINE_HOST
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler

_CLIENT_NAME = "pm-ai-trader"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"
DEFAULT_PRESET = "noise-retail"

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher autonomous AI trader")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-ai-trader")
    parser.add_argument("--id", help="Participant id, e.g. AI001")
    which = parser.add_mutually_exclusive_group()
    which.add_argument(
        "--preset",
        default=None,
        choices=sorted(builtin_presets()),
        help=f"Built-in preset (default: {DEFAULT_PRESET}); see --list-presets",
    )
    which.add_argument(
        "--preset-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Preset YAML file",
    )
    parser.add_argument(
        "--list-presets", action="store_true", help="List the built-in presets and exit"
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols to trade (default: every symbol)",
    )
    parser.add_argument("--seed", type=int, default=1, help="Random seed")
    parser.add_argument(
        "--alf-host",
        default=EDUMATCHER_ENGINE_HOST,
        help="Host of pm-alf-gwy (default: EDUMATCHER_ENGINE_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--alf-port",
        type=int,
        default=None,
        help="Port of pm-alf-gwy (default: alf_gateway.port of the deployed config)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Run duration in seconds; 0 means run until stopped",
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
        help="Increase verbosity (-v: INFO, -vv: DEBUG)",
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


def resolve_preset(args: argparse.Namespace) -> Preset:
    if args.preset_file is not None:
        return load_preset_file(args.preset_file)
    return get_preset(args.preset or DEFAULT_PRESET)


def list_presets() -> str:
    lines = []
    for name, p in sorted(builtin_presets().items()):
        lines.append(
            f"{name:16} {p.strategy:10} {p.execution.style:11} "
            f"{p.risk.protection:10} {p.description}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.list_presets:
        print(list_presets())
        raise SystemExit(0)
    if not args.id:
        parser.error("--id is required")
    _configure_logging(args)
    try:
        preset = resolve_preset(args)
    except PresetError as exc:
        raise SystemExit(f"pm-ai-trader: {exc}") from exc
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    spec = AgentSpec(str(args.id).upper(), preset, symbols, int(args.seed))
    port = args.alf_port or load_default_alf_gateway_config().port
    transport = AlfTransport(args.alf_host, port, seed=int(args.seed))
    worker = Worker([spec], transport, name=spec.gateway_id)
    signal.signal(signal.SIGTERM, worker.stop)
    try:
        if not worker.start():
            raise SystemExit(1)
        worker.run(duration=float(args.duration))
    except KeyboardInterrupt:
        log.info("pm-ai-trader interrupted")
    finally:
        worker.close()
    raise SystemExit(0)


if __name__ == "__main__":
    main()
