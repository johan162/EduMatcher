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

#: An enum value with no lexicon entry: the message spec has grown a value and
#: the vocabulary has not. The value prints verbatim in backticks rather than
#: being guessed at or dropped. Section 12.5.
UNKNOWN_ENUM = "UNKNOWN_ENUM"

#: A gap in a topic's per-topic ``seq``: messages are missing from the audit
#: trail for that topic. Dense by construction, so this is a proof of loss
#: rather than a suspicion. Section 12.3.
SEQ_GAP = "SEQ_GAP"

#: A fact that arrived after its reorder window had closed. Section 12.3.
LATE_ARRIVAL = "LATE_ARRIVAL"

# -- Lifecycle, from the state model (section 12.1, 12.2) -------------------

#: A status change outside ``NEW -> PARTIAL -> FILLED | CANCELLED | REJECTED |
#: EXPIRED``. Recorded and then applied: refusing the step would leave the
#: model describing a world the log does not.
ILLEGAL_STATUS_TRANSITION = "ILLEGAL_STATUS_TRANSITION"

#: A fill for an order the trail has already ended.
FILL_AFTER_TERMINAL = "FILL_AFTER_TERMINAL"

#: Two acks for one ``order_id``.
ACK_DUPLICATE = "ACK_DUPLICATE"

#: ``sum(fill_qty) != quantity - remaining_qty``. The tool's own tally against
#: the engine's, which is why the model keeps both.
QTY_MISMATCH = "QTY_MISMATCH"

#: ``remaining_qty`` rose across fills of one order.
REMAINING_NOT_MONOTONIC = "REMAINING_NOT_MONOTONIC"

#: An engine restart observed mid-window. Not a fault -- but ``arrival_seq``
#: and the trade counter restart with it, so nothing may be compared across
#: the boundary (section 5.1.3).
RUN_SEQ_CHANGE = "RUN_SEQ_CHANGE"

#: A resume for a symbol with no halt on record. Section 12.4.
RESUME_WITHOUT_HALT = "RESUME_WITHOUT_HALT"

# -- Causality, from the link resolver (sections 12.3, 12.4) ----------------

#: A ``causation_id`` naming a ``msg_id`` that is nowhere in the window.
#: Usually the window starts too late; occasionally a dropped message.
CAUSE_NOT_FOUND = "CAUSE_NOT_FOUND"

#: An effect whose ``correlation_id`` differs from its cause's. The chain is
#: propagated by ``Envelope.caused()``, so a break means something built an
#: envelope by hand -- the exact mistake wrapping the publisher was meant to
#: make impossible.
CHAIN_BROKEN = "CHAIN_BROKEN"

#: Two messages with the same ``msg_id``. Should be impossible; would mean a
#: ULID generator was shared unsafely across threads.
MSG_ID_DUPLICATE = "MSG_ID_DUPLICATE"

#: An engine-published message carrying no envelope. Expected on archived
#: lines; on a current log it means a publisher is bypassing
#: ``CausalPublisher``.
ENVELOPE_MISSING = "ENVELOPE_MISSING"

#: A fact the resolver could not attach to anything. The tool's failure to
#: explain something is information the reader needs, so it is counted rather
#: than swallowed.
ORPHAN_EVENT = "ORPHAN_EVENT"

#: An ack's list of affected entities disagrees with what was observed. Since
#: AR-0.5 the acks name the ids, so this reports *which* are missing rather
#: than only how many.
EFFECT_COUNT_MISMATCH = "EFFECT_COUNT_MISMATCH"

#: An ack whose ``command_id`` matches no request in the window.
ACK_WITHOUT_COMMAND = "ACK_WITHOUT_COMMAND"


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
