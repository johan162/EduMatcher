"""Which lane each replay finding belongs to (design §4.1).

Findings keep the replay's own codes and severities; the lane says what a
reviewer should infer, so a broken trade leg and a recorder gap are never
mixed into one list:

``evidence``
    The trail itself is incomplete or unreadable here: loss, restarts,
    missing envelopes or configuration, unknown vocabulary. Some conclusions
    may be unsupported; investigate capture first.
``consistency``
    Recorded facts disagree with an exchange invariant (lifecycle,
    conservation, causal chain, print versus legs versus drop copies). Read
    with the evidence lane: an absent message inside a proven gap is not an
    engine defect, and the window-edge codes (``TERMINAL_MISSING``,
    ``ACK_MISSING``) keep their ``info``/``warn`` severity.
``operations``
    Something a participant, the configuration or the infrastructure did:
    engine restarts, clocks, unacknowledged commands, a halt still in force.
``behaviour``
    R2 detector candidates. Not available in this release; it never holds a
    replay code.

Every code in :mod:`edumatcher.audit.replay.anomalies` must have a lane: the
tests fail when one is added without it.
"""

from __future__ import annotations

from types import MappingProxyType

from edumatcher.audit.replay import anomalies as a

EVIDENCE = "evidence"
CONSISTENCY = "consistency"
OPERATIONS = "operations"
BEHAVIOUR = "behaviour"

#: The lanes in the order a reviewer reads them.
LANES = (EVIDENCE, CONSISTENCY, OPERATIONS, BEHAVIOUR)

_LANE: dict[str, str] = {
    **dict.fromkeys(
        (
            a.UNKNOWN_TOPIC,
            a.TICK_SCALE_UNKNOWN,
            a.UNKNOWN_ENUM,
            a.SEQ_GAP,
            a.ESEQ_GAP,
            a.ESEQ_DISCONTINUITY,
            a.LATE_ARRIVAL,
            a.RECORDER_RESTART,
            a.CONFIG_NOT_RECORDED,
            a.ENVELOPE_MISSING,
            a.CAUSE_NOT_FOUND,
            a.ORPHAN_EVENT,
            a.PARSE_FAILURE,
            a.DROP_COPY_SEQ_GAP,
            a.ARRIVAL_SEQ_GAP,
            a.TRADE_COUNTER_GAP,
            a.RESUME_WITHOUT_HALT,
        ),
        EVIDENCE,
    ),
    **dict.fromkeys(
        (
            a.ILLEGAL_STATUS_TRANSITION,
            a.FILL_AFTER_TERMINAL,
            a.ACK_DUPLICATE,
            a.QTY_MISMATCH,
            a.REMAINING_NOT_MONOTONIC,
            a.CHAIN_BROKEN,
            a.MSG_ID_DUPLICATE,
            a.EFFECT_COUNT_MISMATCH,
            a.ACK_WITHOUT_COMMAND,
            a.ACK_MISSING,
            a.FILL_BEFORE_ACK,
            a.TERMINAL_MISSING,
            a.CANCEL_UNSOLICITED,
            a.CANCEL_UNMATCHED,
            a.TRADE_LEG_MISSING,
            a.FILL_WITHOUT_TRADE,
            a.LEG_QTY_DISAGREE,
            a.LEG_PRICE_DISAGREE,
            a.PRICE_THROUGH_LIMIT,
            a.PRICE_OUTSIDE_CORRIDOR,
            a.PRINT_QTY_DISAGREE,
            a.PRINT_PRICE_DISAGREE,
            a.TRADE_LEG_UNKNOWN,
            a.FILL_STATUS_DISAGREE,
            a.LIQUIDITY_FLAG_DISAGREE,
            a.DROP_COPY_DISAGREE,
            a.DROP_COPY_MISSING,
            a.ARRIVAL_SEQ_REUSED,
        ),
        CONSISTENCY,
    ),
    **dict.fromkeys(
        (
            a.RUN_SEQ_CHANGE,
            a.CLOCK_SKEW,
            a.CLIENT_CLOCK_ABSURD,
            a.COMMAND_UNACKED,
            a.HALT_UNRESUMED,
        ),
        OPERATIONS,
    ),
}


#: Replay finding code -> its lane.
CODE_LANES = MappingProxyType(_LANE)


def lane_of(code: str) -> str:
    """The lane of replay finding *code*. An unknown code (a newer replay
    than this mapping) is evidence: the tool could not place it."""
    return _LANE.get(code, EVIDENCE)
