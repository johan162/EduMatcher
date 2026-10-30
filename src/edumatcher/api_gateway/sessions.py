"""Authentication and session dependencies for FastAPI routes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig

#: Declares the bearer scheme in OpenAPI (Swagger's "Authorize" button) and
#: parses the header. ``auto_error=False`` so a missing or non-Bearer header
#: reaches ``auth`` as ``None`` and gets this API's own 401, not FastAPI's 403.
_bearer = HTTPBearer(
    auto_error=False,
    description=(
        "API key as a bearer token: `Authorization: Bearer <api_key>`. Keys are "
        "configured under `api_gateways.<name>.credentials`."
    ),
)


@dataclass(frozen=True)
class Session:
    """Authenticated API session returned to route handlers."""

    api_key: str
    gateway_id: str | None
    description: str

    @property
    def can_trade(self) -> bool:
        return self.gateway_id is not None


class SessionRegistry:
    """API-key lookup table backed by the central config file."""

    def __init__(self, credentials: tuple[ApiCredential, ...]) -> None:
        self._credentials = {
            credential.api_key: credential for credential in credentials
        }

    @classmethod
    def from_config(cls, config: ApiGatewayConfig) -> "SessionRegistry":
        return cls(config.credentials)

    def get(self, api_key: str) -> ApiCredential | None:
        return self._credentials.get(api_key)


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": "AUTH", "message": message}},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Session:
    """Authenticate an API key and ensure engine auth for trading sessions."""
    token = credentials.credentials.strip() if credentials is not None else ""
    if not token:
        raise _unauthorized("Expected Authorization: Bearer <api_key>")
    registry: SessionRegistry = request.app.state.sessions
    credential = registry.get(token)
    if credential is None:
        raise _unauthorized("Unknown API key")

    session = Session(
        api_key=token,
        gateway_id=credential.gateway_id,
        description=credential.description,
    )
    if session.gateway_id is not None:
        timeout = request.app.state.config.timeouts.engine_auth_sec
        accepted, reason = await request.app.state.engine.authenticate(
            session.gateway_id, timeout=timeout
        )
        if not accepted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "ENGINE_AUTH", "message": reason}},
            )
    return session


def correlation_id(session: Session) -> str:
    """Reply-topic suffix for an engine query made on behalf of *session*.

    A trading key uses its gateway id. A read-only key has none, so it gets an
    id derived from the key: upper-case and at most 32 characters, because the
    engine upper-cases and clamps the id it echoes in the reply topic
    (``engine/main.py`` ``_clamp_wire_id``), and stable rather than fresh per
    request, because EngineClient keeps state for every id it sees a reply
    for. Hashed, so the key itself never travels on the bus.
    """
    if session.gateway_id is not None:
        return session.gateway_id
    digest = hashlib.sha256(session.api_key.encode()).hexdigest()
    return f"RO{digest[:16].upper()}"


def require_trading(session: Session) -> str:
    """Return gateway id or raise if this key is read-only."""
    if session.gateway_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "READ_ONLY", "message": "API key is read-only"}},
        )
    return session.gateway_id


async def require_admin(request: Request, session: Session) -> str:
    """Return gateway id or raise unless the gateway holds the ADMIN role.

    The API credential store does not carry role, so it is resolved from the
    engine gateways reply. Non-admin gateways receive ``403 ROLE_DENIED``.
    """
    gateway_id = require_trading(session)
    role = await request.app.state.engine.resolve_role(
        gateway_id, request.app.state.config.timeouts.engine_reply_sec
    )
    if role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "ROLE_DENIED", "message": "ADMIN role required"}},
        )
    return gateway_id
