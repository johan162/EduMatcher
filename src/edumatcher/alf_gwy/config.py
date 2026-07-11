"""Configuration loading helpers for ``pm-alf-gwy``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from edumatcher.config import ENGINE_CONFIG_FILE, ENGINE_PULL_ADDR, ENGINE_PUB_ADDR


@dataclass(frozen=True)
class AlfGatewayConfig:
    """Runtime settings for ALF TCP gateway."""

    enabled: bool = True
    name: str = "alf-gwy01"
    bind_address: str = "0.0.0.0"
    port: int = 5565
    engine_pull_addr: str = ENGINE_PULL_ADDR
    engine_pub_addr: str = ENGINE_PUB_ADDR
    heartbeat_interval_sec: int = 5
    idle_timeout_sec: int = 30
    max_connections: int = 64
    max_client_queue: int = 10_000
    max_commands_per_second: int = 100
    max_errors_before_disconnect: int = 50
    error_window_sec: int = 60
    gateway_roles: tuple[tuple[str, str], ...] = ()


def _as_int(raw: object, field: str) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"alf_gateway.{field} must be an integer")
    if not isinstance(raw, (int, float, str, bytes, bytearray)):
        raise ValueError(f"alf_gateway.{field} must be an integer")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"alf_gateway.{field} must be an integer") from exc


def _parse_gateway_roles(raw: Any) -> tuple[tuple[str, str], ...]:
    gateways = raw.get("gateways") if isinstance(raw, dict) else None
    if not isinstance(gateways, dict):
        return ()

    alf = gateways.get("alf")
    if not isinstance(alf, list):
        return ()

    parsed: list[tuple[str, str]] = []
    for idx, item in enumerate(alf):
        if not isinstance(item, dict):
            raise ValueError(f"gateways.alf[{idx}] must be a mapping")
        gw_id = str(item.get("id", "")).strip().upper()
        role = str(item.get("role", "TRADER")).strip().upper()
        if not gw_id:
            raise ValueError(f"gateways.alf[{idx}].id must be a non-empty string")
        parsed.append((gw_id, role))

    for idx, (gw_id, _role) in enumerate(parsed):
        for other_idx, (other_id, _other_role) in enumerate(parsed):
            if idx == other_idx:
                continue
            if other_id.startswith(gw_id):
                raise ValueError(
                    "gateways.alf IDs must not be prefixes of each other "
                    f"({gw_id!r}, {other_id!r})"
                )
    return tuple(parsed)


def _load_alf_gateway_config_from_raw(raw: dict[str, Any]) -> AlfGatewayConfig:
    gw_roles = _parse_gateway_roles(raw)

    section = raw.get("alf_gateway")
    if section is None:
        return AlfGatewayConfig(gateway_roles=gw_roles)
    if not isinstance(section, dict):
        raise ValueError("alf_gateway must be a mapping")

    enabled = bool(section.get("enabled", True))
    name = str(section.get("name", "alf-gwy01"))
    bind_address = str(section.get("bind_address", "0.0.0.0"))
    port = _as_int(section.get("port", 5565), "port")
    heartbeat_interval_sec = _as_int(
        section.get("heartbeat_interval_sec", 5), "heartbeat_interval_sec"
    )
    idle_timeout_sec = _as_int(section.get("idle_timeout_sec", 30), "idle_timeout_sec")
    max_connections = _as_int(section.get("max_connections", 64), "max_connections")
    max_client_queue = _as_int(
        section.get("max_client_queue", 10_000), "max_client_queue"
    )
    max_commands_per_second = _as_int(
        section.get("max_commands_per_second", 100), "max_commands_per_second"
    )
    max_errors_before_disconnect = _as_int(
        section.get("max_errors_before_disconnect", 50),
        "max_errors_before_disconnect",
    )
    error_window_sec = _as_int(section.get("error_window_sec", 60), "error_window_sec")

    if port <= 0:
        raise ValueError("alf_gateway.port must be > 0")
    if heartbeat_interval_sec <= 0:
        raise ValueError("alf_gateway.heartbeat_interval_sec must be > 0")
    if idle_timeout_sec <= 0:
        raise ValueError("alf_gateway.idle_timeout_sec must be > 0")
    if max_connections <= 0:
        raise ValueError("alf_gateway.max_connections must be > 0")
    if max_client_queue <= 0:
        raise ValueError("alf_gateway.max_client_queue must be > 0")
    if max_commands_per_second <= 0:
        raise ValueError("alf_gateway.max_commands_per_second must be > 0")
    if max_errors_before_disconnect <= 0:
        raise ValueError("alf_gateway.max_errors_before_disconnect must be > 0")
    if error_window_sec <= 0:
        raise ValueError("alf_gateway.error_window_sec must be > 0")

    return AlfGatewayConfig(
        enabled=enabled,
        name=name,
        bind_address=bind_address,
        port=port,
        engine_pull_addr=ENGINE_PULL_ADDR,
        engine_pub_addr=ENGINE_PUB_ADDR,
        heartbeat_interval_sec=heartbeat_interval_sec,
        idle_timeout_sec=idle_timeout_sec,
        max_connections=max_connections,
        max_client_queue=max_client_queue,
        max_commands_per_second=max_commands_per_second,
        max_errors_before_disconnect=max_errors_before_disconnect,
        error_window_sec=error_window_sec,
        gateway_roles=gw_roles,
    )


def load_alf_gateway_config(path: Path) -> AlfGatewayConfig:
    """Load optional ``alf_gateway`` section from engine config YAML."""
    if not path.exists():
        return AlfGatewayConfig()

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return AlfGatewayConfig()

    return _load_alf_gateway_config_from_raw(raw)


def validate_alf_gateway_section(raw: dict[str, Any]) -> None:
    """Validate the ``alf_gateway`` section using runtime loader semantics."""
    _load_alf_gateway_config_from_raw(raw)


def load_default_alf_gateway_config() -> AlfGatewayConfig:
    """Load config from the resolved default engine config path."""
    return load_alf_gateway_config(ENGINE_CONFIG_FILE)
