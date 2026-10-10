"""market_sim.yaml: schema, precedence, generator, shipped examples."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from edumatcher.market_sim.config import (
    DEFAULT_SECTOR,
    SimConfigError,
    generate_sim_config,
    load_sim_config,
)
from edumatcher.market_sim.sectors import PROFILES

ENGINE = {"AAPL", "MSFT", "XOM", "ZZZZ"}
FULL = """\
version: 1
seed: 7
step_sec: 0.5
overnight_fraction: 0.3
defaults: {vol: 0.2, drift: 0.01, jump_rate: 0.1, jump_mean: -0.01, jump_std: 0.05,
           beta_market: 0.3, beta_sector: 0.3}
sectors:
  tech: {vol: 0.4, beta_market: 0.6}
symbols:
  AAPL: {sector: TECH, vol: 0.25, initial: 150.0}
  MSFT: {sector: TECH}
  XOM: {sector: ENERGY, jump_rate: 0.0}
"""


def _load(tmp_path: Path, text: str, engine: set[str] = ENGINE):
    path = tmp_path / "market_sim.yaml"
    path.write_text(text)
    return load_sim_config(path, engine)


def test_precedence_defaults_sector_symbol(tmp_path: Path) -> None:
    cfg = _load(tmp_path, FULL)
    assert (cfg.seed, cfg.step_sec, cfg.overnight_fraction) == (7, 0.5, 0.3)
    aapl, msft, xom, zzzz = (cfg.params[s] for s in ("AAPL", "MSFT", "XOM", "ZZZZ"))
    assert (aapl.sector, aapl.vol, aapl.beta_market, aapl.drift) == (
        "TECH",
        0.25,
        0.6,
        0.01,
    )
    assert (msft.vol, msft.beta_sector) == (0.4, 0.3)
    assert (xom.sector, xom.vol, xom.jump_rate) == ("ENERGY", 0.2, 0.0)
    assert zzzz.sector == DEFAULT_SECTOR and zzzz.vol == 0.2
    assert cfg.initial == {"AAPL": 150.0}


def test_minimal_file_uses_model_defaults(tmp_path: Path) -> None:
    cfg = _load(tmp_path, "version: 1\n")
    assert cfg.seed == 1 and cfg.params["AAPL"].vol == 0.30 and cfg.initial == {}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("seed: 1\n", "version must be 1"),
        ("version: 1\nsymbol: {}\n", "did you mean 'symbols'"),
        ("version: 1\nsymbols: {TSLA: {}}\n", "not in the engine configuration: TSLA"),
        ("version: 1\nsymbols: {AAPL: {volatility: 1}}\n", "unknown key 'volatility'"),
        ("version: 1\ndefaults: {vol: 5}\n", "must lie in"),
        ("version: 1\ndefaults: {vol: yes}\n", "must be a number"),
        ("version: 1\ndefaults: {sector: TECH}\n", "unknown key 'sector'"),
        ("version: 1\nsymbols: {AAPL: {initial: 0}}\n", "initial"),
        (
            "version: 1\ndefaults: {beta_market: 0.9, beta_sector: 0.9}\n",
            "AAPL: beta_market",
        ),
        ("version: 1\nseed: -1\n", "seed must be"),
        ("version: 1\nstep_sec: 0\n", "step_sec"),
        ("- 1\n", "must contain a YAML mapping"),
    ],
)
def test_refusals(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(SimConfigError, match=message):
        _load(tmp_path, text)


def test_generator_covers_every_symbol_with_known_sectors(tmp_path: Path) -> None:
    text = generate_sim_config(sorted(ENGINE), seed=5)
    cfg = _load(tmp_path, text)
    assert set(cfg.params) == ENGINE and cfg.seed == 5
    assert cfg.params["AAPL"].sector == "TECH" and cfg.params["XOM"].sector == "ENERGY"
    assert cfg.params["ZZZZ"].sector in PROFILES  # unknown ticker, still a sector
    tech = PROFILES["TECH"]
    assert 0.8 * tech.vol <= cfg.params["AAPL"].vol <= 1.25 * tech.vol
    assert cfg.params["AAPL"].beta_market == tech.beta_market
    assert generate_sim_config(sorted(ENGINE), seed=5) == text  # stable


EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples" / "ref_data"


@pytest.mark.parametrize(
    "example", sorted(p.parent.name for p in EXAMPLES.glob("*/market_sim.yaml"))
)
def test_shipped_files_match_their_engine_config(example: str) -> None:
    engine = set(
        yaml.safe_load((EXAMPLES / example / "engine_config.yaml").read_text())[
            "symbols"
        ]
    )
    cfg = load_sim_config(EXAMPLES / example / "market_sim.yaml", engine)
    assert set(cfg.params) == engine
    assert DEFAULT_SECTOR not in {p.sector for p in cfg.params.values()}


def test_every_ai_example_ships_one() -> None:
    assert len(list(EXAMPLES.glob("*/market_sim.yaml"))) == 7


def test_news_section(tmp_path: Path) -> None:
    cfg = _load(tmp_path, "version: 1\nnews: {rate_symbol: 2, rumour_share: 0.5}\n")
    assert (cfg.news.rate_symbol, cfg.news.rumour_share, cfg.news.rate_market) == (
        2.0,
        0.5,
        0.3,
    )
    with pytest.raises(SimConfigError, match="did you mean 'rate_symbol'"):
        _load(tmp_path, "version: 1\nnews: {rate_symbols: 2}\n")
    with pytest.raises(SimConfigError, match="rumour_delay_min exceeds"):
        _load(
            tmp_path, "version: 1\nnews: {rumour_delay_min: 1, rumour_delay_max: 0.5}\n"
        )


def test_load_sectors(tmp_path: Path) -> None:
    from edumatcher.market_sim.config import load_sectors

    path = tmp_path / "market_sim.yaml"
    path.write_text(
        "version: 1\nsymbols: {AAPL: {sector: tech}, MSFT: {sector: TECH}, X: {}}\n"
    )
    assert load_sectors(path) == {"TECH": frozenset({"AAPL", "MSFT"})}
    assert load_sectors(tmp_path / "missing.yaml") == {}
