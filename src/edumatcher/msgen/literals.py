"""Find topic string literals that a generated constant should have replaced.

Design section 7.4. Section 1.2 measured the problem — 108 distinct topic
literals across 25 files — and Phase 5 migrates them family by family. This is
how that migration is measured: a family is done when its count here is zero,
and the report is the acceptance check rather than someone's manual grep.

The failure it guards against is specific. A subscriber that hard-codes
``"trade.executed"`` keeps compiling and keeps running after a publisher-side
rename; it simply stops receiving. Nothing errors. Replacing the literal with
the generated constant turns that silence into an import error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from edumatcher.msgen.spec import Family

#: Directories whose topic literals are legitimate: the generated bindings
#: define the constants, and the generator's own tests build fixture specs.
_EXEMPT_PARTS = ("generated", "msgen")


@dataclass(frozen=True)
class Hit:
    """One topic literal found outside the generated bindings."""

    family: str
    topic: str
    path: Path
    line: int
    text: str


def _patterns(families: list[Family]) -> list[tuple[str, str, re.Pattern[str]]]:
    """Return (family, topic, regex) for every declared topic.

    A parameterised topic is searched by its literal prefix, since that is what
    a subscriber hard-codes: ``"order.ack."`` rather than the whole pattern.

    **The prefix is matched without requiring a closing quote**, and that is the
    whole point. Requiring one — which this did until 5.3b — meant an f-string
    never matched, because ``f"order.fill.{gateway_id}"`` continues with ``{``
    rather than ``"``. The report therefore said ``order: 0 literals -
    migrated`` while forty hard-coded parameterised topics sat in eight
    modules, and had said so since 5.1e. A gate that cannot see the most common
    way of writing the thing it gates is worse than no gate, because it is
    believed.

    Dropping the anchor is safe here precisely because a parameterised needle
    ends in ``.``: ``"risk.kill_switch_ack.`` cannot match inside
    ``f"risk.kill_switch_gateway_ack.{gw}"``, since the quote must sit
    immediately before the needle. A non-parameterised topic keeps the closing
    quote, without which ``"risk.kill_switch"`` would match
    ``"risk.kill_switch_gateway"``.
    """
    out: list[tuple[str, str, re.Pattern[str]]] = []
    for family in families:
        for message in family.messages:
            if message.topic is None:
                continue
            if message.topic_params:
                needle = message.topic[: message.topic.index("{")]
                source = f"['\"]{re.escape(needle)}"
            else:
                source = f"['\"]{re.escape(message.topic)}['\"]"
            out.append((family.family, message.topic, re.compile(source)))
    return out


def scan(roots: list[Path], families: list[Family]) -> list[Hit]:
    """Return every topic literal under ``roots``, in a stable order."""
    patterns = _patterns(families)
    hits: list[Hit] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if any(part in _EXEMPT_PARTS for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:  # pragma: no cover - not expected
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for family, topic, pattern in patterns:
                    if pattern.search(line):
                        hits.append(Hit(family, topic, path, number, stripped))
    return hits


def format_report(hits: list[Hit], families: list[Family], root: Path) -> str:
    """Render the report, one section per specified family."""
    lines: list[str] = []
    by_family: dict[str, list[Hit]] = {f.family: [] for f in families}
    for hit in hits:
        by_family[hit.family].append(hit)

    for family in sorted(by_family):
        found = by_family[family]
        modules = {hit.path for hit in found}
        header = (
            f"{family}: {len(found)} literal(s) in {len(modules)} module(s)"
            if found
            else f"{family}: 0 literals - migrated"
        )
        lines.append(header)
        for hit in found:
            try:
                shown = hit.path.relative_to(root)
            except ValueError:  # pragma: no cover - defensive
                shown = hit.path
            lines.append(f"    {shown}:{hit.line}: {hit.text}")
        lines.append("")

    total = len(hits)
    lines.append(
        f"{total} literal(s) remaining across {len({h.path for h in hits})} module(s)"
        if total
        else "no topic literals remain for any specified family"
    )
    return "\n".join(lines)
