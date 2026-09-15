"""The episode index, read back (design section 6.1).

The build side is :mod:`~edumatcher.audit.replay.index`; this is the half that
makes it worth having. Without it every ``story`` would reconstruct the whole
log to answer a question about one order -- 87 seconds on a 200 MB trail
against section 16's 100 ms target, which is not a slow tool but a different
one.

**An Episode read back is the same object the assembler produced.** The
payload is stored verbatim, so a Fact is rebuilt by handing that payload back
to :func:`~edumatcher.audit.replay.facts.to_fact` -- the same normalisation
pass 1 ran, not a second implementation of it. Prices are re-resolved rather
than stored resolved, for the same reason: two code paths that both decide
what a price means is one more than can be kept in agreement.

The stream ordinal is recovered from the packed sort key rather than stored
again beside it. It is already in there, and a column that restates part of
another column is a column that can disagree with it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Iterable, Iterator, Mapping, Sequence

from edumatcher.audit.query import AuditEntry
from edumatcher.audit.replay.anomalies import Anomaly
from edumatcher.audit.replay.episodes import Episode, EpisodeEvent
from edumatcher.audit.replay.facts import to_fact
from edumatcher.audit.replay.links import Confidence, Link, Resolution
from edumatcher.audit.replay.pipeline import Step
from edumatcher.audit.replay.state import StateModel

#: The separator :func:`~edumatcher.audit.replay.ordering.pack_sort_key` joins
#: the key's four fields with.
_PACK_SEP = "\x1f"


def episodes_in_window(
    conn: sqlite3.Connection,
    *,
    from_ts: str | None = None,
    to_ts: str | None = None,
    symbols: Sequence[str] | None = None,
    gateways: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[Episode]:
    """Every episode that opened inside the window, in canonical order.

    Filtering is on the episode rather than the fact: an order whose fills are
    in the window but whose submission is not is still that order's story, and
    dropping its opening line would make the narration start mid-sentence.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if from_ts:
        clauses.append("opened_ts >= ?")
        params.append(from_ts)
    if to_ts:
        clauses.append("opened_ts <= ?")
        params.append(to_ts)
    _in(clauses, params, "symbol", symbols)
    _in(clauses, params, "actor", gateways)
    _in(clauses, params, "kind", kinds)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM episodes {where} ORDER BY opened_sort_key"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return _hydrate(conn, conn.execute(sql, params).fetchall())


def episode_by_anchor(
    conn: sqlite3.Connection, kind: str, anchor: str
) -> Episode | None:
    """One episode by ``(kind, anchor)``, accepting an unambiguous prefix.

    An exact match is tried first, because a full id that happens to prefix a
    longer one must resolve to itself rather than to an ambiguity error.
    """
    exact = conn.execute(
        "SELECT * FROM episodes WHERE kind = ? AND anchor_key = ?", (kind, anchor)
    ).fetchall()
    if exact:
        return _hydrate(conn, exact)[0]
    rows = conn.execute(
        "SELECT * FROM episodes WHERE kind = ? AND anchor_key LIKE ? LIMIT 2",
        (kind, f"{anchor}%"),
    ).fetchall()
    if len(rows) != 1:
        return None
    return _hydrate(conn, rows)[0]


def episodes_in_chain(conn: sqlite3.Connection, chain: str) -> list[Episode]:
    """The whole causal descent, as one indexed read (section 9.3)."""
    return _hydrate(
        conn,
        conn.execute(
            "SELECT * FROM episodes WHERE correlation_id = ? ORDER BY opened_sort_key",
            (chain,),
        ).fetchall(),
    )


def episode_containing(conn: sqlite3.Connection, ref: str) -> Episode | None:
    """The episode one message landed in, by ``msg_id`` or stream ref."""
    row = conn.execute(
        "SELECT episode_id FROM episode_events WHERE ref = ? OR msg_id = ? LIMIT 1",
        (ref, ref),
    ).fetchone()
    return None if row is None else _by_id(conn, int(row["episode_id"]))


def episode_by_client_tag(conn: sqlite3.Connection, tag: str) -> Episode | None:
    """The episode carrying a client's own tag.

    A payload scan, because ``client_tag`` is the trader's string and not
    something the index promotes to a column. It is bounded by the window and
    is the only query here that is not keyed.
    """
    needle = f'%"client_tag": "{tag}"%'
    row = conn.execute(
        "SELECT episode_id FROM episode_events WHERE payload LIKE ? LIMIT 1",
        (needle,),
    ).fetchone()
    return None if row is None else _by_id(conn, int(row["episode_id"]))


