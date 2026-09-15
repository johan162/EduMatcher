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

#: ``(mint_ms, receipt_ts, ordinal)``.
SortKey = tuple[int, datetime, int]


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

    The ULID's **millisecond** is the ordering signal and its remaining 80
    bits are not. This key used to sort on the whole ``msg_id`` second, on the
    reasoning that "within one millisecond, ULIDs order by their monotonic
    counter, which is mint order". That is true only within one *process*: a
    publisher's own ids do advance by one, but two processes minting in the
    same millisecond produce tails that sort at random relative to each other
    -- and an order's envelope is minted by the submitting gateway while its
    ack is minted by the engine.

    The effect was not subtle. On a real run the ack sorted *before* the
    ``order.new`` it cites, which split the order across two episodes, made
    the ack's ``causation_id`` point at a message the resolver had not read
    yet, and reported both as findings. Every hand-written fixture was
    authored with ascending ids, so none of it showed.

    So: millisecond, then receipt, then read order. ``ordinal`` is the
    position ``pm-audit`` wrote the line at, and ``pm-audit`` receives on one
    socket in one thread -- so within a millisecond it *is* the order the
    exchange published in, which is the strongest signal available and the one
    the ULID tail was standing in for. ``line_no`` cannot serve, because it
    restarts at every rotated file.
    """
    return (mint_millis(fact), fact.receipt_ts, fact.ordinal)


def in_canonical_order(facts: Iterable[Fact]) -> list[Fact]:
    """Sort a materialised stream. The reference the streaming path must match."""
    return sorted(facts, key=sort_key)


#: Widths that make the packed key sort lexicographically the way the tuple
#: sorts numerically. 13 digits of epoch milliseconds runs to the year 2286;
#: 12 of ordinal to a trillion lines in one window.
_MILLIS_WIDTH = 13
_ORDINAL_WIDTH = 12


def pack_sort_key(fact: Fact) -> str:
    """The canonical key as one lexicographically sortable string.

    What ``episodes.opened_sort_key`` stores (design section 6.2). A tuple
    cannot be a SQLite column and three columns cannot be one index, so the
    ordering has to survive being flattened: each numeric field is
    zero-padded to a fixed width, and the separator is below every character
    that can appear in a field so a short value never sorts after a longer one
    that starts the same way.

    Changing this packing changes what a stored index means, so it is one of
    the three things section 6.2 says must bump ``rules_version``.
    """
    millis, receipt, ordinal = sort_key(fact)
    return (
        f"{millis:0{_MILLIS_WIDTH}d}"
        f"\x1f{receipt.isoformat(timespec='microseconds')}"
        f"\x1f{ordinal:0{_ORDINAL_WIDTH}d}"
    )


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
        if previous is None or seq <= previous or fact.late:
            # A late fact's sequence is behind by construction; it has already
            # been reported as LATE_ARRIVAL and is not evidence of loss.
            #
            # Its sequence must not become the high-water mark either. Writing
            # it back unconditionally let the counter *regress*, so the next
            # healthy fact was measured against a number already emitted and
            # reported as loss: seqs 1,3,4,2(late),5 produced a SEQ_GAP for
            # "2 -> 4" one line after 2 had gone past. SEQ_GAP is the tool's
            # only proof of loss, so a false one is expensive.
            #
            # A decrease that is NOT late still resets, which is the deliberate
            # restart rule documented above.
            if previous is None or (seq < previous and not fact.late):
                last[fact.topic] = seq
            yield fact
            continue
        last[fact.topic] = seq
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
