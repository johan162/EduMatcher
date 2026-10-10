"""ai_trader.preset: strict YAML presets and the built-in set."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from edumatcher.ai_trader.agent import Agent
from edumatcher.ai_trader.preset import (
    TEMPOS,
    PresetError,
    TempoSpec,
    builtin_presets,
    get_preset,
    load_preset_file,
    parse_preset,
)
from edumatcher.models.order import OrderType


def _raw(**over: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "name": "t",
        "strategy": {"name": "trend", "strength": 0.5},
        "execution": {"style": "passive"},
        "tempo": "cautious",
        "risk": {"max_position": 10},
    }
    raw.update(over)
    return raw


def test_builtins_load_and_build_agents() -> None:
    presets = builtin_presets()
    assert {
        "noise-retail",
        "scalper",
        "trend-follower",
        "contrarian",
        "institutional",
        "auction-player",
        "iceberg-seller",
        "market-taker",
        "block-taker",
    } <= set(presets)
    for preset in presets.values():
        Agent("AI001", preset, ["AAPL"], seed=1, now=0.0)


def test_builtins_cover_every_order_type_and_protection() -> None:
    presets = builtin_presets().values()
    sweeps = {p.execution.sweep_type for p in presets if p.execution.style == "sweep"}
    assert sweeps == {"MARKET", "IOC", "FOK"}
    assert {p.execution.style for p in presets} == {
        "passive",
        "marketable",
        "sweep",
        "iceberg",
        "twap",
    }
    assert {p.risk.protection for p in presets} >= {
        "stop",
        "stop_limit",
        "trailing",
        "bracket",
    }
    assert any(p.execution.tif == "GTC" for p in presets)
    assert len(list(OrderType)) == 8  # if the engine grows a type, cover it here


def test_unknown_preset_name() -> None:
    with pytest.raises(PresetError, match="unknown preset 'nope'"):
        get_preset("nope")


def test_inline_tempo() -> None:
    p = parse_preset(
        _raw(tempo={"decisions_per_min": 12, "size_min": 1, "size_max": 9}), "x"
    )
    assert p.tempo == TempoSpec(12.0, 1, 9, "balanced")


@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"colour": "red"}, "unknown key\\(s\\) in preset: colour"),
        ({"strategy": {"name": "astrology"}}, "strategy.name='astrology'"),
        (
            {"strategy": {"name": "noise", "strength": 1}},
            "unknown key\\(s\\) in strategy: strength",
        ),
        (
            {"strategy": {"name": "trend", "strength": 2}},
            "strategy.strength=2 is outside",
        ),
        (
            {"strategy": {"name": "trend", "sample": 0.5}},
            "strategy.sample must be an integer",
        ),
        ({"execution": {"style": "yolo"}}, "execution.style='yolo'"),
        ({"execution": {"tif": "ATO"}}, "execution.tif='ATO'"),
        ({"execution": {"sweep_type": "LIMIT"}}, "execution.sweep_type"),
        ({"execution": {"offset_ticks": True}}, "offset_ticks must be an integer"),
        ({"execution": {"child_style": "sweep"}}, "execution.child_style"),
        ({"tempo": "glacial"}, "tempo='glacial'"),
        (
            {"tempo": {"decisions_per_min": 1, "size_min": 5}},
            "missing key: tempo.size_max",
        ),
        (
            {"tempo": {"decisions_per_min": 1, "size_min": 9, "size_max": 2}},
            "size_min must not exceed",
        ),
        ({"risk": {"max_position": 0}}, "risk.max_position=0 is outside"),
        ({"risk": {"protection": "prayer"}}, "risk.protection='prayer'"),
        ({"risk": {"leverage": 10}}, "unknown key\\(s\\) in risk: leverage"),
        ({"name": ""}, "name must be a non-empty string"),
        ({"description": 5}, "description must be a string"),
    ],
)
def test_validation(over: dict[str, Any], match: str) -> None:
    with pytest.raises(PresetError, match=match):
        parse_preset(_raw(**over), "my.yaml")


@pytest.mark.parametrize("missing", ["name", "strategy", "execution", "tempo", "risk"])
def test_missing_top_level_key(missing: str) -> None:
    raw = _raw()
    del raw[missing]
    with pytest.raises(PresetError, match=f"missing key: {missing}"):
        parse_preset(raw, "x")


def test_errors_name_the_file(tmp_path: Path) -> None:
    f = tmp_path / "bad.yaml"
    f.write_text("name: x\nstrategy: [1]\n")
    with pytest.raises(
        PresetError,
        match=r"bad\.yaml: strategy must be a mapping|bad\.yaml: missing key",
    ):
        load_preset_file(f)
    with pytest.raises(PresetError, match="nope.yaml"):
        load_preset_file(tmp_path / "nope.yaml")
    f.write_text("name: [unclosed\n")
    with pytest.raises(PresetError, match="invalid YAML"):
        load_preset_file(f)


def test_preset_file_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "mine.yaml"
    f.write_text(
        "name: mine\nstrategy: {name: reversion, strength: 0.9, sample: 2}\n"
        "execution: {style: iceberg, visible_fraction: 0.1}\ntempo: few-large\n"
        "risk: {max_position: 50, protection: bracket, protection_pct: 0.05}\n"
    )
    p = load_preset_file(f)
    assert (p.name, p.strategy, p.execution.style, p.risk.protection) == (
        "mine",
        "reversion",
        "iceberg",
        "bracket",
    )
    assert p.make_strategy().sample == 2


@pytest.mark.parametrize("dist", ["balanced", "small-heavy", "block-heavy"])
def test_tempo_sizes_within_bounds(dist: str) -> None:
    t = TempoSpec(1.0, 10, 50, dist)
    rng = random.Random(4)
    sizes = [t.sample_qty(rng) for _ in range(5000)]
    assert min(sizes) >= 10 and max(sizes) <= 50
    mean = sum(sizes) / len(sizes)
    expected = {"balanced": 30, "small-heavy": 23.3, "block-heavy": 36.7}[dist]
    assert abs(mean - expected) < 1.5


def test_builtin_tempos_are_the_old_profiles() -> None:
    assert set(TEMPOS) == {"many-small", "aggressive", "cautious", "few-large"}
