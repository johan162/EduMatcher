"""Findings the reconstruction notices, and the codes it reports them under.

An anomaly is not an error in the tool; it is the tool saying what it could not
reconcile. Design section 12 catalogues the codes. Only the ones the Fact layer
and the ordering layer can raise exist here so far -- the rest arrive with the
passes that can detect them.

The severities are the three of section 12: ``info`` for something expected at
a window edge, ``warn`` for something a reader should look at, ``error`` for a
broken invariant.
"""

from __future__ import annotations

from dataclasses import dataclass

SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_ERROR = "error"

#: A topic with no entry in the generated registry: the message spec has grown
#: and the tool has not. Section 12.5.
UNKNOWN_TOPIC = "UNKNOWN_TOPIC"

#: A tick-scaled price with no ``tick_decimals`` for its symbol anywhere in the
#: window. The price is reported raw, in ticks, and explicitly *not* converted:
#: a tool that silently guesses a price scale is worse than one that stops.
#: Section 5.3.1, rung 5.
TICK_SCALE_UNKNOWN = "TICK_SCALE_UNKNOWN"

#: A gap in a topic's per-topic ``seq``: messages are missing from the audit
#: trail for that topic. Dense by construction, so this is a proof of loss
#: rather than a suspicion. Section 12.3.
SEQ_GAP = "SEQ_GAP"

#: A fact that arrived after its reorder window had closed. Section 12.3.
LATE_ARRIVAL = "LATE_ARRIVAL"


@dataclass(frozen=True, slots=True)
class Anomaly:
    """One finding, anchored to the line that produced it.

    ``file``/``line_no`` rather than an episode id: at this stage there are no
    episodes yet, and a finding a reader cannot go and look at is a finding
    they cannot act on.
    """

    code: str
    severity: str
    detail: str
    receipt_ts: str = ""
    file: str | None = None
    line_no: int = 0

    def __str__(self) -> str:
        where = f" [{self.file}:{self.line_no}]" if self.file else ""
        return f"{self.severity.upper()} {self.code}: {self.detail}{where}"
