"""The engine configuration has exactly one location, for every process.

While each process took a ``--config`` path it was possible to start an
exchange whose parts disagreed about their own configuration, and the failure
was quiet: pm-md-gwy came up against a config the engine had never read, found
no symbols, disabled SUB validation and dropped SYMBOLS= from every WELCOME,
all while looking healthy. These tests pin the property that replaced the
flag — no runtime process accepts a config path at all, so there is nothing
left to get wrong.
"""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

import pytest

# Every process that reads the deployed engine configuration. Authoring and
# query tools (pm-cverifier, pm-config-gen, pm-index-cli) are deliberately
# absent: they operate on arbitrary files by design and cannot desynchronise a
# running exchange.
RUNTIME_MODULES = [
    "edumatcher.ai_trader.swarm",
    "edumatcher.alf_gwy.main",
    "edumatcher.api_gateway.main",
    "edumatcher.balf_gwy.main",
    "edumatcher.dc_gateway.main",
    "edumatcher.engine.main",
    "edumatcher.index.main",
    "edumatcher.log_srv.main",
    "edumatcher.md_gateway.main",
    "edumatcher.ralf_gateway.main",
    "edumatcher.scheduler.main",
]


def _parser(module_name: str) -> argparse.ArgumentParser:
    module = importlib.import_module(module_name)
    return module._build_parser()


@pytest.mark.parametrize("module_name", RUNTIME_MODULES)
class TestNoConfigPathAtRuntime:
    def test_rejects_a_config_path(
        self, module_name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parser = _parser(module_name)

        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--config", str(tmp_path / "other.yaml")])

        # argparse exits 2 on an unrecognised option; anything else would mean
        # the flag was quietly accepted and ignored, which is worse than both
        # keeping it and removing it.
        assert exc.value.code == 2

    def test_rejects_the_short_form(
        self, module_name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parser = _parser(module_name)

        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["-c", str(tmp_path / "other.yaml")])

        assert exc.value.code == 2

    def test_needs_no_arguments_to_find_its_config(self, module_name: str) -> None:
        # The corollary of removing the flag: a bare invocation is complete.
        # If any of these grew a required argument the operator would be back
        # to typing per-process startup lines that can drift apart.
        parser = _parser(module_name)
        assert parser.parse_args([]) is not None
