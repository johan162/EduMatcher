# GENERATED FROM spec/messages/admin.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``admin`` message family.

Family version 1. Derived from ``spec/messages/admin.yaml`` by the rest emitter; edit
the spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AdminActionAction = Literal[
    "kill_switch.self",
    "kill_switch.gateway",
    "kill_switch.global",
    "kill_switch.symbol",
    "circuit_breaker.trigger",
    "circuit_breaker.resume",
    "auction.reopen",
]


class AdminActionScope(BaseModel):
    """What one admin command acted on, and what it did. Every field is optional
    because every action uses a different subset -- see the family header on why
    that is a stated limitation rather than a variant type. The name is inherited
    from the wire key rather than chosen: three of the seven fields are outcome
    counts rather than scope, which makes "AdminActionScope" a slightly generous
    reading of its own contents. It was kept because renaming the key is a wire
    change for every `/admin/monitor` client and buys nothing a reader can use.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str | None = Field(default=None, max_length=16)
    """The instrument, when the command named one. `kill_switch.self` used to emit
    this as an explicit `null` when unscoped while its siblings omitted the key --
    two spellings of one absence, and this is now the second.
    """
    target_gateway_id: str | None = Field(default=None, max_length=32)
    """The participant acted upon, for `kill_switch.gateway`."""
    level: str | None = Field(default=None, max_length=32)
    """The circuit-breaker rung, for `circuit_breaker.trigger`. Not an enum: the
    ladder is per-symbol configuration, so the value set differs per deployment.
    Bounded to match `circuit_breaker.halt.level`, which carries the same name
    onward.
    """
    note: str | None = Field(default=None, max_length=256)
    """The operator's free-text reason, when one was supplied. Regime 4 to match
    `risk.kill_switch`'s own `note`, which is where this value arrives from -- a
    field that omits on one message and emits `""` on the next would be two
    answers to one question.
    """
    cancelled_orders: int | None = Field(default=None, ge=0)
    """Outcome, on accepted kill-switch actions only."""
    cancelled_order_ids: list[str] | None = Field(default=None)
    """AR-0.5: the order ids counted in cancelled_orders, mirroring
    risk.kill_switch_ack (and friends) — see risk.yaml for why this is the right
    key even for the quote-cancellation counterpart below.
    """
    cancelled_quotes: int | None = Field(default=None, ge=0)
    """Outcome, on accepted kill-switch actions only."""
    cancelled_quote_order_ids: list[str] | None = Field(default=None)
    """AR-0.5: the order ids counted in cancelled_quotes."""
    affected_gateways: int | None = Field(default=None, ge=0)
    """Outcome, on an accepted `kill_switch.global` only."""
    affected_gateway_ids: list[str] | None = Field(default=None)
    """AR-0.5: the gateway ids counted in affected_gateways."""


class AdminAction(BaseModel):
    """Engine to the admin monitor: one admin-gated command ran, who ran it, what it
    acted on, and whether it was accepted.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    command_id: str = Field(max_length=64)
    initiator_gateway_id: str = Field(max_length=32)
    action: AdminActionAction
    """Which command ran. The seven the engine publishes, enumerated rather than left
    a free string: an eighth admin command that forgets to declare itself here
    fails loudly at its first invocation, which is better than appearing in the
    monitor as a value no client renders. The values look like topics and are not:
    `circuit_breaker.trigger` is the action behind `risk.symbol_halt`, and there
    is no `circuit_breaker.trigger` topic anywhere. `auction.reopen` is the action
    behind `risk.force_uncross`.
    """
    scope: AdminActionScope
    accepted: bool
    reason: str = Field(max_length=512)
    """Why it was rejected; "" on an accepted action."""
