"""``pm-log-srv`` configuration loading helpers.

Mirrors ``edumatcher.md_gateway.config`` exactly: a frozen dataclass of
resolved settings, a loader that reads the optional ``log_server:`` block
from ``engine_config.yaml`` (docs-design/EduMatcher-log-srv.md §7.7), and a
validator usable by ``pm-config-gen``/config-validation tooling. The nested
``client:`` sub-block from §7.7 (``connect_timeout_sec``/
``failover_timeout_sec``/``failover_dir``) is phase-2 territory — it only
matters once ``TcpLogHandler`` exists to read it — so it is deliberately
not modeled here yet; only the server-side fields are.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from edumatcher.config import (
    ENGINE_CONFIG_FILE,
    LOG_DB_FILE,
    LOG_SRV_HOST,
    LOG_SRV_PORT,
)
from edumatcher.logclient.protocol import DEFAULT_MAX_MESSAGE_BYTES

DEFAULT_RETENTION_DAYS = 30  # §6.5 — null/0 opts back into unbounded retention


@dataclass(frozen=True)
class LogServerConfig:
    """Runtime configuration for ``pm-log-srv``."""

    enabled: bool = True
    name: str = "log-srv01"
    bind_address: str = "0.0.0.0"
    port: int = LOG_SRV_PORT
    db_path: Path = LOG_DB_FILE
    retention_days: int | None = DEFAULT_RETENTION_DAYS
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES
    max_client_queue: int = 10_000
    write_batch_size: int = 50
    write_batch_interval_ms: int = 100
    heartbeat_interval_sec: int = 5


def _as_int(raw: object, field: str) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"log_server.{field} must be an integer")
    if not isinstance(raw, (int, str, float)):
        raise ValueError(f"log_server.{field} must be an integer")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"log_server.{field} must be an integer") from exc


def _as_optional_int(raw: object, field: str) -> int | None:
    if raw is None:
        return None
    return _as_int(raw, field)


def _load_log_server_config_from_raw(raw: dict[str, Any]) -> LogServerConfig:
    ls_raw = raw.get("log_server")
    if ls_raw is None:
        return LogServerConfig()
    if not isinstance(ls_raw, dict):
        raise ValueError("log_server must be a mapping")

    enabled = bool(ls_raw.get("enabled", True))
    name = str(ls_raw.get("name", "log-srv01"))
    bind_address = str(ls_raw.get("bind_address", "0.0.0.0"))
    port = _as_int(ls_raw.get("port", LOG_SRV_PORT), "port")
    db_path_raw = ls_raw.get("db_path", str(LOG_DB_FILE))
    retention_days = _as_optional_int(
        ls_raw.get("retention_days", DEFAULT_RETENTION_DAYS), "retention_days"
    )
    max_message_bytes = _as_int(
        ls_raw.get("max_message_bytes", DEFAULT_MAX_MESSAGE_BYTES),
        "max_message_bytes",
    )
    max_client_queue = _as_int(
        ls_raw.get("max_client_queue", 10_000), "max_client_queue"
    )
    write_batch_size = _as_int(ls_raw.get("write_batch_size", 50), "write_batch_size")
    write_batch_interval_ms = _as_int(
        ls_raw.get("write_batch_interval_ms", 100), "write_batch_interval_ms"
    )
    heartbeat_interval_sec = _as_int(
        ls_raw.get("heartbeat_interval_sec", 5), "heartbeat_interval_sec"
    )

    if port <= 0:
        raise ValueError("log_server.port must be > 0")
    if retention_days is not None and retention_days < 0:
        raise ValueError("log_server.retention_days must be >= 0 or null")
    if max_message_bytes <= 0:
        raise ValueError("log_server.max_message_bytes must be > 0")
    if max_client_queue <= 0:
        raise ValueError("log_server.max_client_queue must be > 0")
    if write_batch_size <= 0:
        raise ValueError("log_server.write_batch_size must be > 0")
    if write_batch_interval_ms <= 0:
        raise ValueError("log_server.write_batch_interval_ms must be > 0")
    if heartbeat_interval_sec <= 0:
        raise ValueError("log_server.heartbeat_interval_sec must be > 0")

    # retention_days: 0 is documented (§6.5, §7.6) as an alias for "unbounded",
    # same as passing --retention-days 0 on the CLI — normalize here so every
    # downstream consumer only ever sees None for "no pruning".
    if retention_days == 0:
        retention_days = None

    return LogServerConfig(
        enabled=enabled,
        name=name,
        bind_address=bind_address,
        port=port,
        db_path=Path(str(db_path_raw)),
        retention_days=retention_days,
        max_message_bytes=max_message_bytes,
        max_client_queue=max_client_queue,
        write_batch_size=write_batch_size,
        write_batch_interval_ms=write_batch_interval_ms,
        heartbeat_interval_sec=heartbeat_interval_sec,
    )


def load_log_server_config(path: Path) -> LogServerConfig:
    """Load optional ``log_server`` block from engine config YAML."""
    if not path.exists():
        return LogServerConfig()

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return LogServerConfig()

    return _load_log_server_config_from_raw(raw)


def validate_log_server_section(raw: dict[str, Any]) -> None:
    """Validate the log_server section using runtime loader semantics."""
    _load_log_server_config_from_raw(raw)


def load_default_log_server_config() -> LogServerConfig:
    """Load config from the resolved default engine config file path."""
    return load_log_server_config(ENGINE_CONFIG_FILE)


def resolve_host_default() -> str:
    """Default bind/connect host used when no config/CLI override is given."""
    return LOG_SRV_HOST
