"""ADMIN-persona REST endpoints (session control, risk, gateway ops).

Every endpoint requires an API key mapped to a gateway whose engine
ParticipantRole is ADMIN. Role is resolved from the engine gateways reply
because the API credential store does not carry role information. All actions
map to existing engine topics; no engine changes are required.

Paths follow one resource-plus-action scheme (REST API review, D1): the
target is always a path segment -- ``/symbols/{symbol}/halt``,
``/gateways/{gateway_id}/kill-switch``, ``/market/kill-switch`` -- and a body,
where there is one, carries only optional parameters such as ``reason``.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from edumatcher.api_gateway import openapi_docs as docs
from edumatcher.api_gateway.responses import (
    AdminOrders,
    DisconnectPending,
    GatewayList,
    GatewayPositions,
    OrderAudit,
    ReloadApplied,
    RiskStateView,
    SimSnapshot,
    TransitionApplied,
)
from edumatcher.api_gateway.params import (
    GatewayIdPath,
    IndexIdPath,
    OrderIdPath,
    SymbolPath,
)
from edumatcher.api_gateway.routing import ContractRoute
from edumatcher.audit.indexer import (
    index_is_available,
    open_readonly_index,
    query_index_events,
)
from edumatcher.models.generated.rest.index import IndexRebalanceAck
from edumatcher.models.generated.rest.risk import (
    CancelSymbolAck,
    KillSwitchGatewayAck,
    KillSwitchGlobalAck,
    SymbolHaltAck,
    SymbolResumeAck,
)
from edumatcher.models.ids import new_command_id
from edumatcher.api_gateway.schemas import (
    AdminNoteRequest,
    IndexRebalanceRequest,
    SessionTransitionRequest,
    SymbolHaltRequest,
)
from edumatcher.api_gateway.sessions import Session, auth, require_admin
from edumatcher.models.generated.risk import (
    topic_cancel_symbol_ack,
    topic_kill_switch_gateway_ack,
    topic_kill_switch_global_ack,
    topic_symbol_halt_ack,
    topic_symbol_resume_ack,
)
from edumatcher.models.generated.system import (
    topic_gateways,
    topic_position_snapshot,
    topic_risk_state,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], route_class=ContractRoute)


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


def _require_accepted(ack: dict[str, Any], code: str) -> dict[str, Any]:
    """Return *ack*, or raise 409 *code* with the engine's reason.

    409, not 403: the caller's role was already checked; the engine refusing
    the command (an unknown symbol, a symbol not halted) is a conflict with
    venue state, as for session transition and reload.
    """
    if not bool(ack.get("accepted")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": code,
                    "message": str(ack.get("reason", "Rejected by engine")),
                }
            },
        )
    return ack


@router.post(
    "/session/transition",
    response_model=TransitionApplied,
    summary="Change session state",
    description=(
        "Force the venue into another session phase (PRE_OPEN, OPENING_AUCTION, "
        "CONTINUOUS, CLOSING_AUCTION, CLOSED). Normally pm-scheduler drives these; "
        "this is the manual override. Entering an auction phase opens the call "
        "period, leaving it uncrosses. Waits for the engine's ack; 409 if the engine "
        "refuses (e.g. sessions are disabled)."
    ),
    responses=docs.merge(
        docs.ok(docs.ADMIN_TRANSITION, "The transition was applied."),
        docs.conflict("TRANSITION_REJECTED", "Sessions are disabled"),
    ),
)
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


@router.post(
    "/reference/reload",
    response_model=ReloadApplied,
    status_code=status.HTTP_200_OK,
    summary="Reload reference data",
    responses=docs.merge(
        docs.ok(docs.ADMIN_RELOAD, "Reloaded; the new `config_version`.", 200),
        docs.conflict("RELOAD_REJECTED", "Symbol set changed; restart required"),
    ),
)
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


@router.get(
    "/sim",
    response_model=SimSnapshot,
    summary="Market simulator state",
    description=(
        "The market model's latest state and its true (hidden) fair values per symbol"
        " from pm-market-sim. `available` is false, and `state`/`values` null, when "
        "the simulator is not running."
    ),
    responses=docs.merge(
        docs.ok(docs.ADMIN_SIM, "Simulator state and the model's true values.", 200)
    ),
)
async def market_sim(  # pyright: ignore[reportUnusedFunction]
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    """The market model's latest state and true values (pm-market-sim)."""
    await require_admin(request, session)
    snapshot: dict[str, Any] = request.app.state.sim.snapshot()
    return snapshot


