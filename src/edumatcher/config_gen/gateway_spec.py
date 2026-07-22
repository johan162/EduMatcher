"""Parser for gateway specs: ID[:ROLE[:DISCONNECT]]."""

from __future__ import annotations

from dataclasses import dataclass

from edumatcher.models.order import SmpAction
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole


@dataclass(frozen=True)
class GatewaySpec:
    gateway_id: str
    role: ParticipantRole
    disconnect_behaviour: DisconnectBehaviour
    description: str = ""
    # Gateway-level self-match-prevention default, applied by the engine to
    # any order/quote from this gateway that doesn't specify its own SMP=
    # (see gateways.alf[].smp_action in docs/user-guide/120-risk-controls.md).
    # Not part of the colon-delimited --gateways spec syntax (would collide
    # with the free-text DESCRIPTION slot) -- set via the separate,
    # repeatable --gateway-smp GW_ID:SMP_ACTION flag instead.
    smp_action: SmpAction = SmpAction.NONE


_ROLE_DEFAULT_DISCONNECT: dict[ParticipantRole, DisconnectBehaviour] = {
    ParticipantRole.TRADER: DisconnectBehaviour.CANCEL_ALL,
    ParticipantRole.MARKET_MAKER: DisconnectBehaviour.CANCEL_QUOTES_ONLY,
    ParticipantRole.ADMIN: DisconnectBehaviour.LEAVE_ALL,
}


def parse_gateway_spec(raw: str) -> GatewaySpec:
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) > 4:
        raise ValueError(
            f"Invalid gateway spec '{raw}': expected ID[:ROLE[:DISCONNECT[:DESCRIPTION]]]"
        )

    gateway_id = parts[0].upper()
    if not gateway_id:
        raise ValueError("Gateway ID cannot be empty")

    role = ParticipantRole.TRADER
    if len(parts) >= 2 and parts[1]:
        try:
            role = ParticipantRole(parts[1].upper())
        except ValueError as exc:
            raise ValueError(f"Invalid role in gateway spec '{raw}'") from exc

    disconnect = _ROLE_DEFAULT_DISCONNECT[role]
    if len(parts) >= 3 and parts[2]:
        try:
            disconnect = DisconnectBehaviour(parts[2].upper())
        except ValueError as exc:
            raise ValueError(
                f"Invalid disconnect_behaviour in gateway spec '{raw}'"
            ) from exc

    description = parts[3] if len(parts) >= 4 else ""

    return GatewaySpec(
        gateway_id=gateway_id,
        role=role,
        disconnect_behaviour=disconnect,
        description=description,
    )
