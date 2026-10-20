"""web-apps/dash-gui's metric names (``apps/web/src/lib/metrics.ts``, D3.1).

The dashboard reads some figures from a process's beacon metrics and some
from the series pm-monitor stores. Each name in lib/metrics.ts is pinned
here to what its producer actually emits -- read from the producers'
source, as tests/test_health_contract.py does for pm-monitor itself -- so
a renamed metric fails here before it silently blanks a panel. The
TypeScript is read as text, so no Node toolchain is needed.
"""

from __future__ import annotations

import re
from pathlib import Path

from edumatcher.monitor.activity import REQUEST_COUNTERS
from edumatcher.monitor.collector import VITALS
from edumatcher.monitor.thresholds import MIN_REQUESTS_5M
from tests.test_health_contract import COUNTER, GAUGE, _emitted

REPO = Path(__file__).resolve().parents[1]
TS = (REPO / "web-apps/dash-gui/apps/web/src/lib/metrics.ts").read_text(
    encoding="utf-8"
)


def _block(name: str) -> str:
    """The text of ``export const <name> = ...`` up to its end (``;``)."""
    match = re.search(rf"export const {name} = (.*?);\n", TS, re.DOTALL)
    assert match, f"metrics.ts has no {name}"
    return match.group(1)


def test_every_beacon_metric_is_emitted_by_its_process() -> None:
    pairs = re.findall(r'process: "([\w-]+)", name: "([\w.]+)"', _block("METRIC"))
    assert len(pairs) >= 4
    for process, name in pairs:
        assert name in _emitted(process), f"{process} does not emit {name}"


def test_every_counter_is_an_engine_counter() -> None:
    names = re.findall(r'"(engine\.\w+)"', _block("COUNTER"))
    emitted = _emitted("pm-engine")
    assert len(names) == 5
    for name in names:
        assert emitted.get(name) == COUNTER, name


def test_every_gauge_is_an_engine_gauge() -> None:
    names = re.findall(r'"(engine\.\w+)"', _block("GAUGE"))
    emitted = _emitted("pm-engine")
    assert len(names) == 4
    for name in names:
        assert emitted.get(name) == GAUGE, name


def test_the_requests_are_pm_monitors() -> None:
    assert set(re.findall(r'"([\w.]+)"', _block("REQUEST_COUNTERS"))) == set(
        REQUEST_COUNTERS
    )


def test_the_vitals_are_stored_ones() -> None:
    names = re.findall(r'"proc\.(\w+)"', _block("VITAL"))
    assert sorted(names) == sorted(VITALS)


def test_the_minimum_requests_are_pm_monitors() -> None:
    assert int(_block("MIN_REQUESTS")) == MIN_REQUESTS_5M
