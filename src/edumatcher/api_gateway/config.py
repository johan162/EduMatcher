"""Configuration loading for ``pm-api-gwy``.

The original design used a separate ``api_gateway_config.yaml``. The project
already keeps CALF and RALF gateway settings in ``engine_config.yaml``, so this
implementation follows that established pattern and reads optional
``api_gateways`` blocks from the central engine config. API keys are plain
bearer tokens because EduMatcher is an educational system; the loader keeps the
parsing rules explicit so switching to hashed keys later is localised to this
module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from edumatcher.config import (
    AUDIT_INDEX_DB_FILE,
    ENGINE_PULL_ADDR,
    ENGINE_PUB_ADDR,
    INDEX_PULL_ADDR,
    INDEX_PUB_ADDR,
    resolve_data_path,
    STATS_DB_FILE,
)
from edumatcher.stats.trading_day import resolve_timezone


@dataclass(frozen=True)
class ApiCredential:
    """One API key mapped to one optional engine gateway identity."""

    api_key: str
    gateway_id: str | None
    description: str = ""


@dataclass(frozen=True)
class RateLimitConfig:
    """Token-bucket write limiter settings."""

    writes_per_second: int = 10
    burst: int = 20


@dataclass(frozen=True)
class TimeoutConfig:
    """Timeouts for engine handshakes and request/reply calls."""

    engine_auth_sec: float = 3.0
    engine_reply_sec: float = 3.0
    wait_ack_sec: float = 3.0


@dataclass(frozen=True)
class ApiGatewayConfig:
    """Runtime configuration for ``pm-api-gwy``."""

    name: str = "default"
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    engine_pull_addr: str = ENGINE_PULL_ADDR
    engine_pub_addr: str = ENGINE_PUB_ADDR
    index_pull_addr: str = INDEX_PULL_ADDR
    index_pub_addr: str = INDEX_PUB_ADDR
    stats_db: Path = STATS_DB_FILE
    #: `pm-audit`'s index, opened **read-only** for the admin order-lifecycle
    #: endpoint. The gateway never writes it and never requires it: when the
    #: file is absent — because `pm-audit` is not deployed, or has not indexed
    #: yet — that one endpoint reports it and every other route is unaffected.
    #: The audit trail is the venue's complete cross-gateway event record, so
    #: reading it is preferable to the gateway keeping a second, weaker
    #: lifecycle store of its own.
    audit_db: Path = AUDIT_INDEX_DB_FILE
    #: How long a *terminal* order (FILLED, CANCELLED, EXPIRED, REJECTED)
    #: stays in the in-memory order cache before being evicted.
    #:
    #: The cache is the read model behind `GET /orders` and the admin order
    #: table. Without eviction it grows for the lifetime of the process and an
    #: admin table would still be showing orders that filled hours ago. One
    #: hour keeps a session's recent activity visible while bounding the
    #: memory; older orders live in the audit trail, which is durable.
    #: Set to 0 to disable eviction (the previous, unbounded behaviour).
    order_retention_sec: int = 3600
    #: How long the market-data stream cache retains the per-symbol ``trades``
    #: tail that backs the snapshot/resume verbs on WS /api/v1/market-data.
    #: The latest ``book``/``depth``/``auction`` snapshot per topic is kept
    #: regardless of age (a gap there is self-healing); only the trade tail is
    #: bounded. 30–60s is enough for a browser to repair a brief drop; 0
    #: disables the trade buffer while still serving latest snapshots.
    market_data_cache_sec: int = 60
    #: Optional override for the session timezone that ``date`` filters on the
    #: history endpoints resolve their trading day in. ``None`` — the default —
    #: means "use the timezone ``stats_db`` was recorded with", which is what
    #: keeps the gateway and the recorder from disagreeing. Set this only when
    #: it must deliberately differ.
    session_timezone: str | None = None
    log_level: str = "info"
    swagger_enabled: bool = True
    credentials: tuple[ApiCredential, ...] = ()
    rate_limit: RateLimitConfig = RateLimitConfig()
    timeouts: TimeoutConfig = TimeoutConfig()


def _as_int(raw: object, section: str, field: str) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"{section}.{field} must be an integer")
    if not isinstance(raw, (int, float, str, bytes, bytearray)):
        raise ValueError(f"{section}.{field} must be an integer")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{section}.{field} must be an integer") from exc


def _as_float(raw: object, section: str, field: str) -> float:
    if isinstance(raw, bool):
        raise ValueError(f"{section}.{field} must be a number")
    if not isinstance(raw, (int, float, str, bytes, bytearray)):
        raise ValueError(f"{section}.{field} must be a number")
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{section}.{field} must be a number") from exc


def _load_credentials(raw: Any, section_name: str) -> tuple[ApiCredential, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{section_name}.credentials must be a list")

    credentials: list[ApiCredential] = []
    seen_keys: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{section_name}.credentials[{index}] must be a mapping")
        api_key = str(item.get("api_key", "")).strip()
        if not api_key:
            raise ValueError(f"{section_name}.credentials[{index}].api_key is required")
        if api_key in seen_keys:
            raise ValueError(
                f"duplicate {section_name} credential key at index {index}"
            )
        seen_keys.add(api_key)

        gateway_raw = item.get("gateway_id")
        gateway_id = None if gateway_raw is None else str(gateway_raw).strip().upper()
        description = str(item.get("description", ""))
        credentials.append(
            ApiCredential(
                api_key=api_key, gateway_id=gateway_id, description=description
            )
        )
    return tuple(credentials)


def _load_api_gateway_section(
    section: dict[str, Any], section_name: str, gateway_name: str
) -> ApiGatewayConfig:
    rate_raw = section.get("rate_limit", {})
    if not isinstance(rate_raw, dict):
        raise ValueError(f"{section_name}.rate_limit must be a mapping")
    writes_per_second = _as_int(
        rate_raw.get("writes_per_second", 10),
        f"{section_name}.rate_limit",
        "writes_per_second",
    )
    burst = _as_int(rate_raw.get("burst", 20), f"{section_name}.rate_limit", "burst")
    if writes_per_second <= 0:
        raise ValueError(f"{section_name}.rate_limit.writes_per_second must be > 0")
    if burst <= 0:
        raise ValueError(f"{section_name}.rate_limit.burst must be > 0")

    timeouts_raw = section.get("timeouts", {})
    if not isinstance(timeouts_raw, dict):
        raise ValueError(f"{section_name}.timeouts must be a mapping")
    engine_auth_sec = _as_float(
        timeouts_raw.get("engine_auth_sec", 3.0),
        f"{section_name}.timeouts",
        "engine_auth_sec",
    )
    engine_reply_sec = _as_float(
        timeouts_raw.get("engine_reply_sec", 3.0),
        f"{section_name}.timeouts",
        "engine_reply_sec",
    )
    wait_ack_sec = _as_float(
        timeouts_raw.get("wait_ack_sec", 3.0),
        f"{section_name}.timeouts",
        "wait_ack_sec",
    )
    for name, value in {
        "engine_auth_sec": engine_auth_sec,
        "engine_reply_sec": engine_reply_sec,
        "wait_ack_sec": wait_ack_sec,
    }.items():
        if value <= 0:
            raise ValueError(f"{section_name}.timeouts.{name} must be > 0")

    port = _as_int(section.get("port", 8080), section_name, "port")
    if port <= 0:
        raise ValueError(f"{section_name}.port must be > 0")

    stats_db_raw = section.get("stats_db", STATS_DB_FILE)
    stats_db = resolve_data_path(str(stats_db_raw))

    audit_db_raw = section.get("audit_db", AUDIT_INDEX_DB_FILE)
    audit_db = resolve_data_path(str(audit_db_raw))

    order_retention_sec = _as_int(
        section.get("order_retention_sec", 3600), section_name, "order_retention_sec"
    )
    if order_retention_sec < 0:
        raise ValueError(f"{section_name}.order_retention_sec must be >= 0")

    market_data_cache_sec = _as_int(
        section.get("market_data_cache_sec", 60), section_name, "market_data_cache_sec"
    )
    if market_data_cache_sec < 0:
        raise ValueError(f"{section_name}.market_data_cache_sec must be >= 0")

    session_timezone_raw = section.get("session_timezone")
    session_timezone = (
        None if session_timezone_raw is None else str(session_timezone_raw)
    )
    if session_timezone is not None and resolve_timezone(session_timezone) is None:
        raise ValueError(
            f"{section_name}.session_timezone: unknown timezone {session_timezone!r}"
        )

    return ApiGatewayConfig(
        name=gateway_name,
        enabled=bool(section.get("enabled", True)),
        host=str(section.get("host", "0.0.0.0")),
        port=port,
        engine_pull_addr=str(section.get("engine_pull_addr", ENGINE_PULL_ADDR)),
        engine_pub_addr=str(section.get("engine_pub_addr", ENGINE_PUB_ADDR)),
        index_pull_addr=str(section.get("index_pull_addr", INDEX_PULL_ADDR)),
        index_pub_addr=str(section.get("index_pub_addr", INDEX_PUB_ADDR)),
        stats_db=stats_db,
        audit_db=audit_db,
        order_retention_sec=order_retention_sec,
        market_data_cache_sec=market_data_cache_sec,
        session_timezone=session_timezone,
        log_level=str(section.get("log_level", "info")),
        swagger_enabled=bool(section.get("swagger_enabled", True)),
        credentials=_load_credentials(section.get("credentials"), section_name),
        rate_limit=RateLimitConfig(writes_per_second=writes_per_second, burst=burst),
        timeouts=TimeoutConfig(
            engine_auth_sec=engine_auth_sec,
            engine_reply_sec=engine_reply_sec,
            wait_ack_sec=wait_ack_sec,
        ),
    )


def _load_named_api_gateways(raw: dict[str, Any]) -> dict[str, ApiGatewayConfig]:
    section = raw.get("api_gateways")
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ValueError("api_gateways must be a mapping")

    configs: dict[str, ApiGatewayConfig] = {}
    seen_gateway_ids: dict[str, str] = {}
    for raw_name, raw_gateway in section.items():
        name = str(raw_name).strip()
        if not name:
            raise ValueError("api_gateways names cannot be empty")
        if not isinstance(raw_gateway, dict):
            raise ValueError(f"api_gateways.{name} must be a mapping")
        config = _load_api_gateway_section(raw_gateway, f"api_gateways.{name}", name)
        configs[name] = config
        for credential in config.credentials:
            if credential.gateway_id is None:
                continue
            existing = seen_gateway_ids.get(credential.gateway_id)
            if existing is not None and existing != name:
                raise ValueError(
                    f"gateway_id {credential.gateway_id!r} is used by multiple "
                    f"api_gateways entries: {existing!r} and {name!r}"
                )
            seen_gateway_ids[credential.gateway_id] = name
    return configs


def validate_api_gateway_sections(raw: dict[str, Any]) -> None:
    """Validate api_gateways section using runtime loader rules.

    Raises ValueError with the same messages the runtime loader would emit.
    """

    if "api_gateway" in raw:
        raise ValueError("api_gateway is not supported; use api_gateways")

    _load_named_api_gateways(raw)


def select_api_gateway(
    named: dict[str, ApiGatewayConfig], instance: str | None = None
) -> ApiGatewayConfig:
    """Choose one API gateway instance from those configured.

    Shared by the YAML loader and the compiled-artifact reader so the two
    cannot disagree about which instance a bare ``pm-api-gwy`` gets.
    """
    if named:
        if instance is not None:
            try:
                return named[instance]
            except KeyError as exc:
                available = ", ".join(sorted(named))
                raise ValueError(
                    f"api_gateways instance {instance!r} not found; available: {available}"
                ) from exc
        if len(named) == 1:
            return next(iter(named.values()))
        raise ValueError(
            "multiple api_gateways entries are configured; pass --instance to select one"
        )

    if instance is not None:
        raise ValueError(
            f"api_gateways instance {instance!r} requested, but no api_gateways block is configured"
        )
    return ApiGatewayConfig()


def load_named_api_gateway_configs(path: Path) -> dict[str, ApiGatewayConfig]:
    """Load every configured API gateway instance, keyed by name.

    ``load_api_gateway_config`` returns one instance and needs ``--instance``
    to disambiguate. The compiled artifact carries them all, since it is built
    once for the whole exchange rather than per process.
    """
    if not path.exists():
        return {}

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}

    if "api_gateway" in raw:
        raise ValueError("api_gateway is not supported; use api_gateways")

    return _load_named_api_gateways(raw)


def load_api_gateway_config(
    path: Path, instance: str | None = None
) -> ApiGatewayConfig:
    """Load one API gateway config from central engine config."""
    if not path.exists():
        return ApiGatewayConfig()

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return ApiGatewayConfig()

    if "api_gateway" in raw:
        raise ValueError("api_gateway is not supported; use api_gateways")

    return select_api_gateway(_load_named_api_gateways(raw), instance)


def load_default_api_gateway_config(instance: str | None = None) -> ApiGatewayConfig:
    """Return one API gateway instance from the deployed compiled configuration.

    Falls back to defaults when nothing has been deployed, matching what the
    YAML loader did for a missing file.

    The import is deferred because ``config_artifact`` imports this module.
    """
    from edumatcher.config_artifact import load_compiled_config

    compiled = load_compiled_config()
    named = {} if compiled is None else compiled.api_gateways
    return select_api_gateway(named, instance)
