"""Gateway and log-server loaders refuse flags and names they cannot hold
(For-Later L024, WP-FL09).

``bool("false")`` is ``True`` and ``str(5)`` is ``"5"``, so a quoted flag or a
number where a name or path belongs used to load as something else.
pm-cverifier refuses these; a loader called without it did not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from edumatcher.alf_gwy.config import load_alf_gateway_config
from edumatcher.api_gateway.config import load_named_api_gateway_configs
from edumatcher.balf_gwy.config import load_balf_gateway_config
from edumatcher.log_srv.config import load_log_server_config

_LOADERS: dict[str, Callable[[Path], Any]] = {
    "log_server": load_log_server_config,
    "balf_gateway": load_balf_gateway_config,
    "alf_gateway": load_alf_gateway_config,
}

# (section, field, value)
_CASES: list[tuple[str, str, object]] = [
    *(
        (section, field, value)
        for section in _LOADERS
        for field, value in (
            ("enabled", "false"),
            ("enabled", "x"),
            ("enabled", 1),
            ("name", 5),
            ("bind_address", 127001),
        )
    ),
    ("log_server", "pubsub_enabled", "x"),
    ("log_server", "db_path", 5),
]

_API_CASES: list[tuple[str, object]] = [
    ("enabled", "false"),
    ("enabled", "x"),
    ("swagger_enabled", "x"),
    ("swagger_enabled", "false"),
    ("host", 5),
    ("stats_db", 5),
    ("audit_db", 5),
    ("clearing_db", 5),
    ("eod_db", 5),
    ("engine_pull_addr", 5),
    ("log_level", 5),
]


def _write(tmp_path: Path, doc: dict[str, Any]) -> Path:
    p = tmp_path / "engine_config.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


@pytest.mark.parametrize(
    ("section", "field", "value"),
    _CASES,
    ids=[f"{s}.{f}={v!r}" for s, f, v in _CASES],
)
def test_section_refuses_the_value(
    tmp_path: Path, section: str, field: str, value: object
) -> None:
    p = _write(tmp_path, {section: {field: value}})
    with pytest.raises(ValueError, match=f"{section}.{field}"):
        _LOADERS[section](p)


@pytest.mark.parametrize(("section", "field"), [(s, "enabled") for s in _LOADERS])
@pytest.mark.parametrize("value", [True, False])
def test_a_real_boolean_loads(
    tmp_path: Path, section: str, field: str, value: bool
) -> None:
    cfg = _LOADERS[section](_write(tmp_path, {section: {field: value}}))
    assert cfg.enabled is value


@pytest.mark.parametrize(
    ("field", "value"), _API_CASES, ids=[f"{f}={v!r}" for f, v in _API_CASES]
)
def test_api_gateway_refuses_the_value(
    tmp_path: Path, field: str, value: object
) -> None:
    p = _write(tmp_path, {"api_gateways": {"main": {field: value}}})
    with pytest.raises(ValueError, match=f"api_gateways.main.{field}"):
        load_named_api_gateway_configs(p)


@pytest.mark.parametrize("value", [True, False])
def test_api_gateway_real_booleans_load(tmp_path: Path, value: bool) -> None:
    p = _write(
        tmp_path,
        {"api_gateways": {"main": {"enabled": value, "swagger_enabled": value}}},
    )
    cfg = load_named_api_gateway_configs(p)["main"]
    assert cfg.enabled is value
    assert cfg.swagger_enabled is value


# -- every configuration the repository ships still loads ---------------------

_ROOT = Path(__file__).resolve().parents[1]
_SHIPPED = sorted(
    [
        *(_ROOT / "docs/examples/ref_data").glob("*/engine_config.yaml"),
        _ROOT / "src/data/ref_data/engine_config.yaml",
        *(_ROOT / "web-apps/config-gui/.fixtures").glob("*.yaml"),
    ]
)


@pytest.mark.parametrize(
    "path", _SHIPPED, ids=[str(p.relative_to(_ROOT)) for p in _SHIPPED]
)
def test_every_shipped_configuration_still_loads(path: Path) -> None:
    from edumatcher.dc_gateway.config import load_dc_gateway_config
    from edumatcher.engine.config_loader import load_engine_config
    from edumatcher.log_srv.config import load_log_client_config
    from edumatcher.md_gateway.config import load_market_data_gateway_config
    from edumatcher.monitor.config import load_monitor_config
    from edumatcher.ralf_gateway.config import load_ralf_gateway_config

    load_engine_config(path)
    load_alf_gateway_config(path)
    load_balf_gateway_config(path)
    load_market_data_gateway_config(path)
    load_ralf_gateway_config(path)
    load_dc_gateway_config(path)
    load_log_server_config(path)
    load_log_client_config(path)
    load_monitor_config(path)
    load_named_api_gateway_configs(path)