@router.get(
    "/gateways",
    response_model=GatewayList,
    summary="List gateways",
    description=(
        "Every gateway known to the engine with its role (TRADER, MARKET_MAKER, "
        "ADMIN, ...) and whether it is currently connected."
    ),
    responses=docs.merge(
        docs.ok(
            docs.ADMIN_GATEWAYS_REPLY,
            "Every configured gateway, with role and connection state.",
            200,
        )
    ),
)
async def list_gateways(  # pyright: ignore[reportUnusedFunction]
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    gateway_id = await require_admin(request, session)
    request.app.state.engine.request_gateways(gateway_id)
    reply = await _await_reply(request, topic_gateways(gateway_id))
    return {**reply, "count": len(reply.get("gateways", []))}


@router.post(
    "/gateways/{gateway_id}/disconnect",
    response_model=DisconnectPending,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Disconnect a gateway",
    description=(
        "Ask the engine to drop the gateway's session. Its resting orders are "
        "handled according to that participant's configured disconnect policy. "
        "The optional `reason` is recorded in the engine log. Not awaited: the "
        "roster in `GET /admin/gateways` shows the result."
    ),
    responses=docs.merge(
        docs.ok(docs.ADMIN_DISCONNECT, "Disconnect sent to the engine.", 202)
    ),
)
async def disconnect_gateway(  # pyright: ignore[reportUnusedFunction]
    gateway_id: GatewayIdPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
    body: AdminNoteRequest | None = None,
) -> dict[str, str]:
    await require_admin(request, session)
    _check_rate_limit(request, session)
    target = gateway_id.upper()
    note = body.reason if body is not None and body.reason else "admin disconnect"
    request.app.state.engine.send_disconnect(target, note)
    return {"gateway_id": target, "status": "PENDING_DISCONNECT"}


@router.post(
    "/symbols/{symbol}/halt",
    response_model=SymbolHaltAck,
    summary="Halt a symbol",
    responses=docs.merge(
        docs.ok(docs.ADMIN_HALT_ACK_REPLY, "The symbol is halted."),
        docs.conflict("HALT_REJECTED", "Unknown symbol: XYZ"),
    ),
)
async def halt_symbol(  # pyright: ignore[reportUnusedFunction]
    symbol: SymbolPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
    body: SymbolHaltRequest | None = None,
) -> dict[str, Any]:
    """Halt one symbol. With ``level``, the halt runs through the same
    activation the price-triggered breaker uses (real ``resume_at_ns``, ACE
    corridor); without it, the halt is indefinite until an explicit resume.
    """
    gateway_id = await require_admin(request, session)
    _check_rate_limit(request, session)
    symbol = symbol.upper()
    body = body or SymbolHaltRequest()
    command_id = new_command_id()
    request.app.state.engine.send_symbol_halt(
        gateway_id,
        symbol,
        level=body.level,
        note=body.reason or "",
        command_id=command_id,
    )
    ack = await _await_ack(
        request,
        topic_symbol_halt_ack(gateway_id),
        match={"symbol": symbol},
    )
    return _require_accepted(ack, "HALT_REJECTED")


@router.post(
    "/symbols/{symbol}/resume",
    response_model=SymbolResumeAck,
    summary="Resume a halted symbol",
    description=(
        "Lift a halt on one symbol, whether it came from a price-triggered circuit "
        "breaker or from `POST /admin/symbols/{symbol}/halt`."
    ),
    responses=docs.merge(
        docs.ok(docs.ADMIN_RESUME_ACK_REPLY, "The symbol is trading again."),
        docs.conflict("RESUME_REJECTED", "TSLA is not halted"),
    ),
)
async def resume_symbol(  # pyright: ignore[reportUnusedFunction]
    symbol: SymbolPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
    body: AdminNoteRequest | None = None,
) -> dict[str, Any]:
    gateway_id = await require_admin(request, session)
    _check_rate_limit(request, session)
    symbol = symbol.upper()
    note = body.reason if body is not None and body.reason else ""
    command_id = new_command_id()
    request.app.state.engine.send_symbol_resume(
        gateway_id, symbol, note=note, command_id=command_id
    )
    ack = await _await_ack(
        request,
        topic_symbol_resume_ack(gateway_id),
        match={"symbol": symbol},
    )
    return _require_accepted(ack, "RESUME_REJECTED")


@router.get(
    "/risk/state",
    response_model=RiskStateView,
    summary="Live risk state",
    responses=docs.merge(
        docs.ok(
            docs.ADMIN_RISK_STATE_REPLY,
            "Collar reference and circuit-breaker state per symbol.",
            200,
        )
    ),
)
async def risk_state(  # pyright: ignore[reportUnusedFunction]
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    """Live per-symbol risk state: collar reference price and circuit-breaker
    reference/trigger/expansion/corridor state, for every symbol with either
    configured — halted or not.

    Distinct from ``GET /reference/risk`` (static, named risk-level
    definitions) and ``GET /halts`` (currently-halted symbols only).
    """
    gateway_id = await require_admin(request, session)
    request.app.state.engine.request_risk_state(gateway_id)
    reply = await _await_reply(request, topic_risk_state(gateway_id))
    return {**reply, "count": len(reply.get("symbols", []))}


# ---------------------------------------------------------------------------
# Index administration (pm-index bridge)
# ---------------------------------------------------------------------------


@router.post(
    "/indexes/{index_id}/rebalance",
    response_model=IndexRebalanceAck,
    summary="Rebalance an index",
    responses=docs.merge(
        docs.ok(docs.ADMIN_REBALANCE_REPLY, "pm-index applied the rebalance."),
        docs.conflict("REBALANCE_REJECTED", "Unknown constituent XYZ"),
    ),
)
async def index_rebalance(  # pyright: ignore[reportUnusedFunction]
    index_id: IndexIdPath,
    body: IndexRebalanceRequest,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    """Batch shares-outstanding update for an index's existing constituents.

    Each entry in ``updates`` mirrors the SHARES_ISSUANCE corporate action,
    applied to one constituent; the whole batch is validated before any of
    it is applied, and recomputes/publishes the index level once. Bridges to
    ``pm-index`` over its own PULL/PUB pair — distinct from every other
    endpoint in this router, which talks to the engine.
    """
    gateway_id = await require_admin(request, session)
    _check_rate_limit(request, session)
    command_id = new_command_id()
    index_client = request.app.state.index_client
    try:
        ack = cast(
            dict[str, Any],
            await index_client.send_and_await_rebalance(
                gateway_id=gateway_id,
                index_id=index_id.upper(),
                updates=[u.model_dump() for u in body.updates],
                command_id=command_id,
                timeout=request.app.state.config.timeouts.wait_ack_sec,
            ),
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "INDEX_TIMEOUT", "message": str(exc)}},
        ) from exc
    if not bool(ack.get("accepted")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "REBALANCE_REJECTED",
                    "message": str(ack.get("reason", "Rejected by pm-index")),
                }
            },
        )
    return ack


