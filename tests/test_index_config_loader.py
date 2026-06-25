from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from edumatcher.engine.config_loader import IndexConfig, SymbolConfig
from edumatcher.index.config_loader import (
    _reference_price,
    _to_runtime_index_config,
    load_index_runtime_configs,
)


def test_reference_price_prefers_midpoint() -> None:
    cfg = SymbolConfig(name="AAPL", last_buy_price=100.0, last_sell_price=102.0)
    assert _reference_price("AAPL", cfg) == 101.0


def test_reference_price_single_side() -> None:
    cfg_buy = SymbolConfig(name="AAPL", last_buy_price=100.0, last_sell_price=None)
    cfg_sell = SymbolConfig(name="AAPL", last_buy_price=None, last_sell_price=102.0)
    assert _reference_price("AAPL", cfg_buy) == 100.0
    assert _reference_price("AAPL", cfg_sell) == 102.0


def test_reference_price_requires_one_side() -> None:
    cfg = SymbolConfig(name="AAPL", last_buy_price=None, last_sell_price=None)
    with pytest.raises(ValueError):
        _reference_price("AAPL", cfg)


def test_to_runtime_index_config_enriches_shares_and_prices() -> None:
    idx = IndexConfig(
        id="EDU100",
        description="Test",
        base_value=1000.0,
        publish_interval_sec=1.0,
        history_file="/tmp/h.jsonl",
        state_file="/tmp/s.json",
        constituents=["AAPL"],
    )
    symbols = {
        "AAPL": SymbolConfig(
            name="AAPL",
            outstanding_shares=1_000,
            last_buy_price=100.0,
            last_sell_price=102.0,
        )
    }

    rt = _to_runtime_index_config(idx, symbols)
    assert rt.id == "EDU100"
    assert rt.outstanding_shares["AAPL"] == 1_000
    assert rt.reference_prices["AAPL"] == 101.0


def test_to_runtime_index_config_requires_shares() -> None:
    idx = IndexConfig(
        id="EDU100",
        description="Test",
        history_file="h",
        state_file="s",
        constituents=["AAPL"],
    )
    symbols = {
        "AAPL": SymbolConfig(
            name="AAPL",
            outstanding_shares=None,
            last_buy_price=100.0,
            last_sell_price=102.0,
        )
    }
    with pytest.raises(ValueError):
        _to_runtime_index_config(idx, symbols)


def test_load_index_runtime_configs_uses_engine_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    idx = IndexConfig(
        id="EDU100",
        description="Test",
        history_file="h",
        state_file="s",
        constituents=["AAPL"],
    )
    symbols = {
        "AAPL": SymbolConfig(
            name="AAPL",
            outstanding_shares=10,
            last_buy_price=10.0,
            last_sell_price=10.0,
        )
    }
    fake_cfg = SimpleNamespace(indices=[idx], symbols=symbols)

    monkeypatch.setattr(
        "edumatcher.index.config_loader.load_engine_config",
        lambda _path: fake_cfg,
    )

    loaded = load_index_runtime_configs(Path("engine_config.yaml"))
    assert len(loaded) == 1
    assert loaded[0].id == "EDU100"
