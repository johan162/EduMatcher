"""The confidence report (task AR-2.5).

The one number worth watching. Every link the tool draws is labelled with how
it was arrived at, and the distribution of those labels says whether the
narration can be trusted:

* On a log recorded since the envelope landed, ``RECORDED`` should dominate.
  Anything much below that means a publisher is bypassing ``CausalPublisher``,
  and finding that here is far cheaper than finding it in the prose.
* On an older archive the same command measures how much of the history
  predates the envelope -- which is worth knowing before drawing any
  conclusion from it.

So this is a diagnostic on the *audit trail*, not on the tool, which is why it
reports envelope coverage and the anomaly mix beside the link mix.
"""

from __future__ import annotations

from edumatcher.audit.replay import terminal
from edumatcher.audit.replay.terminal import Palette

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from edumatcher.audit.replay.links import CONFIDENCE_ORDER, Confidence
from edumatcher.audit.replay.pipeline import Step


@dataclass
class Stats:
    """Counts over one reconstructed window."""

    facts: int = 0
    with_envelope: int = 0
    origins: int = 0
    orphans: int = 0
    unknown_topics: int = 0
    links: Counter[Confidence] = field(default_factory=Counter)
    relations: Counter[str] = field(default_factory=Counter)
    anomalies: Counter[str] = field(default_factory=Counter)
    severities: Counter[str] = field(default_factory=Counter)

    @property
    def total_links(self) -> int:
        return sum(self.links.values())

    def envelope_share(self) -> float:
        return self.with_envelope / self.facts if self.facts else 0.0


def collect(steps: Iterable[Step]) -> Stats:
    stats = Stats()
    for step in steps:
        stats.facts += 1
        if step.fact.has_envelope:
            stats.with_envelope += 1
        if not step.fact.known:
            stats.unknown_topics += 1
        if step.resolution.origin:
            stats.origins += 1
        elif step.resolution.orphan:
            stats.orphans += 1
        for link in step.resolution.links:
            stats.links[link.confidence] += 1
            stats.relations[link.relation] += 1
        for anomaly in step.anomalies:
            stats.anomalies[anomaly.code] += 1
            stats.severities[anomaly.severity] += 1
    return stats


def _bar(share: float, width: int = 24) -> str:
    filled = round(share * width)
    return "#" * filled + "." * (width - filled)


def render(stats: Stats, palette: Palette = terminal.PLAIN) -> str:
    """A plain-text report. Shares as well as counts, because the question is
    always *what proportion*, and a reader made to divide two numbers to reach
    it will eventually divide the wrong pair."""
    if stats.facts == 0:
        return "No facts in window.\n"

    lines = [
        f"{stats.facts} fact(s) reconstructed.",
        "",
        palette.bold("Envelope coverage"),
        f"  with envelope   {stats.with_envelope:>8}  "
        f"{stats.envelope_share():6.1%}  {_bar(stats.envelope_share())}",
        f"  declared origin {stats.origins:>8}",
        f"  orphan          {stats.orphans:>8}",
        "",
        palette.bold("Link confidence"),
    ]
    total = stats.total_links
    if total == 0:
        lines.append("  (no links)")
    else:
        for level in CONFIDENCE_ORDER:
            count = stats.links.get(level, 0)
            share = count / total
            lines.append(f"  {level.value:<9} {count:>8}  {share:6.1%}  {_bar(share)}")
    if stats.relations:
        lines += ["", palette.bold("Relations")]
        for relation, count in sorted(
            stats.relations.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            lines.append(f"  {relation:<16} {count:>8}")
    lines += ["", palette.bold("Anomalies")]
    if not stats.anomalies:
        lines.append("  (none)")
    else:
        for code, count in sorted(
            stats.anomalies.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            lines.append(f"  {code:<26} {count:>8}")
        summary = ", ".join(
            f"{stats.severities[name]} {name}"
            for name in ("error", "warn", "info")
            if stats.severities.get(name)
        )
        lines.append(f"  -- {summary}")
    return "\n".join(lines) + "\n"
