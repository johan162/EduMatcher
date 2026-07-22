"""Tests for pm-engine's CLI entrypoint: argument parsing and logging setup.

Mirrors the _build_parser/_configure_logging conventions established in
ralf_gateway/main.py, alf_gwy/main.py, and dc_gateway/main.py — the engine
now uses the same -v/-vv/--log-level/-q flags and
"%(asctime)s %(levelname)s %(name)s - %(message)s" format as every other
process, instead of a bespoke boolean --verbose flag and a bare
"%(message)s" format with hand-embedded "[ENGINE] " prefixes.
"""

from __future__ import annotations

from argparse import Namespace
import logging

import pytest

from edumatcher.engine.main import _build_parser, _configure_logging


def test_build_parser_defaults() -> None:
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.config is None
    assert args.log_level is None
    assert args.verbose == 0
    assert args.quiet is False


def test_build_parser_logging_flags() -> None:
    parser = _build_parser()
    args = parser.parse_args(["-vv", "--quiet", "--log-level", "ERROR"])
    assert args.verbose == 2
    assert args.quiet is True
    assert args.log_level == "ERROR"


def test_build_parser_config_flag() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--config", "custom.yaml"])
    assert args.config == "custom.yaml"
    args = parser.parse_args(["-c", "custom.yaml"])
    assert args.config == "custom.yaml"


def test_build_parser_version(capsys: pytest.CaptureFixture[str]) -> None:
    parser = _build_parser()
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
