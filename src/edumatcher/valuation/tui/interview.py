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

from edumatcher.valuation.fields import FIELDS, PAGES, FieldSpec
from edumatcher.valuation.pipeline import CannotValue, Run, run
from edumatcher.valuation.presets import Presets
from edumatcher.valuation.resolve import InvalidAnswers, Resolved, resolve
from edumatcher.valuation.units import NOT_ANSWERED, ParseError, format_value, parse

#: The pages --quick shows: the company and management's constraints.
QUICK_PAGES = (1, 11)


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
        self, answers: Mapping[str, Any], presets: Presets, quick: bool = False
    ) -> None:
        by_key = {spec.key: spec for spec in FIELDS}
        self.presets = presets
        self.texts: dict[str, str] = {
            key: format_value(by_key[key], value) for key, value in answers.items()
        }
        self.pages: tuple[int, ...] = (
            QUICK_PAGES if quick else tuple(range(1, len(PAGES) + 1))
        )
        self.page_index = 0
        self.show_advanced = False
        self.dirty = False
        self._last_resolved = resolve({}, presets)
        self.evaluation = self.evaluate()

    # -- navigation -----------------------------------------------------------

    @property
    def page(self) -> int:
        return self.pages[self.page_index]

    def turn(self, step: int) -> None:
        self.page_index = (self.page_index + step) % len(self.pages)

    def fields(self, page: int | None = None) -> list[FieldSpec]:
        page = self.page if page is None else page
        return [
            spec
            for spec in FIELDS
            if spec.page == page and (self.show_advanced or not spec.advanced)
        ]

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
        value = format_value(spec, resolved.values[spec.key])
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
