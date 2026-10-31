# GENERATED FROM spec/messages/session.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``session`` message family.

Family version 1. Derived from ``spec/messages/session.yaml`` by the rest emitter; edit
the spec, not this file.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NextTransition(BaseModel):
    """The transition after this one: what the session moves to, and when. Present
    only when the scheduler drove the transition, since it alone knows the day's
    timetable. A manual or admin-driven transition carries no next - deliberately,
    because the schedule says what *should* happen while the engine decides what
    *does*, and a countdown derived from the timetable alone would tick toward a
    transition nobody will perform. The two fields are one record rather than two
    optional keys because neither is meaningful alone: a phase without a time
    cannot be counted down to, and a time without a phase does not say what
    happens.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    state: str = Field(max_length=32)
    """The session state being moved to."""
    at: str = Field(max_length=32)
    """UTC ISO-8601 instant of the transition."""


class ReplyTo(BaseModel):
    """Where to send the outcome of a command, and under what correlation id.
    Supplied by an *interactive* requester that wants to know what happened. pm-
    scheduler omits it: it drives the timetable, has nobody to report back to, and
    the public session.state broadcast already says what occurred. A record rather
    than two optional keys for the same reason as NextTransition - a command_id
    with no gateway to answer on is undeliverable, and a gateway with no
    command_id cannot be correlated.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    command_id: str = Field(max_length=64)
    gateway_id: str = Field(max_length=32)


class SessionState(BaseModel):
    """Broadcast the engine's current session state to every subscriber. The most
    widely consumed topic in the system.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    state: str = Field(max_length=32)
    """The session state now in effect."""
    prev_state: str | None = Field(default=None, max_length=32)
    """The state departed from; absent on the first broadcast."""
    next: NextTransition | None = Field(default=None)
    command_id: str | None = Field(default=None, max_length=64)
    """AR-0.6: echoes the session.transition.reply_to.command_id that caused this
    broadcast, when the requester supplied one. Absent for a schedule-driven
    transition (pm-scheduler sends no reply_to at all) and for a rejected request
    (no broadcast happens at all in that case). Converts the engine's own STRONG
    session.transition -> session.state link (adjacency in the stream) into a
    CERTAIN one (a shared id), the same way the risk family's acks already do for
    kill-switch/circuit-breaker commands. Deliberately just the command_id, not
    the full reply_to: gateway_id is not repeated here -- session_transition_ack
    (addressed to that one gateway) is still the only place accepted, reason and
    to_state travel, since those are meaningless broadcast to every subscriber. A
    bare command_id is a much smaller disclosure than the full reply-to record,
    and it is what the audit tooling needs to link the two topics -- not who is
    allowed to see the outcome.
    """


class SessionTransition(BaseModel):
    """Scheduler or operator to engine: request a state change."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    to_state: str = Field(max_length=32)
    next: NextTransition | None = Field(default=None)
    """Describes the transition *after* this one, so the engine can publish a
    countdown target. A manual transition omits it, which clears any stale target
    the engine was holding.
    """
    reply_to: ReplyTo | None = Field(default=None)


class SessionNext(BaseModel):
    """Scheduler to engine: announce the next transition without performing one. A
    `session.transition` can only describe the transition after itself, so a
    scheduler that starts while the exchange is closed, or before the day's first
    transition, would otherwise leave the engine with no countdown target until
    that transition fires -- possibly many hours away.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    next: NextTransition


class SessionTransitionAck(BaseModel):
    """Engine to the requesting gateway: the outcome of a transition request."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    command_id: str = Field(max_length=64)
    accepted: bool
    to_state: str = Field(max_length=32)
    reason: str = Field(max_length=256)
    """Rejection detail; empty when accepted."""
