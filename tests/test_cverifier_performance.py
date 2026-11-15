"""pm-cverifier parses each file once.

YAML parsing is the verifier's main cost (about half of a run on the s300
example), and Layer 1 used to parse the main file twice: once to classify a
syntax error, once more to resolve includes.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher.cverifier.cli import run, run_layers


def _count_parses(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls = [0]
    real = yaml.safe_load

    def counting(stream: Any) -> Any:
        calls[0] += 1
        return real(stream)

    monkeypatch.setattr(yaml, "safe_load", counting)
    return calls


def test_main_file_is_parsed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text(textwrap.dedent("""
            symbols:
              AAPL: {tick_decimals: 2}
            participants:
              - {id: OPS01, role: ADMIN}
            """))
    calls = _count_parses(monkeypatch)
    run_layers(p)
    assert calls[0] == 1


def test_each_included_file_is_parsed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "symbols.yaml").write_text("symbols:\n  AAPL: {tick_decimals: 2}\n")
    p = tmp_path / "engine_config.yaml"
    p.write_text(
        "include: [symbols.yaml]\nparticipants:\n  - {id: OPS01, role: ADMIN}\n"
    )
    calls = _count_parses(monkeypatch)
    results, raw = run(p)
    assert raw is not None and "AAPL" in raw["symbols"]
    assert calls[0] == 2


def test_syntax_and_shape_errors_are_unchanged(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("symbols:\n  AAPL: [unclosed\n")
    results, _raw = run(p)
    assert [r.code for r in results] == ["Y003"]
    assert "line 3" in results[0].message

    p.write_text("- just\n- a list\n")
    results, _raw = run(p)
    assert [r.code for r in results] == ["Y004"]
    assert "Got list" in results[0].message
