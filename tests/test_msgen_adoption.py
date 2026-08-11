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

#: The one message deliberately built without a generated ``make_*`` builder.
#: It is a documented exclusion (design section 9), not an omission:
#:
#:   * ``order.execution_report`` — the BALF binary frame. It has no bus topic
#:     and makes no ``make_*`` call; its layout already comes from the spec via
#:     the generated C/Python projections (``test_msgen_balf_roundtrip.py``), so
#:     it is generated where it counts, just not as a JSON builder call.
#:
#: ``index.index_history`` was the second exclusion until its archive was made
#: canonical by validating on write, letting the reply adopt the checked builder
#: (design section 9). Anything else unadopted is a regression. To adopt this
#: one, delete it here in the same change that routes it through its builder.
ADOPTION_EXCLUSIONS = frozenset({"execution_report"})


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


def _bus_encode_call_sites() -> set[str]:
    """Files that call the bus-level ``message.encode`` outside message.py.

    A raw ``encode(topic, payload)`` is how a producer reaches the wire without
    a builder, bypassing validation. The enumeration test above only sees
    messages that made it into a spec; this catches the other direction — an
    unspec'd producer wired straight to ``encode`` — which is how
    ``order.orders`` slipped the net before it was specced.
    """
    offenders: set[str] = set()
    for path in SRC.rglob("*.py"):
        if "generated" in path.parts or "msgen" in path.parts:
            continue
        if path == SRC / "models" / "message.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))

        # Names bound to the bus encode: `from ...message import encode` and
        # module aliases of `edumatcher.models.message`.
        by_name = False
        module_aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "edumatcher.models.message":
                    by_name |= any(a.name == "encode" for a in node.names)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "edumatcher.models.message":
                        module_aliases.add(a.asname or "edumatcher.models.message")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if by_name and isinstance(func, ast.Name) and func.id == "encode":
                offenders.add(path.name)
            elif (
                isinstance(func, ast.Attribute)
                and func.attr == "encode"
                and isinstance(func.value, ast.Name)
                and func.value.id in module_aliases
            ):
                offenders.add(path.name)
    return offenders


def test_no_producer_reaches_the_wire_through_raw_encode() -> None:
    """Every bus producer goes through a builder, never raw ``encode``.

    ``models/message.py`` owns the primitive and generated code delegates to
    it; no other module should call it directly.
    """
    assert _bus_encode_call_sites() == set()
