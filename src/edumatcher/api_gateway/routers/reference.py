"""Reference-data, status, and health REST endpoints."""

from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import closing
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status


from edumatcher.api_gateway import openapi_docs as docs
from edumatcher.api_gateway.responses import (
    Company,
    ConfigVersion,
    HaltList,
    News,
    Positions,
    QuoteLegList,
    QuoteList,
    ReferenceIndexes,
    ReferenceRiskView,
    ReferenceScheduleView,
    ReferenceSymbols,
    Session as SessionReply,
    Status,
    SymbolList,
)
from edumatcher.api_gateway.routing import ContractRoute
from edumatcher.api_gateway.params import SymbolPath
from edumatcher.api_gateway.sessions import (
    Session,
    auth,
    correlation_id,
    require_trading,
)
from edumatcher.audit.archive import session_timezone
from edumatcher.compdb import store as compdb
from edumatcher.models.generated.rest.system import Reference
from edumatcher.stats.trading_day import timezone_name, trading_date
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

router = APIRouter(prefix="/api/v1", tags=["reference"], route_class=ContractRoute)

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


def _counted(reply: dict[str, Any], key: str) -> dict[str, Any]:
    """Add the D6 ``count`` of the reply's list under *key*."""
    return {**reply, "count": len(reply.get(key, []))}


