"""web-apps/dash-gui's copy of pm-monitor's threshold rules (I113).

The dashboard bridge serves ``/api/thresholds`` from the deployed artifact's
``monitor.thresholds``, and from its own copy of pm-monitor's defaults when
no artifact is deployed (pm-monitor then runs on those). That copy, the
inverted rules and the rules fixed in pm-monitor's code live in
``apps/bridge/src/thresholds.ts``; this file pins them to the Python they
mirror, and pins the artifact's shape the bridge reads. The TypeScript is
read as text, so no Node toolchain is needed.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields
from pathlib import Path

from edumatcher.config_artifact import encode
from edumatcher.config_deploy import compile_config, resolve_example
from edumatcher.monitor.activity import SLOW_RULE, WATCHED_INCREASES
from edumatcher.monitor.config import INVERTED_THRESHOLDS, MonitorThresholds
from edumatcher.monitor.thresholds import (
    LOOP_AGE_RULE,
    LOOP_AGE_WARN_MS,
    increase_reading,
)

REPO = Path(__file__).resolve().parents[1]
TS = (REPO / "web-apps/dash-gui/apps/bridge/src/thresholds.ts").read_text(
    encoding="utf-8"
)


def _block(name: str) -> str:
    match = re.search(rf"export const {name}[^=]*= ([\[{{].*?[\]}}]);\n", TS, re.DOTALL)
    assert match, f"thresholds.ts has no {name}"
    return match.group(1)


def _numbers(text: str) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for name, body in re.findall(r"(\w+): \{([^}]*)\}", text):
        out[name] = {
            key: None if value == "null" else float(value)
            for key, value in re.findall(r"(warn|crit): ([\d.]+|null)", body)
        }
    return out


def test_the_defaults_are_pm_monitors() -> None:
    defaults = MonitorThresholds()
    expected = {
        f.name: {
            "warn": getattr(defaults, f.name).warn,
            "crit": getattr(defaults, f.name).crit,
        }
        for f in fields(MonitorThresholds)
    }
    assert _numbers(_block("DEFAULT_THRESHOLDS")) == expected


def test_the_inverted_rules_are_pm_monitors() -> None:
    assert set(re.findall(r'"(\w+)"', _block("INVERTED"))) == set(INVERTED_THRESHOLDS)


def test_the_fixed_rules_are_pm_monitors() -> None:
    fixed = _numbers(_block("FIXED_RULES"))
    increases = set(WATCHED_INCREASES.values()) | {SLOW_RULE}
    assert set(fixed) == {LOOP_AGE_RULE} | increases
    assert fixed[LOOP_AGE_RULE] == {"warn": LOOP_AGE_WARN_MS, "crit": None}
    # An increase rule warns on any increase: warn 0, no critical level.
    reading = increase_reading("x", "s", 1.0)
    for rule in increases:
        assert fixed[rule] == {"warn": reading.warn, "crit": reading.crit}


def test_a_compiled_artifact_has_what_the_bridge_reads() -> None:
    """``monitor.thresholds.<rule>.warn|crit``, every rule, numbers."""
    artifact = json.loads(encode(compile_config(resolve_example("s10-basic"))))
    block = artifact["monitor"]["thresholds"]
    assert set(block) == {f.name for f in fields(MonitorThresholds)}
    for rule, band in block.items():
        assert isinstance(band["warn"], float) and isinstance(band["crit"], float), rule


def test_the_scanner_sees_what_it_should() -> None:
    """Guards the guard: a regex that found nothing would pass above."""
    assert len(_numbers(_block("DEFAULT_THRESHOLDS"))) == 7
    assert _numbers(_block("FIXED_RULES"))["loop_age_ms"]["warn"] == 1000.0
