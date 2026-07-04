from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.api_gateway.config import load_api_gateway_config


def test_defaults_when_api_gateway_block_missing(tmp_path: Path) -> None:
    path = tmp_path / "engine_config.yaml"
    path.write_text("symbols: {}\ngateways: {alf: []}\n")
    cfg = load_api_gateway_config(path)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8080
    assert cfg.swagger_enabled is True
    assert cfg.credentials == ()


def test_load_single_named_api_gateway_block(tmp_path: Path) -> None:
    path = tmp_path / "engine_config.yaml"
    path.write_text("""
api_gateways:
  desk:
    enabled: true
    host: 0.0.0.0
    port: 9090
    swagger_enabled: false
    stats_db: /tmp/stats.db
    credentials:
      - api_key: key-trader
        gateway_id: GW01
        description: Desk
      - api_key: key-viewer
        gateway_id: null
    rate_limit:
      writes_per_second: 5
      burst: 7
    timeouts:
      engine_auth_sec: 1.5
      engine_reply_sec: 2.5
      wait_ack_sec: 3.5
""")
    cfg = load_api_gateway_config(path)
    assert cfg.name == "desk"
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9090
    assert cfg.swagger_enabled is False
    assert cfg.credentials[0].gateway_id == "GW01"
    assert cfg.credentials[1].gateway_id is None
    assert cfg.rate_limit.writes_per_second == 5
    assert cfg.rate_limit.burst == 7
    assert cfg.timeouts.wait_ack_sec == 3.5


def test_load_named_api_gateway_instance(tmp_path: Path) -> None:
    path = tmp_path / "engine_config.yaml"
    path.write_text("""
api_gateways:
  desk:
    host: 127.0.0.1
    port: 8080
    credentials:
      - api_key: desk-key
        gateway_id: GW01
  algos:
    host: 127.0.0.1
    port: 8081
    credentials:
      - api_key: algo-key
        gateway_id: GW02
""")
    cfg = load_api_gateway_config(path, instance="algos")
    assert cfg.name == "algos"
    assert cfg.port == 8081
    assert cfg.credentials[0].gateway_id == "GW02"


def test_named_api_gateways_require_instance_when_ambiguous(tmp_path: Path) -> None:
    path = tmp_path / "engine_config.yaml"
    path.write_text("""
api_gateways:
  desk:
    port: 8080
  algos:
    port: 8081
""")
    with pytest.raises(ValueError, match="--instance"):
        load_api_gateway_config(path)


def test_duplicate_gateway_id_across_named_api_gateways_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "engine_config.yaml"
    path.write_text("""
api_gateways:
  desk:
    credentials:
      - api_key: desk-key
        gateway_id: GW01
  algos:
    credentials:
      - api_key: algo-key
        gateway_id: GW01
""")
    with pytest.raises(ValueError, match="multiple api_gateways"):
        load_api_gateway_config(path, instance="desk")


def test_duplicate_api_key_rejected(tmp_path: Path) -> None:
    path = tmp_path / "engine_config.yaml"
    path.write_text("""
api_gateways:
  desk:
    credentials:
      - api_key: dup
        gateway_id: GW01
      - api_key: dup
        gateway_id: GW02
""")
    with pytest.raises(ValueError, match="duplicate"):
        load_api_gateway_config(path)


def test_positive_integer_validation(tmp_path: Path) -> None:
    path = tmp_path / "engine_config.yaml"
    path.write_text("""
api_gateways:
  desk:
    rate_limit:
      writes_per_second: 0
""")
    with pytest.raises(ValueError, match="writes_per_second"):
        load_api_gateway_config(path)


def test_legacy_api_gateway_block_rejected(tmp_path: Path) -> None:
    path = tmp_path / "engine_config.yaml"
    path.write_text("api_gateway:\n  host: 127.0.0.1\n")
    with pytest.raises(ValueError, match="api_gateway is not supported"):
        load_api_gateway_config(path)


@pytest.mark.parametrize(
    "yaml_text, message",
    [
        ("api_gateways: 1\n", "api_gateways must be a mapping"),
        (
            "api_gateways:\n  desk:\n    credentials: nope\n",
            "credentials must be a list",
        ),
        (
            "api_gateways:\n  desk:\n    credentials:\n      - nope\n",
            "must be a mapping",
        ),
        (
            "api_gateways:\n  desk:\n    credentials:\n      - api_key: ''\n",
            "api_key is required",
        ),
        (
            "api_gateways:\n  desk:\n    rate_limit: 1\n",
            "rate_limit must be a mapping",
        ),
        (
            "api_gateways:\n  desk:\n    rate_limit:\n      burst: 0\n",
            "burst must be > 0",
        ),
        (
            "api_gateways:\n  desk:\n    timeouts: 1\n",
            "timeouts must be a mapping",
        ),
        (
            "api_gateways:\n  desk:\n    timeouts:\n      wait_ack_sec: 0\n",
            "wait_ack_sec must be > 0",
        ),
        ("api_gateways:\n  desk:\n    port: 0\n", "port must be > 0"),
    ],
)
def test_invalid_config_shapes_raise(
    yaml_text: str, message: str, tmp_path: Path
) -> None:
    path = tmp_path / "engine_config.yaml"
    path.write_text(yaml_text)
    with pytest.raises(ValueError, match=message):
        load_api_gateway_config(path)
