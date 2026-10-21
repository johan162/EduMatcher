"""Keep tools/mutate_engine.py's mutants applicable.

Each mutant is an exact text replacement in the engine source. A refactor that
changes the text would silently disable the mutant (a mutation run would then
report it as "pattern not found" at best, or measure nothing). This pins every
mutant to the current source, so the refactor fails here and the mutant gets
updated with it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import mutate_engine as mut  # noqa: E402


def test_every_mutant_applies_exactly_once_and_still_parses() -> None:
    assert mut.check(mut.MUTANTS) == []


def test_every_mutant_changes_the_source() -> None:
    for m in mut.MUTANTS:
        assert m.old != m.new, m.id


def test_mutant_ids_are_unique() -> None:
    ids = [m.id for m in mut.MUTANTS]
    assert len(ids) == len(set(ids))
