"""The instructor news scenarios shipped in docs/examples/news (WP-E6) load,
and name only symbols and sectors every s150 and s300 example has."""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.market_sim.config import load_sectors
from edumatcher.market_sim.news_cli import load_scenario

ROOT = Path(__file__).resolve().parents[1] / "docs" / "examples"
SCENARIOS = sorted((ROOT / "news").glob("*.yaml"))
EXAMPLES = sorted((ROOT / "ref_data").glob("s*-setup/market_sim.yaml"))


def test_examples_found() -> None:
    assert len(SCENARIOS) == 3
    assert len(EXAMPLES) == 7  # six s150 + s300-load


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.parent.name)
def test_scenario_fits_example(path: Path, example: Path) -> None:
    sectors = load_sectors(example)
    symbols = set().union(*sectors.values())
    for step in load_scenario(path):
        if step.news is None:
            continue
        targets = set(step.news["targets"])
        known = sectors.keys() if step.news["scope"] == "SECTOR" else symbols
        assert targets <= set(known), (path.name, targets)
