"""swarm.yaml schema and composition arithmetic."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from edumatcher.ai_trader.swarm_config import (
    SwarmConfigError,
    composition_counts,
    interleave,
    load_swarm_config,
    parse_presets_flag,
)

FULL = """\
version: 1
agents: {prefix: ai, start: 5, count: 500}
workers: 4
budget: 1000
seed: 7
duration: 3600
composition: {noise-retail: 40, scalper: 10, mine.yaml: 5}
symbols: {include: [aapl, MSFT], exclude: [tsla], per_agent: 3}
alf: {host: alf.local, port: 6000}
logging: {level: info, target: file, file: swarm.log, failover_timeout: 5}
"""

PRESET = """\
name: mine
description: test
strategy: {name: noise}
execution: {style: passive}
tempo: cautious
risk: {max_position: 100}
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "swarm.yaml"
    path.write_text(text)
    return path


def test_every_key(tmp_path: Path) -> None:
    (tmp_path / "mine.yaml").write_text(PRESET)
    cfg = load_swarm_config(_write(tmp_path, FULL))
    assert cfg.values == {
        "prefix": "AI",
        "start_index": 5,
        "count": 500,
        "workers": 4,
        "budget": 1000.0,
        "seed_base": 7,
        "duration": 3600.0,
        "symbols": "AAPL,MSFT",
        "symbols_per_agent": 3,
        "alf_host": "alf.local",
        "alf_port": 6000,
        "log_level": "INFO",
        "log_target": "file",
        "log_file": "swarm.log",
        "log_failover_timeout": 5.0,
    }
    assert cfg.exclude_symbols == ["TSLA"]
    assert cfg.composition is not None
    assert {k: w for k, (_, w) in cfg.composition.items()} == {
        "noise-retail": 40,
        "scalper": 10,
        "mine.yaml": 5,
    }
    assert cfg.composition["mine.yaml"][0].name == "mine"


def test_minimal(tmp_path: Path) -> None:
    cfg = load_swarm_config(_write(tmp_path, "version: 1\n"))
    assert cfg.values == {} and cfg.composition is None and cfg.exclude_symbols == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("agents: {count: 1}\n", "version must be 1"),
        ("version: 2\n", "version must be 1"),
        ("version: 1\nbudjet: 3\n", "did you mean 'budget'"),
        ("version: 1\nagents: {cnt: 3}\n", "unknown key 'cnt'"),
        ("version: 1\nagents: {count: 0}\n", "agents.count: must be an integer >= 1"),
        ("version: 1\nagents: {count: true}\n", "agents.count"),
        ("version: 1\nworkers: -1\n", "workers: must be an integer >= 0"),
        ("version: 1\nbudget: -5\n", "budget: must be a number >= 0"),
        ("version: 1\ncomposition: {scalper: 0}\n", "weight must be > 0"),
        ("version: 1\ncomposition: {nope: 1}\n", "unknown preset 'nope'"),
        ("version: 1\ncomposition: {}\n", "must map preset -> weight"),
        ("version: 1\ncomposition: {gone.yaml: 1}\n", "gone.yaml"),
        ("version: 1\nsymbols: {include: AAPL}\n", "must be a list of symbols"),
        ("version: 1\nlogging: {level: LOUD}\n", "logging.level: must be one of"),
        ("version: 1\nalf: 5565\n", "alf must be a mapping"),
        ("- 1\n", "must contain a YAML mapping"),
        ("version: [1\n", "not valid YAML"),
    ],
)
def test_refusals(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(SwarmConfigError, match=message.replace("(", r"\(")):
        load_swarm_config(_write(tmp_path, text))


@pytest.mark.parametrize(
    "weights",
    [[40, 10, 5], [1, 1, 1], [0.3, 0.3, 0.4], [7], [1, 1000], [3, 3, 3, 3, 3, 3, 3]],
)
def test_counts_add_up_exactly(weights: list[float]) -> None:
    counts = composition_counts(weights, 500)
    assert sum(counts) == 500
    total = sum(weights)
    for w, c in zip(weights, counts):
        assert abs(c - 500 * w / total) < 1


def test_interleave_is_exact_and_even() -> None:
    counts = composition_counts([40, 10, 5], 500)
    order = interleave(counts)
    assert Counter(order) == dict(enumerate(counts))
    # every block of 100 (one worker) has nearly the full-population mix
    for start in range(0, 500, 100):
        block = Counter(order[start : start + 100])
        for i, c in enumerate(counts):
            assert abs(block[i] - c / 5) <= 1


def test_presets_flag() -> None:
    comp = parse_presets_flag("scalper:3, noise-retail")
    assert {k: w for k, (_, w) in comp.items()} == {"scalper": 3.0, "noise-retail": 1.0}
    with pytest.raises(SwarmConfigError, match="bad weight"):
        parse_presets_flag("scalper:x")


EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples" / "ref_data"


@pytest.mark.parametrize(
    "example", sorted(p.parent.name for p in EXAMPLES.glob("*/swarm.yaml"))
)
def test_shipped_swarm_files_match_their_participants(example: str) -> None:
    from edumatcher.ai_trader.swarm import build_gateway_ids
    from edumatcher.engine.config_loader import load_engine_config

    cfg = load_swarm_config(EXAMPLES / example / "swarm.yaml")
    ids = build_gateway_ids(
        cfg.values["prefix"], cfg.values["start_index"], cfg.values["count"]
    )
    allowed = load_engine_config(EXAMPLES / example / "engine_config.yaml")
    assert set(ids) <= set(allowed.allowed_fix_gateways)


def test_every_example_ships_a_swarm_file() -> None:
    assert len(list(EXAMPLES.glob("*/swarm.yaml"))) == 7
