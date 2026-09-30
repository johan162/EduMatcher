"""Scenario files: a student's answers as YAML (design §21).

A file holds only what the student entered, grouped by the first part of each
field key, and written exactly as the interview would accept it::

    pm_valuation: 1
    company:
      name: Aurora Metrics Inc.
    customers:
      last_fy_revenue: 90m
      now: 1,800

Defaults are recomputed on load, so an edit to a preset shows up. With
``resolved`` given, dump() writes every value instead, each commented with
its source: a fully specified case to hand out. Loading such a file makes
every value the student's own.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml

from edumatcher.valuation.fields import BY_KEY, FIELDS
from edumatcher.valuation.resolve import Resolved
from edumatcher.valuation.units import (
    NOT_ANSWERED,
    ParseError,
    format_value,
    market_of,
    parse,
)

FORMAT = 1


def _scalar(text: str) -> str:
    """*text* as a YAML scalar that loads back as the same string."""
    dumped = yaml.safe_dump(text, default_flow_style=True, allow_unicode=True)
    return dumped.removesuffix("\n...\n").strip()


def dump(answers: Mapping[str, Any], resolved: Resolved | None = None) -> str:
    values = answers if resolved is None else resolved.values
    market = market_of(values)
    lines = [f"pm_valuation: {FORMAT}"]
    section = None
    for spec in FIELDS:  # catalogue order, so the file reads like the interview
        if spec.key not in values:
            continue
        head, _, rest = spec.key.partition(".")
        if head != section:
            lines.append(f"{head}:")
            section = head
        line = f"  {rest}: {_scalar(format_value(spec, values[spec.key], market))}"
        if resolved is not None:
            line += f"  # {resolved.sources[spec.key].value}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def load(text: str) -> dict[str, Any]:
    """The answers in a scenario file; ValueError on anything unusable."""
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict) or raw.get("pm_valuation") != FORMAT:
        raise ValueError(f"not a pm-valuation scenario file (pm_valuation: {FORMAT})")
    answers: dict[str, Any] = {}
    problems: list[str] = []
    for head, section in raw.items():
        if head == "pm_valuation":
            continue
        if not isinstance(section, dict):
            raise ValueError(f"section {head!r} must be a mapping")
        for rest, value in section.items():
            key = f"{head}.{rest}"
            spec = BY_KEY.get(key)
            if spec is None:
                problems.append(f"unknown field {key!r}")
                continue
            text = "none" if value is None else str(value)
            if isinstance(value, bool):  # YAML turns yes/no into booleans
                text = "yes" if value else "no"
            try:
                parsed = parse(spec, text)
            except ParseError as exc:
                problems.append(f"{key}: {exc}")
                continue
            if parsed is not NOT_ANSWERED:
                answers[key] = parsed
    if problems:
        raise ValueError("; ".join(problems))
    return answers
