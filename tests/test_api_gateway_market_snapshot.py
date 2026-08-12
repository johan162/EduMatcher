"""Market-data snapshot / resume: the stream cache and the WS verbs.

Covers ``api_gateway/market_cache.py`` and the snapshot/resume handlers added
to ``api_gateway/routers/ws.py``. See
``docs-design/EduMatcher-MarketData-Snapshot-Resume.md``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.events import envelope
from edumatcher.api_gateway.market_cache import (
    MarketDataCache,
    ReplayMiss,
    channel_for_topic,
    event_channel,
)
from edumatcher.api_gateway.routers import ws as ws_mod
from edumatcher.api_gateway.routers.ws import Subscription
from edumatcher.api_gateway.schemas import MarketDataControl

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _book(symbol: str, seq: int, last: float) -> dict[str, Any]:
    return envelope(f"book.{symbol}", {"symbol": symbol, "last_price": last}, seq=seq)


def _depth(symbol: str, seq: int) -> dict[str, Any]:
    return envelope(f"depth.{symbol}", {"symbol": symbol}, seq=seq)


def _trade(symbol: str, seq: int, price: float) -> dict[str, Any]:
    return envelope("trade.executed", {"symbol": symbol, "price": price}, seq=seq)


def _auction_result(symbol: str, seq: int) -> dict[str, Any]:
    return envelope(f"auction.result.{symbol}", {"symbol": symbol}, seq=seq)


def _auction_indicative(symbol: str, seq: int) -> dict[str, Any]:
    return envelope(f"auction.indicative.{symbol}", {"symbol": symbol}, seq=seq)


# ---------------------------------------------------------------------------
# Channel classifiers
# ---------------------------------------------------------------------------


def test_event_channel_mapping() -> None:
    assert event_channel("trade") == "trades"
    assert event_channel("book") == "book"
    assert event_channel("depth") == "depth"
    assert event_channel("auction") == "auction"
    assert event_channel("auction.indicative") == "auction"
    assert event_channel("session") is None
    assert event_channel("circuit_breaker") is None
    assert event_channel("nonsense") is None


def test_channel_for_topic_mapping() -> None:
    assert channel_for_topic("trade.executed") == "trades"
    assert channel_for_topic("book.AAPL") == "book"
    assert channel_for_topic("depth.AAPL") == "depth"
    assert channel_for_topic("auction.result.AAPL") == "auction"
    assert channel_for_topic("auction.indicative.AAPL") == "auction"
    assert channel_for_topic("session.state") is None
    assert channel_for_topic("") is None


# ---------------------------------------------------------------------------
# Cache: snapshots
# ---------------------------------------------------------------------------


def test_book_snapshot_returns_latest() -> None:
    cache = MarketDataCache()
    cache.record(_book("AAPL", 1, 150.0))
    cache.record(_book("AAPL", 2, 151.0))
    snaps = cache.snapshot("AAPL", "book")
    assert len(snaps) == 1
    assert snaps[0]["seq"] == 2
    assert snaps[0]["data"]["last_price"] == 151.0


def test_depth_snapshot_overwrites() -> None:
    cache = MarketDataCache()
    cache.record(_depth("AAPL", 1))
    cache.record(_depth("AAPL", 5))
    snaps = cache.snapshot("AAPL", "depth")
    assert [e["seq"] for e in snaps] == [5]


def test_auction_keeps_both_tenses() -> None:
    cache = MarketDataCache()
    cache.record(_auction_result("AAPL", 3))
    cache.record(_auction_indicative("AAPL", 4))
    snaps = cache.snapshot("AAPL", "auction")
    topics = {e["topic"] for e in snaps}
    assert topics == {"auction.result.AAPL", "auction.indicative.AAPL"}


def test_snapshot_unknown_returns_empty() -> None:
    cache = MarketDataCache()
    assert cache.snapshot("AAPL", "book") == []
    assert cache.snapshot("AAPL", "trades") == []


def test_symbol_is_case_normalised_on_serve() -> None:
    cache = MarketDataCache()
    cache.record(_book("AAPL", 1, 150.0))
    assert cache.snapshot("aapl", "book")[0]["seq"] == 1


# ---------------------------------------------------------------------------
# Cache: trades tail + resume
# ---------------------------------------------------------------------------


def test_trades_tail_in_order() -> None:
    cache = MarketDataCache()
    for seq in (1, 2, 3):
        cache.record(_trade("AAPL", seq, 100.0 + seq))
    tail = cache.snapshot("AAPL", "trades")
    assert [e["seq"] for e in tail] == [1, 2, 3]


def test_resume_trades_returns_after_from_seq() -> None:
    cache = MarketDataCache()
    for seq in (1, 2, 3, 4):
        cache.record(_trade("AAPL", seq, 100.0))
    assert [e["seq"] for e in cache.resume_trades("AAPL", 2)] == [3, 4]


def test_resume_trades_empty_when_nothing_buffered() -> None:
    cache = MarketDataCache()
    assert cache.resume_trades("AAPL", 0) == []


def test_resume_trades_too_old_raises() -> None:
    cache = MarketDataCache()
    # First two prints age out, leaving oldest seq = 3.
    clock = [1000.0]
    with patch("edumatcher.api_gateway.market_cache.time.monotonic", lambda: clock[0]):
        cache = MarketDataCache(window_sec=10)
        cache.record(_trade("AAPL", 1, 100.0))
        cache.record(_trade("AAPL", 2, 100.0))
        clock[0] += 100.0  # push past the window
        cache.record(_trade("AAPL", 3, 100.0))
        # seq 1 and 2 are evicted; oldest retained is 3.
        with pytest.raises(ReplayMiss):
            cache.resume_trades("AAPL", 0)
        # A from_seq at the boundary is still serviceable.
        assert [e["seq"] for e in cache.resume_trades("AAPL", 2)] == [3]


def test_aged_trades_evicted_but_snapshot_kept() -> None:
    clock = [0.0]
    with patch("edumatcher.api_gateway.market_cache.time.monotonic", lambda: clock[0]):
        cache = MarketDataCache(window_sec=10)
        cache.record(_book("AAPL", 1, 150.0))
        cache.record(_trade("AAPL", 1, 100.0))
        clock[0] = 999.0
        # Trade tail aged out ...
        assert cache.snapshot("AAPL", "trades") == []
        # ... but the latest book snapshot is retained regardless of age.
        assert cache.snapshot("AAPL", "book")[0]["seq"] == 1


def test_window_zero_disables_trade_buffer_but_serves_snapshots() -> None:
    cache = MarketDataCache(window_sec=0)
    cache.record(_trade("AAPL", 1, 100.0))
    cache.record(_book("AAPL", 2, 150.0))
    assert cache.snapshot("AAPL", "trades") == []
    assert cache.snapshot("AAPL", "book")[0]["seq"] == 2


# ---------------------------------------------------------------------------
# Cache: wildcard + ingest guards
# ---------------------------------------------------------------------------


def test_snapshot_channel_expands_over_seen_symbols() -> None:
    cache = MarketDataCache()
    cache.record(_book("AAPL", 1, 150.0))
    cache.record(_book("MSFT", 1, 400.0))
    symbols = {e["data"]["symbol"] for e in cache.snapshot_channel("book")}
    assert symbols == {"AAPL", "MSFT"}


def test_snapshot_channel_cold_is_empty() -> None:
    cache = MarketDataCache()
    assert cache.snapshot_channel("book") == []


def test_record_ignores_non_cached_channels() -> None:
    cache = MarketDataCache()
    cache.record(envelope("session.state", {"state": "CONTINUOUS"}, seq=1))
    cache.record(envelope("circuit_breaker.halt.AAPL", {"symbol": "AAPL"}, seq=1))
    assert cache.snapshot_channel("book") == []
    assert cache.snapshot("AAPL", "trades") == []


def test_record_ignores_event_with_no_symbol() -> None:
    cache = MarketDataCache()
    # A trade envelope whose payload has no symbol yields no cache entry.
    cache.record(envelope("trade.executed", {"price": 1.0}, seq=1))
    assert cache.snapshot_channel("trades") == []


def test_snapshot_unknown_channel_is_empty() -> None:
    # A channel with no topic mapping falls through _topics_for to ().
    cache = MarketDataCache()
    cache.record(_book("AAPL", 1, 150.0))
    assert cache.snapshot("AAPL", "not-a-channel") == []


def test_has_topic() -> None:
    cache = MarketDataCache()
    assert not cache.has_topic("book.AAPL")
    cache.record(_book("AAPL", 1, 150.0))
    assert cache.has_topic("book.AAPL")


# ---------------------------------------------------------------------------
# Wiring: EngineClient records market data into the cache
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[EngineClient]:
    loop = asyncio.new_event_loop()
    try:
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
            yield EngineClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", loop)
    finally:
        loop.close()


def test_handle_event_populates_market_cache(client: EngineClient) -> None:
    client._handle_event("book.AAPL", {"symbol": "AAPL", "last_price": 150.0})
    snaps = client.market_cache.snapshot("AAPL", "book")
    assert snaps and snaps[0]["data"]["last_price"] == 150.0


def test_private_events_are_not_cached(client: EngineClient) -> None:
    # order.ack.GW01 is a private, gateway-scoped topic — never market data.
    client._handle_event("order.ack.GW01", {"order_id": "A"})
    assert client.market_cache.snapshot_channel("book") == []


# ---------------------------------------------------------------------------
# WS handler: fake socket
# ---------------------------------------------------------------------------


class _FakeWS:
    """Minimal WebSocket double: queued inbound frames, recorded outbound."""

    def __init__(self, engine: Any, frames: list[dict[str, Any]] | None = None) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(engine=engine))
        self._frames = list(frames or [])
        self.sent: list[dict[str, Any]] = []

    async def receive_json(self) -> dict[str, Any]:
        if not self._frames:
            raise WebSocketDisconnect(code=1000)
        return self._frames.pop(0)

    async def send_json(self, obj: dict[str, Any]) -> None:
        self.sent.append(obj)


def _run(coro: Any) -> None:
    asyncio.new_event_loop().run_until_complete(coro)


def _warm_engine(client: EngineClient) -> None:
    client._handle_event("book.AAPL", {"symbol": "AAPL", "last_price": 150.0})
    client._handle_event("depth.AAPL", {"symbol": "AAPL"})
    for seq_price in ((100.0,), (101.0,), (102.0,)):
        client._handle_event(
            "trade.executed", {"symbol": "AAPL", "price": seq_price[0]}
        )


def test_emit_snapshots_named_symbol(client: EngineClient) -> None:
    _warm_engine(client)
    ws: Any = _FakeWS(client)
    items = [
        MarketDataControl.model_validate(
            {
                "action": "snapshot",
                "items": [{"symbols": ["AAPL"], "channels": ["book"]}],
            }
        ).as_items()[0]
    ]
    _run(ws_mod._emit_snapshots(ws, client.market_cache, items))
    assert [e["type"] for e in ws.sent] == ["book"]


def test_emit_snapshots_wildcard(client: EngineClient) -> None:
    _warm_engine(client)
    client._handle_event("book.MSFT", {"symbol": "MSFT", "last_price": 400.0})
    ws: Any = _FakeWS(client)
    items = MarketDataControl.model_validate(
        {"action": "snapshot", "items": [{"symbols": ["*"], "channels": ["book"]}]}
    ).as_items()
    _run(ws_mod._emit_snapshots(ws, client.market_cache, items))
    symbols = {e["data"]["symbol"] for e in ws.sent}
    assert symbols == {"AAPL", "MSFT"}


def test_emit_snapshots_trades_resume_from(client: EngineClient) -> None:
    _warm_engine(client)  # trades seq 1,2,3
    ws: Any = _FakeWS(client)
    items = MarketDataControl.model_validate(
        {
            "action": "subscribe",
            "items": [
                {
                    "symbols": ["AAPL"],
                    "channels": ["trades"],
                    "resume_from": {"trades": 1},
                }
            ],
        }
    ).as_items()
    _run(ws_mod._emit_snapshots(ws, client.market_cache, items))
    assert [e["seq"] for e in ws.sent] == [2, 3]


def test_emit_resume_trades_replay(client: EngineClient) -> None:
    _warm_engine(client)
    ws: Any = _FakeWS(client)
    control = MarketDataControl.model_validate(
        {
            "action": "resume",
            "topic": "trade.executed",
            "symbols": ["AAPL"],
            "from_seq": 2,
        }
    )
    _run(ws_mod._emit_resume(ws, client.market_cache, control))
    assert [e["seq"] for e in ws.sent] == [3]


def test_emit_resume_trades_too_old_resets(client: EngineClient) -> None:
    clock = [0.0]
    with patch("edumatcher.api_gateway.market_cache.time.monotonic", lambda: clock[0]):
        cache = MarketDataCache(window_sec=10)
        cache.record(_trade("AAPL", 1, 100.0))
        clock[0] = 500.0
        cache.record(_trade("AAPL", 2, 101.0))
        ws: Any = _FakeWS(client)
        control = MarketDataControl.model_validate(
            {
                "action": "resume",
                "topic": "trade.executed",
                "symbols": ["AAPL"],
                "from_seq": 0,
            }
        )
        _run(ws_mod._emit_resume(ws, cache, control))
    types = [e["type"] for e in ws.sent]
    assert types[0] == "trades.reset"
    assert types[1] == "resume.rejected"
    assert ws.sent[1]["data"]["reason"] == "too_old"
    # Followed by the fresh tail (seq 2 survived).
    assert types[2] == "trade"


def test_emit_resume_snapshot_channel_self_heals(client: EngineClient) -> None:
    _warm_engine(client)
    ws: Any = _FakeWS(client)
    control = MarketDataControl.model_validate(
        {"action": "resume", "topic": "book.AAPL", "from_seq": 5}
    )
    _run(ws_mod._emit_resume(ws, client.market_cache, control))
    assert [e["type"] for e in ws.sent] == ["book"]


def test_emit_resume_unknown_topic_rejected(client: EngineClient) -> None:
    ws: Any = _FakeWS(client)
    control = MarketDataControl.model_validate(
        {"action": "resume", "topic": "nonsense.topic", "from_seq": 1}
    )
    _run(ws_mod._emit_resume(ws, client.market_cache, control))
    assert ws.sent[0]["type"] == "resume.rejected"
    assert ws.sent[0]["data"]["reason"] == "unknown_topic"


def test_emit_resume_snapshot_channel_cold_rejected(client: EngineClient) -> None:
    ws: Any = _FakeWS(client)
    control = MarketDataControl.model_validate(
        {"action": "resume", "topic": "book.ZZZZ", "from_seq": 1}
    )
    _run(ws_mod._emit_resume(ws, client.market_cache, control))
    assert ws.sent[0]["type"] == "resume.rejected"


def test_emit_resume_trades_without_symbol_rejected(client: EngineClient) -> None:
    ws: Any = _FakeWS(client)
    # trade.executed is not symbol-qualified, and no symbol supplied.
    control = MarketDataControl.model_validate(
        {"action": "resume", "topic": "trade.executed", "from_seq": 1}
    )
    _run(ws_mod._emit_resume(ws, client.market_cache, control))
    assert ws.sent[0]["type"] == "resume.rejected"
    assert ws.sent[0]["data"]["reason"] == "unknown_topic"


# ---------------------------------------------------------------------------
# WS receiver loop: action dispatch
# ---------------------------------------------------------------------------


def test_receive_subscribe_acks_and_bursts_snapshot(client: EngineClient) -> None:
    _warm_engine(client)
    ws: Any = _FakeWS(
        client,
        frames=[
            {
                "action": "subscribe",
                "items": [{"symbols": ["AAPL"], "channels": ["book"]}],
            }
        ],
    )
    with pytest.raises(WebSocketDisconnect):
        _run(ws_mod._receive_market_controls(ws, Subscription()))
    types = [e["type"] for e in ws.sent]
    assert types[0] == "subscription"  # the ack
    assert "book" in types  # the snapshot burst


def test_receive_snapshot_action(client: EngineClient) -> None:
    _warm_engine(client)
    ws: Any = _FakeWS(
        client,
        frames=[
            {
                "action": "snapshot",
                "items": [{"symbols": ["AAPL"], "channels": ["depth"]}],
            }
        ],
    )
    with pytest.raises(WebSocketDisconnect):
        _run(ws_mod._receive_market_controls(ws, Subscription()))
    assert [e["type"] for e in ws.sent] == ["depth"]


def test_receive_resume_action(client: EngineClient) -> None:
    _warm_engine(client)
    ws: Any = _FakeWS(
        client,
        frames=[
            {
                "action": "resume",
                "topic": "trade.executed",
                "symbols": ["AAPL"],
                "from_seq": 2,
            }
        ],
    )
    with pytest.raises(WebSocketDisconnect):
        _run(ws_mod._receive_market_controls(ws, Subscription()))
    assert [e["seq"] for e in ws.sent] == [3]


def test_receive_unsubscribe_does_not_burst(client: EngineClient) -> None:
    _warm_engine(client)
    ws: Any = _FakeWS(
        client,
        frames=[{"action": "unsubscribe", "symbols": ["AAPL"], "channels": ["book"]}],
    )
    with pytest.raises(WebSocketDisconnect):
        _run(ws_mod._receive_market_controls(ws, Subscription()))
    # Only the subscription ack — no snapshot burst on unsubscribe.
    assert [e["type"] for e in ws.sent] == ["subscription"]


def test_receive_validation_error_is_reported(client: EngineClient) -> None:
    ws: Any = _FakeWS(client, frames=[{"action": "bogus"}])
    with pytest.raises(WebSocketDisconnect):
        _run(ws_mod._receive_market_controls(ws, Subscription()))
    assert ws.sent[0]["type"] == "error"


# ---------------------------------------------------------------------------
# Schema round-trips
# ---------------------------------------------------------------------------


def test_control_accepts_snapshot_and_resume_actions() -> None:
    assert MarketDataControl.model_validate({"action": "snapshot"}).action == "snapshot"
    r = MarketDataControl.model_validate(
        {"action": "resume", "topic": "trade.executed", "from_seq": 9}
    )
    assert r.action == "resume"
    assert r.topic == "trade.executed"
    assert r.from_seq == 9


def test_resume_from_round_trips() -> None:
    control = MarketDataControl.model_validate(
        {
            "action": "subscribe",
            "items": [
                {
                    "symbols": ["AAPL"],
                    "channels": ["trades"],
                    "resume_from": {"trades": 5},
                }
            ],
        }
    )
    assert control.items[0].resume_from == {"trades": 5}


def test_control_still_rejects_unknown_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MarketDataControl.model_validate({"action": "snapshot", "bogus": 1})
