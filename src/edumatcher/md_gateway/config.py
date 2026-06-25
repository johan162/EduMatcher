"""CALF gateway configuration loading helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from edumatcher.config import (
    ENGINE_CONFIG_FILE,
    ENGINE_PUB_ADDR,
    INDEX_PUB_CONNECT_ADDR,
)


@dataclass(frozen=True)
class MarketDataGatewayConfig:
    """Runtime configuration for ``pm-md-gwy``."""

    enabled: bool = True
    name: str = "md-gwy01"
    bind_address: str = "0.0.0.0"
    port: int = 5570
    engine_pub_addr: str = ENGINE_PUB_ADDR
    index_pub_addr: str = INDEX_PUB_CONNECT_ADDR
    heartbeat_interval_sec: int = 1
    idle_timeout_sec: int = 5
    replay_window_sec: int = 30
    max_symbols_per_client: int = 200
    max_client_queue: int = 10_000


def _as_int(raw: object, field: str) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"market_data_gateway.{field} must be an integer")
    if not isinstance(raw, (int, str, float)):
        raise ValueError(f"market_data_gateway.{field} must be an integer")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"market_data_gateway.{field} must be an integer") from exc


def load_market_data_gateway_config(path: Path) -> MarketDataGatewayConfig:
    """Load optional ``market_data_gateway`` block from engine config YAML."""
    if not path.exists():
        return MarketDataGatewayConfig()

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return MarketDataGatewayConfig()

    md_raw = raw.get("market_data_gateway")
    if md_raw is None:
        return MarketDataGatewayConfig()
    if not isinstance(md_raw, dict):
        raise ValueError("market_data_gateway must be a mapping")

    enabled = bool(md_raw.get("enabled", True))
    name = str(md_raw.get("name", "md-gwy01"))
    bind_address = str(md_raw.get("bind_address", "0.0.0.0"))
    port = _as_int(md_raw.get("port", 5570), "port")
    heartbeat_interval_sec = _as_int(
        md_raw.get("heartbeat_interval_sec", 1),
        "heartbeat_interval_sec",
    )
    idle_timeout_sec = _as_int(md_raw.get("idle_timeout_sec", 5), "idle_timeout_sec")
    replay_window_sec = _as_int(
        md_raw.get("replay_window_sec", 30),
        "replay_window_sec",
    )
    max_symbols_per_client = _as_int(
        md_raw.get("max_symbols_per_client", 200),
        "max_symbols_per_client",
    )
    max_client_queue = _as_int(
        md_raw.get("max_client_queue", 10_000),
        "max_client_queue",
    )

    if port <= 0:
        raise ValueError("market_data_gateway.port must be > 0")
    if heartbeat_interval_sec <= 0:
        raise ValueError("market_data_gateway.heartbeat_interval_sec must be > 0")
    if idle_timeout_sec <= 0:
        raise ValueError("market_data_gateway.idle_timeout_sec must be > 0")
    if replay_window_sec <= 0:
        raise ValueError("market_data_gateway.replay_window_sec must be > 0")
    if max_symbols_per_client <= 0:
        raise ValueError("market_data_gateway.max_symbols_per_client must be > 0")
    if max_client_queue <= 0:
        raise ValueError("market_data_gateway.max_client_queue must be > 0")

    return MarketDataGatewayConfig(
        enabled=enabled,
        name=name,
        bind_address=bind_address,
        port=port,
        engine_pub_addr=ENGINE_PUB_ADDR,
        index_pub_addr=INDEX_PUB_CONNECT_ADDR,
        heartbeat_interval_sec=heartbeat_interval_sec,
        idle_timeout_sec=idle_timeout_sec,
        replay_window_sec=replay_window_sec,
        max_symbols_per_client=max_symbols_per_client,
        max_client_queue=max_client_queue,
    )


def load_default_market_data_gateway_config() -> MarketDataGatewayConfig:
    """Load config from the resolved default engine config file path."""
    return load_market_data_gateway_config(ENGINE_CONFIG_FILE)
