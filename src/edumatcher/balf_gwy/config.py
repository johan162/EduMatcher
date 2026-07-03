"""Configuration loading for ``pm-balf-gwy``.

The gateway reads two sections from the engine config YAML:
- ``balf_gateway`` — BALF-specific runtime settings (port, timeouts, etc.)
- ``gateways.alf``  — gateway identity allowlist shared with ALF in v1.0.0

Gateway identity and ``disconnect_behaviour`` come from ``gateways.alf``
to keep Phase-1 engine changes at zero.  See spec §12.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from edumatcher.config import ENGINE_CONFIG_FILE, ENGINE_PULL_ADDR, ENGINE_PUB_ADDR


@dataclass(frozen=True)
class BalfGatewayConfig:
    """Runtime settings for the BALF TCP gateway."""

    enabled: bool = True
    name: str = "balf-gwy01"
    bind_address: str = "0.0.0.0"
    port: int = 5560
    engine_pull_addr: str = ENGINE_PULL_ADDR
    engine_pub_addr: str = ENGINE_PUB_ADDR
    # Liveness
    heartbeat_interval_sec: float = 1.0
    heartbeat_timeout_sec: float = 5.0
    idle_timeout_sec: float = 30.0
    auth_timeout_sec: float = 10.0
    # Capacity
    max_connections: int = 64
    max_client_queue: int = 10_000
    max_messages_per_second: int = 100
    # Error tolerance before hard-close
    max_errors_before_disconnect: int = 10
    error_window_sec: float = 60.0
    # Duplicate session policy: "REJECT_NEW" or "EVICT_OLD"
    duplicate_session_policy: str = "REJECT_NEW"
    # Gateway roles from gateways.alf: tuple of (gateway_id, role)
    gateway_roles: tuple[tuple[str, str], ...] = ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_int(raw: object, field: str) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"balf_gateway.{field} must be an integer")
    if not isinstance(raw, (int, float, str)):
        raise ValueError(f"balf_gateway.{field} must be an integer")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"balf_gateway.{field} must be an integer") from exc


def _as_float(raw: object, field: str) -> float:
    try:
        val = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"balf_gateway.{field} must be numeric") from exc
    if val <= 0:
        raise ValueError(f"balf_gateway.{field} must be > 0")
    return val


def _parse_gateway_roles(raw: Any) -> tuple[tuple[str, str], ...]:
    """Read gateway identity + role list from ``gateways.alf``."""
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

    # Prefix uniqueness guard (same rule as ALF gateway)
    for idx, (gw_id, _) in enumerate(parsed):
        for other_idx, (other_id, _) in enumerate(parsed):
            if idx != other_idx and other_id.startswith(gw_id):
                raise ValueError(
                    "gateways.alf IDs must not be prefixes of each other "
                    f"({gw_id!r}, {other_id!r})"
                )
    return tuple(parsed)


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------


def load_balf_gateway_config(path: Path) -> BalfGatewayConfig:
    """Load the ``balf_gateway`` section from an engine config YAML.

    Falls back to defaults for any missing field.
    Raises ``ValueError`` for invalid values.
    """
    if not path.exists():
        return BalfGatewayConfig()

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return BalfGatewayConfig()

    gw_roles = _parse_gateway_roles(raw)

    section = raw.get("balf_gateway")
    if section is None:
        return BalfGatewayConfig(gateway_roles=gw_roles)
    if not isinstance(section, dict):
        raise ValueError("balf_gateway must be a mapping")

    enabled = bool(section.get("enabled", True))
    name = str(section.get("name", "balf-gwy01"))
    bind_address = str(section.get("bind_address", "0.0.0.0"))
    port = _as_int(section.get("port", 5560), "port")
    if port <= 0 or port > 65535:
        raise ValueError("balf_gateway.port must be in 1-65535")

    heartbeat_interval_sec = _as_float(
        section.get("heartbeat_interval_sec", 1.0), "heartbeat_interval_sec"
    )
    heartbeat_timeout_sec = _as_float(
        section.get("heartbeat_timeout_sec", 5.0), "heartbeat_timeout_sec"
    )
    idle_timeout_sec = _as_float(
        section.get("idle_timeout_sec", 30.0), "idle_timeout_sec"
    )
    auth_timeout_sec = _as_float(
        section.get("auth_timeout_sec", 10.0), "auth_timeout_sec"
    )
    max_connections = _as_int(section.get("max_connections", 64), "max_connections")
    if max_connections <= 0:
        raise ValueError("balf_gateway.max_connections must be > 0")
    max_client_queue = _as_int(
        section.get("max_client_queue", 10_000), "max_client_queue"
    )
    if max_client_queue <= 0:
        raise ValueError("balf_gateway.max_client_queue must be > 0")
    max_messages_per_second = _as_int(
        section.get("max_messages_per_second", 100), "max_messages_per_second"
    )
    if max_messages_per_second <= 0:
        raise ValueError("balf_gateway.max_messages_per_second must be > 0")
    max_errors_before_disconnect = _as_int(
        section.get("max_errors_before_disconnect", 10),
        "max_errors_before_disconnect",
    )
    if max_errors_before_disconnect <= 0:
        raise ValueError("balf_gateway.max_errors_before_disconnect must be > 0")
    error_window_sec = _as_float(
        section.get("error_window_sec", 60.0), "error_window_sec"
    )

    dup_policy_raw = str(section.get("duplicate_session_policy", "REJECT_NEW")).upper()
    if dup_policy_raw not in {"REJECT_NEW", "EVICT_OLD"}:
        raise ValueError(
            "balf_gateway.duplicate_session_policy must be REJECT_NEW or EVICT_OLD"
        )

    return BalfGatewayConfig(
        enabled=enabled,
        name=name,
        bind_address=bind_address,
        port=port,
        engine_pull_addr=ENGINE_PULL_ADDR,
        engine_pub_addr=ENGINE_PUB_ADDR,
        heartbeat_interval_sec=heartbeat_interval_sec,
        heartbeat_timeout_sec=heartbeat_timeout_sec,
        idle_timeout_sec=idle_timeout_sec,
        auth_timeout_sec=auth_timeout_sec,
        max_connections=max_connections,
        max_client_queue=max_client_queue,
        max_messages_per_second=max_messages_per_second,
        max_errors_before_disconnect=max_errors_before_disconnect,
        error_window_sec=error_window_sec,
        duplicate_session_policy=dup_policy_raw,
        gateway_roles=gw_roles,
    )


def load_default_balf_gateway_config() -> BalfGatewayConfig:
    """Load config from the resolved default engine config path."""
    return load_balf_gateway_config(ENGINE_CONFIG_FILE)
