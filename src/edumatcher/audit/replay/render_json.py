"""Section 11's machine-readable narrative: the model, not the log.

``--format ndjson`` emits one JSON object per narrated element; ``--format
json`` wraps the same objects in one document with a header. Consumers get the
causal graph without re-implementing section 5, which is the whole point of
separating the model from the prose.

Both are produced by the *same*
:class:`~edumatcher.audit.replay.render_text.Renderer` as the prose, at the
same :class:`~edumatcher.audit.replay.render_text.Options` -- so the two
formats agree beat for beat by construction rather than by intention. The text
renderer *is* the ``text`` field. A format that quietly narrated more, or
less, than the other would be worse than having only one.

Four object types:

``episode``  one per narrated episode, with its summary and derived facts
``beat``     one per narrated fact; its ``text`` is the prose line
``link``     one per edge between two episodes
``anomaly``  one per finding

They come out as a stream in narration order, an episode announced the first
time one of its beats appears, so a consumer can process the output without
holding the window in memory. The edges come last, deduplicated and sorted:
a link is a fact about two episodes, not about the beat that happened to
state it, and which of its two ends carries it differs between a live
reconstruction and one read back from the index -- so interleaving them would
make ``--no-index`` and an indexed run emit the same edges in different
places. Deduplicated on ``(from, to, relation)``, which is the primary key
the index's own ``links`` table uses.

Three places where this departs from section 11's sketch, each because the
implementation settled the question differently and one vocabulary is worth
more than a matching example:

* ``derived`` is :meth:`~edumatcher.audit.replay.derived.Derived.as_dict`
  verbatim -- the same names and units the index already stores in
  ``episodes.facts_json``. The sketch's ``ack_latency_ms`` is ``time_to_ack``
  in seconds here, and a second spelling for one number is how two sources of
  truth start.
* ``fields`` is the recorded payload, whole, beside a ``prices`` map of
  whatever section 5.3.1 resolved into display money. The sketch shows a
  curated handful per kind, which would be another vocabulary to keep in step
  with ``templates.py``; a payload that is simply complete cannot drift.
* An anomaly hangs off its **episode**, not off a beat. Read back out of the
  index every finding arrives on the episode's first event rather than on the
  fact that produced it, so anchoring to the beat would make ``--no-index``
  and indexed runs disagree about where a finding sits.

An anomaly carries a ``source`` that section 11 does not give it, for the
reason ``Anomaly`` carries a file and line at all: a finding a reader cannot
go and look at is a finding they cannot act on. The index's ``anomalies``
table had no column for either until schema version 2, which is why it is
here rather than in the sketch.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Iterator, Mapping, Sequence

from edumatcher.audit.replay import templates, views
from edumatcher.audit.replay.anomalies import SEVERITY_INFO, Anomaly
from edumatcher.audit.replay.derived import derive
from edumatcher.audit.replay.episodes import Episode, EpisodeEvent
from edumatcher.audit.replay.links import Link
from edumatcher.audit.replay.ordering import pack_sort_key
from edumatcher.audit.replay.render_text import Options, Rendered, Renderer, suppressed
from edumatcher.audit.replay.state import StateModel

TYPE_EPISODE = "episode"
TYPE_BEAT = "beat"
TYPE_LINK = "link"
TYPE_ANOMALY = "anomaly"


def objects(
    episodes: Sequence[Episode],
    state: StateModel | None = None,
    options: Options | None = None,
) -> Iterator[dict[str, Any]]:
    """The window as section 11 objects, in the order the prose narrates it."""
    options = options or Options()
    renderer = Renderer(episodes, state, options)
    refs = _refs(episodes)
    announced: set[int] = set()

    if options.level <= templates.LEVEL_OUTCOMES:
        for episode in sorted(episodes, key=lambda e: e.opened_sort_key):
            # Level 0 is a different shape, not a quieter level 1 -- the same
            # reason `Renderer.summaries` asks about LEVEL_DEFAULT here.
            if suppressed(episode.opened, templates.LEVEL_DEFAULT):
                continue
            yield from _announce(renderer, episode, announced)
        return

    edges: dict[tuple[int, int, str], dict[str, Any]] = {}
    for episode, event in _narrated(episodes):
        rendered = renderer.line(episode, event)
        if rendered is None:
            continue
        yield from _announce(renderer, episode, announced)
        yield _beat(episode, event, rendered)
        for link in event.step.resolution.links:
            edge = _link(link, refs)
            if edge is not None:
                edges[(edge["from"], edge["to"], edge["relation"])] = edge
    for key in sorted(edges):
        yield edges[key]


def ndjson(
    episodes: Sequence[Episode],
    state: StateModel | None = None,
    options: Options | None = None,
) -> list[str]:
    """One compact JSON object per line."""
    return [dumps(obj) for obj in objects(episodes, state, options)]


def document(
    episodes: Sequence[Episode],
    state: StateModel | None = None,
    options: Options | None = None,
    *,
    window: Mapping[str, str | None] | None = None,
    source_files: Iterable[str] = (),
    rules_version: int | None = None,
) -> str:
    """The same objects in one document, for a consumer that wants one read."""
    body = list(objects(episodes, state, options))
    counts: dict[str, int] = {}
    for obj in body:
        counts[obj["type"]] = counts.get(obj["type"], 0) + 1
    return dumps(
        {
            "window": dict(window or {}),
            "source_files": list(source_files),
            "rules_version": rules_version,
            "counts": counts,
            "objects": body,
        }
    )


def markdown(
    episodes: Sequence[Episode],
    state: StateModel | None = None,
    options: Options | None = None,
) -> list[str]:
    """The prose under a heading per episode, for pasting into a write-up.

    Grouped rather than chronological: an incident report is read episode by
    episode, which is the one place the stream's interleaving gets in the way.
    The sentences are the beats' own ``text``, so this cannot say anything the
    other two formats do not.
    """
    beats: dict[int, list[dict[str, Any]]] = {}
    headings: dict[int, dict[str, Any]] = {}
    for obj in objects(episodes, state, options):
        if obj["type"] == TYPE_EPISODE:
            headings[int(obj["id"])] = obj
        elif obj["type"] == TYPE_BEAT:
            beats.setdefault(int(obj["episode"]), []).append(obj)

    lines: list[str] = []
    for episode_id, head in headings.items():
        lines.append(f"## {head['summary']}")
        lines.append("")
        for beat in beats.get(episode_id, ()):
            lines.append(f"- `{beat['receipt_ts']}` {beat['text']}")
        lines.append("")
    return lines


def anomalies(
    episodes: Sequence[Episode], *, severity: str = SEVERITY_INFO
) -> Iterator[dict[str, Any]]:
    """Just the findings, for ``anomalies --format ndjson``.

    Ordered as :func:`views.render_anomalies` orders them -- worst first, then
    by time -- so the machine-readable report and the printed one are the same
    report rather than two reports that happen to agree.
    """
    floor = views.at_least(severity)
    rows = [
        (episode, anomaly)
        for episode in episodes
        for anomaly in views.findings(episode)
        if views.at_least(anomaly.severity) <= floor
    ]
    rows.sort(key=lambda row: (views.at_least(row[1].severity), row[1].receipt_ts))
    for episode, anomaly in rows:
        obj = _anomaly(anomaly, episode.episode_id)
        obj["episode_kind"] = episode.kind
        obj["anchor"] = episode.anchor_key
        obj["story"] = views.story_command(episode)
        yield obj


# ---------------------------------------------------------------------------
# The objects
# ---------------------------------------------------------------------------


def _announce(
    renderer: Renderer, episode: Episode, announced: set[int]
) -> Iterator[dict[str, Any]]:
    """The episode object, once, with its findings behind it."""
    if episode.episode_id in announced:
        return
    announced.add(episode.episode_id)
    yield _episode(renderer, episode)
    for anomaly in views.findings(episode):
        yield _anomaly(anomaly, episode.episode_id)


def _episode(renderer: Renderer, episode: Episode) -> dict[str, Any]:
    return {
        "type": TYPE_EPISODE,
        "id": episode.episode_id,
        "kind": episode.kind,
        "anchor": episode.anchor_key,
        "actor": episode.actor,
        "correlation_id": episode.correlation_id,
        "root_msg_id": episode.root_msg_id,
        "symbol": episode.symbol,
        "run_seq": episode.run_seq,
        "opened": episode.opened_ts.isoformat(),
        "closed": episode.closed_ts.isoformat() if episode.closed_ts else None,
        "outcome": episode.outcome,
        "summary": renderer.summary(episode),
        "derived": derive(episode).as_dict(),
    }


def _beat(episode: Episode, event: EpisodeEvent, rendered: Rendered) -> dict[str, Any]:
    fact = event.fact
    return {
        "type": TYPE_BEAT,
        "episode": episode.episode_id,
        "seq": event.seq_in_ep,
        "sort_key": pack_sort_key(fact),
        "msg_id": fact.msg_id,
        "causation_id": fact.causation_id,
        "correlation_id": fact.correlation_id,
        "topic_seq": fact.topic_seq,
        "receipt_ts": fact.receipt_raw,
        "topic": fact.topic,
        "kind": fact.kind,
        "role": event.role,
        "late": fact.late,
        "text": rendered.text,
        "source": {"file": fact.file, "line": fact.line_no},
        "fields": dict(fact.payload),
        "prices": {
            name: price.display
            for name, price in fact.prices.items()
            if price.display is not None
        },
    }


def _link(link: Link, refs: Mapping[str, int]) -> dict[str, Any] | None:
    """One edge, projected onto episode ids -- ``index.py``'s rule, in Python.

    A link with an end outside this window resolves to nothing and is not an
    edge, which is the truthful answer; the resolver's own ``CAUSE_NOT_FOUND``
    is the finding rather than this being one. A link inside one episode is
    something the episode already expresses, and as a self-loop here it would
    be noise.
    """
    source = refs.get(link.source)
    target = refs.get(link.target)
    if source is None or target is None or source == target:
        return None
    return {
        "type": TYPE_LINK,
        "from": source,
        "to": target,
        "relation": link.relation,
        "confidence": link.confidence,
        "evidence": link.evidence,
    }


def _anomaly(anomaly: Anomaly, episode_id: int) -> dict[str, Any]:
    return {
        "type": TYPE_ANOMALY,
        "code": anomaly.code,
        "severity": anomaly.severity,
        "episode": episode_id,
        "receipt_ts": anomaly.receipt_ts,
        "detail": anomaly.detail,
        "source": {"file": anomaly.file, "line": anomaly.line_no},
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _narrated(episodes: Sequence[Episode]) -> list[tuple[Episode, EpisodeEvent]]:
    """Every event, in the order ``render_text.narrate`` walks them.

    Spelled out again rather than shared: a constant with a name would let the
    two orderings look identical while differing, and what actually guards the
    agreement is the property test that compares the two outputs.
    """
    return sorted(
        ((episode, event) for episode in episodes for event in episode.events),
        key=lambda pair: pair[1].fact.ordinal,
    )


def _refs(episodes: Sequence[Episode]) -> dict[str, int]:
    """``episode_events.ref`` -> episode id, which is ``_RESOLVE_SQL``'s join."""
    return {
        event.step.resolution.ref: episode.episode_id
        for episode in episodes
        for event in episode.events
    }


def dumps(obj: Any) -> str:
    """Compact, key order as written, non-ASCII left alone.

    ``sort_keys`` is off on purpose: the field order above is the order
    section 11 documents, and a reader diffing two runs should meet the shape
    they read in the design.
    """
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)


__all__ = [
    "TYPE_ANOMALY",
    "TYPE_BEAT",
    "TYPE_EPISODE",
    "TYPE_LINK",
    "anomalies",
    "document",
    "dumps",
    "markdown",
    "ndjson",
    "objects",
]
