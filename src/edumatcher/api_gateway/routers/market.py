"""Market-data snapshot REST endpoints: the book as of now, without a WebSocket.

Served from the gateway's ``MarketDataCache``, the same latest-snapshot-per-topic
store that answers a WebSocket ``snapshot``. The engine publishes a book when it
changes, so a quiet symbol may have nothing cached; the first read then asks the
engine to publish it (``book.snapshot_request``) and waits for that publish.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from edumatcher.api_gateway import openapi_docs as docs
from edumatcher.api_gateway.market_cache import MarketDataCache
from edumatcher.api_gateway.params import SymbolPath
from edumatcher.api_gateway.responses import BookSummaries, BookView
from edumatcher.api_gateway.routers.reference import fetch_reference_bundle
from edumatcher.api_gateway.routing import ContractRoute
from edumatcher.api_gateway.sessions import Session, auth
from edumatcher.models.generated.book import topic_book_snapshot

router = APIRouter(prefix="/api/v1", tags=["market-data"], route_class=ContractRoute)

#: Upper bound of ``levels``; the engine publishes every level.
MAX_LEVELS = 100
DEFAULT_LEVELS = 10


def _ticks(price: float, tick_decimals: int) -> int:
    return round(price * float(10**tick_decimals))


def _optional_ticks(price: float | None, tick_decimals: int) -> int | None:
    return None if price is None else _ticks(price, tick_decimals)


def _level(level: dict[str, Any], tick_decimals: int) -> dict[str, Any]:
    return {**level, "price_ticks": _ticks(level["price"], tick_decimals)}


def _stamp(event: dict[str, Any]) -> dict[str, Any]:
    data = event["data"]
    return {
        "symbol": data["symbol"],
        "tick_decimals": data["tick_decimals"],
        "ts_ns": data["ts_ns"],
        "seq": event["seq"],
    }


def _book_view(event: dict[str, Any], levels: int) -> dict[str, Any]:
    data = event["data"]
    td = int(data["tick_decimals"])
    view: dict[str, Any] = {
        **_stamp(event),
        "bids": [_level(lvl, td) for lvl in data["bids"][:levels]],
        "asks": [_level(lvl, td) for lvl in data["asks"][:levels]],
        "last_price": data.get("last_price"),
        "last_price_ticks": _optional_ticks(data.get("last_price"), td),
        "last_qty": data.get("last_qty"),
    }
    for side in ("buy", "sell"):
        price = data.get(f"last_{side}_price")
        view[f"last_{side}_price"] = price
        view[f"last_{side}_price_ticks"] = _optional_ticks(price, td)
    view["recent_trades"] = [
        {**trade, "price_ticks": _ticks(trade["price"], td)}
        for trade in data["recent_trades"]
    ]
    return view


def _book_summary(event: dict[str, Any]) -> dict[str, Any]:
    data = event["data"]
    td = int(data["tick_decimals"])
    bids, asks = data["bids"], data["asks"]
    return {
        **_stamp(event),
        "best_bid": _level(bids[0], td) if bids else None,
        "best_ask": _level(asks[0], td) if asks else None,
        "last_price": data.get("last_price"),
        "last_price_ticks": _optional_ticks(data.get("last_price"), td),
    }


def _engine_timeout(exc: TimeoutError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": {"code": "ENGINE_TIMEOUT", "message": str(exc)}},
    )


async def _publish_books(request: Request, symbols: list[str]) -> None:
    """Ask the engine to publish *symbols* and wait until the cache has them."""
    engine = request.app.state.engine
    timeout = request.app.state.config.timeouts.engine_reply_sec
    waits = [
        asyncio.ensure_future(engine.await_topic(topic_book_snapshot(symbol), timeout))
        for symbol in symbols
    ]
    # Let every wait register before any request goes out, so a fast publish
    # cannot beat the wait it answers.
    await asyncio.sleep(0)
    for symbol in symbols:
        engine.request_book_snapshot(symbol)
    for outcome in await asyncio.gather(*waits, return_exceptions=True):
        if isinstance(outcome, TimeoutError):
            raise _engine_timeout(outcome)
        if isinstance(outcome, BaseException):
            raise outcome


@router.get(
    "/book/{symbol}",
    response_model=BookView,
    summary="Order book snapshot",
    description=(
        "The latest aggregated book for one symbol: bid and ask levels (best first, "
        "iceberg orders at their displayed size), the last trade and the last five "
        "prints. Every price comes twice, as a display price and as `*_ticks`. "
        "`seq` is the sequence of the WebSocket `book` frame for the same "
        "snapshot: a client that reads this and then subscribes ignores frames "
        "with `seq` at or below it. The engine publishes a book when it changes, so "
        "a quiet book keeps an old `ts_ns` and is still current. Any key, "
        "read-only included."
    ),
    responses=docs.merge(
        docs.ok(docs.BOOK_REPLY, "The latest snapshot."),
        docs.errors(
            *docs.ANY_KEY,
            "ENGINE_TIMEOUT",
            "UNKNOWN_SYMBOL",
            "VALIDATION",
            examples={"UNKNOWN_SYMBOL": {"message": "Unknown symbol XYZ"}},
        ),
    ),
)
async def book(
    symbol: SymbolPath,
    request: Request,
    session: Annotated[Session, Depends(auth)],
    levels: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_LEVELS,
            description="How many price levels to return per side.",
        ),
    ] = DEFAULT_LEVELS,
) -> dict[str, Any]:
    symbol = symbol.upper()
    cache: MarketDataCache = request.app.state.engine.market_cache
    if not cache.snapshot(symbol, "book"):
        # Nothing cached: either a quiet book or no such symbol. The engine
        # answers only for a symbol it has, so check before waiting on it.
        bundle = await fetch_reference_bundle(request, session)
        if symbol not in {str(s["symbol"]).upper() for s in bundle["symbols"]}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": {
                        "code": "UNKNOWN_SYMBOL",
                        "message": f"Unknown symbol {symbol}",
                    }
                },
            )
        await _publish_books(request, [symbol])
    return _book_view(cache.snapshot(symbol, "book")[0], levels)


@router.get(
    "/book",
    response_model=BookSummaries,
    summary="Top of book, all symbols",
    description=(
        "Best bid, best ask and last price for every symbol in the reference "
        "data, sorted by symbol, from the same snapshots as `GET /book/{symbol}` "
        "(`seq` and `ts_ns` mean the same). A side with no orders is `null`. "
        "Any key, read-only included."
    ),
    responses=docs.merge(
        docs.ok(docs.BOOK_LIST_REPLY, "One entry per symbol."),
        docs.errors(*docs.ANY_KEY, "ENGINE_TIMEOUT"),
    ),
)
async def book_list(
    request: Request, session: Annotated[Session, Depends(auth)]
) -> dict[str, Any]:
    # The reference bundle, not the cache, says which symbols exist: the cache
    # holds only the books the engine has published since this gateway started.
    bundle = await fetch_reference_bundle(request, session)
    symbols = sorted({str(s["symbol"]).upper() for s in bundle["symbols"]})
    cache: MarketDataCache = request.app.state.engine.market_cache
    missing = [s for s in symbols if not cache.snapshot(s, "book")]
    if missing:
        await _publish_books(request, missing)
    books = [_book_summary(cache.snapshot(s, "book")[0]) for s in symbols]
    return {"books": books, "count": len(books)}
