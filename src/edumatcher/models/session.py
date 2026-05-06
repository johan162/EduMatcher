"""
Domain models: SessionState enum and helpers for the trading session lifecycle.

The engine moves through session states during the trading day:
  PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED

Transitions are driven by the session scheduler (pm-scheduler) process.
"""

from __future__ import annotations

from enum import Enum


class SessionState(str, Enum):
    """Trading session phase — determines whether matching is active."""

    PRE_OPEN = "PRE_OPEN"  # orders accepted, no matching
    OPENING_AUCTION = (
        "OPENING_AUCTION"  # orders accepted, no matching (uncross on exit)
    )
    CONTINUOUS = "CONTINUOUS"  # normal continuous matching
    CLOSING_AUCTION = (
        "CLOSING_AUCTION"  # orders accepted, no matching (uncross on exit)
    )
    CLOSED = "CLOSED"  # no new orders accepted


# Valid transitions: from_state → set of allowed to_states
VALID_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.PRE_OPEN: {SessionState.OPENING_AUCTION, SessionState.CONTINUOUS},
    SessionState.OPENING_AUCTION: {SessionState.CONTINUOUS},
    SessionState.CONTINUOUS: {SessionState.CLOSING_AUCTION, SessionState.CLOSED},
    SessionState.CLOSING_AUCTION: {SessionState.CLOSED},
    SessionState.CLOSED: {SessionState.PRE_OPEN},
}


def is_matching_enabled(state: SessionState) -> bool:
    """Return True if continuous matching should be active in the given state."""
    return state == SessionState.CONTINUOUS


def is_auction_phase(state: SessionState) -> bool:
    """Return True if the state is an auction collection phase."""
    return state in (SessionState.OPENING_AUCTION, SessionState.CLOSING_AUCTION)


def accepts_orders(state: SessionState) -> bool:
    """Return True if new orders are accepted in the given state."""
    return state != SessionState.CLOSED
