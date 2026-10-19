"""The documented `monitor` defaults are the code's (design E2.2, WP-B7).

Both the reference manual's example block and the formal specification's
tables state every default; a default changed in `MonitorConfig` without the
docs would otherwise go unnoticed.
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

import yaml

from edumatcher.monitor.config import MonitorConfig, monitor_config_from_raw

DOCS = Path(__file__).resolve().parents[1] / "docs" / "books" / "reference-manual"
SCHEMA = DOCS / "part-3-configuration" / "010-schema-and-process-blocks.md"
FORMAL = DOCS / "part-3-configuration" / "030-formal-specification.md"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def test_the_reference_example_is_exactly_the_defaults() -> None:
    section = _section(SCHEMA.read_text(), "## Configuring `pm-monitor`")
    (block,) = re.findall(r"```yaml\n(.*?)```", section, re.S)
    assert monitor_config_from_raw(yaml.safe_load(block)) == MonitorConfig()


def test_the_formal_specification_states_the_code_defaults() -> None:
    section = _section(FORMAL.read_text(), "MonitorSpec:")
    defaults = MonitorConfig()
    for f in fields(MonitorConfig):
        if f.name in ("retention", "thresholds"):
            continue
        match = re.search(rf"^  {f.name}:\s+\? \w+ = (\S+)", section, re.M)
        assert match, f.name
        documented = yaml.safe_load(match.group(1))
        assert documented == getattr(defaults, f.name), f.name
    for name in ("raw_hours", "minute_days"):
        match = re.search(rf"^  {name}:\s+\? Int = (\d+)", section, re.M)
        assert match and int(match.group(1)) == getattr(defaults.retention, name)
    for f in fields(defaults.thresholds):
        match = re.search(
            rf"^  {f.name}:\s+\? ThresholdBandSpec = \{{warn: (\S+),\s+crit: (\S+)\}}",
            section,
            re.M,
        )
        assert match, f.name
        band = getattr(defaults.thresholds, f.name)
        assert (float(match.group(1)), float(match.group(2))) == (band.warn, band.crit)