def neighbours(
    conn: sqlite3.Connection, episode_ids: Iterable[int], *, recorded_only: bool
) -> dict[int, list[tuple[int, Link]]]:
    """Episodes one link away, in both directions.

    Both directions on purpose: an order's story includes the trade it caused
    *and* the command that cancelled it, and a reader asking "what happened to
    this order" does not care which way the arrow points.

    ``recorded_only`` is ``--strict-causality``: follow only what the exchange
    stated, so a conclusion drawn from an inferred link cannot be mistaken for
    one the engine recorded.
    """
    ids = list(episode_ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    confidence = " AND confidence = 'RECORDED'" if recorded_only else ""
    rows = conn.execute(
        f"SELECT * FROM links WHERE (from_episode IN ({marks}) "
        f"OR to_episode IN ({marks})){confidence}",
        ids + ids,
    ).fetchall()
    found: dict[int, list[tuple[int, Link]]] = {}
    for row in rows:
        link = Link(
            source=str(row["from_episode"]),
            target=str(row["to_episode"]),
            relation=str(row["relation"]),
            confidence=Confidence(str(row["confidence"])),
            evidence=str(row["evidence"]),
        )
        for near, far in (
            (int(row["from_episode"]), int(row["to_episode"])),
            (int(row["to_episode"]), int(row["from_episode"])),
        ):
            found.setdefault(near, []).append((far, link))
    return found


def walk(
    conn: sqlite3.Connection,
    seed: Episode,
    *,
    depth: int,
    recorded_only: bool = False,
) -> list[Episode]:
    """*seed* and everything within *depth* links of it, in canonical order.

    Breadth-first, so a depth of 2 means two hops and not two episodes. The
    seed is always included even at depth 0, because "show me this order" is
    a question that has an answer without following anything.
    """
    seen = {seed.episode_id: seed}
    frontier = [seed.episode_id]
    for _hop in range(max(depth, 0)):
        edges = neighbours(conn, frontier, recorded_only=recorded_only)
        frontier = [
            far
            for near in frontier
            for far, _link in edges.get(near, [])
            if far not in seen
        ]
        if not frontier:
            break
        for episode in _by_ids(conn, frontier):
            seen[episode.episode_id] = episode
    return sorted(seen.values(), key=lambda e: e.opened_sort_key)


# ---------------------------------------------------------------------------
# Rows back into objects
# ---------------------------------------------------------------------------


def _hydrate(conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> list[Episode]:
    if not rows:
        return []
    ids = [int(row["episode_id"]) for row in rows]
    events = _events_for(conn, ids)
    anomalies = _anomalies_for(conn, ids)
    links = _stated_links(conn)
    return [_episode(row, events, anomalies, links) for row in rows]


def _episode(
    row: sqlite3.Row,
    events: Mapping[int, list[sqlite3.Row]],
    anomalies: Mapping[int, list[Anomaly]],
    links: Mapping[str, list[Link]],
) -> Episode:
    episode_id = int(row["episode_id"])
    found = anomalies.get(episode_id, [])
    return Episode(
        episode_id=episode_id,
        kind=str(row["kind"]),
        anchor_key=str(row["anchor_key"]),
        events=[
            _event(event_row, links, found if index == 0 else [])
            for index, event_row in enumerate(events.get(episode_id, []))
        ],
        outcome=str(row["outcome"] or ""),
        closed=row["closed_ts"] is not None,
        closed_ts=_ts(row["closed_ts"]),
        closed_sort_key=None,
    )


def _ts(value: Any) -> datetime | None:
    """``episodes.closed_ts`` back as the datetime that was written.

    Dropping it left an episode read from the index looking as if it had never
    ended, which the section 11 object reports as ``"closed": null`` and
    ``derive`` reports by omitting ``time_to_completion`` -- so ``--no-index``
    and an indexed run said different things about the same episode.
    """
    return datetime.fromisoformat(str(value)) if value else None


def _event(
    row: sqlite3.Row, links: Mapping[str, list[Link]], anomalies: Sequence[Anomaly]
) -> EpisodeEvent:
    ref = str(row["ref"])
    entry = AuditEntry(
        str(row["receipt_ts"]),
        str(row["topic"]),
        json.loads(str(row["payload"])),
        _meta(row),
        file=str(row["file"]) or None,
        line_no=int(row["line_no"]),
    )
    fact = to_fact(entry, _ordinal(str(row["sort_key"])))
    resolution = Resolution(
        ref=ref,
        origin=fact.msg_id is not None and fact.causation_id is None,
        enveloped=fact.msg_id is not None,
        links=tuple(links.get(ref, ())),
        anomalies=tuple(anomalies),
    )
    return EpisodeEvent(
        step=Step(fact=fact, resolution=resolution, anomalies=tuple(anomalies)),
        seq_in_ep=int(row["seq_in_ep"]),
        role=str(row["role"]),
    )


def _meta(row: sqlite3.Row) -> dict[str, str]:
    """The envelope frame, as ``pm-audit`` wrote it and ``to_fact`` reads it."""
    meta: dict[str, str] = {}
    for key, column in (
        ("msg", "msg_id"),
        ("cause", "causation_id"),
        ("chain", "correlation_id"),
    ):
        value = row[column]
        if value:
            meta[key] = str(value)
    if row["topic_seq"] is not None:
        meta["seq"] = str(row["topic_seq"])
    return meta


def _ordinal(sort_key: str) -> int:
    """The stream position, back out of the packed key."""
    parts = sort_key.split(_PACK_SEP)
    try:
        return int(parts[-1])
    except (IndexError, ValueError):
        return 0


def _events_for(
    conn: sqlite3.Connection, ids: Sequence[int]
) -> dict[int, list[sqlite3.Row]]:
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM episode_events WHERE episode_id IN ({marks}) "
        f"ORDER BY episode_id, seq_in_ep",
        list(ids),
    ).fetchall()
    found: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        found.setdefault(int(row["episode_id"]), []).append(row)
    return found


def _anomalies_for(
    conn: sqlite3.Connection, ids: Sequence[int]
) -> dict[int, list[Anomaly]]:
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM anomalies WHERE episode_id IN ({marks})", list(ids)
    ).fetchall()
    found: dict[int, list[Anomaly]] = {}
    for row in rows:
        found.setdefault(int(row["episode_id"]), []).append(
            Anomaly(
                code=str(row["code"]),
                severity=str(row["severity"]),
                detail=str(row["detail"]),
                receipt_ts=str(row["receipt_ts"]),
                file=str(row["file"]) if row["file"] else None,
                line_no=int(row["line_no"]),
            )
        )
    return found


