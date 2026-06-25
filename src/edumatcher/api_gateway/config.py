"""Configuration loading for ``pm-api-gateway``.

The original design used a separate ``api_gateway_config.yaml``.  The project
already keeps CALF and RALF gateway settings in ``engine_config.yaml``, so this
implementation follows that established pattern and reads optional
``api_gateway``/``api_gateways`` blocks from the central engine config.  API keys are plain bearer
tokens because EduMatcher is an educational system; the loader keeps the parsing
rules explicit so switching to hashed keys later is localised to this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from edumatcher.config import (
    ENGINE_CONFIG_FILE,
    ENGINE_PULL_ADDR,
    ENGINE_PUB_ADDR,
    STATS_DB_FILE,
)


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
    """Runtime configuration for ``pm-api-gateway``."""

    name: str = "default"
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080
    engine_pull_addr: str = ENGINE_PULL_ADDR
    engine_pub_addr: str = ENGINE_PUB_ADDR
    stats_db: Path = STATS_DB_FILE
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
    stats_db = Path(str(stats_db_raw)).expanduser()

    return ApiGatewayConfig(
        name=gateway_name,
        enabled=bool(section.get("enabled", True)),
        host=str(section.get("host", "127.0.0.1")),
        port=port,
        engine_pull_addr=str(section.get("engine_pull_addr", ENGINE_PULL_ADDR)),
        engine_pub_addr=str(section.get("engine_pub_addr", ENGINE_PUB_ADDR)),
        stats_db=stats_db,
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


def load_api_gateway_config(
    path: Path, instance: str | None = None
) -> ApiGatewayConfig:
    """Load one API gateway config from central engine config.

    ``api_gateways`` is the preferred multi-process form.  The older singular
    ``api_gateway`` block is still accepted as a compatibility default.
    """
    if not path.exists():
        return ApiGatewayConfig()

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return ApiGatewayConfig()

    named_configs = _load_named_api_gateways(raw)
    if named_configs:
        if instance is not None:
            try:
                return named_configs[instance]
            except KeyError as exc:
                available = ", ".join(sorted(named_configs))
                raise ValueError(
                    f"api_gateways instance {instance!r} not found; available: {available}"
                ) from exc
        if len(named_configs) == 1:
            return next(iter(named_configs.values()))
        raise ValueError(
            "multiple api_gateways entries are configured; pass --instance to select one"
        )

    section = raw.get("api_gateway")
    if section is None:
        if instance is not None:
            raise ValueError(
                f"api_gateway instance {instance!r} requested, but no api_gateways block is configured"
            )
        return ApiGatewayConfig()
    if not isinstance(section, dict):
        raise ValueError("api_gateway must be a mapping")
    return _load_api_gateway_section(section, "api_gateway", "default")


def load_default_api_gateway_config() -> ApiGatewayConfig:
    """Load API gateway config from the resolved central engine config path."""
    return load_api_gateway_config(ENGINE_CONFIG_FILE)
