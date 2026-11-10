"""Tests for pm-engine's CLI entrypoint: argument parsing and logging setup.

Mirrors the build_parser/_configure_logging conventions established in
ralf_gateway/main.py, alf_gwy/main.py, and dc_gateway/main.py — the engine
now uses the same -v/-vv/--log-level/-q flags and
"%(asctime)s %(levelname)s %(name)s - %(message)s" format as every other
process, instead of a bespoke boolean --verbose flag and a bare
"%(message)s" format with hand-embedded "[ENGINE] " prefixes.
"""

from __future__ import annotations

from argparse import Namespace
import logging
from pathlib import Path
import sys

import pytest

import edumatcher.engine.main as engine_main
from edumatcher.engine.main import (
    build_parser,
    _configure_logging,
    _country_wire_code,
)


def test_build_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args([])
    assert args.log_level is None
    assert args.verbose == 0
    assert args.quiet is False


def test_build_parser_logging_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["-vv", "--quiet", "--log-level", "ERROR"])
    assert args.verbose == 2
    assert args.quiet is True
    assert args.log_level == "ERROR"


def test_build_parser_version(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--version"])
    out = capsys.readouterr().out
    assert "pm-engine" in out


def test_configure_logging_default_is_warning() -> None:
    args = Namespace(log_level=None, verbose=0, quiet=False)
    assert _configure_logging(args) == logging.WARNING


def test_configure_logging_single_v_is_info() -> None:
    args = Namespace(log_level=None, verbose=1, quiet=False)
    assert _configure_logging(args) == logging.INFO


def test_configure_logging_double_v_is_debug() -> None:
    args = Namespace(log_level=None, verbose=2, quiet=False)
    assert _configure_logging(args) == logging.DEBUG


def test_configure_logging_quiet_is_warning() -> None:
    args = Namespace(log_level=None, verbose=0, quiet=True)
    assert _configure_logging(args) == logging.WARNING


def test_configure_logging_prefers_explicit_level() -> None:
    args = Namespace(log_level="INFO", verbose=2, quiet=True)
    assert _configure_logging(args) == logging.INFO


def test_country_wire_code_accepts_configured_country_names() -> None:
    assert _country_wire_code("Sweden") == "SE"
    assert _country_wire_code("SE") == "SE"
    assert _country_wire_code(None) is None


@pytest.mark.parametrize(
    ("arguments", "debug_enabled"),
    [([], False), (["-vv"], True)],
    ids=["normal", "verbose"],
)
def test_invalid_deployed_artifact_exits_without_a_traceback(
    arguments: list[str],
    debug_enabled: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    artifact = tmp_path / "engine_config.json"
    artifact.write_text("{ not json")
    monkeypatch.setattr(
        "edumatcher.config_artifact.COMPILED_CONFIG_FILE", artifact, raising=True
    )
    monkeypatch.setattr(sys, "argv", ["pm-engine", *arguments])
    monkeypatch.setattr(
        engine_main,
        "_configure_logging",
        lambda args: logging.DEBUG if args.verbose else logging.WARNING,
    )

    level = logging.DEBUG if debug_enabled else logging.WARNING
    with caplog.at_level(level, logger="edumatcher.engine.main"):
        with pytest.raises(SystemExit) as exc_info:
            engine_main.main()

    assert exc_info.value.code == 1
    errors = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(errors) == 1
    assert "cannot read the deployed configuration" in errors[0].getMessage()
    assert "pm-config-deploy" in errors[0].getMessage()
    debug_errors = [record for record in caplog.records if record.exc_info]
    assert bool(debug_errors) is debug_enabled
