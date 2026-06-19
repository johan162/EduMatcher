"""RALF gateway configuration loading helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from edumatcher.config import ENGINE_CONFIG_FILE, ENGINE_PUB_ADDR


@dataclass(frozen=True)
class RalfGatewayConfig:
    name: str = "ralf-gwy01"
    bind_address: str = "0.0.0.0"
    port: int = 5580
    engine_pub_addr: str = ENGINE_PUB_ADDR
    replay_retention_sec: int = 86_400
    heartbeat_interval_sec: int = 1
    idle_timeout_sec: int = 5
    max_client_queue: int = 10_000
    allowed_roles: tuple[str, ...] = ("CLEARING", "DROP_COPY", "AUDIT")


def _as_int(raw: object, field: str) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"post_trade_gateway.{field} must be an integer")
    if not isinstance(raw, (int, float, str, bytes, bytearray)):
        raise ValueError(f"post_trade_gateway.{field} must be an integer")
    try:
        val = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"post_trade_gateway.{field} must be an integer") from exc
    return val


def load_ralf_gateway_config(path: Path) -> RalfGatewayConfig:
    """Load optional post_trade_gateway section from engine_config.yaml."""
    if not path.exists():
        return RalfGatewayConfig()

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        return RalfGatewayConfig()

    pg = raw.get("post_trade_gateway")
    if pg is None:
        return RalfGatewayConfig()
    if not isinstance(pg, dict):
        raise ValueError("post_trade_gateway must be a mapping")

    name = str(pg.get("name", "ralf-gwy01"))
    bind_address = str(pg.get("bind_address", "0.0.0.0"))
    port = _as_int(pg.get("port", 5580), "port")
    replay_retention_sec = _as_int(
        pg.get("replay_retention_sec", 86_400), "replay_retention_sec"
    )
    heartbeat_interval_sec = _as_int(
        pg.get("heartbeat_interval_sec", 1), "heartbeat_interval_sec"
    )
    idle_timeout_sec = _as_int(pg.get("idle_timeout_sec", 5), "idle_timeout_sec")
    max_client_queue = _as_int(pg.get("max_client_queue", 10_000), "max_client_queue")

    allowed_roles_raw = pg.get("allowed_roles", ["CLEARING", "DROP_COPY", "AUDIT"])
    if not isinstance(allowed_roles_raw, list):
        raise ValueError("post_trade_gateway.allowed_roles must be a list")
    allowed_roles = tuple(str(x).upper() for x in allowed_roles_raw)

    if port <= 0:
        raise ValueError("post_trade_gateway.port must be > 0")
    if replay_retention_sec <= 0:
        raise ValueError("post_trade_gateway.replay_retention_sec must be > 0")
    if heartbeat_interval_sec <= 0:
        raise ValueError("post_trade_gateway.heartbeat_interval_sec must be > 0")
    if idle_timeout_sec <= 0:
        raise ValueError("post_trade_gateway.idle_timeout_sec must be > 0")
    if max_client_queue <= 0:
        raise ValueError("post_trade_gateway.max_client_queue must be > 0")

    return RalfGatewayConfig(
        name=name,
        bind_address=bind_address,
        port=port,
        engine_pub_addr=ENGINE_PUB_ADDR,
        replay_retention_sec=replay_retention_sec,
        heartbeat_interval_sec=heartbeat_interval_sec,
        idle_timeout_sec=idle_timeout_sec,
        max_client_queue=max_client_queue,
        allowed_roles=allowed_roles,
    )


def load_default_ralf_gateway_config() -> RalfGatewayConfig:
    """Load gateway config from EDUMATCHER_CONFIG resolution path."""
    return load_ralf_gateway_config(ENGINE_CONFIG_FILE)
