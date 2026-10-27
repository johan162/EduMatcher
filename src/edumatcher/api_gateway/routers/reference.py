"""Reference-data, status, and health REST endpoints."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status


from edumatcher.api_gateway.sessions import Session, auth, require_trading
from edumatcher.compdb import store as compdb
from edumatcher.clearing.query import (
    PeriodRealizedPnl,
    open_readonly_connection,
    query_period_realized_pnl,
)
from edumatcher.models.generated.system import (
    topic_gateways,
    topic_halt_status,
    topic_position_snapshot,
    topic_quote_bootstrap,
    topic_quote_legs,
    topic_reference,
    topic_session_status,
    topic_symbols,
)

router = APIRouter(prefix="/api/v1", tags=["reference"])

log = logging.getLogger(__name__)

#: Clearing is reachable but has no closed trades for this symbol.
_NO_REALIZED_PNL = PeriodRealizedPnl(session=0.0, mtd=0.0, ytd=0.0)


def _period_realized_pnl(
    request: Request, gateway_id: str
) -> dict[str, PeriodRealizedPnl] | None:
    """Per-symbol realized P&L from clearing, or ``None`` if unavailable.

    Realized P&L is a nicety on a positions row, not the point of it: a
    venue running without pm-clearing, or one whose ledger is momentarily
    locked, should still get its positions. Every failure therefore
    degrades to ``None`` -- rendered as "no data" -- rather than failing
    the request.
    """
    db_path = request.app.state.config.clearing_db
    try:
        conn = open_readonly_connection(db_path)
    except FileNotFoundError:
        return None
    except sqlite3.Error:
        log.warning("positions: cannot open clearing DB %s", db_path, exc_info=True)
        return None
    try:
        return query_period_realized_pnl(conn, gateway_id=gateway_id)
    except sqlite3.Error:
        log.warning("positions: clearing DB read failed", exc_info=True)
        return None
    finally:
        conn.close()


async def _request_reply(
    request: Request, send: str, topic: str, gateway_id: str
) -> dict[str, Any]:
    engine = request.app.state.engine
    if send == "symbols":
        engine.request_symbols(gateway_id)
    elif send == "session":
        engine.request_session(gateway_id)
    elif send == "halts":
        engine.request_halt_status(gateway_id)
    elif send == "positions":
        engine.request_position(gateway_id)
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
                topic_reference(correlation_id),
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
    # `sessions_enabled`, `country` and a nested `schedule` — the resolved
    # weekly table moved inside the last of those in 6.1e, so that one record
    # could be declared once and carried by `system.session_schedule` too.
    schedule = cast(dict[str, Any], bundle["schedule"])
    return {**schedule, "config_version": bundle["config_version"]}


@router.get("/symbols")
async def symbols(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return await _request_reply(
        request, "symbols", topic_symbols(gateway_id), gateway_id
    )


@router.get("/news")
async def news(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """The latest headlines from pm-market-sim, oldest first, plus which
    symbols each sector holds. Any key, read-only ones included: news is
    public. Empty when pm-market-sim is not running."""
    snapshot: dict[str, Any] = request.app.state.sim.news_snapshot(limit)
    return snapshot


@router.get("/companies/{symbol}")
async def company(
    symbol: str, request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    """One company profile from ``<DATA_DIR>/companies.db`` (pm-compdb-cli's
    default), stored and derived columns alike, opened read-only. Any key,
    read-only ones included: the profiles are public. 503 when the database
    is missing or unreadable, 404 when it has no row for *symbol*."""
    try:
        with closing(compdb.connect(compdb.COMPANIES_DB, readonly=True)) as conn:
            row = compdb.get(conn, symbol)
    except (compdb.CompanyError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "COMPANY_DB_UNAVAILABLE",
                    "message": f"Cannot read the company database: {exc}",
                }
            },
        ) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "UNKNOWN_COMPANY",
                    "message": f"No company profile for {symbol.upper()}",
                }
            },
        )
    return row


@router.get("/session")
async def session_state(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return await _request_reply(
        request, "session", topic_session_status(gateway_id), gateway_id
    )


@router.get("/halts")
async def halts(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    """Currently-halted symbols, for TRADER/MARKET_MAKER (§H4).

    Same engine query as ``GET /admin/halts``, without the ADMIN-role gate:
    the halt_status_request/halt_status pair carries no admin-only state, and
    a trading gateway needs it too — at login (bootstrap) and again on every
    market-data reconnect, since a halt missed while disconnected would
    otherwise leave a stale badge for the rest of the session.
    """
    gateway_id = require_trading(session)
    return await _request_reply(
        request, "halts", topic_halt_status(gateway_id), gateway_id
    )


@router.get("/quotes/bootstrap")
async def quote_bootstrap(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return await _request_reply(
        request, "quote_bootstrap", topic_quote_bootstrap(gateway_id), gateway_id
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
        request, "quote_legs", topic_quote_legs(gateway_id), gateway_id
    )


@router.get("/positions")
async def positions(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    """Net position per symbol for the caller's own gateway (M4).

    A genuine engine round trip on ``system.position_request`` /
    ``system.position_snapshot.<gateway_id>`` -- the same pair
    ``GET /admin/positions`` uses for any gateway -- rather than this
    process's own local fill cache (``SessionCaches.positions``), which
    reads flat after a gateway restart even though the engine still holds
    the position. ``last_price`` still comes from this cache: it tracks
    venue-wide trade prints, not the position calculation itself. The
    returned rows also include the engine's VWAP ``avg_cost`` plus market
    value and unrealized P&L derived from the live fill cache.

    Realized P&L comes from ``clearing.db`` instead, over three windows:
    ``realized_pnl_session`` (today's trading day), ``realized_pnl_mtd``
    and ``realized_pnl_ytd``. pm-clearing records it per trading day and
    keeps it for good, so unlike the in-memory fill cache it survives a
    gateway restart. All three are ``null`` when clearing is not deployed,
    and lag a fill by up to one clearing flush (5s by default).
    """
    gateway_id = require_trading(session)
    cache = request.app.state.engine.get_caches(gateway_id)
    realized = _period_realized_pnl(request, gateway_id)
    reply = await _request_reply(
        request, "positions", topic_position_snapshot(gateway_id), gateway_id
    )
    raw_positions = reply.get("positions", [])
    if not isinstance(raw_positions, list):
        raw_positions = []
    positions_payload = []
    for entry in raw_positions:
        if not isinstance(entry, dict):
            continue
        symbol = str(entry.get("symbol", ""))
        qty = int(entry.get("net_qty", 0) or 0)
        avg_cost = float(entry.get("avg_cost", 0.0) or 0.0)
        last_price = cache.last_prices.get(symbol)
        # A symbol clearing has no rows for has simply closed nothing yet,
        # which is a real zero -- only an unreachable ledger is unknown.
        period = None if realized is None else realized.get(symbol, _NO_REALIZED_PNL)
        positions_payload.append(
            {
                "symbol": symbol,
                "net_qty": qty,
                "avg_cost": avg_cost,
                "last_price": last_price,
                "market_value": None if last_price is None else qty * float(last_price),
                "unrealized_pnl": (
                    None if last_price is None else qty * (float(last_price) - avg_cost)
                ),
                "realized_pnl_session": None if period is None else period.session,
                "realized_pnl_mtd": None if period is None else period.mtd,
                "realized_pnl_ytd": None if period is None else period.ytd,
            }
        )
    positions_payload.sort(key=lambda p: str(p["symbol"]))
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
                await engine.await_topic(topic_gateways(gateway_id), timeout),
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
