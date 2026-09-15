"""The sentences, as data (design section 8.2).

One module, one template per ``(fact kind, detail level)``, and nothing
anywhere else in the codebase concatenates prose. That is what keeps the output
reviewable by someone who knows the market and not this code, and what makes a
house-style change a single-file edit rather than a grep.

A template is a ``str.format`` string over slots the renderer fills. It may not
contain logic: every choice -- which verb, whether a clause appears at all --
is made by the renderer and arrives as a slot, so that a reader of this file
sees the shape of every sentence the tool can produce.

**Absence is a slot, not a missing template.** A market order has no price, so
``{at_price}`` is filled with the empty string rather than the template
branching. This is why so many slots are clauses with their own leading space:
the alternative is a sentence with a hole in the middle of it.

Levels are those of section 8.1. Level 0 is not here -- it narrates whole
episodes rather than facts, and its sentences are :data:`SUMMARIES`.
"""

from __future__ import annotations

from typing import Mapping

from edumatcher.audit.replay import kinds

#: Detail levels this module covers (section 8.1). :data:`MIN_LEVEL` is what
#: holds a kind back, so a fact belonging to a higher level is *withheld*,
#: never dropped -- the distinction the round-trip property of AR-4.5 rests
#: on, and which at :data:`LEVEL_RAW` has nothing left to hold.
LEVEL_OUTCOMES = 0
LEVEL_DEFAULT = 1
LEVEL_DETAIL = 2
LEVEL_MARKET = 3
LEVEL_RAW = 4

#: The level at which a fact kind starts being narrated. Anything not listed
#: is narrated from level 1. Market data is the bulk of a real log and is
#: context rather than event, so it waits for ``-vv``.
#:
#: ``book`` and ``depth`` are spelled as literals here and not as
#: ``kinds.BOOK``/``kinds.DEPTH``; they are pre-existing and equal in value,
#: so they are left alone rather than tidied.
#:
#: Keyed by :mod:`~edumatcher.audit.replay.kinds`, never by a literal. A topic
#: spelled out here would keep compiling after a publisher-side rename and
#: quietly narrate nothing -- the exact failure ``pm-msgen``'s literal gate
#: exists to prevent, and which it caught in this file.
MIN_LEVEL: Mapping[str, int] = {
    "book": 3,
    "depth": 3,
    kinds.INDEX_UPDATE: 3,
    kinds.DROP_COPY_EVENT: 3,
    kinds.DROP_COPY_REPLAY: 3,
    kinds.AUCTION_INDICATIVE: 3,
    kinds.SYSTEM_SYMBOLS: 3,
    kinds.SYSTEM_REFERENCE: 3,
    kinds.ORDER_ORDERS: 3,
    kinds.SYSTEM_GATEWAYS: 3,
    kinds.SYSTEM_VOLUME: 3,
    kinds.SYSTEM_POSITION_SNAPSHOT: 3,
    kinds.SYSTEM_QUOTE_BOOTSTRAP: 3,
    kinds.SYSTEM_QUOTE_LEGS: 3,
    kinds.SYSTEM_HALT_STATUS: 3,
    kinds.SYSTEM_RISK_STATE: 3,
    kinds.SYSTEM_SESSION_SCHEDULE: 3,
    kinds.SYSTEM_SESSION_STATUS: 3,
    kinds.INDEX_HISTORY: 3,
}

