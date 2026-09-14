"""Golden-fixture harness for pm-audit-replay (task AR-1.5).

A golden test freezes what the tool *says*, so a change to the wording -- or to
the order the wording comes in -- shows up as a diff in review rather than as a
surprise six months later. That is worth having in place before there is output
to freeze: the alternative is writing the harness once there are ten scenarios,
against output nobody has reviewed.

Layout, per design section 15.2::

    tests/fixtures/replay/
      01_simple_limit_partial_fill.log
      01_simple_limit_partial_fill.expected.order.txt

The level suffix names what is frozen. There is no prose yet, so the two
levels are structural: ``order``, the canonical sequence of facts, which is
the thing everything downstream is wrong without; and ``causality``, what the
resolver made of each fact and how sure it is. Freezing the confidence matters
more than freezing the links -- a change that silently promoted a guess to a
certainty is exactly what a reviewer would otherwise wave through. The prose
levels (``q``, ``v1``, ``v2``) join them when there is prose.

Run ``pytest --update-goldens`` to rewrite the expected files from current
output, then **read the diff** before committing it. A golden accepted without
being read is not a test.

Not a test module (no ``test_`` prefix) -- pytest will not collect it.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Iterable

from edumatcher.audit.query import iter_entries
from edumatcher.audit.replay.facts import Fact, normalise
from edumatcher.audit.replay.ordering import ordered
from edumatcher.audit.replay.pipeline import Step, reconstruct

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "replay"

LEVEL_ORDER = "order"
LEVEL_CAUSALITY = "causality"


def fixture_log(name: str) -> Path:
    path = FIXTURE_DIR / f"{name}.log"
    if not path.exists():
        raise FileNotFoundError(f"No replay fixture named {name!r} at {path}")
    return path


def golden_path(name: str, level: str) -> Path:
    return FIXTURE_DIR / f"{name}.expected.{level}.txt"


def load_facts(name: str) -> list[Fact]:
    """Run the phase-1 pipeline over a fixture: normalise, then order.

    One pass. Every message carrying a tick price carries its own scale, so
    there is nothing to learn from the rest of the log first.
    """
    return list(ordered(normalise(iter_entries([fixture_log(name)]))))


def render_order(facts: Iterable[Fact]) -> str:
    """One line per fact, in canonical order.

    Deliberately close to what a reader would want from ``--show-source``: the
    position, the receipt clock, what the message was, who it was for, and the
    id that decided where it landed.
    """
    lines = []
    for position, fact in enumerate(facts, start=1):
        flags = []
        if fact.late:
            flags.append("LATE")
        flags += [anomaly.code for anomaly in fact.anomalies]
        lines.append(
            "  ".join(
                [
                    f"{position:03d}",
                    fact.receipt_ts.strftime("%H:%M:%S.%f")[:-3],
                    f"{fact.kind:<28}",
                    f"{fact.actor or '-':<10}",
                    f"{fact.msg_id or '-':<26}",
                    f"seq={fact.topic_seq if fact.topic_seq is not None else '-'}",
                    " ".join(flags),
                ]
            ).rstrip()
        )
    return "\n".join(lines) + "\n"


def load_steps(name: str) -> list[Step]:
    """Run the whole of pass 1 over a fixture: normalise, order, reconstruct."""
    _run, steps = reconstruct(iter_entries([fixture_log(name)]))
    return list(steps)


def render_causality(steps: Iterable[Step]) -> str:
    """What the resolver made of each fact, confidence included.

    Origins are spelled out rather than left blank. "The publisher said
    nothing caused this" and "nothing was found" are different claims, and a
    golden that rendered both as an empty line would let a regression turn one
    into the other without showing a diff.
    """
    lines = []
    for position, step in enumerate(steps, start=1):
        marker = (
            "origin"
            if step.resolution.origin
            else ("orphan" if step.resolution.orphan else "")
        )
        lines.append(
            f"{position:03d}  {step.fact.kind:<28}  {step.fact.actor or '-':<10}  {marker}".rstrip()
        )
        for link in step.resolution.links:
            lines.append(
                f"     <- {link.relation:<17} {link.confidence.value:<9} "
                f"{link.source:<28} {link.evidence}"
            )
        for anomaly in step.anomalies:
            lines.append(
                f"     !  {anomaly.severity.upper():<5} {anomaly.code}: {anomaly.detail}"
            )
    return "\n".join(lines) + "\n"


def assert_golden(name: str, level: str, actual: str, *, update: bool) -> None:
    """Compare *actual* against the committed expectation, or rewrite it."""
    path = golden_path(name, level)
    if update:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        return
    if not path.exists():
        raise AssertionError(
            f"No golden file at {path}. Run `pytest --update-goldens` and review "
            f"the result before committing it."
        )
    expected = path.read_text(encoding="utf-8")
    if expected == actual:
        return
    diff = "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f"{path.name} (committed)",
            tofile=f"{path.name} (current output)",
        )
    )
    raise AssertionError(f"Golden output changed for {name} [{level}]:\n{diff}")
