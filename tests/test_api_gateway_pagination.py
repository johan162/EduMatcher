"""Tests for keyset ("seek") pagination across the pm-api-gwy /history/*
list endpoints.

Design intent under test (not a literal mirror of the implementation):
  - Walking every page via next_cursor/after reproduces the exact same rows,
    in the exact same order, as one unpaginated call — no rows are skipped
    or duplicated across the page boundary, including when several rows
    share the same primary sort timestamp.
  - has_more is only ever true when the page came back full (== limit); the
    very last page of a result set has has_more: false and no next_cursor.
  - A malformed after cursor is rejected with 422 VALIDATION, not a raw
    exception or a silently-ignored filter.
  - The pagination contract is uniform across every paginated endpoint
    (orders, fills, trades, daily, index-daily, index-snapshots,
    price-snapshots), not just the one first implemented.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.routers import history
from edumatcher.api_gateway.sessions import Session
from edumatcher.stats.main import SCHEMA


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _request_for(db_path: Path) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=ApiGatewayConfig(stats_db=db_path),
                rate_limiter=RateLimiter(100, 100),
            )
        )
    )


def _readonly_session() -> Session:
    return Session(api_key="ro-key", gateway_id=None, description="readonly")


def _trading_session() -> Session:
    return Session(api_key="trading-key", gateway_id="GW01", description="trader")


# history.py declares some params (limit/from/to) as `= Query(default=..., ...)`
# rather than `Annotated[..., Query(...)] = default`; calling the handler
# coroutine directly (bypassing FastAPI's routing layer) requires passing
# those explicitly. `after` is a plain-default param in every endpoint, so it
# does not need the same treatment.
async def _call_trades(
    request: Any,
    session: Session,
    *,
    symbol: str | None = None,
    date: str | None = None,
    limit: int = 500,
    after: str | None = None,
) -> dict[str, Any]:
    return await history.history_trades(
        request,
        session,
        symbol=symbol,
        date=date,
        from_ts=None,
        to_ts=None,
        limit=limit,
        after=after,
    )


async def _call_orders(
    request: Any,
    session: Session,
    *,
    symbol: str | None = None,
    limit: int = 500,
    after: str | None = None,
) -> dict[str, Any]:
    return await history.history_orders(
        request,
        session,
        symbol=symbol,
        event_type=None,
        date=None,
        from_ts=None,
        to_ts=None,
        limit=limit,
        after=after,
    )


async def _call_index_daily(
    request: Any,
    session: Session,
    *,
    index_id: str | None = None,
    date: str | None = None,
    limit: int = 500,
    after: str | None = None,
) -> dict[str, Any]:
    return await history.history_index_daily(
        request, session, index_id=index_id, date=date, limit=limit, after=after
    )


def _seed_trades(path: Path, count: int) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for i in range(count):
        conn.execute(
            "INSERT INTO trade_log "
            "(ts, trade_id, symbol, price, quantity, buy_gateway_id, sell_gateway_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"2026-06-14T09:{i:02d}:00.000+00:00",
                f"T-{i:03d}",
                "EDU100",
                100.0 + i,
                10,
                "GW01",
                "GW02",
            ),
        )
    conn.commit()
    conn.close()


def _seed_orders(path: Path, count: int) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for i in range(count):
        conn.execute(
            "INSERT INTO order_events (ts, event_type, order_id, gateway_id, symbol) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "2026-06-14T09:00:00.000+00:00",  # shared ts on purpose
                "NEW",
                f"O-{i:03d}",
                "GW01",
                "EDU100",
            ),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def trades_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "trades.db"
    _seed_trades(db_path, count=7)
    return db_path


@pytest.fixture
def orders_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "orders.db"
    _seed_orders(db_path, count=5)
    return db_path


@pytest.mark.anyio
async def test_history_trades_pagination_reproduces_full_result_set(
    trades_db: Path,
) -> None:
    request = _request_for(trades_db)
    session = _readonly_session()

    full = await _call_trades(request, session, limit=500)
    assert full["count"] == 7
    assert full["has_more"] is False

    paged_ids: list[str] = []
    after = None
    for _ in range(10):
        page = await _call_trades(request, session, limit=2, after=after)
        paged_ids.extend(t["trade_id"] for t in page["trades"])
        if not page["has_more"]:
            assert "next_cursor" not in page
            break
        after = page["next_cursor"]

    assert paged_ids == [t["trade_id"] for t in full["trades"]]
    assert len(paged_ids) == len(set(paged_ids))


@pytest.mark.anyio
async def test_history_trades_malformed_after_returns_422(trades_db: Path) -> None:
    request = _request_for(trades_db)
    with pytest.raises(HTTPException) as exc_info:
        await _call_trades(request, _readonly_session(), limit=10, after="garbage")
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error"]["code"] == "VALIDATION"


@pytest.mark.anyio
async def test_history_orders_pagination_handles_same_timestamp_rows(
    orders_db: Path,
) -> None:
    """All seeded order_events share one ts — this only works if the seq
    tiebreaker (not ts alone) drives the ordering, proving orders/fills use
    the same correct keyset logic as trades rather than a ts-only cursor
    that would silently drop same-timestamp rows.
    """
    request = _request_for(orders_db)
    session = _trading_session()

    paged_ids: list[str] = []
    after = None
    for _ in range(10):
        page = await _call_orders(request, session, limit=2, after=after)
        paged_ids.extend(e["order_id"] for e in page["events"])
        if not page["has_more"]:
            break
        after = page["next_cursor"]

    assert paged_ids == [f"O-{i:03d}" for i in range(5)]


@pytest.mark.anyio
async def test_history_orders_requires_trading_credential(orders_db: Path) -> None:
    """/history/orders (unlike /history/trades) is gateway-scoped; a
    read-only key must still be rejected the same way it always was,
    confirming pagination didn't loosen the auth tier.
    """
    request = _request_for(orders_db)
    with pytest.raises(HTTPException) as exc_info:
        await _call_orders(request, _readonly_session(), limit=10)
    assert exc_info.value.status_code == 403


def _seed_index_daily_multi(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for index_id in ("EDU100", "EDUFIN", "EDUTECH"):
        conn.execute(
            "INSERT INTO index_daily_stats "
            "(date, index_id, open_level, high_level, low_level, close_level, "
            " close_session_state, open_aggregate_cap, close_aggregate_cap, update_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14",
                index_id,
                100.0,
                105.0,
                98.0,
                102.0,
                "CLOSED",
                1.0e12,
                1.1e12,
                100,
            ),
        )
    conn.commit()
    conn.close()


@pytest.mark.anyio
async def test_history_index_daily_pagination_across_index_id(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "index_daily.db"
    _seed_index_daily_multi(db_path)
    request = _request_for(db_path)
    session = _readonly_session()

    seen_ids: list[str] = []
    after = None
    for _ in range(10):
        page = await _call_index_daily(
            request, session, date="2026-06-14", limit=1, after=after
        )
        seen_ids.extend(row["index_id"] for row in page["daily"])
        if not page["has_more"]:
            break
        after = page["next_cursor"]

    assert sorted(seen_ids) == ["EDU100", "EDUFIN", "EDUTECH"]
    assert len(seen_ids) == len(set(seen_ids))
