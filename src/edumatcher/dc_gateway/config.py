"""DC gateway configuration loading helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from edumatcher.config import DROP_COPY_PUB_ADDR, ENGINE_CONFIG_FILE


@dataclass(frozen=True)
class DcGatewayConfig:
    """Runtime settings for the DC TCP gateway."""

    name: str = "dc-gwy01"
    bind_address: str = "0.0.0.0"
    port: int = 5590
    drop_copy_pub_addr: str = DROP_COPY_PUB_ADDR
    heartbeat_interval_sec: int = 5
    idle_timeout_sec: int = 30
    max_client_queue: int = 10_000


def _as_int(raw: object, field: str) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"dc_gateway.{field} must be an integer")
    if not isinstance(raw, (int, float, str, bytes, bytearray)):
        raise ValueError(f"dc_gateway.{field} must be an integer")
    try:
        val = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"dc_gateway.{field} must be an integer") from exc
    return val


def _load_dc_gateway_config_from_raw(raw: dict[str, Any]) -> DcGatewayConfig:
    section = raw.get("dc_gateway")
    if section is None:
        return DcGatewayConfig()
    if not isinstance(section, dict):
        raise ValueError("dc_gateway must be a mapping")

    name = str(section.get("name", "dc-gwy01"))
    bind_address = str(section.get("bind_address", "0.0.0.0"))
    port = _as_int(section.get("port", 5590), "port")
    heartbeat_interval_sec = _as_int(
        section.get("heartbeat_interval_sec", 5), "heartbeat_interval_sec"
    )
    idle_timeout_sec = _as_int(section.get("idle_timeout_sec", 30), "idle_timeout_sec")
    max_client_queue = _as_int(
        section.get("max_client_queue", 10_000), "max_client_queue"
    )

    if port <= 0:
        raise ValueError("dc_gateway.port must be > 0")
    if heartbeat_interval_sec <= 0:
        raise ValueError("dc_gateway.heartbeat_interval_sec must be > 0")
    if idle_timeout_sec <= 0:
        raise ValueError("dc_gateway.idle_timeout_sec must be > 0")
    if max_client_queue <= 0:
        raise ValueError("dc_gateway.max_client_queue must be > 0")

    return DcGatewayConfig(
        name=name,
        bind_address=bind_address,
        port=port,
        # drop_copy_pub_addr is always taken from the global DROP_COPY_PUB_ADDR
        # constant. It cannot be overridden per-gateway in YAML; use the
        # --engine-dc-pub CLI flag.
        drop_copy_pub_addr=DROP_COPY_PUB_ADDR,
        heartbeat_interval_sec=heartbeat_interval_sec,
        idle_timeout_sec=idle_timeout_sec,
        max_client_queue=max_client_queue,
    )


def load_dc_gateway_config(path: Path) -> DcGatewayConfig:
    """Load optional dc_gateway section from engine_config.yaml."""
    if not path.exists():
        return DcGatewayConfig()

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        return DcGatewayConfig()

    return _load_dc_gateway_config_from_raw(raw)


def validate_dc_gateway_section(raw: dict[str, Any]) -> None:
    """Validate dc_gateway section using runtime loader semantics."""

    _load_dc_gateway_config_from_raw(raw)


def load_default_dc_gateway_config() -> DcGatewayConfig:
    """Load gateway config from EDUMATCHER_CONFIG resolution path."""
    return load_dc_gateway_config(ENGINE_CONFIG_FILE)