def _stated_links(conn: sqlite3.Connection) -> dict[str, list[Link]]:
    """Links by the ref they point *at*, which is what ``--explain`` shows.

    Read whole rather than per episode: a story is a handful of episodes and
    a window is bounded, so one scan beats a query per line.
    """
    found: dict[str, list[Link]] = {}
    for row in conn.execute("SELECT * FROM stated_links"):
        found.setdefault(str(row["to_ref"]), []).append(
            Link(
                source=str(row["from_ref"]),
                target=str(row["to_ref"]),
                relation=str(row["relation"]),
                confidence=Confidence(str(row["confidence"])),
                evidence=str(row["evidence"]),
            )
        )
    return found


def _by_id(conn: sqlite3.Connection, episode_id: int) -> Episode | None:
    found = _by_ids(conn, [episode_id])
    return found[0] if found else None


def _by_ids(conn: sqlite3.Connection, ids: Sequence[int]) -> list[Episode]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return _hydrate(
        conn,
        conn.execute(
            f"SELECT * FROM episodes WHERE episode_id IN ({marks})", list(ids)
        ).fetchall(),
    )


def _in(
    clauses: list[str], params: list[Any], column: str, values: Sequence[str] | None
) -> None:
    if not values:
        return
    clauses.append(f"{column} IN ({','.join('?' * len(values))})")
    params.extend(values)


def actors(conn: sqlite3.Connection) -> StateModel:
    """A state model carrying just the gateway descriptions.

    The narrator reads exactly one thing from the state model -- a gateway's
    human name, for ``--actor-style=descriptive`` -- and the index has it in
    ``actors``. Without this the switch would silently do nothing whenever the
    story came from the index rather than from the log, which is the worst
    kind of broken flag.
    """
    state = StateModel()
    for row in conn.execute("SELECT gateway_id, description FROM actors"):
        gateway = state.gateway(str(row["gateway_id"]))
        gateway.description = str(row["description"]) if row["description"] else None
    return state


def facts_of(episodes: Iterable[Episode]) -> Iterator[EpisodeEvent]:
    """Every event of every episode, in canonical order across all of them."""
    yield from sorted(
        (event for episode in episodes for event in episode.events),
        key=lambda event: event.fact.ordinal,
    )
