"""CLI entrypoint for pm-alf-gwy."""

from __future__ import annotations

import argparse
from pathlib import Path

from edumatcher.alf_gwy.config import (
    AlfGatewayConfig,
    load_alf_gateway_config,
    load_default_alf_gateway_config,
)
from edumatcher.alf_gwy.gateway import AlfGateway
from edumatcher.config import ENGINE_CONFIG_FILE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher ALF TCP gateway")
    parser.add_argument(
        "--config",
        "-c",
        default=str(ENGINE_CONFIG_FILE),
        help="Engine config YAML path (default: engine_config.yaml)",
    )
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
    return parser


def _resolve_config(args: argparse.Namespace) -> AlfGatewayConfig:
    cfg_path = Path(str(args.config))
    cfg = load_alf_gateway_config(cfg_path)

    bind_address = str(args.bind) if args.bind else cfg.bind_address
    port = int(args.port) if args.port else cfg.port

    engine_pull_addr = cfg.engine_pull_addr
    engine_pub_addr = cfg.engine_pub_addr
    if args.engine_host:
        engine_pull_addr = f"tcp://{args.engine_host}:5555"
        engine_pub_addr = f"tcp://{args.engine_host}:5556"

    return AlfGatewayConfig(
        enabled=cfg.enabled,
        name=cfg.name,
        bind_address=bind_address,
        port=port,
        engine_pull_addr=engine_pull_addr,
        engine_pub_addr=engine_pub_addr,
        heartbeat_interval_sec=cfg.heartbeat_interval_sec,
        idle_timeout_sec=cfg.idle_timeout_sec,
        max_connections=cfg.max_connections,
        max_client_queue=cfg.max_client_queue,
        max_commands_per_second=cfg.max_commands_per_second,
        max_errors_before_disconnect=cfg.max_errors_before_disconnect,
        error_window_sec=cfg.error_window_sec,
        gateway_roles=cfg.gateway_roles,
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        config = _resolve_config(args)
    except Exception as exc:
        parser.error(str(exc))

    if not config.enabled:
        parser.error("alf_gateway.enabled is false")

    gateway = AlfGateway(config)
    try:
        gateway.run()
    finally:
        gateway.close()


__all__ = [
    "main",
    "_build_parser",
    "_resolve_config",
    "load_default_alf_gateway_config",
]
