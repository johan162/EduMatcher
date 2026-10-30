"""The canonical order of events, and what proves it complete (section 5.2).

Prose implies sequence. If the sequence is wrong the prose is a lie, and a
plausible one -- so ordering here is a lookup rather than a judgement call.

**Order is ``eseq`` within a publisher run.** ``eseq`` is the socket-wide
counter stamped by the engine's ``SequencedPublisher``. Unlike ``msg_id``, it
describes the order the engine actually published messages: an inbound
gateway envelope is deliberately preserved when the engine republishes it,
so its ULID timestamp can predate messages published earlier by the engine.
``system.startup`` marks the reset boundary. Older logs without ``eseq`` use
the ULID millisecond, receipt time, and stream ordinal fallback.

**Completeness is ``seq`` and ``eseq``.** The per-topic sequence localises
loss; the socket-wide sequence also catches loss when the missing message was
the last on its topic.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable, Iterator

from edumatcher.audit.replay.anomalies import (
    ESEQ_DISCONTINUITY,
    ESEQ_GAP,
    LATE_ARRIVAL,
    SEQ_GAP,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    Anomaly,
)
from edumatcher.audit.replay.facts import Fact
from edumatcher.models.envelope import ulid_millis
from edumatcher.models.generated.system import TOPIC_STARTUP

#: Design section 5.2.3's default window: whichever bound is reached first.
DEFAULT_MAX_FACTS = 2000
DEFAULT_MAX_SECONDS = 5.0

#: ``(publisher_run, sequence_mode, sequence_or_mint_ms, receipt_ts, ordinal)``.
SortKey = tuple[int, int, int, datetime, int]


def mint_millis(fact: Fact) -> int:
    """A legacy ordering timestamp in epoch milliseconds.

    Older audit lines have no socket-wide ``eseq``. In those, the ULID time is
    the best available ordering hint; a line without an envelope falls back
    to the audit receipt clock. Neither fallback is as authoritative as the
    engine's publisher sequence.
    """
    if fact.msg_id:
        minted = ulid_millis(fact.msg_id)
        if minted is not None:
            return minted
    return int(fact.receipt_ts.timestamp() * 1000)


def sort_key(fact: Fact) -> SortKey:
    """The canonical key of section 5.2.2.

    A current audit line's ``eseq`` is the engine socket's total publication
    order. It takes precedence over the ULID timestamp, which can belong to
    the gateway that originally minted a preserved envelope. The run number
    is assigned at ``system.startup`` because ``eseq`` resets there. Older
    lines fall back to ULID milliseconds, receipt time, and stream ordinal.
    """
    if fact.eseq is not None:
        return (fact.publisher_run, 0, fact.eseq, fact.receipt_ts, fact.ordinal)
    return (
        fact.publisher_run,
        1,
        mint_millis(fact),
        fact.receipt_ts,
        fact.ordinal,
    )


def in_canonical_order(facts: Iterable[Fact]) -> list[Fact]:
    """Sort a materialised stream. The reference the streaming path must match."""
    return sorted(facts, key=sort_key)


#: Widths that make the packed key sort lexicographically the way the tuple
#: sorts numerically.
_RUN_WIDTH = 12
_MILLIS_WIDTH = 13
_SEQUENCE_WIDTH = 20
_ORDINAL_WIDTH = 12


def pack_sort_key(fact: Fact) -> str:
    """The canonical key as one lexicographically sortable string.

    What ``episodes.opened_sort_key`` stores (design section 6.2). A tuple
    cannot be a SQLite column, so the ordering has to survive being flattened:
    each numeric field is
    zero-padded to a fixed width, and the separator is below every character
    that can appear in a field so a short value never sorts after a longer one
    that starts the same way.

    Changing this packing changes what a stored index means, so it is one of
    the three things section 6.2 says must bump ``rules_version``.
    """
    return pack_sort_key_tuple(sort_key(fact))


def pack_sort_key_tuple(key: SortKey) -> str:
    """Pack a stored episode-boundary key using the same ordering as facts."""
    run, mode, value, receipt, ordinal = key
    width = _SEQUENCE_WIDTH if mode == 0 else _MILLIS_WIDTH
    return (
        f"{run:0{_RUN_WIDTH}d}\x1f{mode}\x1f{value:0{width}d}"
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
    if key[0] != emitted[0]:
        detail = f"publisher run {key[0]} arrived after run {emitted[0]} was emitted"
    elif key[1] == emitted[1] == 0:
        detail = f"engine eseq {key[2]} arrived after eseq {emitted[2]} was emitted"
    elif key[1] == emitted[1] == 1:
        behind = (emitted[2] - key[2]) / 1000
        detail = f"minted {behind:.3f}s earlier"
    else:
        detail = "publisher sequence metadata changed within the run"
    return replace(
        fact,
        late=True,
        anomalies=fact.anomalies
        + (
            Anomaly(
                code=LATE_ARRIVAL,
                severity=SEVERITY_INFO,
                detail=f"{fact.kind} arrived after its reorder window closed ({detail})",
                receipt_ts=fact.receipt_raw,
                file=fact.file,
                line_no=fact.line_no,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Completeness (design sections 5.2.3, 12.3)
# ---------------------------------------------------------------------------


def detect_eseq_gaps(facts: Iterable[Fact]) -> Iterator[Fact]:
    """Attach publisher-sequence findings in audit receipt order.

    Unlike ``seq``, ``eseq`` counts every message on the engine's PUB socket,
    which pm-audit subscribes to without filtering. It must therefore be
    checked before the reorder window changes stream order. The first observed
    value is only a baseline unless the audit contains ``system.startup``.
    """
    last: int | None = None
    for fact in facts:
        if fact.topic == TOPIC_STARTUP and fact.topic_seq == 1:
            last = 0
        sequence = fact.eseq
        if sequence is None:
            last = None
            yield fact
            continue
        if last is None:
            last = sequence
            yield fact
            continue
        if sequence > last + 1:
            missing = sequence - last - 1
            anomaly = Anomaly(
                code=ESEQ_GAP,
                severity=SEVERITY_ERROR,
                detail=(
                    f"engine eseq {last}->{sequence} - " f"{missing} message(s) missing"
                ),
                receipt_ts=fact.receipt_raw,
                file=fact.file,
                line_no=fact.line_no,
            )
            fact = replace(fact, anomalies=fact.anomalies + (anomaly,))
        elif sequence <= last:
            anomaly = Anomaly(
                code=ESEQ_DISCONTINUITY,
                severity=SEVERITY_ERROR,
                detail=f"engine eseq {last}->{sequence} repeated or decreased",
                receipt_ts=fact.receipt_raw,
                file=fact.file,
                line_no=fact.line_no,
            )
            fact = replace(fact, anomalies=fact.anomalies + (anomaly,))
        last = sequence
        yield fact


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
    """Canonical order, with publisher/topic gaps and late arrivals reported."""
    facts = detect_eseq_gaps(facts)
    window = ReorderWindow(max_facts=max_facts, max_seconds=max_seconds)
    return detect_seq_gaps(window.emit(facts))
