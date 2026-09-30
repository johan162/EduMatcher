"""The interview's state, independent of any screen (design §19).

The student's answers are kept as the text they typed, so a half-typed or
invalid value survives until they fix it. evaluate() parses every text,
resolves the whole company, and runs the deterministic valuation for the
live preview.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from edumatcher.valuation.fields import BY_KEY, FIELDS, PAGES, FieldSpec, Level
from edumatcher.valuation.pipeline import CannotValue, Run, run
from edumatcher.valuation.presets import Presets
from edumatcher.valuation.resolve import InvalidAnswers, Resolved, resolve
from edumatcher.valuation.units import (
    NOT_ANSWERED,
    ParseError,
    format_value,
    market_of,
    parse,
)


@dataclass(frozen=True)
class Evaluation:
    answers: dict[str, Any]  # every valid, non-empty answer
    problems: dict[str | None, str]  # field key (None: whole company) → message
    resolved: Resolved  # of these answers, or the last valid ones for hints
    preview: Run | None  # the deterministic run, when the answers allow one

    @property
    def valid(self) -> bool:
        return not self.problems


class Interview:
    def __init__(
        self,
        answers: Mapping[str, Any],
        presets: Presets,
        level: Level = Level.BEGINNER,
    ) -> None:
        by_key = {spec.key: spec for spec in FIELDS}
        self.presets = presets
        market = market_of(answers)
        self.texts: dict[str, str] = {
            key: format_value(by_key[key], value, market)
            for key, value in answers.items()
        }
        self.level = level
        self.page_index = 0
        self.dirty = False
        self._last_resolved = resolve({}, presets)
        self.evaluation = self.evaluate()

    # -- navigation -----------------------------------------------------------

    @property
    def pages(self) -> tuple[int, ...]:
        """The pages with at least one field at the current level."""
        return tuple(n for n in range(1, len(PAGES) + 1) if self.fields(n))

    @property
    def page(self) -> int:
        return self.pages[self.page_index]

    def turn(self, step: int) -> None:
        self.page_index = (self.page_index + step) % len(self.pages)

    def fields(self, page: int | None = None) -> list[FieldSpec]:
        page = self.page if page is None else page
        return [
            spec for spec in FIELDS if spec.page == page and spec.level <= self.level
        ]

    def next_level(self) -> Level:
        return Level(self.level % len(Level) + 1)

    def cycle_level(self) -> None:
        """F3: the next level, staying on this page or the next one shown."""
        page = self.page
        self.level = self.next_level()
        pages = self.pages
        self.page_index = next(
            (i for i, n in enumerate(pages) if n >= page), len(pages) - 1
        )

    def added_on(self, page: int) -> int:
        """Fields on *page* that the next level would add."""
        return sum(
            1 for spec in FIELDS if spec.page == page and spec.level == self.level + 1
        )

    def hidden_answers(self) -> int:
        """Answers typed (or loaded) in fields the current level hides."""
        return sum(1 for key in self.texts if BY_KEY[key].level > self.level)

    def answered_on(self, page: int) -> int:
        return sum(
            1 for spec in FIELDS if spec.page == page and self.texts.get(spec.key)
        )

    # -- editing ----------------------------------------------------------------

    def set_text(self, key: str, text: str) -> None:
        if self.texts.get(key, "") == text:
            return
        if text:
            self.texts[key] = text
        else:
            self.texts.pop(key, None)
        self.dirty = True
        self.evaluation = self.evaluate()

    def hint(self, spec: FieldSpec) -> str:
        """The automatic value an empty field takes, and where it comes from."""
        resolved = self.evaluation.resolved
        value = format_value(
            spec, resolved.values[spec.key], resolved.values["company.market"]
        )
        return f"auto {value} · {resolved.sources[spec.key].value}"

    # -- evaluation ---------------------------------------------------------------

    def evaluate(self) -> Evaluation:
        by_key = {spec.key: spec for spec in FIELDS}
        answers: dict[str, Any] = {}
        problems: dict[str | None, str] = {}
        for key, text in self.texts.items():
            try:
                value = parse(by_key[key], text)
            except ParseError as exc:
                problems[key] = str(exc)
                continue
            if value is not NOT_ANSWERED:
                answers[key] = value
        preview = None
        if not problems:
            try:
                preview = run(answers, self.presets, deterministic_only=True)
                self._last_resolved = preview.resolved
            except InvalidAnswers as exc:
                problems.update(exc.problems)
            except CannotValue as exc:
                problems[None] = str(exc)
        return Evaluation(answers, problems, self._last_resolved, preview)