#: ``{kind: {level: sentence}}``. A kind with a level-2 entry uses it at 2 and
#: above; one without falls back to its level-1 sentence, because most lines
#: are already as detailed as they need to be and repeating them here would
#: invite the two copies to drift.
TEMPLATES: Mapping[str, Mapping[int, str]] = {
    # -- the order lifecycle ----------------------------------------------
    kinds.ORDER_NEW: {
        1: "{actor} submitted {side} {order_type} {qty} {symbol}"
        "{at_price}{tif_clause} — order {ref}",
        2: "{actor} submitted {side} {order_type} {qty} {symbol}"
        "{at_price}{tif_clause} — order {ref}{origin_clause}",
    },
    kinds.ORDER_ACK: {1: "Engine {verdict} {ref}{reject_clause}"},
    kinds.ORDER_FILL: {
        1: "{ref} {verb} {fill_qty} @ {fill_price} {prep} {counterparty}",
        2: "{ref} {verb} {fill_qty} @ {fill_price} {prep} {counterparty}"
        "{progress_clause}",
    },
    kinds.ORDER_CANCELLED: {1: "{ref} was cancelled{because_clause}"},
    kinds.ORDER_CANCEL: {1: "{actor} asked to cancel {ref}"},
    kinds.ORDER_AMEND: {1: "{actor} asked to amend {ref}"},
    kinds.ORDER_AMENDED: {1: "{ref} was amended{amend_clause}"},
    kinds.ORDER_EXPIRED: {1: "{ref} expired"},
    kinds.TRADE_EXECUTED: {
        1: "{symbol} traded {qty} @ {price} — {sides_clause} (trade {ref})",
        2: "{symbol} traded {qty} @ {price} — {sides_clause} (trade {ref})"
        "{notional_clause}",
    },
    # -- structures --------------------------------------------------------
    kinds.QUOTE_NEW: {
        1: "{actor} quoted {symbol} {bid_qty} @ {bid_price} / "
        "{ask_qty} @ {ask_price} — quote {ref}"
    },
    kinds.QUOTE_ACK: {1: "Engine {verdict} quote {ref}{legs_clause}"},
    kinds.QUOTE_STATUS: {1: "Quote {ref} is {status}{because_clause}"},
    kinds.ORDER_OCO: {
        1: "{actor} submitted a one-cancels-other pair on {symbol} — OCO {ref}"
    },
    kinds.QUOTE_CANCEL: {1: "{actor} asked to cancel quote {ref}"},
    kinds.OCO_ACK: {1: "Engine {verdict} OCO {ref}{legs_clause}"},
    kinds.OCO_CANCELLED: {
        1: "OCO {ref} pulled its remaining leg {leg_ref}{because_clause}"
    },
    kinds.ORDER_OCO_CANCEL: {1: "{actor} asked to cancel OCO {ref}"},
    kinds.ORDER_COMBO: {
        1: "{actor} submitted {combo_article} {combo_type} combo — combo {ref}"
    },
    kinds.COMBO_ACK: {1: "Engine {verdict} combo {ref}{because_clause}"},
    kinds.COMBO_STATUS: {1: "Combo {ref} is {status}{because_clause}"},
    kinds.ORDER_COMBO_CANCEL: {1: "{actor} asked to cancel combo {ref}"},
    # -- the market ---------------------------------------------------------
    # Level 3 (``-vv``) and above. These are the bulk of a real log by line
    # count, and until this level they are withheld rather than dropped. The
    # sentences are deliberately compact: at the level that turns market data
    # on there are thousands of them, and a paragraph each would bury the
    # business events they are context for.
    kinds.BOOK: {
        LEVEL_MARKET: "{symbol} book: {top_bid} bid / {top_ask} ask{last_clause}"
    },
    kinds.DEPTH: {
        LEVEL_MARKET: "{symbol} depth: mid {mid_price}, {bid_depth} bid / "
        "{ask_depth} ask{skew_clause}"
    },
    kinds.INDEX_UPDATE: {LEVEL_MARKET: "{index_id} is at {index_level}"},
    kinds.AUCTION_INDICATIVE: {
        LEVEL_MARKET: "{symbol} would uncross {qty} @ {price}{imbalance_clause}"
    },
    kinds.DROP_COPY_EVENT: {
        LEVEL_MARKET: "Drop copy to {actor}: {event_type} on {ref}"
    },
    kinds.DROP_COPY_REPLAY: {
        LEVEL_MARKET: "Drop copy replayed to {actor}: {event_type} on {ref}"
    },
    # -- risk and admin commands -------------------------------------------
    kinds.RISK_KILL_SWITCH: {
        1: "{actor} pulled the kill switch{on_clause}{note_clause}"
    },
    kinds.RISK_KILL_SWITCH_GATEWAY: {
        1: "{actor} pulled the kill switch on a whole gateway{note_clause}"
    },
    kinds.RISK_KILL_SWITCH_GLOBAL: {
        1: "{actor} pulled the global kill switch{note_clause}"
    },
    kinds.RISK_SYMBOL_HALT: {1: "{actor} halted {symbol}{note_clause}"},
    kinds.RISK_SYMBOL_RESUME: {1: "{actor} resumed {symbol}{note_clause}"},
    kinds.RISK_CANCEL_SYMBOL: {
        1: "{actor} cancelled everything on {symbol}{note_clause}"
    },
    kinds.RISK_FORCE_UNCROSS: {1: "{actor} forced an uncross on {symbol}{note_clause}"},
    kinds.RISK_HALT_ALL: {1: "{actor} halted the whole market"},
    kinds.RISK_RESUME_ALL: {1: "{actor} resumed the whole market"},
    kinds.ADMIN_ACTION: {1: "{actor} ran {action}"},
    kinds.SESSION_TRANSITION_ACK: {1: "Engine {verdict} the session transition"},
    kinds.CIRCUIT_BREAKER_HALT: {
        1: "{symbol} was halted by {halt_source}{corridor_clause}",
        2: "{symbol} was halted by {halt_source}{corridor_clause}{trigger_clause}",
    },
    kinds.CIRCUIT_BREAKER_EXTEND: {1: "{symbol}'s halt was extended{corridor_clause}"},
    kinds.CIRCUIT_BREAKER_RESUME: {1: "{symbol} resumed trading{because_clause}"},
    kinds.AUCTION_RESULT: {
        1: "{symbol} uncrossed {qty} @ {price}{imbalance_clause}{because_clause}"
    },
    kinds.SESSION_TRANSITION: {1: "The session was asked to move to {to_state}"},
    kinds.SESSION_STATE: {1: "The session is now {state}{from_clause}"},
    kinds.SYSTEM_EOD: {1: "End of day"},
    # -- participants and commands -----------------------------------------
    kinds.GATEWAY_AUTH: {1: "{actor} connected{auth_clause}"},
    kinds.GATEWAY_CONNECT: {1: "{actor} is connecting"},
    kinds.GATEWAY_DISCONNECT: {1: "{actor} disconnected{because_clause}"},
    kinds.GATEWAY_BYE: {1: "{actor} disconnected{because_clause}"},
    kinds.STARTUP_RECOVERY: {
        1: "The engine restarted and restored {restored}{recovery_failure_clause}"
    },
    # The outcome gloss carries its own verb, so "failed to restore" does not
    # have to be squeezed into "was ...".
    kinds.RECOVERY_ITEM: {1: "{entity_kind} {ref} {outcome}{detail_clause}"},
    kinds.INDEX_CORP_ACTION: {1: "{actor} applied {action} to {symbol} in {index_id}"},
    kinds.INDEX_CONSTITUENT_CHANGE: {1: "{actor} {change_type} {index_id}: {symbol}"},
    kinds.INDEX_REBALANCE: {1: "{actor} rebalanced {index_id}"},
    kinds.INDEX_CORP_ACTION_ACK: {
        1: "pm-index {verdict} the corporate action{because_clause}"
    },
    kinds.INDEX_CONSTITUENT_CHANGE_ACK: {
        1: "pm-index {verdict} the constituent change{because_clause}"
    },
    kinds.INDEX_REBALANCE_ACK: {1: "pm-index {verdict} the rebalance{because_clause}"},
}

