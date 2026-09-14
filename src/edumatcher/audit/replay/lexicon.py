"""Enum constants to business English (design sections 5.3.3, 8.2).

Data, not code, so that someone who knows the domain and not Python can review
it. Every enum value declared anywhere in ``spec/messages/`` has an entry here,
and :mod:`tests.test_audit_replay_lexicon` enumerates the generated registry to
prove it -- the same discipline ``pm-msgen check`` applies to the bindings.

**An unmapped value is never silent and never fatal.** It prints verbatim in
backticks and raises ``UNKNOWN_ENUM``, because the two failure modes that
matter are both worse: a tool that crashes on a value the spec grew last week
is useless exactly when the new value is what you are investigating, and one
that quietly renders an empty string is worse still, since the sentence still
reads like a sentence.

**Entries are glosses, not translations.** ``KILL_SWITCH`` becomes "a kill
switch" rather than "kill switch" because it is written into sentences like
*"cancelled by a kill switch"*; the article belongs to the phrase, not to the
template. Where a value reads naturally on its own -- a side, a status -- the
gloss is bare.

One field name can be declared by more than one family (``status`` by
``order``, ``quote`` and ``structure``), so the maps below are keyed by field
name and merged across families. That is correct only while a shared value
means the same thing everywhere, which today it does: a cancelled order, a
cancelled quote and a cancelled combo are all cancelled. A family that needed
its own reading of a value it shares would need this keyed by family too.
"""

from __future__ import annotations

from typing import Mapping

#: Fill verbs, per section 8.2. Market convention, not a coin toss: a resting
#: **bid** is *hit* (a seller hits it) and a resting **offer** is *lifted* (a
#: buyer lifts it), so the verb for a passive fill depends on the side of the
#: order that was resting. An aggressor *takes*. An uncross has no aggressor at
#: all, so both sides *cross* -- never "took", which would name a taker the
#: engine explicitly says does not exist.
VERB_TOOK = "took"
VERB_HIT = "was hit for"
VERB_LIFTED = "was lifted for"
VERB_CROSSED = "crossed"

#: The preposition that follows each verb, so a template never has to know.
PREP_FROM = "from"
PREP_BY = "by"
PREP_WITH = "with"

_SIDE_BUY = "BUY"


