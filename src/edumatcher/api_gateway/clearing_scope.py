"""Who may read which gateway's clearing and settlement data.

Every ``/clearing`` route that returns gateway-keyed rows resolves its scope
here, from the authenticated session, before it looks at the ``gateway`` the
client asked for: an ADMIN reads the venue (optionally narrowed to one
gateway), a TRADER or MARKET_MAKER reads its own gateway, and a request for
any other gateway is refused rather than silently answered with the caller's
own rows. A read-only key has no gateway and so no clearing scope.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from edumatcher.api_gateway.sessions import Session, report_refusal, require_trading

#: The audit trail's reject vocabulary has no separate value for "another
#: gateway's data"; it is a missing role (ADMIN), which is what it records.
_AUDIT_REJECT = "ROLE_DENIED"


@dataclass(frozen=True)
class ClearingScope:
    """The rows one request may see."""

    #: The authenticated gateway.
    caller: str
    #: Venue-wide visibility, including the ``EXCHANGE`` settlement account.
    admin: bool
    #: The gateway to filter on; ``None`` (ADMIN only) is every gateway.
    gateway: str | None


async def clearing_scope(
    request: Request, session: Session, requested: str | None = None
) -> ClearingScope:
    """Resolve the caller's scope, then check *requested* against it.

    The role comes from the engine (the credential store holds none); an
    unanswered lookup resolves to ``TRADER``, so an ADMIN that cannot be
    confirmed sees its own gateway only.
    """
    caller = require_trading(session)
    role = await request.app.state.engine.resolve_role(
        caller, request.app.state.config.timeouts.engine_reply_sec
    )
    wanted = (requested or "").strip().upper() or None
    if role == "ADMIN":
        return ClearingScope(caller=caller, admin=True, gateway=wanted)
    if wanted is not None and wanted != caller:
        message = f"Gateway {caller} may read only its own clearing data, not {wanted}"
        report_refusal(request, _AUDIT_REJECT, message, caller)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "SCOPE_DENIED", "message": message}},
        )
    return ClearingScope(caller=caller, admin=False, gateway=caller)
