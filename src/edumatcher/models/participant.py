"""Participant session model used by engine gateway-state checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ParticipantRole(str, Enum):
    TRADER = "TRADER"
    MARKET_MAKER = "MARKET_MAKER"
    ADMIN = "ADMIN"


class DisconnectBehaviour(str, Enum):
    CANCEL_QUOTES_ONLY = "CANCEL_QUOTES_ONLY"
    CANCEL_ALL = "CANCEL_ALL"
    LEAVE_ALL = "LEAVE_ALL"


@dataclass(slots=True)
class ParticipantSession:
    gateway_id: str
    role: ParticipantRole = ParticipantRole.TRADER
    disconnect_behaviour: DisconnectBehaviour = DisconnectBehaviour.CANCEL_QUOTES_ONLY
    connected: bool = False
    # Liveness, opt-in: 0 until the participant's first system.gateway_heartbeat,
    # which carries its own beat interval. Only sessions that have beaten are
    # ever timed out.
    heartbeat_interval_sec: int = 0
    last_heartbeat: float = 0.0
