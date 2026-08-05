"""ADMIN-persona REST endpoints (session control, risk, gateway ops).

Every endpoint requires an API key mapped to a gateway whose engine
ParticipantRole is ADMIN. Role is resolved from the engine gateways reply
because the API credential store does not carry role information. All actions
map to existing engine topics; no engine changes are required.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from edumatcher.audit.indexer import (
    index_is_available,
    open_readonly_index,
    query_index_events,
)
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
    gateway_id = await require_admin(request, session)
    _check_rate_limit(request, session)
    try:
        ack = await request.app.state.engine.send_and_await_session_transition(
            gateway_id,
            body.to_state,
            request.app.state.config.timeouts.wait_ack_sec,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc
    # The engine discards a transition it cannot perform (sessions disabled,
    # unknown state). It now says so instead of leaving the caller to infer it
    # from a timeout that looks identical to a slow engine.
    if not bool(ack.get("accepted")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "TRANSITION_REJECTED",
                    "message": str(ack.get("reason", "Rejected by engine")),
                }
            },
        )
    return {
        "requested_state": body.to_state,
        "status": "APPLIED",
        "command_id": str(ack.get("command_id", "")),
    }


@router.post("/reference/reload", status_code=status.HTTP_200_OK)
async def reference_reload(  # pyright: ignore[reportUnusedFunction]
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    """Reload static reference data (tick sizes, risk bands, circuit-breaker
    ladders, schedule, index definitions) from the engine's config file.

    For controlled reloads in development/classroom mode. Deliberately
    narrower than a full engine config reload: it never touches order
    books, market-maker seeding, or session state, and is rejected outright
    (409) if the file's symbol or index set no longer matches the running
    engine's — adding or removing an instrument mid-session isn't safe and
    still requires a restart.
    """
    gateway_id = await require_admin(request, session)
    _check_rate_limit(request, session)
    try:
        ack = await request.app.state.engine.send_and_await_reference_reload(
            gateway_id,
            request.app.state.config.timeouts.wait_ack_sec,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc
    if not bool(ack.get("accepted")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "RELOAD_REJECTED",
                    "message": str(ack.get("reason", "Rejected by engine")),
                }
            },
        )
    return {"status": "RELOADED", "config_version": ack.get("config_version")}


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


# ---------------------------------------------------------------------------
# Cross-gateway order views
# ---------------------------------------------------------------------------


@router.get("/orders")
async def admin_orders(  # pyright: ignore[reportUnusedFunction]
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: str | None = None,
    gateway_id: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    """Every cached order across every gateway, filtered.

    Served entirely from the gateway's own read model — no engine round-trip
    — because `_caches` already accumulates an entry per gateway whose events
    pass through. This is *current state*, bounded by
    `order_retention_sec`: terminal orders age out, so it answers "what is
    open now", not "what happened today". For the latter, see
    `GET /admin/orders/{order_id}` and the audit trail.
    """
    await require_admin(request, session)
    orders = request.app.state.engine.all_orders()

    wanted_symbol = symbol.upper() if symbol else None
    wanted_gateway = gateway_id.upper() if gateway_id else None
    wanted_status = status_filter.upper() if status_filter else None

    filtered = [
        order
        for order in orders
        if (
            wanted_symbol is None
            or str(order.get("symbol", "")).upper() == wanted_symbol
        )
        and (
            wanted_gateway is None
            or str(order.get("gateway_id", "")).upper() == wanted_gateway
        )
        and (
            wanted_status is None
            or str(order.get("status", "")).upper() == wanted_status
        )
    ]
    return {
        "count": len(filtered),
        "orders": filtered,
        "retention_sec": request.app.state.config.order_retention_sec,
    }


@router.get("/orders/{order_id}")
async def admin_order_lifecycle(  # pyright: ignore[reportUnusedFunction]
    order_id: str,
    request: Request,
    session: Annotated[Session, Depends(auth)],
    limit: int = 500,
) -> dict[str, Any]:
    """The full cross-gateway lifecycle of one order, from the audit trail.

    Read from `pm-audit`'s index (`audit_index.db`), **not** from the
    gateway's cache: the cache folds each event into current state and keeps
    no history, so a lifecycle served from it would be a weaker duplicate of
    an audit trail that already exists, is complete, and is durable.

    The dependency is read-only and optional. If `pm-audit` is not deployed
    or has not built its index, this endpoint returns 503 with a specific
    reason and every other route is unaffected.
    """
    await require_admin(request, session)
    audit_db = request.app.state.config.audit_db
    if not index_is_available(audit_db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "AUDIT_INDEX_UNAVAILABLE",
                    "message": (
                        f"No audit index at {audit_db}. Order lifecycle needs "
                        "pm-audit running and 'pm-audit-cli index' built."
                    ),
                }
            },
        )
    conn = open_readonly_index(audit_db)
    try:
        events = query_index_events(conn, order_id=order_id, limit=limit)
    finally:
        conn.close()
    if not events:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "UNKNOWN_ORDER",
                    "message": f"No audited events for order {order_id}",
                }
            },
        )
    return {"order_id": order_id, "count": len(events), "events": events}
