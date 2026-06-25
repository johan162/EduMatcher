from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.md_gateway.config import load_market_data_gateway_config


def test_defaults_when_missing_file(tmp_path: Path) -> None:
    cfg = load_market_data_gateway_config(tmp_path / "missing.yaml")
    assert cfg.name == "md-gwy01"
    assert cfg.port == 5570
    assert cfg.index_pub_addr.startswith("tcp://")


def test_load_custom_block(tmp_path: Path) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text("""
market_data_gateway:
  enabled: true
  name: md-lab
  bind_address: 127.0.0.1
  port: 6001
  heartbeat_interval_sec: 2
  idle_timeout_sec: 9
  replay_window_sec: 45
  max_symbols_per_client: 50
  max_client_queue: 500
""")
    cfg = load_market_data_gateway_config(p)
    assert cfg.name == "md-lab"
    assert cfg.bind_address == "127.0.0.1"
    assert cfg.port == 6001
    assert cfg.replay_window_sec == 45


def test_invalid_section_type_raises(tmp_path: Path) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text("market_data_gateway: 123\n")
    with pytest.raises(ValueError):
        load_market_data_gateway_config(p)


@pytest.mark.parametrize(
    "field,value",
    [
        ("port", 0),
        ("heartbeat_interval_sec", 0),
        ("idle_timeout_sec", 0),
        ("replay_window_sec", 0),
        ("max_symbols_per_client", 0),
        ("max_client_queue", 0),
    ],
)
def test_positive_int_fields(field: str, value: int, tmp_path: Path) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text(f"""
market_data_gateway:
  {field}: {value}
""")
    with pytest.raises(ValueError):
        load_market_data_gateway_config(p)
