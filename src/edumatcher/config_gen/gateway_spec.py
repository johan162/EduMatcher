"""Parser for gateway specs: ID[:ROLE[:DISCONNECT]]."""

from __future__ import annotations

import re
from dataclasses import dataclass

from edumatcher.models.order import SmpAction
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole


@dataclass(frozen=True)
class GatewaySpec:
    gateway_id: str
    role: ParticipantRole
    disconnect_behaviour: DisconnectBehaviour
    # Free text, set via the separate --participant-desc GW_ID:TEXT flag. Not
    # part of the --participants spec: an unquoted space there split one spec
    # into several shell words, each silently accepted as a bare participant ID.
    description: str = ""
    # Gateway-level self-match-prevention default, applied by the engine to
    # any order/quote from this gateway that doesn't specify its own SMP=
    # (see participants[].smp_action in ../../../docs/books/operator-guide/part-4-run-a-market/040-risk-controls.md).
    # Set via the separate, repeatable --participant-smp GW_ID:SMP_ACTION flag.
    smp_action: SmpAction = SmpAction.NONE
    # True when the spec named the value itself (rather than taking the role
    # default), so it must be written even when a ``participant_defaults`` exists.
    disconnect_explicit: bool = False
    smp_explicit: bool = False


_ROLE_DEFAULT_DISCONNECT: dict[ParticipantRole, DisconnectBehaviour] = {
    ParticipantRole.TRADER: DisconnectBehaviour.CANCEL_ALL,
    ParticipantRole.MARKET_MAKER: DisconnectBehaviour.CANCEL_QUOTES_ONLY,
    ParticipantRole.ADMIN: DisconnectBehaviour.LEAVE_ALL,
}


# Uppercase letter first, then uppercase letters, digits or "_"; 32 chars max
# (the gateway_id max_len of the message specs). Strict on purpose: a stray
# shell word such as "desk" or "1" must be rejected, not become a participant.
_GATEWAY_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")


def parse_gateway_spec(raw: str) -> GatewaySpec:
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) > 3:
        raise ValueError(
            f"Invalid gateway spec '{raw}': expected ID[:ROLE[:DISCONNECT]]; "
            "set a description with --participant-desc GW_ID:TEXT"
        )

    gateway_id = parts[0]
    if not gateway_id:
        raise ValueError("Gateway ID cannot be empty")
    if not _GATEWAY_ID_RE.match(gateway_id):
        raise ValueError(
            f"Invalid gateway ID '{gateway_id}' in spec '{raw}': must start with "
            "an uppercase letter and contain only A-Z, 0-9 and _ (max 32 chars). "
            "A stray word here usually means an unquoted value with spaces."
        )

    role = ParticipantRole.TRADER
    if len(parts) >= 2 and parts[1]:
        try:
            role = ParticipantRole(parts[1].upper())
        except ValueError as exc:
            raise ValueError(f"Invalid role in gateway spec '{raw}'") from exc

    disconnect = _ROLE_DEFAULT_DISCONNECT[role]
    disconnect_explicit = len(parts) >= 3 and bool(parts[2])
    if disconnect_explicit:
        try:
            disconnect = DisconnectBehaviour(parts[2].upper())
        except ValueError as exc:
            raise ValueError(
                f"Invalid disconnect_behaviour in gateway spec '{raw}'"
            ) from exc

    return GatewaySpec(
        gateway_id=gateway_id,
        role=role,
        disconnect_behaviour=disconnect,
        disconnect_explicit=disconnect_explicit,
    )
