from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.alf_gwy.config import load_alf_gateway_config


def test_load_defaults_when_missing(tmp_path: Path) -> None:
    cfg = load_alf_gateway_config(tmp_path / "missing.yaml")
    assert cfg.port == 5565
    assert cfg.max_connections == 64


def test_load_alf_gateway_custom_values(tmp_path: Path) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text("""
alf_gateway:
  enabled: true
  name: alf-lab
  bind_address: 127.0.0.1
  port: 6005
  heartbeat_interval_sec: 3
  idle_timeout_sec: 20
  max_connections: 10
  max_client_queue: 200
  max_commands_per_second: 25
  max_errors_before_disconnect: 12

gateways:
  alf:
    - id: trader01
      role: TRADER
    - id: mm01
      role: MARKET_MAKER
""")

    cfg = load_alf_gateway_config(p)
    assert cfg.name == "alf-lab"
    assert cfg.bind_address == "127.0.0.1"
    assert cfg.port == 6005
    assert cfg.max_connections == 10
    assert cfg.max_client_queue == 200
    assert cfg.max_commands_per_second == 25
    assert cfg.max_errors_before_disconnect == 12
    assert ("TRADER01", "TRADER") in cfg.gateway_roles
    assert ("MM01", "MARKET_MAKER") in cfg.gateway_roles


def test_invalid_alf_gateway_mapping_raises(tmp_path: Path) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text("alf_gateway: 123\n")
    with pytest.raises(ValueError):
        load_alf_gateway_config(p)


@pytest.mark.parametrize(
    "field",
    [
        "port",
        "heartbeat_interval_sec",
        "idle_timeout_sec",
        "max_connections",
        "max_client_queue",
        "max_commands_per_second",
        "max_errors_before_disconnect",
    ],
)
def test_positive_int_fields_enforced(tmp_path: Path, field: str) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text(f"""
alf_gateway:
  {field}: 0
""")
    with pytest.raises(ValueError):
        load_alf_gateway_config(p)


def test_gateway_roles_requires_mapping_entries(tmp_path: Path) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text("""
gateways:
  alf:
    - id: ""
      role: TRADER
""")
    with pytest.raises(ValueError):
        load_alf_gateway_config(p)
