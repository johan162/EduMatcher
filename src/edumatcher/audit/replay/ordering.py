"""The canonical order of events, and what proves it complete (section 5.2).

Prose implies sequence. If the sequence is wrong the prose is a lie, and a
plausible one -- so ordering here is a lookup rather than a judgement call.

**Order is ``msg_id``.** The envelope's id is a ULID minted at the publish
site: the first 48 bits are a millisecond timestamp and ``new_ulid`` keeps a
monotonic counter within a millisecond, so ids sort in mint order. The engine
publishes from one thread, so mint order *is* publish order -- across every
topic, not just within one. File order, by contrast, is *receipt* order, and
on a PUB/SUB bus with several publishers receipt order is not causal order: an
``order.ack`` can land after the ``trade.executed`` it logically precedes.

Two consequences worth stating, because both used to need machinery:

* Out-of-order delivery stops mattering. There is no table of protocol-implied
  precedence (a submission before its ack, an ack before its fills) -- that was
  a pile of special cases standing in for a number the engine already knew.
* Engine restarts need no special handling. A ULID's timestamp prefix carries
  ordering across a restart, so nothing partitions by run.

**Completeness is ``seq``.** ``msg_id`` is not dense, so it cannot prove
nothing was lost. The per-topic sequence is dense, so a gap in it *proves*
messages are missing from that topic -- on any topic, not just trades.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable, Iterator

from edumatcher.audit.replay.anomalies import (
    LATE_ARRIVAL,
    SEQ_GAP,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    Anomaly,
)
from edumatcher.audit.replay.facts import Fact
from edumatcher.models.envelope import ulid_millis

#: Design section 5.2.3's default window: whichever bound is reached first.
DEFAULT_MAX_FACTS = 2000
DEFAULT_MAX_SECONDS = 5.0

#: ``(mint_ms, msg_id, receipt_ts, ordinal)``.
SortKey = tuple[int, str, datetime, int]


def mint_millis(fact: Fact) -> int:
    """When the exchange made this message, in epoch milliseconds.

    Read out of the ULID when there is one. A fact with no envelope -- an
    archived line, or a publisher that stamps none -- falls back to the audit
    receipt clock, which is the only clock on every line. The two are not the
    same measurement, and on a mixed archive the tool is only as accurate as
    the gap between minting and recording; that is honest, and better than
    refusing to interleave them at all.
    """
    if fact.msg_id:
        minted = ulid_millis(fact.msg_id)
        if minted is not None:
            return minted
    return int(fact.receipt_ts.timestamp() * 1000)


def sort_key(fact: Fact) -> SortKey:
    """The canonical key of section 5.2.2.

    ``msg_id`` second rather than first so an enveloped and an envelope-less
    fact can be compared at all: they share the millisecond scale, not the id
    space. Within one millisecond, ULIDs order by their monotonic counter,
    which is mint order. ``ordinal`` last makes the sort total and stable --
    ``line_no`` cannot, because it restarts at every rotated file.
    """
    return (mint_millis(fact), fact.msg_id or "", fact.receipt_ts, fact.ordinal)


def in_canonical_order(facts: Iterable[Fact]) -> list[Fact]:
    """Sort a materialised stream. The reference the streaming path must match."""
    return sorted(facts, key=sort_key)


# ---------------------------------------------------------------------------
# The reorder window (design section 5.2.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReorderWindow:
    """Buffers facts briefly and emits them in canonical order.

    The window has two bounds and closes on whichever is reached first: a fact
    count, and a span of *receipt* time. A fact that arrives after its window
    has closed cannot be put back where it belongs without unsaying what has
    already been said, so it is emitted where it landed and tagged ``late``.
    Neither a late fact nor a sequence gap should appear on a healthy system,
    so either is itself a finding.
    """

    max_facts: int = DEFAULT_MAX_FACTS
    max_seconds: float = DEFAULT_MAX_SECONDS

    def __post_init__(self) -> None:
        if self.max_facts < 1:
            raise ValueError("max_facts must be at least 1")
        if self.max_seconds < 0:
            raise ValueError("max_seconds must not be negative")

    def emit(self, facts: Iterable[Fact]) -> Iterator[Fact]:
        # The arrival counter is a tie-break the heap needs, not part of the
        # order: without it two equal keys would make heapq compare the Facts
        # themselves, which are frozen dataclasses and not orderable.
        buffer: list[tuple[SortKey, int, Fact]] = []
        arrivals = 0
        emitted: SortKey | None = None

        for fact in facts:
            key = sort_key(fact)
            if emitted is not None and key < emitted:
                yield _mark_late(fact, key, emitted)
                continue
            arrivals += 1
            heapq.heappush(buffer, (key, arrivals, fact))
            while buffer and self._closed(buffer, fact.receipt_ts):
                emitted, _arrival, ready = heapq.heappop(buffer)
                yield ready

        while buffer:
            _key, _arrival, ready = heapq.heappop(buffer)
            yield ready

    def _closed(self, buffer: list[tuple[SortKey, int, Fact]], now: datetime) -> bool:
        if len(buffer) > self.max_facts:
            return True
        oldest = buffer[0][2].receipt_ts
        return (now - oldest).total_seconds() > self.max_seconds


def _mark_late(fact: Fact, key: SortKey, emitted: SortKey) -> Fact:
    behind = (emitted[0] - key[0]) / 1000
    return replace(
        fact,
        late=True,
        anomalies=fact.anomalies
        + (
            Anomaly(
                code=LATE_ARRIVAL,
                severity=SEVERITY_INFO,
                detail=(
                    f"{fact.kind} arrived after its reorder window closed "
                    f"(minted {behind:.3f}s earlier)"
                ),
                receipt_ts=fact.receipt_raw,
                file=fact.file,
                line_no=fact.line_no,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Completeness (design sections 5.2.3, 12.3)
# ---------------------------------------------------------------------------


def detect_seq_gaps(facts: Iterable[Fact]) -> Iterator[Fact]:
    """Attach ``SEQ_GAP`` where a topic's dense sequence skips.

    Keyed on the wire topic rather than the message kind, because that is what
    ``SequencedPublisher`` counts: ``order.fill.TRADER01`` and
    ``order.fill.MM01`` have independent counters, and merging them would
    manufacture a gap on every message addressed to the other gateway.

    Sequences restart at 1 when a publisher restarts, so a *decrease* is a
    restart rather than a gap -- the counter is per process, and nothing was
    necessarily lost.
    """
    last: dict[str, int] = {}
    for fact in facts:
        seq = fact.topic_seq
        if seq is None:
            yield fact
            continue
        previous = last.get(fact.topic)
        last[fact.topic] = seq
        if previous is None or seq <= previous or fact.late:
            # A late fact's sequence is behind by construction; it has already
            # been reported as LATE_ARRIVAL and is not evidence of loss.
            yield fact
            continue
        missing = seq - previous - 1
        if missing <= 0:
            yield fact
            continue
        yield replace(
            fact,
            anomalies=fact.anomalies
            + (
                Anomaly(
                    code=SEQ_GAP,
                    severity=SEVERITY_ERROR,
                    detail=(
                        f"{fact.topic} seq {previous}->{seq} - "
                        f"{missing} message(s) missing"
                    ),
                    receipt_ts=fact.receipt_raw,
                    file=fact.file,
                    line_no=fact.line_no,
                ),
            ),
        )


def ordered(
    facts: Iterable[Fact],
    *,
    max_facts: int = DEFAULT_MAX_FACTS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> Iterator[Fact]:
    """Canonical order, with late arrivals and sequence gaps reported."""
    window = ReorderWindow(max_facts=max_facts, max_seconds=max_seconds)
    return detect_seq_gaps(window.emit(facts))