#: The fallback when no template names a kind: the topic, the actor and
#: nothing invented. Deliberately dull -- it is a prompt to write a real
#: sentence, and it keeps the round-trip property true in the meantime. The
#: query replies (``system.reference``, ``system.volume``, ``order.orders``
#: and their siblings) still land here at level 3; section 8.1 names only the
#: market data and drop copy above, and a sentence written for a reply shape
#: nobody has looked at would be a guess.
GENERIC = "{kind}{actor_clause}"

#: Every ``*_ack`` topic the spec declares gets this unless it has its own
#: sentence. There are sixteen of them and they all say the same thing, so
#: listing each would be sixteen chances to phrase one differently.
ACK_TEMPLATE = "Engine {verdict} {command_label}{because_clause}"

#: Level 0, and the closing line of an episode at level 2. One line for the
#: whole happening rather than one per fact.
SUMMARIES: Mapping[str, str] = {
    "order": "order {ref} {outcome_phrase}{fill_summary}",
    "trade": "trade {ref} — {symbol} {qty} @ {price}",
    "quote": "quote {ref} on {symbol} {outcome_phrase}",
    "oco": "OCO {ref} {outcome_phrase}",
    "combo": "combo {ref} {outcome_phrase}",
    "command": "command {ref} {outcome_phrase}",
    "market_phase": "{symbol}'s market-phase span {outcome_phrase}",
    "session": "the {ref} session {outcome_phrase}",
    "gateway": "{ref}'s connection {outcome_phrase}",
    "index": "index command {ref} {outcome_phrase}",
    "recovery": "engine restart {ref} {outcome_phrase}",
    "orphan": "unattached {kind}",
}

#: How an episode's outcome reads in a summary. ``OPEN`` is the one that has
#: to be unmistakable: section 7.3 calls narrating an unfinished episode as a
#: finished one the most misleading thing this tool could do.
OUTCOME_PHRASES: Mapping[str, str] = {
    "FILLED": "filled",
    "PARTIAL": "is still working at the end of the window",
    "CANCELLED": "was cancelled",
    "REJECTED": "was rejected",
    "EXPIRED": "expired",
    "ACCEPTED": "ran to completion",
    "DENIED": "was refused",
    "OPEN": "was still open at the end of the window",
    "UNKNOWN": "reached no recorded outcome",
}