@router.post(
    "/symbols/{symbol}/cancel-orders",
    response_model=CancelSymbolAck,
    summary="Cancel every order on a symbol",
    responses=docs.merge(
        docs.ok(docs.ADMIN_KILL_SYMBOL_REPLY, "What the engine cancelled."),
        docs.conflict(
            "KILL_SWITCH_REJECTED",
            "Symbol-level mass cancel is only allowed for ADMIN participants",
        ),
    ),
)
async def cancel_symbol_orders(  # pyright: ignore[reportUnusedFunction]
    symbol: SymbolPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
    body: AdminNoteRequest | None = None,
) -> dict[str, Any]:
    """Cancel every resting order/quote for *symbol*, across every gateway."""
    gateway_id = await require_admin(request, session)
    _check_rate_limit(request, session)
    symbol = symbol.upper()
    note = body.reason if body is not None and body.reason else ""
    command_id = new_command_id()
    request.app.state.engine.send_cancel_symbol(
        gateway_id, symbol, note=note, command_id=command_id
    )
    ack = await _await_ack(
        request,
        topic_cancel_symbol_ack(gateway_id),
        match={"symbol": symbol},
    )
    return _require_accepted(ack, "KILL_SWITCH_REJECTED")


@router.post(
    "/gateways/{gateway_id}/kill-switch",
    response_model=KillSwitchGatewayAck,
    summary="Kill switch: one gateway",
    responses=docs.merge(
        docs.ok(docs.ADMIN_KILL_GATEWAY_REPLY, "What the engine cancelled."),
        docs.conflict(
            "KILL_SWITCH_REJECTED",
            "Gateway-targeted kill switch is only allowed for ADMIN participants",
        ),
    ),
)
async def kill_switch_gateway(  # pyright: ignore[reportUnusedFunction]
    gateway_id: GatewayIdPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
    body: AdminNoteRequest | None = None,
) -> dict[str, Any]:
    """Cancel every resting order/quote belonging to *gateway_id*.

    Unlike ``POST /mass-cancel`` (self-service, caller's own gateway only),
    this lets an ADMIN act on a *named* other gateway. It does not disconnect
    it -- that is ``POST /admin/gateways/{gateway_id}/disconnect``.
    """
    caller = await require_admin(request, session)
    _check_rate_limit(request, session)
    note = body.reason if body is not None and body.reason else ""
    command_id = new_command_id()
    request.app.state.engine.send_kill_switch_gateway(
        caller,
        gateway_id.upper(),
        note=note,
        command_id=command_id,
    )
    ack = await _await_ack(
        request,
        topic_kill_switch_gateway_ack(caller),
        match={"command_id": command_id},
    )
    return _require_accepted(ack, "KILL_SWITCH_REJECTED")


