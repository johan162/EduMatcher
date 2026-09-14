"""The three tabular views: ``anomalies``, ``episodes`` and ``digest``.

Separate from :mod:`render_text` because these are not narration. The prose
renderer turns a fact into a sentence; these three turn a set of episodes into
a table, a report or a ranking, and none of them reads a sentence template.
Keeping them apart means the wording of the narrative can change without a
column moving.

Every function here takes episodes and returns text, so each is testable
without argparse and none of them knows whether the episodes came from the
index or straight off the log. That is what makes ``--no-index`` answer the
same question rather than a similar one.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Callable, Mapping, Sequence

from edumatcher.audit.replay.anomalies import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    Anomaly,
)
from edumatcher.audit.replay.derived import Derived, derive
from edumatcher.audit.replay.episodes import (
    KIND_COMBO,
    KIND_COMMAND,
    KIND_OCO,
    KIND_ORDER,
    KIND_QUOTE,
    KIND_TRADE,
    Episode,
)
from edumatcher.audit.replay.render_text import Abbreviator

#: Most severe first, which is the order section 9.6 asks for and the order a
#: reader wants: the errors are why they ran the command.
SEVERITY_ORDER = (SEVERITY_ERROR, SEVERITY_WARN, SEVERITY_INFO)

#: ``--severity`` is a floor, so it needs a rank rather than a set.
_RANK = {severity: index for index, severity in enumerate(SEVERITY_ORDER)}

#: The ``story`` selector that reaches each episode kind, for the
#: ready-to-run command section 12.6 prints under every finding. Checked
#: against the CLI's own selector table by the tests, so the two cannot drift
#: apart without something failing.
STORY_FLAG: Mapping[str, str] = {
    KIND_ORDER: "--order",
    KIND_TRADE: "--trade",
    KIND_QUOTE: "--quote",
    KIND_OCO: "--oco",
    KIND_COMBO: "--combo",
    KIND_COMMAND: "--command",
}

SIGNIFICANCE_ANOMALIES = "anomalies"
SIGNIFICANCE_NOTIONAL = "notional"
SIGNIFICANCE_QTY = "qty"
SIGNIFICANCE_DURATION = "duration"
SIGNIFICANCE_RULES = (
    SIGNIFICANCE_ANOMALIES,
    SIGNIFICANCE_NOTIONAL,
    SIGNIFICANCE_QTY,
    SIGNIFICANCE_DURATION,
)

EPISODE_COLUMNS = (
    "opened",
    "span",
    "kind",
    "anchor",
    "actor",
    "symbol",
    "outcome",
    "anomalies",
)


def findings(episode: Episode) -> list[Anomaly]:
    """Every finding on an episode, per-fact and episode-level alike.

    The two live in different places -- a fact's are on its Step, an
    episode's on the Episode -- and every view here wants them as one list.
    Read back out of the index they arrive differently again (all of them on
    the first event), which is exactly why no view may reach for either place
    itself.
    """
    return [
        anomaly for event in episode.events for anomaly in event.step.anomalies
    ] + list(episode.anomalies)


def at_least(severity: str) -> int:
    return _RANK.get(severity, len(SEVERITY_ORDER))


def _clock(when: datetime) -> str:
    return when.strftime("%H:%M:%S.%f")[:-3]


def _span(episode: Episode) -> float:
    """Seconds from the episode's first event to its last.

    Not ``closed_ts``: a session span is ended by the fact that opens the next
    one, which belongs to that episode, and reading it back out of the index
    does not restore it. Last-event time is the same number on both paths.
    """
    return (episode.events[-1].fact.receipt_ts - episode.opened_ts).total_seconds()


def _anchors(
    episodes: Sequence[Episode], id_len: int | None
) -> Callable[[Episode], str]:
    """An abbreviator per episode kind, rather than one over all of them.

    :class:`Abbreviator` raises the length until no two ids in its pool share
    a prefix, and a pool mixing kinds is the wrong pool: trade ids are
    ``000042-000001873`` and differ only in their last digits, so one shared
    pool lengthens every *order* id to fifteen characters to disambiguate
    trades it could never be confused with. The kind is printed beside the
    anchor in all three views, so an order and a trade cannot collide.
    """
    by_kind = {
        kind: Abbreviator([e.anchor_key for e in episodes if e.kind == kind], id_len)
        for kind in {episode.kind for episode in episodes}
    }

    def short(episode: Episode) -> str:
        return by_kind[episode.kind](episode.anchor_key)

    return short


# ---------------------------------------------------------------------------
# anomalies (section 9.6, output shape from section 12.6)
# ---------------------------------------------------------------------------


def render_anomalies(
    episodes: Sequence[Episode],
    *,
    severity: str = SEVERITY_INFO,
    id_len: int | None = 6,
) -> str:
    """Every finding at or above *severity*, worst first, then by time."""
    short = _anchors(episodes, id_len)
    floor = at_least(severity)
    rows = [
        (episode, anomaly)
        for episode in episodes
        for anomaly in findings(episode)
        if at_least(anomaly.severity) <= floor
    ]
    rows.sort(key=lambda row: (at_least(row[1].severity), row[1].receipt_ts))

    lines: list[str] = []
    for episode, anomaly in rows:
        lines.append(
            f"{anomaly.severity.upper():<6} {_time(anomaly)}  "
            f"{anomaly.code:<22} {episode.kind} {short(episode)}"
        )
        lines.append(f"       {anomaly.detail}")
        suggestion = story_command(episode)
        if suggestion:
            lines.append(f"       -> {suggestion}")
        lines.append("")
    lines.append(_tally(rows, len(episodes)))
    return "\n".join(lines) + "\n"


def _time(anomaly: Anomaly) -> str:
    """The clock part of a recorded timestamp, or a placeholder.

    ``receipt_ts`` is the raw string the log carried, so it is sliced rather
    than parsed -- the view has no business re-deciding what a timestamp
    means.
    """
    if "T" in anomaly.receipt_ts:
        return anomaly.receipt_ts.split("T", 1)[1][:12]
    return "-" * 12


def story_command(episode: Episode) -> str | None:
    """The ``story`` invocation that shows this episode, or None.

    Section 12.6 prints one under every finding, because the next thing a
    reader does with a finding is go and look at it, and having to work out
    the command first is the friction that stops them.
    """
    flag = STORY_FLAG.get(episode.kind)
    if flag is None:
        return None
    return f"pm-audit-replay story {flag} {episode.anchor_key} -v --explain"


def _tally(rows: Sequence[tuple[Episode, Anomaly]], episodes: int) -> str:
    if not rows:
        return f"No findings across {episodes} episode(s)."
    counts = {
        severity: sum(1 for _, a in rows if a.severity == severity)
        for severity in SEVERITY_ORDER
    }
    parts = [f"{n} {severity}" for severity, n in counts.items() if n]
    return (
        f"{len(rows)} finding(s) ({', '.join(parts)}) " f"across {episodes} episode(s)."
    )


# ---------------------------------------------------------------------------
# episodes (section 9.5)
# ---------------------------------------------------------------------------


def render_episodes(
    episodes: Sequence[Episode], *, as_csv: bool = False, id_len: int | None = 6
) -> str:
    """One row per episode: the index as a table.

    Chronological by the episode's opening, which is the order a reader
    scanning for "the one at 09:31" expects. ``anomalies`` is a count; the
    findings themselves are what the ``anomalies`` view is for.
    """
    short = _anchors(episodes, id_len)
    ordered = sorted(episodes, key=lambda e: e.opened_sort_key)
    rows = [
        (
            _clock(episode.opened_ts),
            f"{_span(episode):.3f}s",
            episode.kind,
            short(episode) if not as_csv else episode.anchor_key,
            episode.actor or "-",
            episode.symbol or "-",
            episode.outcome,
            str(len(findings(episode))),
        )
        for episode in ordered
    ]
    return _csv(rows) if as_csv else _table(rows)


def _csv(rows: Sequence[Sequence[str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(EPISODE_COLUMNS)
    writer.writerows(rows)
    return out.getvalue()


def _table(rows: Sequence[Sequence[str]]) -> str:
    widths = [
        max(len(column), *(len(row[index]) for row in rows)) if rows else len(column)
        for index, column in enumerate(EPISODE_COLUMNS)
    ]
    lines = ["  ".join(c.ljust(w) for c, w in zip(EPISODE_COLUMNS, widths)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    lines.extend(
        "  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip()
        for row in rows
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# digest (section 9.4)
# ---------------------------------------------------------------------------


def render_digest(
    episodes: Sequence[Episode],
    *,
    significance: str = SIGNIFICANCE_ANOMALIES,
    top: int | None = None,
    id_len: int | None = 6,
) -> str:
    """One paragraph per episode, most significant first.

    Ranked rather than chronological: ``--significance`` has a default, and a
    default ranking that only takes effect when ``--top`` is given would mean
    the same command printed the same episodes in two different orders
    depending on a flag that is about how *many* to print.
    """
    short = _anchors(episodes, id_len)
    ranked = sorted(
        episodes,
        key=lambda e: (-_weight(e, significance), e.opened_sort_key),
    )
    shown = ranked if top is None else ranked[:top]

    blocks = [_paragraph(episode, short) for episode in shown]
    omitted = len(ranked) - len(shown)
    if omitted:
        blocks.append(
            f"... {omitted} more episode(s), less significant by {significance}."
        )
    return "\n\n".join(blocks) + "\n"


def _weight(episode: Episode, rule: str) -> float:
    """How significant this episode is under *rule*.

    ``anomalies`` falls back to notional, as section 9.4 says: without it
    every clean episode would weigh the same and the ranking inside the bulk
    of a day would be arbitrary.
    """
    if rule == SIGNIFICANCE_ANOMALIES:
        return _severity_weight(episode) + _notional(episode) / 1e12
    if rule == SIGNIFICANCE_NOTIONAL:
        return _notional(episode)
    if rule == SIGNIFICANCE_QTY:
        return float(derive(episode).filled_qty or 0)
    return _span(episode)


def _severity_weight(episode: Episode) -> float:
    """An error outranks any number of warnings, and so on down."""
    weights = {SEVERITY_ERROR: 1_000_000.0, SEVERITY_WARN: 1_000.0, SEVERITY_INFO: 1.0}
    return sum(weights.get(a.severity, 0.0) for a in findings(episode))


def _notional(episode: Episode) -> float:
    return derive(episode).notional or 0.0


def _paragraph(episode: Episode, short: Callable[[Episode], str]) -> str:
    lines = [
        f"{_clock(episode.opened_ts)}  {episode.kind} "
        f"{short(episode)}  {episode.actor or '-'}  "
        f"{episode.symbol or '-'}  {episode.outcome}"
    ]
    numbers = _numbers(derive(episode), episode)
    if numbers:
        lines.append(f"       {numbers}")
    found = findings(episode)
    if found:
        codes = ", ".join(sorted({anomaly.code for anomaly in found}))
        lines.append(f"       ! {len(found)} finding(s): {codes}")
    return "\n".join(lines)


def _numbers(derived: Derived, episode: Episode) -> str:
    """The derived facts worth a line, and only the ones that exist.

    Section 8.3's no-invention rule applied to a summary: a field that is
    None is one the log did not support, and it is left out rather than
    printed as a zero.
    """
    parts: list[str] = []
    if derived.filled_qty is not None:
        parts.append(f"{derived.filled_qty} filled")
    if derived.vwap is not None:
        parts.append(f"vwap {derived.vwap:g}")
    if derived.notional is not None:
        parts.append(f"{derived.notional:,.2f} notional")
    if derived.time_to_ack is not None:
        parts.append(f"acked in {derived.time_to_ack * 1000:.0f}ms")
    parts.append(f"{_span(episode):.3f}s")
    return " - ".join(parts)
