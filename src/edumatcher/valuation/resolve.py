"""Turn the student's answers into a complete set of values (design §19.4).

Every field ends up with a value and a source: the student's answer, the
sector preset, a rule over other fields, or a fixed default. Fields are
resolved in dependency order; for a two-way rule (revenue ↔ customers) the
direction is chosen by which of the two the student answered.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from edumatcher.valuation.fields import (
    BY_KEY,
    DRIVER_KEYS,
    FIELDS,
    MARKET_STRUCTURES,
    MARKETS,
    SECTORS,
    Const,
    Ctx,
    Default,
    FieldSpec,
    FromMarket,
    FromPreset,
    Rule,
    Unit,
)
from edumatcher.valuation.presets import Presets


class Source(Enum):
    USER = "you"
    PRESET = "preset"
    DERIVED = "derived"
    DEFAULT = "default"


@dataclass(frozen=True)
class Resolved:
    values: Mapping[str, Any]
    sources: Mapping[str, Source]

    def __getitem__(self, key: str) -> Any:
        return self.values[key]


class InvalidAnswers(ValueError):
    """One or more values are unusable.

    ``problems`` pairs each message with the field it concerns, so the
    interview can mark that field; the key is None for an unknown field.
    """

    def __init__(self, problems: list[tuple[str | None, str]]) -> None:
        super().__init__("; ".join(message for _, message in problems))
        self.problems = problems


def choices(spec: FieldSpec, presets: Presets) -> tuple[str, ...] | None:
    """The values a choice field accepts; None for other fields."""
    if spec.choices == SECTORS:
        return tuple(presets.sectors)
    if spec.choices == MARKET_STRUCTURES:
        return tuple(presets.market_structures)
    if spec.choices == MARKETS:
        return tuple(presets.markets)
    return spec.choices if isinstance(spec.choices, tuple) else None


def _problem(spec: FieldSpec, value: Any, presets: Presets) -> str | None:
    if value is None:
        return None if spec.optional else f"{spec.label}: a value is required"
    options = choices(spec, presets)
    if options is not None:
        return (
            None
            if value in options
            else f"{spec.label}: {value!r} is not one of {', '.join(options)}"
        )
    if spec.unit is Unit.BOOL:
        return None if isinstance(value, bool) else f"{spec.label}: must be yes/no"
    if spec.unit is Unit.TEXT:
        if not isinstance(value, str) or not value.strip():
            return f"{spec.label}: must be non-empty text"
        if spec.pattern and not re.fullmatch(spec.pattern, value):
            return f"{spec.label}: {value!r} does not match {spec.pattern}"
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{spec.label}: must be a number"
    if (spec.lo is not None and value < spec.lo) or (
        spec.hi is not None and value > spec.hi
    ):
        return f"{spec.label}: {value:g} is outside {spec.lo:g}..{spec.hi:g}"
    return None


def _default(spec: FieldSpec, user: Mapping[str, Any]) -> tuple[Default, Source]:
    if spec.inverse is not None and spec.inverse_when in user:
        return spec.inverse, Source.DERIVED
    if isinstance(spec.default, (Const, FromMarket)):
        return spec.default, Source.DEFAULT
    if isinstance(spec.default, FromPreset):
        return spec.default, Source.PRESET
    return spec.default, Source.DERIVED


def _depends(spec: FieldSpec, default: Default) -> tuple[str, ...]:
    if isinstance(default, Rule):
        return default.depends
    if isinstance(default, FromPreset):
        return ("company.sector", "company.market")
    if isinstance(default, FromMarket) or spec.unit is Unit.MONEY:
        return ("company.market",)  # money defaults are in US dollars
    return ()


def resolve(answers: Mapping[str, Any], presets: Presets) -> Resolved:
    """Complete *answers* with defaults; raise InvalidAnswers on any problem."""
    unknown = sorted(set(answers) - set(BY_KEY))
    if unknown:
        raise InvalidAnswers([(None, f"unknown field {key!r}") for key in unknown])
    # The student's own answers are checked before any rule reads them.
    problems: list[tuple[str | None, str]] = [
        (key, p)
        for key, value in answers.items()
        if (p := _problem(BY_KEY[key], value, presets))
    ]
    if problems:
        raise InvalidAnswers(problems)

    values: dict[str, Any] = dict(answers)
    sources = {key: Source.USER for key in answers}
    # A derived value is checked the moment it exists, before any other rule
    # reads it. A field whose inputs are broken is broken too, silently: the
    # student fixes the first problem, not its echoes.
    problems = []
    broken: set[str] = set()
    pending = [spec for spec in FIELDS if spec.key not in values]
    while pending:
        waiting = []
        for spec in pending:
            default, source = _default(spec, answers)
            depends = _depends(spec, default)
            if any(dep in broken for dep in depends):
                broken.add(spec.key)
                continue
            if not all(dep in values for dep in depends):
                waiting.append(spec)
                continue
            ctx = Ctx(values, presets)
            try:
                if isinstance(default, Const):
                    value = default.value
                    if spec.unit is Unit.MONEY and value:
                        value *= ctx.market.fx
                elif isinstance(default, FromPreset):
                    if spec.unit is Unit.MONEY:
                        value = ctx.money(default.attr)
                    else:
                        value = getattr(ctx.preset, default.attr)
                elif isinstance(default, FromMarket):
                    value = getattr(ctx.market, default.attr)
                else:
                    value = default.fn(ctx)
            except ValueError as exc:  # e.g. the forecast behind the comps rule
                problems.append((spec.key, f"{spec.label}: {exc}"))
                broken.add(spec.key)
                continue
            problem = _problem(spec, value, presets)
            if problem:
                problems.append((spec.key, f"{problem} (derived; enter a value)"))
                broken.add(spec.key)
                continue
            values[spec.key] = value
            sources[spec.key] = source
        if len(waiting) == len(pending):
            raise RuntimeError(
                "field defaults depend on each other in a cycle: "
                + ", ".join(spec.key for spec in waiting)
            )
        pending = waiting
    if problems:
        raise InvalidAnswers(problems)

    split = sum(values[f"people.split_{k}"] for k in ("rnd", "snm", "gna", "ops"))
    if abs(split - 1) > 1e-6:
        problems.append(
            ("people.split_rnd", f"Staff shares: they sum to {split:.1%}, not 100%")
        )
    if values["rates.stage1_years"] > values["rates.horizon"]:
        problems.append(
            ("rates.stage1_years", "Stage-1 years: longer than the forecast horizon")
        )
    for key in DRIVER_KEYS:  # the triangle needs bear ≤ base ≤ bull, either way round
        ends = sorted(
            (values[f"simulation.bear.{key}"], values[f"simulation.bull.{key}"])
        )
        if not ends[0] <= values[key] <= ends[1]:
            problems.append(
                (
                    key,
                    f"{BY_KEY[key].label}: the bear and bull values must lie on "
                    "either side of it",
                )
            )
    if problems:
        raise InvalidAnswers(problems)
    return Resolved(values, sources)
