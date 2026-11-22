"""GET /news from pm-market-sim's news history (WP-NR02)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from edumatcher.api_gateway.routers import reference
from edumatcher.api_gateway.sessions import Session
from edumatcher.api_gateway.sim_client import SimClient
from edumatcher.market_sim import news_history
from edumatcher.market_sim.news_history import append_news_event

READ_ONLY = Session(api_key="k", gateway_id=None, description="")
SECTORS = {"TECH": frozenset({"AAPL", "MSFT"}), "ENERGY": frozenset({"XOM"})}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def news_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "market_sim_news.db"
    monkeypatch.setattr(news_history, "NEWS_HISTORY_DB", db)
    return db


def _event(news_id: str, ts_ns: int, **fields: Any) -> dict[str, Any]:
    return {
        "id": news_id,
        "ts_ns": ts_ns,
        "scope": "SYMBOL",
        "targets": ["AAPL"],
        "kind": "EARNINGS",
        "status": "CONFIRMED",
        "headline": news_id,
        "sentiment": 0.5,
        **fields,
    }


async def _news(**params: Any) -> dict[str, Any]:
    with patch(
        "edumatcher.api_gateway.sim_client.make_subscriber", return_value=MagicMock()
    ):
        sim = SimClient("tcp://127.0.0.1:1", asyncio.get_running_loop(), SECTORS)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(sim=sim)))
    defaults: dict[str, Any] = {
        "limit": 50,
        "offset": 0,
        "from_ts": None,
        "to_ts": None,
        "match": None,
        "news_status": None,
        "sentiment": None,
    }
    return await reference.news(cast(Any, request), READ_ONLY, **{**defaults, **params})


def _ids(body: dict[str, Any]) -> list[str]:
    return [n["id"] for n in body["news"]]


@pytest.mark.anyio
async def test_news_comes_from_the_history_newest_first(news_db: Path) -> None:
    """A restarted pm-api-gwy still has everything pm-market-sim recorded."""
    for i in range(3):
        append_news_event(news_db, _event(f"N{i}", 10 + i, credibility=None))
    body = await _news()
    assert _ids(body) == ["N2", "N1", "N0"]
    assert (body["count"], body["total"], body["has_more"]) == (3, 3, False)
    assert body["sectors"] == {"ENERGY": ["XOM"], "TECH": ["AAPL", "MSFT"]}
    assert "credibility" not in body["news"][0]  # absent, as on the wire
    assert body["news"][0]["resolution"] is None


@pytest.mark.anyio
async def test_news_without_a_history_is_empty(news_db: Path) -> None:
    body = await _news()
    assert (body["news"], body["total"], body["has_more"]) == ([], 0, False)
    assert not news_db.exists()  # read-only: never created


@pytest.mark.anyio
async def test_an_unreadable_history_is_503(news_db: Path) -> None:
    news_db.write_text("not a database")
    with pytest.raises(HTTPException) as info:
        await _news()
    assert info.value.status_code == 503
    detail = cast(dict[str, Any], info.value.detail)
    assert detail["error"]["code"] == "NEWS_DB_UNAVAILABLE"


@pytest.mark.anyio
async def test_news_pages_with_limit_offset_and_total(news_db: Path) -> None:
    for i in range(5):
        append_news_event(news_db, _event(f"N{i}", 10 + i))
    first = await _news(limit=2)
    second = await _news(limit=2, offset=2)
    last = await _news(limit=2, offset=4)
    assert (_ids(first), _ids(second), _ids(last)) == (
        ["N4", "N3"],
        ["N2", "N1"],
        ["N0"],
    )
    assert [p["has_more"] for p in (first, second, last)] == [True, True, False]
    assert {p["total"] for p in (first, second, last)} == {5}


@pytest.mark.anyio
async def test_news_time_window_is_inclusive(news_db: Path) -> None:
    second = 1_000_000_000
    for i in range(4):
        append_news_event(news_db, _event(f"N{i}", (100 + i) * second))
    body = await _news(
        from_ts=datetime.fromtimestamp(101, timezone.utc),
        to_ts=datetime.fromtimestamp(102, timezone.utc),
    )
    assert _ids(body) == ["N2", "N1"] and body["total"] == 2
    naive = await _news(from_ts=datetime(1970, 1, 1, 0, 1, 43))  # read as UTC
    assert _ids(naive) == ["N3"]


@pytest.mark.anyio
async def test_news_filter_by_symbol_or_sector(news_db: Path) -> None:
    append_news_event(news_db, _event("AAPL", 1, targets=["AAPL"]))
    append_news_event(news_db, _event("XOM", 2, targets=["XOM"]))
    append_news_event(news_db, _event("TECH", 3, scope="SECTOR", targets=["TECH"]))
    append_news_event(news_db, _event("ENERGY", 4, scope="SECTOR", targets=["ENERGY"]))
    append_news_event(news_db, _event("MKT", 5, scope="MARKET", targets=[]))
    # a symbol: its own news, its sector's and the market's
    assert _ids(await _news(match="aapl")) == ["MKT", "TECH", "AAPL"]
    # a sector: its own news, its symbols' and the market's
    assert _ids(await _news(match=" energy ")) == ["MKT", "ENERGY", "XOM"]
    assert _ids(await _news(match="ZZZ")) == ["MKT"]
    assert (await _news(match="")).get("total") == 5


@pytest.mark.anyio
async def test_news_filter_by_status_and_sentiment(news_db: Path) -> None:
    append_news_event(news_db, _event("UP", 1, sentiment=0.4))
    append_news_event(news_db, _event("DOWN", 2, sentiment=-0.4))
    append_news_event(news_db, _event("FLAT", 3, sentiment=0.0))
    append_news_event(news_db, _event("R", 4, status="RUMOUR", sentiment=0.2))
    assert _ids(await _news(sentiment="positive")) == ["R", "UP"]
    assert _ids(await _news(sentiment="negative")) == ["DOWN"]
    assert _ids(await _news(news_status="RUMOUR")) == ["R"]
    both = await _news(news_status="CONFIRMED", sentiment="positive")
    assert _ids(both) == ["UP"] and both["total"] == 1


@pytest.mark.anyio
async def test_a_rumour_carries_its_resolution_across_pages(news_db: Path) -> None:
    append_news_event(news_db, _event("R1", 1, status="RUMOUR", credibility=0.4))
    append_news_event(news_db, _event("R2", 2, status="RUMOUR", credibility=0.6))
    append_news_event(news_db, _event("R3", 3, status="RUMOUR", credibility=0.5))
    append_news_event(news_db, _event("X1", 4, status="RETRACTED", related_id="R1"))
    append_news_event(news_db, _event("C2", 5, status="CONFIRMED", related_id="R2"))
    page = await _news(news_status="RUMOUR", limit=1, offset=1)
    assert _ids(page) == ["R2"] and page["news"][0]["resolution"] == "CONFIRMED"
    rumours = {n["id"]: n["resolution"] for n in (await _news())["news"]}
    assert rumours["R1"] == "RETRACTED" and rumours["R3"] is None
    assert rumours["X1"] is None  # only a rumour has a resolution
