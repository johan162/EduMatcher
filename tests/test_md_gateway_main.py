from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys

import pytest

from edumatcher.md_gateway import main as md_main
from edumatcher.md_gateway.main import _build_parser, _resolve_config


def test_build_parser_defaults() -> None:
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.bind is None
    assert args.port is None


def test_resolve_config_overrides(tmp_path: Path) -> None:
    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("""
symbols:
  AAPL: {}
gateways:
  alf:
    - id: GW01
market_data_gateway:
  name: md-from-config
  port: 6000
""")
    args = Namespace(
        config=str(cfg_path),
        bind="127.0.0.1",
        port=6001,
        engine_pub="tcp://127.0.0.1:7000",
    )
    cfg, symbols = _resolve_config(args)
    assert cfg.name == "md-from-config"
    assert cfg.bind_address == "127.0.0.1"
    assert cfg.port == 6001
    assert cfg.engine_pub_addr == "tcp://127.0.0.1:7000"
    assert symbols == {"AAPL"}


def test_main_exits_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "engine_config.yaml"
    cfg.write_text("""
symbols:
  AAPL: {}
gateways:
  alf:
    - id: GW01
market_data_gateway:
  enabled: false
""")
    monkeypatch.setattr(sys, "argv", ["pm-md-gwy", "--config", str(cfg)])
    md_main.main()


def test_main_runs_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "engine_config.yaml"
    cfg.write_text("""
symbols:
  AAPL: {}
gateways:
  alf:
    - id: GW01
market_data_gateway: {}
""")
    monkeypatch.setattr(sys, "argv", ["pm-md-gwy", "--config", str(cfg)])

    called = {"run": False}

    class _DummyGateway:
        def __init__(self, config: object, known_symbols: set[str]) -> None:
            _ = (config, known_symbols)

        def run(self) -> None:
            called["run"] = True

    monkeypatch.setattr(md_main, "MarketDataGateway", _DummyGateway)
    md_main.main()
    assert called["run"] is True
