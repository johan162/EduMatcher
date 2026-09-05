"""Tests for mm_bot/config.py — YAML config-file loading for pm-mm-bot."""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.mm_bot.config import load_config_file


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot read config file"):
        load_config_file(tmp_path / "missing.yaml")


def test_load_empty_file_returns_empty_dict(tmp_path: Path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("")
    assert load_config_file(p) == {}


def test_load_valid_config(tmp_path: Path) -> None:
    p = tmp_path / "mm_aapl.yaml"
    p.write_text("""
symbol: AAPL
strategy: symmetric
gap: 0.08
qty: 300
tif: GTC
""")
    values = load_config_file(p)
    assert values == {
        "symbol": "AAPL",
        "strategy": "symmetric",
        "gap": 0.08,
        "qty": 300,
        "tif": "GTC",
    }


def test_load_not_a_mapping_raises(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- AAPL\n- MSFT\n")
    with pytest.raises(ValueError, match="must contain a YAML mapping"):
        load_config_file(p)


def test_load_invalid_yaml_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("symbol: [unclosed\n")
    with pytest.raises(ValueError, match="not valid YAML"):
        load_config_file(p)


def test_load_unknown_key_raises(tmp_path: Path) -> None:
    p = tmp_path / "unknown.yaml"
    p.write_text("symbol: AAPL\nbogus_key: 123\n")
    with pytest.raises(ValueError, match="unknown key.*bogus_key"):
        load_config_file(p)