PHRASES: Mapping[str, Mapping[str, str]] = {
    # -- orders ------------------------------------------------------------
    "side": {"BUY": "buy", "SELL": "sell"},
    "imbalance_side": {"BUY": "buy", "SELL": "sell"},
    "order_type": {
        "MARKET": "market",
        "LIMIT": "limit",
        "STOP": "stop",
        "STOP_LIMIT": "stop-limit",
        "FOK": "fill-or-kill",
        "ICEBERG": "iceberg",
        "IOC": "immediate-or-cancel",
        "TRAILING_STOP": "trailing-stop",
    },
    "tif": {
        "DAY": "good for the day",
        "GTC": "good till cancelled",
        "ATO": "at the open",
        "ATC": "at the close",
    },
    "origin": {
        "ORDER": "a direct submission",
        "QUOTE": "a quote leg",
        "IMPLIED": "an implied order",
    },
    "smp_action": {
        "NONE": "no self-match prevention",
        "CANCEL_AGGRESSOR": "cancelling the aggressor",
        "CANCEL_RESTING": "cancelling the resting order",
        "CANCEL_BOTH": "cancelling both sides",
    },
    "combo_type": {"AON": "all-or-none"},
    "liquidity_flag": {"MAKER": "resting", "TAKER": "aggressing"},
    "aggressor_side": {
        "BUY": "the buyer",
        "SELL": "the seller",
        # Not a side. An uncross has no aggressor, and section 7.4 is explicit
        # that this must never be narrated as one.
        "AUCTION": "nobody -- both sides rested",
    },
    # One map across order, quote and structure. A cancelled order, a
    # cancelled quote and a cancelled combo are all cancelled.
    "status": {
        "NEW": "new",
        "PARTIAL": "partially filled",
        "FILLED": "filled",
        "CANCELLED": "cancelled",
        "REJECTED": "rejected",
        "EXPIRED": "expired",
        "ACTIVE": "active",
        "INACTIVE_BID_FILLED": "inactive, its bid leg filled",
        "INACTIVE_ASK_FILLED": "inactive, its ask leg filled",
        "PENDING": "pending",
        "PARTIALLY_MATCHED": "partially matched",
        "MATCHED": "matched",
        "FAILED": "failed",
    },
    "cancel_reason": {
        "SELF_MATCH_PREVENTED": "self-match prevention",
        "INSUFFICIENT_LIQUIDITY": "insufficient liquidity",
        "KILL_SWITCH": "a kill switch",
        "CIRCUIT_BREAKER_HALT": "a circuit-breaker halt",
        "GATEWAY_DISCONNECT": "its gateway disconnecting",
        "ADMIN_CANCEL_SYMBOL": "an admin cancel-symbol command",
        "QUOTE_REPLACED": "its quote being replaced",
        "QUOTE_LEG_FILLED": "the other leg of its quote filling",
    },
    "reject_code": {
        "UNKNOWN": "an unspecified reason",
        "AUTH_REQUIRED": "the gateway not being authenticated",
        "AUTH_FAILED": "failed authentication",
        "ROLE_DENIED": "the gateway's role not permitting it",
        "NOT_OWNER": "the gateway not owning that order",
        "GATEWAY_NOT_CONFIGURED": "the gateway not being configured",
        "RATE_LIMITED": "rate limiting",
        "MALFORMED_MESSAGE": "a malformed message",
        "MISSING_FIELD": "a missing field",
        "UNSUPPORTED_FIELD": "an unsupported field",
        "INVALID_VALUE": "an invalid value",
        "UNKNOWN_SYMBOL": "an unknown symbol",
        "SYMBOL_NOT_READY": "the symbol not being ready to trade",
        "INSTRUMENT_HALTED": "the instrument being halted",
        "CIRCUIT_BREAKER_ACTIVE": "an active circuit breaker",
        "MARKET_CLOSED": "the market being closed",
        "SESSION_NOT_PERMITTED": "the order type not being permitted "
        "in this session",
        "KILL_SWITCH_ACTIVE": "an active kill switch",
        "TICK_VIOLATION": "a price off the tick grid",
        "LOT_VIOLATION": "a quantity off the lot size",
        "PRICE_OUT_OF_RANGE": "a price out of range",
        "QTY_OUT_OF_RANGE": "a quantity out of range",
        "COLLAR_BREACH": "a price outside the collar",
        "MAX_ORDER_QTY": "exceeding the maximum order quantity",
        "MAX_ORDER_VALUE": "exceeding the maximum order value",
        "POSITION_LIMIT": "a position limit",
        "DUPLICATE_ORDER": "a duplicate order id",
        "ORDER_NOT_FOUND": "no such order",
        "ORDER_ALREADY_TERMINAL": "the order having already ended",
        "AMEND_NOT_PERMITTED": "the amendment not being permitted",
        "SELF_MATCH_PREVENTED": "self-match prevention",
        "INSUFFICIENT_LIQUIDITY": "insufficient liquidity",
        "INTERNAL_ERROR": "an internal error",
    },
    # -- market structure --------------------------------------------------
    "halt_source": {"CB": "the circuit breaker", "ADMIN": "an admin halt"},
    "phase": {
        "OPENING_AUCTION": "the opening auction",
        "CLOSING_AUCTION": "the closing auction",
    },
    # `auction.result.reason`: why the uncross ran.
    "reason": {
        "SCHEDULED": "on schedule",
        "ADMIN_MANUAL": "on an admin instruction",
        "REOPEN": "to reopen a halted instrument",
        "BACKSTOP": "as a backstop",
        "RECOVERY": "during recovery",
    },
    # -- commands ----------------------------------------------------------
    # `admin.action` and `index.corp_action` share a field name and nothing
    # else; their value sets are disjoint, which is what makes one map safe.
    "action": {
        "kill_switch.self": "a self kill switch",
        "kill_switch.symbol": "a symbol kill switch",
        "kill_switch.gateway": "a gateway kill switch",
        "kill_switch.global": "a global kill switch",
        "circuit_breaker.trigger": "a circuit-breaker trigger",
        "circuit_breaker.resume": "a circuit-breaker resume",
        "auction.reopen": "an auction reopen",
        "SPLIT": "a share split",
        "CASH_DIVIDEND": "a cash dividend",
        "SHARES_ISSUANCE": "a share issuance",
    },
    "change_type": {"ADD": "added to", "DELIST": "delisted from"},
    # -- recovery and diagnostics ------------------------------------------
    "kind": {"ORDER": "order", "COMBO": "combo"},
    # Each gloss carries its own verb: "failed to restore" and "was restored"
    # cannot share one, and a template that tried would have to branch.
    "outcome": {
        "RESTORED": "was restored",
        "DISCARDED_STALE_DAY": "was discarded as a stale day order",
        "FAILED": "failed to restore",
        "QUOTE_REMNANT": "was restored as a quote remnant",
    },
    "component": {
        "UNROUTED_TOPIC": "a topic nothing routes",
        "UNDECODABLE_MESSAGE": "a message that could not be decoded",
        "DISPATCH_ERROR": "an error while dispatching",
        "MAINTENANCE_FLUSH": "a maintenance flush",
    },
    # -- query and subscription surfaces -----------------------------------
    "event_type": {"order.fill": "a fill"},
    "mode": {"STREAM": "streaming", "NOTIFY": "notify-only"},
    "state": {"UP": "up", "DOWN": "down"},
    "show": {"ACTIVE": "active only", "RECENT": "recent", "ALL": "all"},
    "show_requested": {"ACTIVE": "active only", "RECENT": "recent", "ALL": "all"},
}


def is_known(field: str, value: str) -> bool:
    """Whether the vocabulary has a gloss for this value."""
    return value in PHRASES.get(field, {})


def phrase(field: str, value: str) -> str:
    """The business-English gloss, or the value verbatim in backticks.

    Backticks rather than a bare value so a reader can see at a glance that
    the tool is quoting the wire rather than speaking. The caller raises
    ``UNKNOWN_ENUM`` beside it -- see :func:`is_known`; keeping the anomaly out
    of here lets a caller that already knows the value is fine skip the check.
    """
    known = PHRASES.get(field, {}).get(value)
    return known if known is not None else f"`{value}`"


def fill_verb(role: str | None, side: str | None, uncrossed: bool) -> tuple[str, str]:
    """The verb and preposition for one fill (section 8.2).

    Returns ``(verb, preposition)`` so a template never has to agree them.

    An uncross is checked first and wins: the engine flags **both** sides of an
    auction print MAKER, because neither equals an ``aggressor_side`` of
    ``AUCTION``, so a rule that read the role alone would narrate an uncross as
    a passive fill and imply an aggressor on the other side of it.
    """
    if uncrossed:
        return VERB_CROSSED, PREP_WITH
    if role == "TAKER":
        return VERB_TOOK, PREP_FROM
    if role == "MAKER":
        return (VERB_HIT if side == _SIDE_BUY else VERB_LIFTED), PREP_BY
    return VERB_CROSSED, PREP_WITH
