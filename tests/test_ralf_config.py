from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.ralf_gateway.config import (
    load_default_ralf_gateway_config,
    load_ralf_gateway_config,
)


def test_load_defaults_when_file_missing(tmp_path: Path) -> None:
    cfg = load_ralf_gateway_config(tmp_path / "missing.yaml")
    assert cfg.name == "ralf-gwy01"
    assert cfg.port == 5580


def test_load_custom_post_trade_gateway(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("""
post_trade_gateway:
  name: ralf-lab
  bind_address: 127.0.0.1
  port: 6001
  replay_retention_sec: 300
  heartbeat_interval_sec: 2
  idle_timeout_sec: 10
  max_client_queue: 500
  allowed_roles:
    - CLEARING
    - AUDIT
""")
    cfg = load_ralf_gateway_config(p)
    assert cfg.name == "ralf-lab"
    assert cfg.bind_address == "127.0.0.1"
    assert cfg.port == 6001
    assert cfg.replay_retention_sec == 300
    assert cfg.heartbeat_interval_sec == 2
    assert cfg.idle_timeout_sec == 10
    assert cfg.max_client_queue == 500
    assert cfg.allowed_roles == ("CLEARING", "AUDIT")


def test_invalid_allowed_roles_type_raises(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("""
post_trade_gateway:
  allowed_roles: CLEARING
""")
    with pytest.raises(ValueError):
        load_ralf_gateway_config(p)


def test_invalid_port_raises(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("""
post_trade_gateway:
  port: 0
""")
    with pytest.raises(ValueError):
        load_ralf_gateway_config(p)


def test_non_mapping_post_trade_gateway_raises(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("post_trade_gateway: 123\n")
    with pytest.raises(ValueError):
        load_ralf_gateway_config(p)


def test_missing_post_trade_gateway_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("symbols: {}\n")
    cfg = load_ralf_gateway_config(p)
    assert cfg.name == "ralf-gwy01"


def test_non_mapping_root_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("- just\n- a\n- list\n")
    cfg = load_ralf_gateway_config(p)
    assert cfg.port == 5580


def test_non_integer_field_raises(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("""
post_trade_gateway:
  max_client_queue: not-a-number
""")
    with pytest.raises(ValueError):
        load_ralf_gateway_config(p)


def test_boolean_integer_field_raises(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("""
post_trade_gateway:
  idle_timeout_sec: true
""")
    with pytest.raises(ValueError):
        load_ralf_gateway_config(p)


def test_non_scalar_integer_field_raises(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("""
post_trade_gateway:
  port:
    nested: value
""")
    with pytest.raises(ValueError):
        load_ralf_gateway_config(p)


@pytest.mark.parametrize(
    "field",
    [
        "replay_retention_sec",
        "heartbeat_interval_sec",
        "idle_timeout_sec",
        "max_client_queue",
    ],
)
def test_positive_integer_fields_enforced(tmp_path: Path, field: str) -> None:
    p = tmp_path / "config.yaml"
    p.write_text(f"""
post_trade_gateway:
  {field}: 0
""")
    with pytest.raises(ValueError):
        load_ralf_gateway_config(p)


def test_load_default_config_callable() -> None:
    cfg = load_default_ralf_gateway_config()
    assert cfg.port > 0
