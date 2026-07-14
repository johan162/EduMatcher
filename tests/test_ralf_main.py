from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys

import pytest

from edumatcher.ralf_gateway import main as ralf_main
from edumatcher.ralf_gateway.main import (
    _build_parser,
    _configure_logging,
    _resolve_config,
)


def test_resolve_config_overrides(tmp_path: Path) -> None:
    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("""
post_trade_gateway:
  name: from-config
  bind_address: 0.0.0.0
  port: 5580
""")

    args = Namespace(
        config=str(cfg_path),
        bind="127.0.0.1",
        port=6002,
        engine_pub="tcp://127.0.0.1:7000",
    )
    cfg = _resolve_config(args)
    assert cfg.name == "from-config"
    assert cfg.bind_address == "127.0.0.1"
    assert cfg.port == 6002
    assert cfg.engine_pub_addr == "tcp://127.0.0.1:7000"


def test_build_parser_defaults() -> None:
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.bind is None
    assert args.port is None
    assert args.engine_pub is None
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


def test_main_invalid_config_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("""
post_trade_gateway:
  allowed_roles: CLEARING
""")
    monkeypatch.setattr(sys, "argv", ["pm-ralf-gwy", "--config", str(cfg)])
    with pytest.raises(SystemExit):
        ralf_main.main()


def test_main_runs_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "ok.yaml"
    cfg.write_text("post_trade_gateway: {}\n")
    monkeypatch.setattr(sys, "argv", ["pm-ralf-gwy", "--config", str(cfg)])

    called = {"run": False}

    class _DummyGateway:
        def __init__(self, config: object) -> None:
            _ = config

        def run(self) -> None:
            called["run"] = True

        def close(self) -> None:
            pass

    monkeypatch.setattr(ralf_main, "RalfGateway", _DummyGateway)
    ralf_main.main()
    assert called["run"] is True