@router.post(
    "/market/kill-switch",
    response_model=KillSwitchGlobalAck,
    summary="Kill switch: whole market",
    responses=docs.merge(
        docs.ok(docs.ADMIN_KILL_GLOBAL_REPLY, "What the engine cancelled."),
        docs.conflict(
            "KILL_SWITCH_REJECTED",
            "Global kill switch is only allowed for ADMIN participants",
        ),
    ),
)
async def kill_switch_market(  # pyright: ignore[reportUnusedFunction]
    request: Request,
    session: Annotated[Session, Depends(auth)],
    body: AdminNoteRequest | None = None,
) -> dict[str, Any]:
    """Full-market emergency stop: cancel every resting order/quote for every
    gateway. Distinct from ``POST /admin/symbols/{symbol}/halt`` applied
    symbol-by-symbol — this cancels resting exposure outright rather than
    halting trading.
    """
    gateway_id = await require_admin(request, session)
    _check_rate_limit(request, session)
    note = body.reason if body is not None and body.reason else ""
    command_id = new_command_id()
    request.app.state.engine.send_kill_switch_global(
        gateway_id, note=note, command_id=command_id
    )
    ack = await _await_ack(
        request,
        topic_kill_switch_global_ack(gateway_id),
        match={"command_id": command_id},
    )
    return _require_accepted(ack, "KILL_SWITCH_REJECTED")


# ---------------------------------------------------------------------------
# Cross-gateway order views
# ---------------------------------------------------------------------------


@router.get(
    "/orders",
    response_model=AdminOrders,
    summary="All orders, all gateways",
    responses=docs.merge(
        docs.ok(
            docs.ADMIN_ORDERS, "Matching orders from the gateway's read model.", 200
        )
    ),
)
async def admin_orders(  # pyright: ignore[reportUnusedFunction]
    request: Request,
    session: Annotated[Session, Depends(auth)],
    symbol: Annotated[
        str | None, Query(description="Only this symbol (case-insensitive).")
    ] = None,
    gateway_id: Annotated[
        str | None, Query(description="Only this gateway's orders (case-insensitive).")
    ] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Only this status, e.g. `NEW` or `PARTIAL`."),
    ] = None,
) -> dict[str, Any]:
    """Every cached order across every gateway, filtered.

    Served from the gateway's own read model of every order whose events it
    has seen since it started -- no engine round trip. This is *current
    state*, bounded by
    `order_retention_sec`: terminal orders age out, so it answers "what is
    open now", not "what happened today". For the latter, see
    `GET /admin/orders/{order_id}/audit`.
    """
    await require_admin(request, session)
    orders = request.app.state.engine.all_orders()

    wanted_symbol = symbol.upper() if symbol else None
    wanted_gateway = gateway_id.upper() if gateway_id else None
    wanted_status = status_filter.upper() if status_filter else None

    filtered = [
        {"client_tag": None, **order}
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


@router.get(
    "/orders/{order_id}/audit",
    response_model=OrderAudit,
    summary="Audit trail of one order",
    responses=docs.merge(
        docs.ok(
            docs.ADMIN_ORDER_LIFECYCLE,
            "The order's events, oldest first. `payload` is the original engine "
            "message as a JSON string.",
            200,
        ),
        docs.not_found("UNKNOWN_ORDER", "No audited events for order 9f2c..."),
    ),
)
async def admin_order_lifecycle(  # pyright: ignore[reportUnusedFunction]
    order_id: OrderIdPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
    limit: Annotated[
        int, Query(ge=1, le=5000, description="Maximum events to return (1-5000).")
    ] = 500,
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


@router.get(
    "/gateways/{gateway_id}/positions",
    response_model=GatewayPositions,
    summary="Positions of any gateway",
    responses=docs.merge(
        docs.ok(docs.ADMIN_POSITIONS, "Net positions held by the gateway.", 200)
    ),
)
async def admin_positions(  # pyright: ignore[reportUnusedFunction]
    gateway_id: GatewayIdPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    """Ask the engine what *gateway_id* -- any gateway, not just the
    caller's own -- is holding: signed net qty and VWAP average cost per
    symbol, from the engine's own position ledger.

    ``GET /positions`` is the caller's own view of the same engine round
    trip on ``system.position_request`` / ``system.position_snapshot.<id>``,
    enriched with prices and P&L; ``pm-alf-console``'s and ``pm-alf-gwy``'s
    ``POS|GW=<gateway_id>`` use the same pair, so all surfaces agree.
    """
    await require_admin(request, session)
    target = gateway_id.upper()
    request.app.state.engine.request_position(target)
    reply = await _await_reply(request, topic_position_snapshot(target))
    positions = reply.get("positions", [])
    if not isinstance(positions, list):
        positions = []
    return {"gateway_id": target, "count": len(positions), "positions": positions}
