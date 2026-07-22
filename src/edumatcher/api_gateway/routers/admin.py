"""ADMIN-persona REST endpoints (session control, risk, gateway ops).

Every endpoint requires an API key mapped to a gateway whose engine
ParticipantRole is ADMIN. Role is resolved from the engine gateways reply
because the API credential store does not carry role information. All actions
map to existing engine topics; no engine changes are required.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from edumatcher.api_gateway.schemas import (
    CircuitBreakerResumeRequest,
    CircuitBreakerTriggerRequest,
    SessionTransitionRequest,
    SymbolCancelRequest,
)
from edumatcher.api_gateway.sessions import Session, auth, require_admin

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _check_rate_limit(request: Request, session: Session) -> None:
    """Raise 429 if the per-key write rate is exceeded."""
    if not request.app.state.rate_limiter.allow(session.api_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "RATE_LIMIT", "message": "Write rate exceeded"}},
        )


async def _await_reply(request: Request, topic: str) -> dict[str, Any]:
    """Await an engine reply on *topic*, mapping timeouts to 503."""
    try:
        return cast(
            dict[str, Any],
            await request.app.state.engine.await_topic(
                topic, request.app.state.config.timeouts.engine_reply_sec
            ),
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc


async def _await_ack(
    request: Request, topic: str, match: dict[str, str] | None = None
) -> dict[str, Any]:
    """Await a single risk ACK on *topic*, mapping timeouts to 503.

    Pass *match* whenever the ack payload carries a field (e.g. ``symbol``)
    that can disambiguate concurrent calls sharing the same topic — without
    it, two concurrent calls race to consume whichever ack arrives first.
    """
    try:
        return cast(
            dict[str, Any],
            await request.app.state.engine.await_event(
                topic,
                match=match,
                timeout=request.app.state.config.timeouts.wait_ack_sec,
            ),
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc


def _require_accepted(ack: dict[str, Any]) -> dict[str, Any]:
    """Return *ack* or raise 403 with the engine reason if it was rejected."""
    if not bool(ack.get("accepted")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "ROLE_DENIED",
                    "message": str(ack.get("reason", "Rejected by engine")),
                }
            },
        )
    return ack


@router.post("/session/transition", status_code=status.HTTP_202_ACCEPTED)
async def session_transition(  # pyright: ignore[reportUnusedFunction]
    body: SessionTransitionRequest,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, str]:
    await require_admin(request, session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_session_transition(body.to_state)
    return {"requested_state": body.to_state, "status": "PENDING"}


@router.get("/session/schedule")
async def session_schedule(  # pyright: ignore[reportUnusedFunction]
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    gateway_id = await require_admin(request, session)
    request.app.state.engine.request_session_schedule(gateway_id)
    return await _await_reply(request, f"system.session_schedule.{gateway_id}")


@router.get("/gateways")
async def list_gateways(  # pyright: ignore[reportUnusedFunction]
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    gateway_id = await require_admin(request, session)
    request.app.state.engine.request_gateways(gateway_id)
    return await _await_reply(request, f"system.gateways.{gateway_id}")


@router.post("/gateways/{gid}/disconnect", status_code=status.HTTP_202_ACCEPTED)
async def disconnect_gateway(  # pyright: ignore[reportUnusedFunction]
    gid: str,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, str]:
    await require_admin(request, session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_disconnect(gid.upper(), "admin disconnect")
    return {"gateway_id": gid.upper(), "status": "DISCONNECTED"}


@router.post("/circuit-breaker/trigger", status_code=status.HTTP_202_ACCEPTED)
async def circuit_breaker_trigger(  # pyright: ignore[reportUnusedFunction]
    body: CircuitBreakerTriggerRequest,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    gateway_id = await require_admin(request, session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_symbol_halt(gateway_id, body.symbol)
    ack = await _await_ack(
        request,
        f"risk.symbol_halt_ack.{gateway_id}",
        match={"symbol": body.symbol},
    )
    return _require_accepted(ack)


@router.post("/circuit-breaker/resume", status_code=status.HTTP_202_ACCEPTED)
async def circuit_breaker_resume(  # pyright: ignore[reportUnusedFunction]
    body: CircuitBreakerResumeRequest,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    gateway_id = await require_admin(request, session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_symbol_resume(gateway_id, body.symbol)
    ack = await _await_ack(
        request,
        f"risk.symbol_resume_ack.{gateway_id}",
        match={"symbol": body.symbol},
    )
    return _require_accepted(ack)


@router.get("/halts")
async def halt_status(  # pyright: ignore[reportUnusedFunction]
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    gateway_id = await require_admin(request, session)
    request.app.state.engine.request_halt_status(gateway_id)
    return await _await_reply(request, f"system.halt_status.{gateway_id}")


@router.post("/kill-switch/symbol", status_code=status.HTTP_202_ACCEPTED)
async def kill_switch_symbol(  # pyright: ignore[reportUnusedFunction]
    body: SymbolCancelRequest,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    gateway_id = await require_admin(request, session)
    _check_rate_limit(request, session)
    request.app.state.engine.send_cancel_symbol(gateway_id, body.symbol)
    ack = await _await_ack(
        request,
        f"risk.cancel_symbol_ack.{gateway_id}",
        match={"symbol": body.symbol},
    )
    return _require_accepted(ack)
