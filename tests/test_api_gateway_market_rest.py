"""WP-API10: ``GET /book/{symbol}`` and ``GET /book`` serve the book over REST.

Drives the real app through raw ASGI calls (``tests/api_gateway_harness.py``)
with a fake engine that has the one behaviour the endpoints depend on: it
publishes ``book.<SYM>`` into the gateway's market-data cache when asked, and
only for a symbol it holds.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.api_gateway import openapi_docs as docs
from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.events import envelope
from edumatcher.api_gateway.market_cache import MarketDataCache
from edumatcher.api_gateway.routers import market
from edumatcher.models.generated.book import topic_book_snapshot
from edumatcher.models.generated.system import topic_reference
from tests.api_gateway_harness import (
    READ_ONLY_KEY,
    TRADER_KEY,
    call,
    check_contract,
    make_app,
)


def _book(symbol: str = "AAPL", **overrides: Any) -> dict[str, Any]:
    """An engine ``book.<SYM>`` payload (display prices) for a 2-decimal symbol."""
    return {
        **docs.BOOK_SNAPSHOT,
        "symbol": symbol,
        "recent_trades": [],
        **overrides,
    }


class FakeEngine:
    def __init__(self, held: dict[str, dict[str, Any]], listed: list[str]) -> None:
        self.market_cache = MarketDataCache()
        #: what the engine would publish on request, by symbol
        self.held = held
        self.listed = listed
        self.calls: list[tuple[str, str]] = []
        self._waiters: dict[str, list[asyncio.Future[dict[str, Any]]]] = {}
        self._seq = 100

    def publish(self, symbol: str) -> None:
        self._seq += 1
        topic = topic_book_snapshot(symbol)
        self.market_cache.record(envelope(topic, self.held[symbol], seq=self._seq))
        for future in self._waiters.pop(topic, []):
            future.set_result(self.held[symbol])

    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
        return True, ""

    def request_reference(self, correlation: str) -> None:
        self.calls.append(("request", "reference"))

    def request_book_snapshot(self, symbol: str) -> None:
        self.calls.append(("request", symbol))
        if symbol in self.held:
            self.publish(symbol)

    async def await_topic(self, topic: str, timeout: float) -> dict[str, Any]:
        self.calls.append(("await", topic))
        if topic.startswith(topic_reference("")):
            return {
                "symbols": [{"symbol": s} for s in self.listed],
                "config_version": "abc",
            }
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._waiters.setdefault(topic, []).append(future)
        try:
            return await asyncio.wait_for(future, timeout=0.05)
        except TimeoutError as exc:
            raise TimeoutError(f"Timed out waiting for {topic}") from exc


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _get(engine: FakeEngine, path: str, key: str = READ_ONLY_KEY) -> Any:
    return await call(make_app(engine), "GET", path, authorization=f"Bearer {key}")


@pytest.mark.anyio
async def test_a_cached_book_is_served_without_asking_the_engine() -> None:
    engine = FakeEngine({"AAPL": _book()}, ["AAPL"])
    engine.publish("AAPL")
    engine.calls.clear()

    status, _, body = await _get(engine, "/api/v1/book/aapl")

    assert status == 200
    assert engine.calls == []
    assert body["symbol"] == "AAPL"
    assert body["seq"] == 101
    assert body["ts_ns"] == docs.BOOK_SNAPSHOT["ts_ns"]
    assert [lvl["price"] for lvl in body["bids"]] == [186.9, 186.85, 186.8]
    assert [lvl["price_ticks"] for lvl in body["bids"]] == [18690, 18685, 18680]
    assert [lvl["price_ticks"] for lvl in body["asks"]] == [18695, 18700, 18710]
    assert body["last_price_ticks"] == 18695
    assert body["last_sell_price_ticks"] == 18690


@pytest.mark.anyio
async def test_a_trading_key_reads_it_too() -> None:
    engine = FakeEngine({"AAPL": _book()}, ["AAPL"])
    engine.publish("AAPL")
    status, _, _ = await _get(engine, "/api/v1/book/AAPL", TRADER_KEY)
    assert status == 200


@pytest.mark.anyio
async def test_levels_cuts_each_side() -> None:
    engine = FakeEngine({"AAPL": _book()}, ["AAPL"])
    engine.publish("AAPL")
    _, _, body = await _get(engine, "/api/v1/book/AAPL?levels=2")
    assert [lvl["price"] for lvl in body["bids"]] == [186.9, 186.85]
    assert [lvl["price"] for lvl in body["asks"]] == [186.95, 187.0]


@pytest.mark.anyio
@pytest.mark.parametrize("levels", ["0", "101", "x"])
async def test_levels_out_of_range_is_a_validation_error(levels: str) -> None:
    engine = FakeEngine({"AAPL": _book()}, ["AAPL"])
    status, _, body = await _get(engine, f"/api/v1/book/AAPL?levels={levels}")
    assert status == 400
    assert body["error"]["code"] == "VALIDATION"
    assert body["error"]["field"] == "levels"


@pytest.mark.anyio
async def test_a_quiet_book_is_published_on_first_read() -> None:
    engine = FakeEngine({"AAPL": _book()}, ["AAPL"])

    status, _, body = await _get(engine, "/api/v1/book/AAPL")

    assert status == 200
    assert body["seq"] == 101
    # The wait is registered before the request goes out, so a fast publish
    # cannot be missed.
    assert [call for call in engine.calls if call[1] in ("book.AAPL", "AAPL")] == [
        ("await", "book.AAPL"),
        ("request", "AAPL"),
    ]
    # Now cached: the second read asks nothing.
    engine.calls.clear()
    status, _, _ = await _get(engine, "/api/v1/book/AAPL")
    assert status == 200
    assert engine.calls == []


@pytest.mark.anyio
async def test_an_unknown_symbol_is_404_and_the_engine_is_not_asked() -> None:
    engine = FakeEngine({"AAPL": _book()}, ["AAPL"])

    status, _, body = await _get(engine, "/api/v1/book/XYZ")

    assert status == 404
    assert body["error"]["code"] == "UNKNOWN_SYMBOL"
    assert body["error"]["message"] == "Unknown symbol XYZ"
    assert ("request", "XYZ") not in engine.calls


@pytest.mark.anyio
async def test_an_engine_that_does_not_publish_is_a_503_timeout() -> None:
    engine = FakeEngine({}, ["AAPL"])  # configured, but the engine says nothing
    status, _, body = await _get(engine, "/api/v1/book/AAPL")
    assert status == 503
    assert body["error"]["code"] == "ENGINE_TIMEOUT"


@pytest.mark.anyio
async def test_a_missing_key_is_401() -> None:
    engine = FakeEngine({}, [])
    status, _, body = await call(
        make_app(engine), "GET", "/api/v1/book/AAPL", authorization=None
    )
    assert status == 401
    assert body["error"]["code"] == "AUTH"


@pytest.mark.anyio
async def test_prices_are_ticks_at_the_symbols_own_scale() -> None:
    # 0.29 * 100 is 28.999999999999996 in binary floating point.
    four = _book(
        "FX",
        tick_decimals=4,
        bids=[{"price": 1.2345, "qty": 1, "count": 1}],
        asks=[{"price": 1.2347, "qty": 1, "count": 1}],
        last_price=0.2901,
        last_buy_price=None,
        last_sell_price=None,
        recent_trades=[{**docs.BOOK_SNAPSHOT["recent_trades"][0], "price": 1.2345}],
    )
    two = _book("LOW", last_price=0.29, bids=[], asks=[])
    engine = FakeEngine({"FX": four, "LOW": two}, ["FX", "LOW"])

    _, _, fx = await _get(engine, "/api/v1/book/FX")
    _, _, low = await _get(engine, "/api/v1/book/LOW")

    assert fx["bids"][0]["price_ticks"] == 12345
    assert fx["asks"][0]["price_ticks"] == 12347
    assert fx["last_price_ticks"] == 2901
    assert fx["recent_trades"][0]["price_ticks"] == 12345
    assert fx["last_buy_price"] is None and fx["last_buy_price_ticks"] is None
    assert low["last_price_ticks"] == 29


@pytest.mark.anyio
async def test_a_book_that_never_traded_has_null_last_fields() -> None:
    fresh = _book(
        last_price=None, last_qty=None, last_buy_price=None, last_sell_price=None
    )
    engine = FakeEngine({"AAPL": fresh}, ["AAPL"])
    _, _, body = await _get(engine, "/api/v1/book/AAPL")
    for field in ("last_price", "last_price_ticks", "last_qty", "last_sell_price"):
        assert body[field] is None, field


@pytest.mark.anyio
async def test_the_list_asks_only_for_books_that_are_not_cached() -> None:
    held = {s: _book(s) for s in ("AAPL", "MSFT", "TSLA")}
    engine = FakeEngine(held, ["TSLA", "AAPL", "MSFT"])
    engine.publish("MSFT")
    engine.calls.clear()

    status, _, body = await _get(engine, "/api/v1/book")

    assert status == 200
    assert [b["symbol"] for b in body["books"]] == ["AAPL", "MSFT", "TSLA"]
    assert body["count"] == 3
    requested = {symbol for kind, symbol in engine.calls if kind == "request"}
    assert requested == {"reference", "AAPL", "TSLA"}
    first = body["books"][0]
    assert first["best_bid"] == {
        "price": 186.9,
        "qty": 300,
        "count": 2,
        "price_ticks": 18690,
    }
    assert first["best_ask"]["price_ticks"] == 18695
    assert first["last_price_ticks"] == 18695


@pytest.mark.anyio
async def test_an_empty_side_is_null() -> None:
    engine = FakeEngine({"AAPL": _book(bids=[], asks=[])}, ["AAPL"])
    _, _, body = await _get(engine, "/api/v1/book")
    assert body["books"][0]["best_bid"] is None
    assert body["books"][0]["best_ask"] is None


@pytest.mark.anyio
async def test_the_list_fails_whole_when_one_book_cannot_be_had() -> None:
    engine = FakeEngine({"AAPL": _book()}, ["AAPL", "GHOST"])
    status, _, body = await _get(engine, "/api/v1/book")
    assert status == 503
    assert body["error"]["code"] == "ENGINE_TIMEOUT"


def test_the_documented_examples_are_what_the_handlers_build() -> None:
    event = envelope("book.AAPL", docs.BOOK_SNAPSHOT, seq=docs.BOOK_SEQ)
    assert market._book_view(event, market.MAX_LEVELS) == docs.BOOK_REPLY
    assert market._book_summary(event) == docs.BOOK_LIST_REPLY["books"][0]
    check_contract(market.book, docs.BOOK_REPLY)
    check_contract(market.book_list, docs.BOOK_LIST_REPLY)


@pytest.mark.anyio
async def test_the_real_engine_client_has_the_book_cached_when_the_wait_returns() -> (
    None
):
    """The handler reads the cache right after the wait resolves, so the
    client must have recorded the book by then; the fake above only assumes it."""
    loop = asyncio.get_running_loop()
    with (
        patch(
            "edumatcher.api_gateway.engine_client.make_pusher",
            return_value=MagicMock(closed=False),
        ),
        patch(
            "edumatcher.api_gateway.engine_client.make_subscriber",
            return_value=MagicMock(),
        ),
    ):
        client = EngineClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", loop)

    def engine_answers(symbol: str) -> None:
        # The listener thread hands events to the loop the same way.
        loop.call_soon(client._handle_event, f"book.{symbol}", _book(symbol))

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                engine=client,
                config=SimpleNamespace(timeouts=SimpleNamespace(engine_reply_sec=1.0)),
            )
        )
    )

    with patch.object(client, "request_book_snapshot", engine_answers):
        await market._publish_books(cast(Any, request), ["AAPL", "MSFT"])

    for symbol in ("AAPL", "MSFT"):
        assert (
            client.market_cache.snapshot(symbol, "book")[0]["data"]["symbol"] == symbol
        )
