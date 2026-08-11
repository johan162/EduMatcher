"""Phase 6.3, handover section 7.3: every message is built through its builder.

A message is *adopted* when some non-generated, non-``msgen`` module reaches the
wire through its generated ``make_<name>`` (or ``make_<name>_unchecked``) builder
rather than an open ``encode(topic, dict)``. Only a builder validates the
payload and, by construction, cannot silently drop a field the spec does not
declare (design section 27.2).

This is the gate the count lived without for a phase: the "thirty" of section
30.2 was really 29, and nobody re-checked it because it existed only in a
handover. This test freezes the end state so a new ``encode``-built producer, or
a builder quietly deleted, fails the suite instead of merging quietly.
"""

from __future__ import annotations

import ast
from pathlib import Path

from edumatcher.msgen.spec import load_all

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPO_ROOT / "spec"
SRC = REPO_ROOT / "src" / "edumatcher"

#: The two messages deliberately built without their generated builder. Both
#: are documented exclusions (design section 31.8), not omissions:
#:
#:   * ``order.execution_report`` — the BALF binary frame. It has no bus topic
#:     and makes no ``make_*`` call; its layout already comes from the spec via
#:     the generated C/Python projections (``test_msgen_balf_roundtrip.py``).
#:   * ``index.index_history`` — replays records verbatim from an append-only
#:     JSONL archive. Routing them through the generated ``HistoryRecord`` would
#:     validate every one, so a single legacy row missing a now-required field
#:     would raise in a handler with no guard and take pm-index down while
#:     serving history.
#:
#: Anything else unadopted is a regression. To adopt one of these, delete it
#: here in the same change that routes it through its builder.
ADOPTION_EXCLUSIONS = frozenset({"execution_report", "index_history"})


def _builder_calls() -> set[str]:
    """Every ``make_*`` builder name called outside generated/ and msgen/."""
    calls: set[str] = set()
    for path in SRC.rglob("*.py"):
        if "generated" in path.parts or "msgen" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name and name.startswith("make_"):
                    calls.add(name)
    return calls


def test_the_unadopted_set_is_exactly_the_documented_exclusions() -> None:
    calls = _builder_calls()
    _records, families = load_all(SPEC_ROOT)
    unadopted = {
        message.name
        for family in families
        for message in family.messages
        if f"make_{message.name}" not in calls
        and f"make_{message.name}_unchecked" not in calls
    }
    assert unadopted == ADOPTION_EXCLUSIONS
