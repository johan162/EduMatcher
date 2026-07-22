from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.dc_gateway.config import (
    load_default_dc_gateway_config,
    load_dc_gateway_config,
)


def test_load_defaults_when_file_missing(tmp_path: Path) -> None:
    cfg = load_dc_gateway_config(tmp_path / "missing.yaml")
    assert cfg.name == "dc-gwy01"
    assert cfg.port == 5590


def test_load_custom_dc_gateway(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("""
dc_gateway:
  name: dc-lab
  bind_address: 127.0.0.1
  port: 6100
  heartbeat_interval_sec: 2
  idle_timeout_sec: 10
  max_client_queue: 500
""")
    cfg = load_dc_gateway_config(p)
    assert cfg.name == "dc-lab"
    assert cfg.bind_address == "127.0.0.1"
    assert cfg.port == 6100
    assert cfg.heartbeat_interval_sec == 2
    assert cfg.idle_timeout_sec == 10
    assert cfg.max_client_queue == 500


def test_invalid_port_raises(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("""
dc_gateway:
  port: 0
""")
    with pytest.raises(ValueError):
        load_dc_gateway_config(p)


def test_non_mapping_dc_gateway_raises(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("dc_gateway: 123\n")
    with pytest.raises(ValueError):
        load_dc_gateway_config(p)


def test_missing_dc_gateway_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("symbols: {}\n")
    cfg = load_dc_gateway_config(p)
    assert cfg.name == "dc-gwy01"


def test_non_mapping_root_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("- just\n- a\n- list\n")
    cfg = load_dc_gateway_config(p)
    assert cfg.port == 5590


def test_non_integer_field_raises(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("""
dc_gateway:
  max_client_queue: not-a-number
""")
    with pytest.raises(ValueError):
        load_dc_gateway_config(p)


def test_boolean_integer_field_raises(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("""
dc_gateway:
  idle_timeout_sec: true
""")
    with pytest.raises(ValueError):
        load_dc_gateway_config(p)


def test_non_scalar_integer_field_raises(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("""
dc_gateway:
  port:
    nested: value
""")
    with pytest.raises(ValueError):
        load_dc_gateway_config(p)


@pytest.mark.parametrize(
    "field",
    [
        "heartbeat_interval_sec",
        "idle_timeout_sec",
        "max_client_queue",
    ],
)
def test_positive_integer_fields_enforced(tmp_path: Path, field: str) -> None:
    p = tmp_path / "config.yaml"
    p.write_text(f"""
dc_gateway:
  {field}: 0
""")
    with pytest.raises(ValueError):
        load_dc_gateway_config(p)


def test_drop_copy_pub_addr_not_overridable_via_yaml(tmp_path: Path) -> None:
    """drop_copy_pub_addr always comes from the global constant; YAML cannot
    override it (only --engine-dc-pub can, at the CLI layer)."""
    p = tmp_path / "config.yaml"
    p.write_text("""
dc_gateway:
  drop_copy_pub_addr: tcp://127.0.0.1:9999
""")
    cfg = load_dc_gateway_config(p)
    assert cfg.drop_copy_pub_addr != "tcp://127.0.0.1:9999"


def test_load_default_config_callable() -> None:
    cfg = load_default_dc_gateway_config()
    assert cfg.port > 0
