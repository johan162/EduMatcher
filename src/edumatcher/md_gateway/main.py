"""CLI entry point for ``pm-md-gwy`` (CALF market data gateway)."""

from __future__ import annotations

import argparse
from pathlib import Path

from edumatcher.config import (
    ENGINE_CONFIG_FILE,
    ENGINE_PUB_ADDR,
    INDEX_PUB_CONNECT_ADDR,
)
from edumatcher.engine.config_loader import load_engine_config
from edumatcher.md_gateway.config import (
    MarketDataGatewayConfig,
    load_market_data_gateway_config,
)
from edumatcher.md_gateway.gateway import MarketDataGateway


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EduMatcher CALF market data gateway",
    )
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
        default=ENGINE_PUB_ADDR,
        help="Engine PUB socket address (default: tcp://127.0.0.1:5556)",
    )
    parser.add_argument(
        "--index-pub",
        default=INDEX_PUB_CONNECT_ADDR,
        help="Index PUB socket address (default: tcp://127.0.0.1:5558)",
    )
    return parser


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
            max_symbols_per_client=cfg.max_symbols_per_client,
            max_client_queue=cfg.max_client_queue,
        ),
        known_symbols,
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        config, known_symbols = _resolve_config(args)
    except Exception as exc:
        parser.error(str(exc))

    if not config.enabled:
        print("[CALF] market_data_gateway.enabled=false — exiting")
        return

    gateway = MarketDataGateway(config=config, known_symbols=known_symbols)
    gateway.run()


__all__ = ["main", "_build_parser", "_resolve_config"]
