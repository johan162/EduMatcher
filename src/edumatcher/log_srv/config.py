"""``pm-log-srv`` configuration loading helpers.

Mirrors ``edumatcher.md_gateway.config`` exactly: a frozen dataclass of
resolved settings, a loader that reads the optional ``log_server:`` block
from ``engine_config.yaml`` (docs-design/EduMatcher-log-srv.md §7.7), and a
validator usable by ``pm-config-gen``/config-validation tooling. The nested
``client:`` sub-block from §7.7 (``connect_timeout_sec``/
``failover_timeout_sec``/``failover_dir``) is modeled by
:class:`LogClientConfig` / :func:`load_log_client_config` below, read by
every ``pm-*`` process's own ``TcpLogHandler`` auto-detection (§8.3) —
kept in this same module since both blocks live under the one
``log_server:`` YAML key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from edumatcher.config import (
    ENGINE_CONFIG_FILE,
    LOG_DB_FILE,
    LOG_FALLBACK_DIR,
    LOG_SRV_HOST,
    LOG_SRV_PORT,
    LOG_SRV_PUB_PORT,
    LOG_SRV_PULL_PORT,
)
from edumatcher.logclient.protocol import DEFAULT_MAX_MESSAGE_BYTES

DEFAULT_RETENTION_DAYS = 30  # §6.5 — null/0 opts back into unbounded retention

# §7.7/§8.2/§8.6 client-side defaults.
DEFAULT_CONNECT_TIMEOUT_SEC = 0.5
DEFAULT_FAILOVER_TIMEOUT_SEC = 30.0

# LALF-PS defaults. A 30 s lease with the documented "renew at half the lease"
# guidance means a crashed viewer is reaped within 30 s while a healthy one
# only spends one small PUSH every 15 s to stay alive.
DEFAULT_LEASE_SEC = 30
DEFAULT_MAX_LEASE_SEC = 300
DEFAULT_MAX_SUBSCRIBERS = 32
DEFAULT_NOTIFY_INTERVAL_MS = 250
DEFAULT_BACKFILL_CHUNK_ROWS = 500
DEFAULT_MAX_BACKFILL_MINUTES = 1440  # 24 h
DEFAULT_MAX_BACKFILL_ROWS = 100_000
DEFAULT_MAX_PENDING_ROWS = 20_000
DEFAULT_PUB_SNDHWM = 10_000


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

    # --- LALF-PS (ZeroMQ log distribution interface) ---------------------
    # Disabled independently of the TCP collector: a deployment that only
    # wants centralized persistence and queries via pm-log-cli should not
    # have to bind two extra ports it will never use.
    pubsub_enabled: bool = True
    pub_port: int = LOG_SRV_PUB_PORT
    pull_port: int = LOG_SRV_PULL_PORT
    lease_sec: int = DEFAULT_LEASE_SEC
    max_lease_sec: int = DEFAULT_MAX_LEASE_SEC
    max_subscribers: int = DEFAULT_MAX_SUBSCRIBERS
    notify_interval_ms: int = DEFAULT_NOTIFY_INTERVAL_MS
    backfill_chunk_rows: int = DEFAULT_BACKFILL_CHUNK_ROWS
    max_backfill_minutes: int = DEFAULT_MAX_BACKFILL_MINUTES
    max_backfill_rows: int = DEFAULT_MAX_BACKFILL_ROWS
    max_pending_rows: int = DEFAULT_MAX_PENDING_ROWS
    pub_sndhwm: int = DEFAULT_PUB_SNDHWM

    @property
    def pub_addr(self) -> str:
        """ZeroMQ bind address for the LALF-PS PUB socket."""
        return f"tcp://{self.bind_address}:{self.pub_port}"

    @property
    def pull_addr(self) -> str:
        """ZeroMQ bind address for the LALF-PS control PULL socket."""
        return f"tcp://{self.bind_address}:{self.pull_port}"


@dataclass(frozen=True)
class LogClientConfig:
    """Client-side defaults for ``TcpLogHandler`` (§7.7's nested ``client:`` block).

    Read by every ``pm-*`` process's own auto-detection (§8.3) — one
    shared source of truth for "how a client should behave" rather than
    19 independently-configured copies (§7.7).
    """

    connect_timeout_sec: float = DEFAULT_CONNECT_TIMEOUT_SEC
    failover_timeout_sec: float = DEFAULT_FAILOVER_TIMEOUT_SEC
    failover_dir: Path = LOG_FALLBACK_DIR


def _as_float(raw: object, field: str) -> float:
    if isinstance(raw, bool):
        raise ValueError(f"log_server.client.{field} must be a number")
    if not isinstance(raw, (int, str, float)):
        raise ValueError(f"log_server.client.{field} must be a number")
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"log_server.client.{field} must be a number") from exc


def _load_log_client_config_from_raw(raw: dict[str, Any]) -> LogClientConfig:
    ls_raw = raw.get("log_server")
    if ls_raw is None or not isinstance(ls_raw, dict):
        return LogClientConfig()

    client_raw = ls_raw.get("client")
    if client_raw is None:
        return LogClientConfig()
    if not isinstance(client_raw, dict):
        raise ValueError("log_server.client must be a mapping")

    connect_timeout_sec = _as_float(
        client_raw.get("connect_timeout_sec", DEFAULT_CONNECT_TIMEOUT_SEC),
        "connect_timeout_sec",
    )
    failover_timeout_sec = _as_float(
        client_raw.get("failover_timeout_sec", DEFAULT_FAILOVER_TIMEOUT_SEC),
        "failover_timeout_sec",
    )
    failover_dir = Path(str(client_raw.get("failover_dir", str(LOG_FALLBACK_DIR))))

    if connect_timeout_sec <= 0:
        raise ValueError("log_server.client.connect_timeout_sec must be > 0")
    if failover_timeout_sec < 0:
        raise ValueError("log_server.client.failover_timeout_sec must be >= 0")

    return LogClientConfig(
        connect_timeout_sec=connect_timeout_sec,
        failover_timeout_sec=failover_timeout_sec,
        failover_dir=failover_dir,
    )


def load_log_client_config(path: Path) -> LogClientConfig:
    """Load the optional ``log_server.client`` block from engine config YAML."""
    if not path.exists():
        return LogClientConfig()

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return LogClientConfig()

    return _load_log_client_config_from_raw(raw)


def load_default_log_client_config() -> LogClientConfig:
    """Load the client config from the resolved default engine config file path."""
    return load_log_client_config(ENGINE_CONFIG_FILE)


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

    pubsub_enabled = bool(ls_raw.get("pubsub_enabled", True))
    pub_port = _as_int(ls_raw.get("pub_port", LOG_SRV_PUB_PORT), "pub_port")
    pull_port = _as_int(ls_raw.get("pull_port", LOG_SRV_PULL_PORT), "pull_port")
    lease_sec = _as_int(ls_raw.get("lease_sec", DEFAULT_LEASE_SEC), "lease_sec")
    max_lease_sec = _as_int(
        ls_raw.get("max_lease_sec", DEFAULT_MAX_LEASE_SEC), "max_lease_sec"
    )
    max_subscribers = _as_int(
        ls_raw.get("max_subscribers", DEFAULT_MAX_SUBSCRIBERS), "max_subscribers"
    )
    notify_interval_ms = _as_int(
        ls_raw.get("notify_interval_ms", DEFAULT_NOTIFY_INTERVAL_MS),
        "notify_interval_ms",
    )
    backfill_chunk_rows = _as_int(
        ls_raw.get("backfill_chunk_rows", DEFAULT_BACKFILL_CHUNK_ROWS),
        "backfill_chunk_rows",
    )
    max_backfill_minutes = _as_int(
        ls_raw.get("max_backfill_minutes", DEFAULT_MAX_BACKFILL_MINUTES),
        "max_backfill_minutes",
    )
    max_backfill_rows = _as_int(
        ls_raw.get("max_backfill_rows", DEFAULT_MAX_BACKFILL_ROWS),
        "max_backfill_rows",
    )
    max_pending_rows = _as_int(
        ls_raw.get("max_pending_rows", DEFAULT_MAX_PENDING_ROWS), "max_pending_rows"
    )
    pub_sndhwm = _as_int(ls_raw.get("pub_sndhwm", DEFAULT_PUB_SNDHWM), "pub_sndhwm")

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
    if pub_port <= 0:
        raise ValueError("log_server.pub_port must be > 0")
    if pull_port <= 0:
        raise ValueError("log_server.pull_port must be > 0")
    if len({port, pub_port, pull_port}) != 3:
        raise ValueError(
            "log_server.port, pub_port and pull_port must all be different"
        )
    if lease_sec <= 0:
        raise ValueError("log_server.lease_sec must be > 0")
    if max_lease_sec < lease_sec:
        raise ValueError("log_server.max_lease_sec must be >= lease_sec")
    if max_subscribers <= 0:
        raise ValueError("log_server.max_subscribers must be > 0")
    if notify_interval_ms <= 0:
        raise ValueError("log_server.notify_interval_ms must be > 0")
    if backfill_chunk_rows <= 0:
        raise ValueError("log_server.backfill_chunk_rows must be > 0")
    if max_backfill_minutes <= 0:
        raise ValueError("log_server.max_backfill_minutes must be > 0")
    if max_backfill_rows <= 0:
        raise ValueError("log_server.max_backfill_rows must be > 0")
    if max_pending_rows <= 0:
        raise ValueError("log_server.max_pending_rows must be > 0")
    if pub_sndhwm <= 0:
        raise ValueError("log_server.pub_sndhwm must be > 0")

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
        pubsub_enabled=pubsub_enabled,
        pub_port=pub_port,
        pull_port=pull_port,
        lease_sec=lease_sec,
        max_lease_sec=max_lease_sec,
        max_subscribers=max_subscribers,
        notify_interval_ms=notify_interval_ms,
        backfill_chunk_rows=backfill_chunk_rows,
        max_backfill_minutes=max_backfill_minutes,
        max_backfill_rows=max_backfill_rows,
        max_pending_rows=max_pending_rows,
        pub_sndhwm=pub_sndhwm,
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
    _load_log_client_config_from_raw(raw)


def load_default_log_server_config() -> LogServerConfig:
    """Load config from the resolved default engine config file path."""
    return load_log_server_config(ENGINE_CONFIG_FILE)


def resolve_host_default() -> str:
    """Default bind/connect host used when no config/CLI override is given."""
    return LOG_SRV_HOST
