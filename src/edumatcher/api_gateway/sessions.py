"""Authentication and session dependencies for FastAPI routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig


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


def _extract_bearer(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "AUTH", "message": "Expected Bearer token"}},
        )
    return token.strip()


async def auth(
    request: Request,
    authorization: Annotated[str, Header()],
) -> Session:
    """Authenticate an API key and ensure engine auth for trading sessions."""
    token = _extract_bearer(authorization)
    registry: SessionRegistry = request.app.state.sessions
    credential = registry.get(token)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "AUTH", "message": "Unknown API key"}},
        )

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


def require_trading(session: Session) -> str:
    """Return gateway id or raise if this key is read-only."""
    if session.gateway_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "READ_ONLY", "message": "API key is read-only"}},
        )
    return session.gateway_id