async def _request_reply(
    request: Request, send: str, topic: str, gateway_id: str
) -> dict[str, Any]:
    engine = request.app.state.engine
    if send == "symbols":
        engine.request_symbols(gateway_id)
    elif send == "halts":
        engine.request_halt_status(gateway_id)
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

    Every /reference/* endpoint below slices this
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


@router.get(
    "/reference",
    response_model=Reference,
    summary="Full reference bundle",
    description=(
        "Everything static about the venue in one round trip: tradable symbols with "
        "tick size, collars, order limits and circuit-breaker ladders; the named risk "
        "levels; index definitions; and the trading schedule. `config_version` is a "
        "hash of the bundle -- compare it to know whether the configuration changed "
        "since you last looked. Open to read-only keys."
    ),
    responses=docs.merge(
        docs.ok(docs.REFERENCE_REPLY, "The compiled reference-data bundle."),
        docs.errors(*docs.ANY_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def reference_bundle(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    return await fetch_reference_bundle(request, session)


@router.get(
    "/reference/config-version",
    response_model=ConfigVersion,
    summary="Reference config version",
    description=(
        "Just the `config_version` hash of the reference bundle -- a cheap way to "
        "detect that the configuration was reloaded (`POST /admin/reference/reload`)."
    ),
    responses=docs.merge(
        docs.ok(docs.REFERENCE_CONFIG_VERSION, "The current hash."),
        docs.errors(*docs.ANY_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def reference_config_version(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    bundle = await fetch_reference_bundle(request, session)
    return {"config_version": bundle.get("config_version")}


@router.get(
    "/reference/symbols",
    response_model=ReferenceSymbols,
    summary="Reference: symbols",
    description=(
        "Per-symbol static configuration. `tick_decimals` is the price scale (2 means "
        "prices move in 0.01 steps). `collar` gives the static and dynamic price bands"
        " in percent, `order_limits` the per-order size and notional caps, and "
        "`circuit_breaker` the halt ladder. Optional blocks are omitted for symbols "
        "without them. For the live, per-caller view (market-maker obligations, "
        "previous close) use `GET /symbols`."
    ),
    responses=docs.merge(
        docs.ok(docs.REFERENCE_SYMBOLS_REPLY, "One entry per tradable symbol."),
        docs.errors(*docs.ANY_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def reference_symbols(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    bundle = await fetch_reference_bundle(request, session)
    # A list of objects each carrying its own `symbol`, not a map keyed by it:
    # a client can iterate this without knowing the keys. The bundle is always
    # complete, so there is nothing to default.
    return {
        "symbols": bundle["symbols"],
        "count": len(bundle["symbols"]),
        "config_version": bundle["config_version"],
    }


@router.get(
    "/reference/risk",
    response_model=ReferenceRiskView,
    summary="Reference: risk levels",
    description=(
        "The named risk levels (price-collar presets) a symbol's `level` refers to, "
        "and the default. Static definitions; for live collar and breaker state per "
        "symbol see `GET /admin/risk/state`."
    ),
    responses=docs.merge(
        docs.ok(docs.REFERENCE_RISK, "The configured risk levels."),
        docs.errors(*docs.ANY_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def reference_risk(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    bundle = await fetch_reference_bundle(request, session)
    risk = cast(dict[str, Any], bundle["risk"])
    return {**risk, "config_version": bundle["config_version"]}


@router.get(
    "/reference/indexes",
    response_model=ReferenceIndexes,
    summary="Reference: indexes",
    description=(
        "Configured exchange indexes: id, description, base value and constituents. "
        "Static configuration only; the live level is on the market-data WebSocket and"
        " in `GET /history/index-daily`."
    ),
    responses=docs.merge(
        docs.ok(docs.REFERENCE_INDEXES_REPLY, "The configured indexes."),
        docs.errors(*docs.ANY_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def reference_indexes(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    bundle = await fetch_reference_bundle(request, session)
    return {
        "indexes": bundle["indexes"],
        "count": len(bundle["indexes"]),
        "config_version": bundle["config_version"],
    }


@router.get(
    "/reference/schedule",
    response_model=ReferenceScheduleView,
    summary="Reference: trading schedule",
    description=(
        "The resolved weekly trading schedule (local wall-clock times per weekday, "
        "holiday override, and the entry in force `today`), the exchange `country` "
        "whose bank holidays apply, and the next holidays. `sessions_enabled: false` "
        "means the venue trades continuously with no daily timeline. Times are in the "
        "exchange timezone (`session_timezone` in `GET /session`)."
    ),
    responses=docs.merge(
        docs.ok(docs.REFERENCE_SCHEDULE, "The trading schedule."),
        docs.errors(*docs.ANY_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def reference_schedule(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    bundle = await fetch_reference_bundle(request, session)
    # `sessions_enabled`, `country` and a nested `schedule` — the resolved
    # weekly table moved inside the last of those in 6.1e, so that one record
    # could be declared once and carried by `system.session_schedule` too.
    schedule = cast(dict[str, Any], bundle["schedule"])
    return {**schedule, "config_version": bundle["config_version"]}


@router.get(
    "/symbols",
    response_model=SymbolList,
    summary="My tradable symbols",
    description=(
        "The symbols the caller can trade, resolved for the caller's gateway. Beyond "
        "`tick_decimals`, a market-maker gateway also sees its quoting obligation "
        "(`enforce_mm_obligation`, `mm_max_spread_ticks`, `mm_min_qty`); `prev_close` "
        "is the last session's closing price when there is one. Requires a trading "
        "key."
    ),
    responses=docs.merge(
        docs.ok(docs.SYMBOLS_REPLY, "Tradable symbols for this gateway."),
        docs.errors(*docs.TRADING_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def symbols(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return _counted(
        await _request_reply(request, "symbols", topic_symbols(gateway_id), gateway_id),
        "symbols",
    )


@router.get(
    "/news",
    response_model=News,
    summary="Latest news",
    description=(
        "Headlines from the market simulator (`pm-market-sim`), oldest first, plus "
        "which symbols each sector holds so a headline's `targets` can be mapped to "
        "instruments. `scope` is SYMBOL, SECTOR or MARKET; `status` RUMOUR, CONFIRMED "
        "or RETRACTED; `sentiment` runs from -1 (bad) to +1 (good). Any key, read-only"
        " included. Empty lists when the simulator is not running."
    ),
    responses=docs.merge(
        docs.ok(docs.NEWS_REPLY, "Recent headlines and the sector map."),
        docs.errors(*docs.ANY_KEY, "VALIDATION"),
    ),
)
async def news(
    request: Request,
    session: Annotated[Session, Depends(auth)],
    limit: Annotated[
        int,
        Query(ge=1, le=200, description="Most recent headlines to return (1-200)."),
    ] = 50,
) -> dict[str, Any]:
    """The latest headlines from pm-market-sim, oldest first, plus which
    symbols each sector holds. Any key, read-only ones included: news is
    public. Empty when pm-market-sim is not running."""
    snapshot: dict[str, Any] = request.app.state.sim.news_snapshot(limit)
    return _counted(snapshot, "news")


@router.get(
    "/companies/{symbol}",
    response_model=Company,
    summary="Company profile",
    description=(
        "The fictional company behind a symbol: sector, history, management, and a set"
        " of financial figures with the ratios derived from them (`pe_ratio`, "
        "`ps_ratio`, `net_margin_pct`, ...). Money figures are USD millions "
        "(`*_musd`). Any key, read-only included."
    ),
    responses=docs.merge(
        docs.ok(docs.COMPANY, "The company profile."),
        docs.errors(
            *docs.ANY_KEY,
            "COMPANY_DB_UNAVAILABLE",
            "UNKNOWN_COMPANY",
            "VALIDATION",
            examples={"UNKNOWN_COMPANY": {"message": "No company profile for XYZ"}},
        ),
    ),
)
async def company(
    symbol: SymbolPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
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


async def fetch_session(request: Request, correlation: str) -> dict[str, Any]:
    """The engine's session phase plus the locale a client renders it in.

    Shared with the bootstrap endpoints, so their ``session`` is exactly this.
    ``session_timezone`` is the compiled config's ``locale.session_timezone``
    -- the zone pm-stats records trading days in and every ``date`` filter
    resolves -- and ``session_date`` is today's trading date in it, by the
    gateway's clock. Raises ``TimeoutError`` when the engine does not answer.
    """
    engine = request.app.state.engine
    engine.request_session(correlation)
    reply = cast(
        dict[str, Any],
        await engine.await_topic(
            topic_session_status(correlation),
            request.app.state.config.timeouts.engine_reply_sec,
        ),
    )
    tz = session_timezone()
    return {
        **reply,
        "session_timezone": timezone_name(tz),
        "session_date": trading_date(time.time(), tz),
    }


@router.get(
    "/session",
    response_model=SessionReply,
    summary="Session state",
    description=(
        "The venue's current trading phase: PRE_OPEN, OPENING_AUCTION, CONTINUOUS, "
        "CLOSING_AUCTION or CLOSED. Orders are accepted in every phase except CLOSED, "
        "but only CONTINUOUS matches immediately; the auctions uncross on exit. `next`"
        " is the scheduled next transition. `session_timezone` (IANA) is the zone the "
        "exchange's wall-clock times and every history `date` filter are in, and "
        "`session_date` today's trading date in it. Live phase changes arrive on the "
        "market-data WebSocket `session` channel. Any key, read-only included."
    ),
    responses=docs.merge(
        docs.ok(docs.SESSION, "The current session state."),
        docs.errors(*docs.ANY_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def session_state(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    try:
        return await fetch_session(request, correlation_id(session))
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc


@router.get(
    "/halts",
    response_model=HaltList,
    summary="Halted symbols",
    description=(
        "Symbols currently halted, with when the halt lapses (`resume_at_ns`, absent "
        "for an indefinite halt), the circuit-breaker `level` that triggered it and "
        "its `halt_source`. An empty list means nothing is halted. Any key, read-only "
        "included."
    ),
    responses=docs.merge(
        docs.ok(docs.HALTS_REPLY, "Currently halted symbols."),
        docs.errors(*docs.ANY_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def halts(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    """Currently-halted symbols, for any caller (§H4, C5).

    The halt_status_request/halt_status pair carries no gateway-scoped state,
    and every client needs it -- at login (bootstrap) and again on every
    market-data reconnect, since a halt missed while disconnected would
    otherwise leave a stale badge for the rest of the session.
    """
    correlation = correlation_id(session)
    return _counted(
        await _request_reply(
            request, "halts", topic_halt_status(correlation), correlation
        ),
        "halted",
    )


@router.get(
    "/quotes",
    response_model=QuoteList,
    summary="My active quotes",
    description=(
        "The caller's active market-maker quotes: both legs' order ids, sizes, "
        "remaining quantities, statuses and prices."
    ),
    responses=docs.merge(
        docs.ok(docs.QUOTES_REPLY, "Active quotes for this gateway."),
        docs.errors(*docs.TRADING_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def active_quotes(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    return _counted(
        await _request_reply(
            request, "quote_bootstrap", topic_quote_bootstrap(gateway_id), gateway_id
        ),
        "quotes",
    )


@router.get(
    "/quotes/legs",
    response_model=QuoteLegList,
    summary="My quote legs",
    description=(
        "Every leg of the caller's quotes, one row per side, with filled and remaining"
        " quantity."
    ),
    responses=docs.merge(
        docs.ok(docs.QUOTE_LEGS_REPLY, "Quote legs for this gateway."),
        docs.errors(*docs.TRADING_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def quote_legs(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    # Always the engine: the gateway's leg cache holds the legs alone, not the
    # `recent`/`show_requested`/`complete` the reply is declared with.
    gateway_id = require_trading(session)
    return _counted(
        await _request_reply(
            request, "quote_legs", topic_quote_legs(gateway_id), gateway_id
        ),
        "legs",
    )


@router.get(
    "/positions",
    response_model=Positions,
    summary="My positions",
    description=(
        "Net position per symbol for the caller's own gateway. `net_qty` is signed "
        "(negative is short); `avg_cost` the volume-weighted entry price. "
        "`market_value` and `unrealized_pnl` are priced at `last_price` and are `null`"
        " until a trade has printed. `realized_pnl_session`/`_mtd`/`_ytd` come from "
        "the clearing ledger and are `null` when clearing is not deployed."
    ),
    responses=docs.merge(
        docs.ok(docs.POSITIONS_REPLY, "Net positions, sorted by symbol."),
        docs.errors(*docs.TRADING_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def positions(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    try:
        rows = await fetch_positions(request, gateway_id)
        return {"positions": rows, "count": len(rows)}
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
        ) from exc


async def fetch_positions(request: Request, gateway_id: str) -> list[dict[str, Any]]:
    """Net position rows for *gateway_id*, as ``GET /positions`` serves them (M4).

    Shared with the bootstrap endpoints so the two cannot disagree. Raises
    ``TimeoutError`` when the engine does not answer.

    A genuine engine round trip on ``system.position_request`` /
    ``system.position_snapshot.<gateway_id>`` -- the same pair
    ``GET /admin/gateways/{gateway_id}/positions`` uses -- rather than this
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
    engine = request.app.state.engine
    cache = engine.get_caches(gateway_id)
    realized = _period_realized_pnl(request, gateway_id)
    engine.request_position(gateway_id)
    reply = cast(
        dict[str, Any],
        await engine.await_topic(
            topic_position_snapshot(gateway_id),
            request.app.state.config.timeouts.engine_reply_sec,
        ),
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
    return positions_payload


@router.get(
    "/status",
    response_model=Status,
    summary="Who am I",
    description=(
        "The caller's gateway id and engine role (TRADER, MARKET_MAKER or ADMIN). "
        "For ADMIN gateways it also reports `gateway_count`, the number of "
        "connected gateways. Requires a trading key."
    ),
    responses=docs.merge(
        docs.ok(docs.STATUS_REPLY, "Gateway summary."), docs.errors(*docs.TRADING_KEY)
    ),
)
async def status_summary(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    gateway_id = require_trading(session)
    engine = request.app.state.engine
    timeout = request.app.state.config.timeouts.engine_reply_sec
    role = await engine.resolve_role(gateway_id, timeout)
    summary: dict[str, Any] = {"gateway_id": gateway_id, "gateway_role": role}
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
async def healthz(request: Request, response: Response) -> dict[str, Any]:
    engine = request.app.state.engine
    healthy = request.app.state.config.enabled and engine.is_running()
    if not healthy:
        # Probes (container, load balancer) read the status, not the body.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
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
