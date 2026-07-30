from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys

import pytest

from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.dc_gateway import main as dc_main
from edumatcher.dc_gateway.main import (
    _build_parser,
    _configure_logging,
    _resolve_config,
)


def test_resolve_config_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The gateway reads its section from the compiled artifact now, so
    # the deployed configuration is stubbed rather than written as YAML.
    monkeypatch.setattr(
        dc_main,
        "load_default_dc_gateway_config",
        lambda: DcGatewayConfig(name="from-config", bind_address="0.0.0.0", port=5590),
    )
    args = Namespace(
        bind="127.0.0.1",
        port=6200,
        engine_dc_pub="tcp://127.0.0.1:7557",
    )
    cfg = _resolve_config(args)
    assert cfg.name == "from-config"
    assert cfg.bind_address == "127.0.0.1"
    assert cfg.port == 6200
    assert cfg.drop_copy_pub_addr == "tcp://127.0.0.1:7557"


def test_build_parser_defaults() -> None:
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.bind is None
    assert args.port is None
    assert args.engine_dc_pub is None
    assert args.log_level is None
    assert args.verbose == 0
    assert args.quiet is False


def test_build_parser_logging_flags() -> None:
    parser = _build_parser()
    args = parser.parse_args(["-vv", "--quiet", "--log-level", "ERROR"])
    assert args.verbose == 2
    assert args.quiet is True
    assert args.log_level == "ERROR"


def test_build_parser_version(capsys: pytest.CaptureFixture[str]) -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--version"])
    out = capsys.readouterr().out
    assert "pm-dc-gwy" in out


def test_configure_logging_prefers_explicit_level() -> None:
    args = Namespace(log_level="INFO", verbose=2, quiet=True)
    assert _configure_logging(args) == 20


def test_main_exits_when_the_configuration_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unreadable or tampered artifact must stop the gateway rather
    # than let it start on defaults nobody chose. A malformed section
    # is no longer reachable: pm-config-deploy will not compile one.
    def _unreadable() -> DcGatewayConfig:
        raise ValueError("compiled config is unreadable")

    monkeypatch.setattr(sys, "argv", ["pm-dc-gwy"])
    monkeypatch.setattr(dc_main, "load_default_dc_gateway_config", _unreadable)
    with pytest.raises(SystemExit):
        dc_main.main()


def test_main_runs_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["pm-dc-gwy"])
    monkeypatch.setattr(
        dc_main, "load_default_dc_gateway_config", lambda: DcGatewayConfig()
    )

    called = {"run": False}

    class _DummyGateway:
        def __init__(self, config: object) -> None:
            _ = config

        def run(self) -> None:
            called["run"] = True

        def close(self) -> None:
            pass

    monkeypatch.setattr(dc_main, "DcGateway", _DummyGateway)
    dc_main.main()
    assert called["run"] is True
