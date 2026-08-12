"""Bootstrap aggregate endpoints — one-request startup payload per role.

Each endpoint issues all independent engine round-trips in parallel using
``asyncio.gather(..., return_exceptions=True)``.  Fields that require a
best-effort query (``session``, ``halts``, ``gateways``) are set to ``null``
and listed in ``incomplete`` when their query times out.  Fields that are
*required* (``reference`` and ``orders`` for trader/mm; ``reference`` for
admin) return ``503 ENGINE_TIMEOUT`` if they fail — a response without them
would leave the UI in an unrecoverable state at login time.

Design doc: docs-design/EduMatcher-bootstrap-api.md
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import closing
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.api_gateway.events import now_iso
from edumatcher.api_gateway.routers.reference import fetch_reference_bundle
from edumatcher.api_gateway.sessions import (
    Session,
    auth,
    require_admin,
    require_trading,
)
from edumatcher.audit.indexer import index_is_available
from edumatcher.models.generated.order import topic_orders
from edumatcher.models.generated.system import (
    topic_gateways,
    topic_halt_status,
    topic_quote_bootstrap,
    topic_quote_legs,
    topic_session_status,
)
from edumatcher.stats.query import (
    open_readonly_connection,
    query_order_events,
    resolve_session_timezone,
)
from edumatcher.stats.trading_day import trading_date

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bootstrap", tags=["bootstrap"])

# Terminal statuses are not counted in the per-gateway active-order totals.
_TERMINAL = frozenset({"FILLED", "CANCELLED", "EXPIRED", "REJECTED"})

_FILLS_LIMIT_MAX = 500
_FILLS_LIMIT_DEFAULT = 50


# ---------------------------------------------------------------------------
# Internal async helpers — each returns the data or raises an exception.
# The callers use asyncio.gather(return_exceptions=True) so one failure
# never aborts the others.
# ---------------------------------------------------------------------------


async def _fetch_reference(
    request: Request, session: Session
) -> dict[str, Any]:
    """Fetch the compiled reference bundle.  503 on timeout — caller treats
    this as a *required* field and re-raises immediately."""
    return await fetch_reference_bundle(request, session)


async def _fetch_session(
    request: Request, gateway_id: str
) -> dict[str, Any]:
    engine = request.app.state.engine
    timeout = request.app.state.config.timeouts.engine_reply_sec
    engine.request_session(gateway_id)
    return await engine.await_topic(topic_session_status(gateway_id), timeout)


async def _fetch_orders(
    request: Request, gateway_id: str
) -> dict[str, Any]:
    """Fetch active orders.  No cache fallback — stale order state at login
    is more dangerous than a 503."""
    engine = request.app.state.engine
    timeout = request.app.state.config.timeouts.engine_reply_sec
    engine.request_orders(gateway_id)
    return await engine.await_topic(topic_orders(gateway_id), timeout)


def _query_fills_sync(
    config: ApiGatewayConfig, gateway_id: str, fills_limit: int
) -> dict[str, Any]:
    """Blocking stats-DB read for today's fills.

    Raises ``FileNotFoundError`` when the stats DB doesn't exist yet — the
    caller maps that to ``null`` + ``incomplete``.  Runs off the event loop
    via ``asyncio.to_thread`` (see ``_fetch_fills``) so the synchronous SQLite
    I/O never blocks the concurrent engine round-trips.
    """
    conn = open_readonly_connection(config.stats_db)
    with closing(conn) as conn:
        tz, warning = resolve_session_timezone(conn, config.session_timezone)
        if warning is not None:
            log.warning("bootstrap fills: %s", warning)
        today = trading_date(time.time(), tz)
        events, _ = query_order_events(
            conn,
            gateway_id=gateway_id,
            symbol=None,
            event_type="FILL",
            date_value=today,
            from_ts=None,
            to_ts=None,
            limit=fills_limit,
            tz=tz,
        )
    return {"events": events, "count": len(events)}


async def _fetch_fills(
    request: Request, gateway_id: str, fills_limit: int
) -> dict[str, Any]:
    """Fetch today's fills from the stats DB, off the event loop.

    Raises ``FileNotFoundError`` when the stats DB doesn't exist yet — the
    caller maps this to ``null`` + ``incomplete``."""
    return await asyncio.to_thread(
        _query_fills_sync, request.app.state.config, gateway_id, fills_limit
    )


async def _fetch_quote_bootstrap(
    request: Request, gateway_id: str
) -> dict[str, Any]:
    engine = request.app.state.engine
    timeout = request.app.state.config.timeouts.engine_reply_sec
    engine.request_quote_bootstrap(gateway_id)
    return await engine.await_topic(topic_quote_bootstrap(gateway_id), timeout)


async def _fetch_quote_legs(
    request: Request, gateway_id: str
) -> dict[str, Any]:
    engine = request.app.state.engine
    timeout = request.app.state.config.timeouts.engine_reply_sec
    cache = engine.get_caches(gateway_id)
    if cache.quote_legs:
        return {"legs": list(cache.quote_legs.values())}
    engine.request_quote_legs(gateway_id)
    return await engine.await_topic(topic_quote_legs(gateway_id), timeout)


async def _fetch_gateways(
    request: Request, gateway_id: str
) -> dict[str, Any]:
    engine = request.app.state.engine
    timeout = request.app.state.config.timeouts.engine_reply_sec
    engine.request_gateways(gateway_id)
    return await engine.await_topic(topic_gateways(gateway_id), timeout)


async def _fetch_halts(
    request: Request, gateway_id: str
) -> dict[str, Any]:
    engine = request.app.state.engine
    timeout = request.app.state.config.timeouts.engine_reply_sec
    engine.request_halt_status(gateway_id)
    return await engine.await_topic(topic_halt_status(gateway_id), timeout)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _capabilities(request: Request, reference: dict[str, Any]) -> dict[str, Any]:
    """Assemble the capability flags from config and reference data."""
    config = request.app.state.config
    schedule = reference.get("schedule") or {}
    sessions_enabled = bool(schedule.get("sessions_enabled", False))
    return {
        "sessions_enabled": sessions_enabled,
        "stats_db_available": config.stats_db.exists(),
        "audit_db_available": index_is_available(config.audit_db),
        "index_available": request.app.state.index_client.is_running(),
    }


def _positions(request: Request, gateway_id: str) -> list[dict[str, Any]]:
    cache = request.app.state.engine.get_caches(gateway_id)
    return [
        {"symbol": sym, "net_qty": qty, "last_price": cache.last_prices.get(sym)}
        for sym, qty in sorted(cache.positions.items())
    ]


def _active_order_counts(request: Request) -> dict[str, int]:
    """Per-gateway count of non-terminal orders.

    Seeded with ``0`` for every authenticated gateway so a connected gateway
    with no live orders still appears (matching the documented response shape
    and keeping the key set aligned with ``monitor_last_seq``).  Any gateway
    with cached orders but no live session is still counted via the union.
    """
    engine = request.app.state.engine
    counts: dict[str, int] = {gid: 0 for gid in engine.active_gateways()}
    for order in engine.all_orders():
        if str(order.get("status", "")).upper() not in _TERMINAL:
            gid = str(order.get("gateway_id", ""))
            counts[gid] = counts.get(gid, 0) + 1
    return counts


def _monitor_last_seq(request: Request) -> dict[str, int]:
    engine = request.app.state.engine
    return {gid: engine.stream_seq(gid) for gid in sorted(engine.active_gateways())}


def _require_or_503(field_results: list[tuple[str, Any]]) -> dict[str, Any]:
    """Return the required fields as a dict, or raise ``503 ENGINE_TIMEOUT``.

    *field_results* is a list of ``(field_name, value_or_exception)`` pairs
    for the endpoint's *required* fields.  A response missing any of them
    would be unusable at login, so the first exception aborts the whole
    request rather than degrading to a partial payload.
    """
    data: dict[str, Any] = {}
    for name, result in field_results:
        if isinstance(result, Exception):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": {
                        "code": "ENGINE_TIMEOUT",
                        "message": (
                            f"Required bootstrap field '{name}' could not be "
                            f"fetched: {result}"
                        ),
                    }
                },
            )
        data[name] = result
    return data


def _collect_optional(
    field_results: list[tuple[str, Any]],
    data: dict[str, Any],
    incomplete: list[str],
) -> None:
    """Fold optional results into *data* and *incomplete* in place."""
    for name, result in field_results:
        if isinstance(result, Exception):
            data[name] = None
            incomplete.append(name)
        else:
            data[name] = result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/trader")
async def bootstrap_trader(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    fills_limit: int = Query(
        default=_FILLS_LIMIT_DEFAULT,
        ge=1,
        le=_FILLS_LIMIT_MAX,
        description="Maximum number of today's fills to include (1–500).",
    ),
) -> dict[str, Any]:
    """One-request startup payload for TRADER, MARKET_MAKER, and ADMIN roles.

    Returns gateway identity, full reference data, live session state,
    positions, active orders, recent fills for today, and capability flags.
    ``reference`` and ``orders`` are required — the endpoint returns ``503``
    if either cannot be fetched.  All other engine-backed fields (``session``,
    ``recent_fills``) are optional: they appear as ``null`` with their name
    listed in ``incomplete`` on failure.

    Read-only keys (``gateway_id: null``) receive ``gateway_role: "READ_ONLY"``,
    empty ``positions``, and empty ``orders`` without an engine round-trip for
    those fields.
    """
    engine = request.app.state.engine
    timeout = request.app.state.config.timeouts.engine_reply_sec
    gateway_id = session.gateway_id

    # --- read-only credential: reference only -------------------------------
    # A keyless credential has no gateway-scoped state. session and
    # recent_fills are *structurally* unavailable (not transiently failed), so
    # they are returned as null but deliberately kept out of `incomplete` —
    # `incomplete` means "retry the per-resource endpoint", which would never
    # succeed here.  Session phase is still available live on the market-data
    # WebSocket `session` event.
    if gateway_id is None:
        reference = await _fetch_reference(request, session)
        return {
            "ts": now_iso(),
            "incomplete": [],
            "gateway_id": None,
            "gateway_role": "READ_ONLY",
            "reference": reference,
            "session": None,
            "positions": [],
            "orders": {"orders": []},
            "recent_fills": None,
            "capabilities": _capabilities(request, reference),
        }

    # --- trading credential: all sub-queries in parallel --------------------
    gateway_role = await engine.resolve_role(gateway_id, timeout)
    ref_r, sess_r, orders_r, fills_r = await asyncio.gather(
        _fetch_reference(request, session),
        _fetch_session(request, gateway_id),
        _fetch_orders(request, gateway_id),
        _fetch_fills(request, gateway_id, fills_limit),
        return_exceptions=True,
    )

    required = _require_or_503([("reference", ref_r), ("orders", orders_r)])
    reference = required["reference"]

    incomplete: list[str] = []
    data: dict[str, Any] = {}
    _collect_optional(
        [("session", sess_r), ("recent_fills", fills_r)], data, incomplete
    )

    return {
        "ts": now_iso(),
        "incomplete": incomplete,
        "gateway_id": gateway_id,
        "gateway_role": gateway_role,
        "reference": reference,
        "session": data.get("session"),
        "positions": _positions(request, gateway_id),
        "orders": required["orders"],
        "recent_fills": data.get("recent_fills"),
        "capabilities": _capabilities(request, reference),
    }


@router.get("/mm")
async def bootstrap_mm(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    fills_limit: int = Query(
        default=_FILLS_LIMIT_DEFAULT,
        ge=1,
        le=_FILLS_LIMIT_MAX,
        description="Maximum number of today's fills to include (1–500).",
    ),
) -> dict[str, Any]:
    """One-request startup payload for MARKET_MAKER role.

    Superset of ``/bootstrap/trader``: adds ``quote_bootstrap`` (active quote
    state) and ``quote_legs`` (per-leg fill flags and prices).

    Restricted to MARKET_MAKER keys.  TRADER and ADMIN keys receive ``403``.
    ``reference`` and ``orders`` are required (503 on failure).  Quote fields
    and ``session``/``recent_fills`` are optional (null + incomplete).
    """
    engine = request.app.state.engine
    timeout = request.app.state.config.timeouts.engine_reply_sec

    # Read-only keys raise 403 READ_ONLY here; role gate raises 403 ROLE_DENIED.
    gateway_id = require_trading(session)
    role = await engine.resolve_role(gateway_id, timeout)
    if role != "MARKET_MAKER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "ROLE_DENIED",
                    "message": "MARKET_MAKER role required",
                }
            },
        )

    # --- all sub-queries in parallel ----------------------------------------
    (
        ref_r,
        sess_r,
        orders_r,
        fills_r,
        qb_r,
        ql_r,
    ) = await asyncio.gather(
        _fetch_reference(request, session),
        _fetch_session(request, gateway_id),
        _fetch_orders(request, gateway_id),
        _fetch_fills(request, gateway_id, fills_limit),
        _fetch_quote_bootstrap(request, gateway_id),
        _fetch_quote_legs(request, gateway_id),
        return_exceptions=True,
    )

    # --- required fields (503 on failure) -----------------------------------
    required = _require_or_503([("reference", ref_r), ("orders", orders_r)])
    reference = required["reference"]

    # --- optional fields ----------------------------------------------------
    incomplete: list[str] = []
    data: dict[str, Any] = {}
    _collect_optional(
        [
            ("session", sess_r),
            ("recent_fills", fills_r),
            ("quote_bootstrap", qb_r),
            ("quote_legs", ql_r),
        ],
        data,
        incomplete,
    )

    caps = _capabilities(request, reference)

    return {
        "ts": now_iso(),
        "incomplete": incomplete,
        "gateway_id": gateway_id,
        "gateway_role": "MARKET_MAKER",
        "reference": reference,
        "session": data.get("session"),
        "positions": _positions(request, gateway_id),
        "orders": required["orders"],
        "recent_fills": data.get("recent_fills"),
        "capabilities": caps,
        "quote_bootstrap": data.get("quote_bootstrap"),
        "quote_legs": data.get("quote_legs"),
    }


@router.get("/admin")
async def bootstrap_admin(
    request: Request,
    session: Annotated[Session, Depends(auth)],
) -> dict[str, Any]:
    """One-request startup payload for ADMIN role.

    Returns reference data, session state, the full gateway roster, active
    halts, per-gateway active-order counts, per-gateway monitor sequence
    numbers, and capability flags.

    Restricted to ADMIN keys.  ``reference`` is required (503 on failure).
    ``session``, ``gateways``, and ``halts`` are optional (null + incomplete):
    both have the ``/admin/monitor`` WebSocket ``monitor.snapshot`` as an
    immediate fallback.
    """
    gateway_id = await require_admin(request, session)

    # --- all sub-queries in parallel ----------------------------------------
    ref_r, sess_r, gw_r, halts_r = await asyncio.gather(
        _fetch_reference(request, session),
        _fetch_session(request, gateway_id),
        _fetch_gateways(request, gateway_id),
        _fetch_halts(request, gateway_id),
        return_exceptions=True,
    )

    # --- required fields (503 on failure) -----------------------------------
    required = _require_or_503([("reference", ref_r)])
    reference = required["reference"]

    # --- optional fields ----------------------------------------------------
    incomplete: list[str] = []
    data: dict[str, Any] = {}
    _collect_optional(
        [("session", sess_r), ("gateways", gw_r), ("halts", halts_r)],
        data,
        incomplete,
    )

    caps = _capabilities(request, reference)

    return {
        "ts": now_iso(),
        "incomplete": incomplete,
        "gateway_id": gateway_id,
        "gateway_role": "ADMIN",
        "reference": reference,
        "session": data.get("session"),
        "gateways": data.get("gateways"),
        "halts": data.get("halts"),
        "active_order_counts": _active_order_counts(request),
        "monitor_last_seq": _monitor_last_seq(request),
        "capabilities": caps,
    }
