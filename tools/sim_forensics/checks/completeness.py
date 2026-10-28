"""A5 — the audit trail is complete.

Every line pm-audit writes comes from the engine's one PUB socket, whose
``SequencedPublisher`` numbers each topic 1, 2, 3 … from the engine's start
(``messaging/bus.py``). ZMQ drops silently once pm-audit's SUB falls behind
its high-water mark, and a lost or deleted audit file leaves no trace
either: a hole in a topic's sequence is the only evidence. Every other check
that reads the audit assumes there is none.

The engine's first message on every start is ``system.startup`` with
seq 1; there all topics start again at 1. An audit that begins after
the engine's start cannot say where each topic began, so a topic's first
line then only sets the baseline.

Each line also carries the socket-wide ``eseq``: one count over every
message, so it must run 1, 2, 3 … from the start without a hole -- a
check that does not depend on how messages spread over topics.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sim_forensics.audit import STARTUP, audit_files, lines
from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Sample, Skipped, check

_KEEP = 50


@dataclass
class _Pass:
    samples: list[Sample] = field(default_factory=list)
    errors: Counter[str] = field(default_factory=Counter)
    #: Last seq seen per topic since the engine's last start.
    last: dict[str, int] = field(default_factory=dict)
    lines = 0
    starts = 0
    missing = 0
    #: Last eseq since the engine's last start (None: not yet known).
    eseq: int | None = None
    #: Whether the audit holds the start of the engine run being read.
    from_start = False

    def flag(self, error: str, **keys: Any) -> None:
        self.errors[error] += 1
        if len(self.samples) < _KEEP:
            self.samples.append({"error": error, **keys})

    def line(self, topic: str, seq: int | None, eseq: int | None, ts: str) -> None:
        self.lines += 1
        if seq is None:
            self.flag("line without seq", topic=topic, ts=ts)
            return
        if topic == STARTUP and seq == 1:
            self.last.clear()
            self.starts += 1
            self.from_start = True
            self.eseq = 0
        if eseq is not None:
            if self.eseq is not None and eseq != self.eseq + 1:
                self.flag("eseq gap", topic=topic, after=self.eseq, got=eseq, ts=ts)  # fmt: skip
            self.eseq = eseq
        prev = self.last.get(topic)
        if prev is None:
            prev = 0 if self.from_start else seq - 1
        if seq > prev + 1:
            self.missing += seq - prev - 1
            self.flag("gap", topic=topic, after=prev, got=seq, missing=seq - prev - 1, ts=ts)  # fmt: skip
        elif seq <= prev:
            self.flag("repeat or out of order", topic=topic, after=prev, got=seq, ts=ts)  # fmt: skip
        self.last[topic] = max(seq, prev)


@check(
    "A5",
    "conservation",
    "The audit is complete: each topic's seq runs without gap or repeat per engine start",
    needs=(),
)
def audit_is_complete(ds: Dataset) -> Outcome:
    files = audit_files(ds.data_dir)
    if not files:
        raise Skipped("no audit.log in the data dir")
    p = _Pass()
    for ln in lines(files):
        p.line(ln.topic, ln.seq, ln.eseq, ln.ts)
    note = (
        f"{p.lines} lines in {len(files)} files, {len(p.last)} topics, "
        f"{p.starts} engine start(s) in the audit, {p.missing} messages missing"
    )
    if not p.from_start:
        note += "; the audit begins after the engine's start: first seq per topic not checked"  # fmt: skip
    note += "".join(f"; {e}: {n}" for e, n in p.errors.most_common())
    return Outcome(sum(p.errors.values()), p.samples, note)
