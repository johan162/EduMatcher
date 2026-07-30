from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys

import pytest

from edumatcher.config_deploy import deploy
from edumatcher.md_gateway import main as md_main
from edumatcher.md_gateway.main import (
    _build_parser,
    _configure_logging,
    _resolve_config,
)


def _deploy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    """Compile *body* and point the artifact reader at the result.

    pm-md-gwy takes its settings *and* its symbol universe from one compiled
    file, so covering the two together is the point: reading them from
    different places is what produced a gateway advertising no instruments.
    """
    source = tmp_path / "authored.yaml"
    source.write_text(body)
    dest = tmp_path / "ref_data" / "engine_config.json"
    deploy(source, dest)
    monkeypatch.setattr(
        "edumatcher.config_artifact.COMPILED_CONFIG_FILE", dest, raising=True
    )


def test_build_parser_defaults() -> None:
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.bind is None
    assert args.port is None
    assert args.log_level is None
    assert args.verbose == 0
    assert args.quiet is False


def test_build_parser_logging_flags() -> None:
    parser = _build_parser()
    args = parser.parse_args(["-vv", "--quiet", "--log-level", "ERROR"])
    assert args.verbose == 2
    assert args.quiet is True
    assert args.log_level == "ERROR"


def test_configure_logging_prefers_explicit_level() -> None:
    args = Namespace(log_level="INFO", verbose=2, quiet=True)
    assert _configure_logging(args) == 20


def test_configure_logging_uses_verbose_levels() -> None:
    assert _configure_logging(Namespace(log_level=None, verbose=2, quiet=False)) == 10
    assert _configure_logging(Namespace(log_level=None, verbose=1, quiet=False)) == 20


def test_resolve_config_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _deploy(
        tmp_path,
        monkeypatch,
        """
symbols:
  AAPL: {tick_decimals: 2, last_buy_price: 150.0}
gateways:
  alf: [{id: GW01, role: TRADER}]
market_data_gateway: {name: md-from-config, port: 6000}
""",
    )
    args = Namespace(
        bind="127.0.0.1",
        port=6001,
        engine_pub="tcp://127.0.0.1:7000",
        index_pub="tcp://127.0.0.1:7001",
    )
    cfg, symbols = _resolve_config(args)
    assert cfg.name == "md-from-config"
    assert cfg.bind_address == "127.0.0.1"
    assert cfg.port == 6001
    assert cfg.engine_pub_addr == "tcp://127.0.0.1:7000"
    assert cfg.index_pub_addr == "tcp://127.0.0.1:7001"
    assert symbols == {"AAPL"}


def test_main_exits_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _deploy(
        tmp_path,
        monkeypatch,
        """
symbols:
  AAPL: {tick_decimals: 2, last_buy_price: 150.0}
gateways:
  alf: [{id: GW01, role: TRADER}]
market_data_gateway: {enabled: false}
""",
    )
    monkeypatch.setattr(sys, "argv", ["pm-md-gwy"])
    md_main.main()


def test_main_runs_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _deploy(
        tmp_path,
        monkeypatch,
        """
symbols:
  AAPL: {tick_decimals: 2, last_buy_price: 150.0}
gateways:
  alf: [{id: GW01, role: TRADER}]
""",
    )
    monkeypatch.setattr(sys, "argv", ["pm-md-gwy"])

    called = {"run": False}

    class _DummyGateway:
        def __init__(self, config: object, known_symbols: set[str]) -> None:
            _ = (config, known_symbols)

        def run(self) -> None:
            called["run"] = True

        def close(self) -> None:
            pass

    monkeypatch.setattr(md_main, "MarketDataGateway", _DummyGateway)
    md_main.main()
    assert called["run"] is True
