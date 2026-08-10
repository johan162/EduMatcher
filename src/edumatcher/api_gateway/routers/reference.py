"""Reference-data, status, and health REST endpoints."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from edumatcher.api_gateway.sessions import Session, auth, require_trading

router = APIRouter(prefix="/api/v1", tags=["reference"])


async def _request_reply(
    request: Request, send: str, topic: str, gateway_id: str
) -> dict[str, Any]:
    engine = request.app.state.engine
    if send == "symbols":
        engine.request_symbols(gateway_id)
    elif send == "session":
        engine.request_session(gateway_id)
    elif send == "quote_bootstrap":
        engine.request_quote_bootstrap(gateway_id)
    elif send == "quote_legs":
        engine.request_quote_legs(gateway_id)
    try:
        return cast(
            dict[str, Any],
            await engine.await_topic(
                topic, request.app.state.config.timeouts.engine_reply_sec
            ),
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc


async def fetch_reference_bundle(request: Request, session: Session) -> dict[str, Any]:
    """Fetch the compiled reference-data bundle, one engine round-trip.

    Every /reference/* endpoint below, plus GET /admin/indexes, slices this
    rather than round-tripping separately. There is no
    per-endpoint caching in the gateway: correctness (never serving stale
    data after a reload) is worth more here than shaving one ZMQ round-trip
    off an endpoint nobody is expected to poll at high frequency.

    Open to any valid key, including read-only (``gateway_id is None``)
    credentials — this is metadata, not account data. The reply topic is
    keyed on the caller's identity (falling back to the API key for
    read-only callers, same as history.py's cursor tokens) purely to give
    concurrent callers distinct correlation keys; the payload itself does
    not vary by caller.
    """
    correlation_id = session.gateway_id or session.api_key
    engine = request.app.state.engine
    engine.request_reference(correlation_id)
    try:
        return cast(
            dict[str, Any],
            await engine.await_topic(
                f"system.reference.{correlation_id}",
                request.app.state.config.timeouts.engine_reply_sec,
            ),
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc


@router.get("/reference")
async def reference_bundle(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    return await fetch_reference_bundle(request, session)


@router.get("/reference/config-version")
async def reference_config_version(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    bundle = await fetch_reference_bundle(request, session)
    return {"config_version": bundle.get("config_version")}


@router.get("/reference/symbols")
async def reference_symbols(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    bundle = await fetch_reference_bundle(request, session)
    # A list of objects each carrying its own `symbol`, not a map keyed by it:
    # a client can iterate this without knowing the keys. The bundle is always
    # complete, so there is nothing to default.
    return {
        "symbols": bundle["symbols"],
        "config_version": bundle["config_version"],
    }


@router.get("/reference/risk")
async def reference_risk(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    bundle = await fetch_reference_bundle(request, session)
    risk = cast(dict[str, Any], bundle["risk"])
    return {**risk, "config_version": bundle["config_version"]}


@router.get("/reference/indexes")
async def reference_indexes(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    bundle = await fetch_reference_bundle(request, session)
    return {
        "indexes": bundle.get("indexes", []),
        "config_version": bundle.get("config_version"),
    }


@router.get("/reference/schedule")
async def reference_schedule(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    bundle = await fetch_reference_bundle(request, session)
    # `sessions_enabled`, `country` and a nested `schedule` — the five clock
    # times moved inside the last of those in 6.1e, so that one record could be
    # declared once and carried by `system.session_schedule` too.
    schedule = cast(dict[str, Any], bundle["schedule"])
    return {**schedule, "config_version": bundle["config_version"]}


@router.get("/symbols")
async def symbols(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return await _request_reply(
        request, "symbols", f"system.symbols.{gateway_id}", gateway_id
    )


@router.get("/session")
async def session_state(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return await _request_reply(
        request, "session", f"system.session_status.{gateway_id}", gateway_id
    )


@router.get("/quotes/bootstrap")
async def quote_bootstrap(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return await _request_reply(
        request, "quote_bootstrap", f"system.quote_bootstrap.{gateway_id}", gateway_id
    )


@router.get("/quotes/legs")
async def quote_legs(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    cache = request.app.state.engine.get_caches(gateway_id)
    if cache.quote_legs:
        return {"legs": list(cache.quote_legs.values())}
    return await _request_reply(
        request, "quote_legs", f"system.quote_legs.{gateway_id}", gateway_id
    )


@router.get("/positions")
async def positions(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    cache = request.app.state.engine.get_caches(gateway_id)
    positions_payload = []
    for symbol, qty in sorted(cache.positions.items()):
        last_price = cache.last_prices.get(symbol)
        positions_payload.append(
            {"symbol": symbol, "net_qty": qty, "last_price": last_price}
        )
    return {"positions": positions_payload}


@router.get("/status")
async def status_summary(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    engine = request.app.state.engine
    summary = cast(dict[str, Any], engine.get_caches(gateway_id).status())
    timeout = request.app.state.config.timeouts.engine_reply_sec
    role = await engine.resolve_role(gateway_id, timeout)
    summary["gateway_role"] = role
    if role == "ADMIN":
        engine.request_gateways(gateway_id)
        try:
            reply = cast(
                dict[str, Any],
                await engine.await_topic(f"system.gateways.{gateway_id}", timeout),
            )
        except TimeoutError:
            reply = {}
        gateways = reply.get("gateways", [])
        connected = [
            gw for gw in gateways if isinstance(gw, dict) and bool(gw.get("connected"))
        ]
        summary["gateway_count"] = len(connected)
    return summary


@router.get("/healthz", include_in_schema=False)
async def healthz(request: Request) -> dict[str, Any]:
    engine = request.app.state.engine
    healthy = request.app.state.config.enabled and engine.is_running()
    # dropped_events is the only server-side evidence that a slow WebSocket
    # consumer lost data. A non-zero count does not make the gateway
    # unhealthy — shedding for a slow client is the intended behaviour — but
    # it must be visible, because previously it was not.
    return {
        "ok": healthy,
        "enabled": request.app.state.config.enabled,
        "active_gateways": sorted(engine.active_gateways()),
        "dropped_events": engine.dropped_events,
    }
