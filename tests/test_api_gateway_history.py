"""Tests for the pm-api-gwy /history/index-* endpoints.

Design intent under test (not a literal mirror of the implementation):
  - index-daily / index-snapshots / index-ids are public market data —
    reachable with a read-only credential (no gateway_id), the same tier
    as /history/trades and /history/daily, unlike the gateway-scoped
    /history/orders and /history/fills.
  - index-daily defaults to the latest available date when omitted, and
    surfaces close_session_state so a caller can tell whether close_level
    is a finalized EOD print or just the most recent tick.
  - index-snapshots requires index_id (unlike /trades, there is no
    "all indexes" firehose mode) and supports the same date/from/to
    filtering contract as the other time-series endpoints.
  - index-ids lists distinct index IDs with recorded data, unpaginated.
  - All three degrade gracefully (empty results, not errors) when no
    index data has been recorded yet.
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


def _seed_index_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)

        # A completed prior day for EDU100 — close_session_state=CLOSED,
        # i.e. close_level is a genuine, finalized EOD print.
        conn.execute(
            "INSERT INTO index_daily_stats "
            "(date, index_id, open_level, high_level, low_level, close_level, "
            " close_session_state, open_aggregate_cap, close_aggregate_cap, update_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14",
                "EDU100",
                1042.10,
                1056.30,
                1040.05,
                1048.73,
                "CLOSED",
                7.3e12,
                7.35e12,
                512,
            ),
        )
        # A later date, still trading — close_level is only "latest so far".
        conn.execute(
            "INSERT INTO index_daily_stats "
            "(date, index_id, open_level, high_level, low_level, close_level, "
            " close_session_state, open_aggregate_cap, close_aggregate_cap, update_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-15",
                "EDU100",
                1048.73,
                1060.00,
                1045.00,
                1055.20,
                "CONTINUOUS",
                7.35e12,
                7.4e12,
                480,
            ),
        )
        # A second, independent index — used to confirm index_id isolation.
        conn.execute(
            "INSERT INTO index_daily_stats "
            "(date, index_id, open_level, high_level, low_level, close_level, "
            " close_session_state, open_aggregate_cap, close_aggregate_cap, update_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14",
                "EDUFIN",
                500.0,
                505.0,
                498.0,
                502.0,
                "CLOSED",
                1.2e12,
                1.21e12,
                300,
            ),
        )

        conn.execute(
            "INSERT INTO index_level_snapshots "
            "(ts, index_id, level, aggregate_cap, divisor, session_state, day_open, day_high, day_low) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14T09:00:00.000+00:00",
                "EDU100",
                1042.10,
                7.3e12,
                1.25,
                "OPENING_AUCTION",
                None,
                None,
                None,
            ),
        )
        conn.execute(
            "INSERT INTO index_level_snapshots "
            "(ts, index_id, level, aggregate_cap, divisor, session_state, day_open, day_high, day_low) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14T16:00:00.000+00:00",
                "EDU100",
                1048.73,
                7.35e12,
                1.25,
                "CLOSED",
                1042.10,
                1056.30,
                1040.05,
            ),
        )
        conn.execute(
            "INSERT INTO index_level_snapshots "
            "(ts, index_id, level, aggregate_cap, divisor, session_state, day_open, day_high, day_low) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14T09:30:00.000+00:00",
                "EDUFIN",
                500.0,
                1.2e12,
                1.0,
                "CONTINUOUS",
                None,
                None,
                None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "stats.db"
    _seed_index_db(db_path)
    return db_path


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "empty_stats.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    return db_path


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
    """A read-only credential — no gateway_id, matches how a market-data
    consumer (not a trading gateway) would authenticate.
    """
    return Session(api_key="ro-key", gateway_id=None, description="readonly")


def _trading_session() -> Session:
    return Session(api_key="trading-key", gateway_id="GW01", description="trader")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# history.py declares `limit`/`from`/`to` params as `= Query(default=..., ...)`
# rather than `Annotated[..., Query(...)] = default`. FastAPI only resolves
# that `Query(...)` sentinel into its default value when routing an actual
# HTTP request through its dependency-injection layer — calling the handler
# coroutine directly (as these tests do, matching test_api_gateway_routes.py's
# style) leaves the sentinel object itself bound to the parameter unless it
# is passed explicitly. These helpers supply the real defaults so tests read
# naturally while still exercising the actual handler code.
async def _call_index_daily(
    request: Any,
    session: Session,
    *,
    index_id: str | None = None,
    date: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    return await history.history_index_daily(
        request, session, index_id=index_id, date=date, limit=limit
    )


async def _call_index_snapshots(
    request: Any,
    session: Session,
    *,
    index_id: str,
    date: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    return await history.history_index_snapshots(
        request,
        session,
        index_id=index_id,
        date=date,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# index-daily
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_index_daily_readonly_key_is_sufficient(seeded_db: Path) -> None:
    """Public market data: a read-only credential (no gateway_id) must be
    able to call this without hitting the trading-only auth gate that
    /history/orders and /history/fills enforce.
    """
    request = _request_for(seeded_db)
    result = await _call_index_daily(
        request, _readonly_session(), index_id="EDU100", date="2026-06-14"
    )
    assert result["count"] == 1
    assert result["daily"][0]["index_id"] == "EDU100"


@pytest.mark.anyio
async def test_index_daily_defaults_to_latest_date(seeded_db: Path) -> None:
    request = _request_for(seeded_db)
    result = await _call_index_daily(
        request, _readonly_session(), index_id="EDU100", date=None
    )
    rows = result["daily"]
    assert isinstance(rows, list)
    assert {row["date"] for row in rows} == {"2026-06-15"}


@pytest.mark.anyio
async def test_index_daily_exposes_close_session_state_for_finality_check(
    seeded_db: Path,
) -> None:
    """The whole point of exposing close_session_state over the API: a
    caller must be able to tell a finalized EOD close (CLOSED) apart from
    a still-live "latest tick so far" value, without a second call.
    """
    request = _request_for(seeded_db)

    closed = await _call_index_daily(
        request, _readonly_session(), index_id="EDU100", date="2026-06-14"
    )
    assert closed["daily"][0]["close_session_state"] == "CLOSED"
    assert closed["daily"][0]["close_level"] == 1048.73

    still_trading = await _call_index_daily(
        request, _readonly_session(), index_id="EDU100", date="2026-06-15"
    )
    assert still_trading["daily"][0]["close_session_state"] == "CONTINUOUS"


@pytest.mark.anyio
async def test_index_daily_index_id_is_case_insensitive(seeded_db: Path) -> None:
    request = _request_for(seeded_db)
    result = await _call_index_daily(
        request, _readonly_session(), index_id="edu100", date="2026-06-14"
    )
    assert result["daily"][0]["index_id"] == "EDU100"


@pytest.mark.anyio
async def test_index_daily_omitting_index_id_returns_all_indexes(
    seeded_db: Path,
) -> None:
    request = _request_for(seeded_db)
    result = await _call_index_daily(
        request, _readonly_session(), index_id=None, date="2026-06-14"
    )
    index_ids = {row["index_id"] for row in result["daily"]}
    assert index_ids == {"EDU100", "EDUFIN"}


@pytest.mark.anyio
async def test_index_daily_invalid_date_rejected_with_422(seeded_db: Path) -> None:
    request = _request_for(seeded_db)
    with pytest.raises(HTTPException) as exc_info:
        await _call_index_daily(
            request, _readonly_session(), index_id="EDU100", date="not-a-date"
        )
    assert exc_info.value.status_code == 422


@pytest.mark.anyio
async def test_index_daily_has_more_reflects_limit_saturation(
    seeded_db: Path,
) -> None:
    request = _request_for(seeded_db)
    # Two rows exist for 2026-06-14 (EDU100, EDUFIN); limit=1 must saturate.
    saturated = await _call_index_daily(
        request, _readonly_session(), index_id=None, date="2026-06-14", limit=1
    )
    assert saturated["has_more"] is True
    not_saturated = await _call_index_daily(
        request, _readonly_session(), index_id=None, date="2026-06-14", limit=10
    )
    assert not_saturated["has_more"] is False


@pytest.mark.anyio
async def test_index_daily_empty_db_returns_empty_not_error(empty_db: Path) -> None:
    """No exchange index configured / no data recorded yet must look like
    an empty result set, not a failure — mirrors /history/daily's and
    /history/trades' behavior for symbols with no stats.
    """
    request = _request_for(empty_db)
    result = await _call_index_daily(
        request, _readonly_session(), index_id="EDU100", date=None
    )
    assert result == {"daily": [], "count": 0, "has_more": False}


# ---------------------------------------------------------------------------
# index-snapshots
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_index_snapshots_readonly_key_is_sufficient(seeded_db: Path) -> None:
    request = _request_for(seeded_db)
    result = await _call_index_snapshots(
        request, _readonly_session(), index_id="EDU100"
    )
    assert result["count"] == 2


@pytest.mark.anyio
async def test_index_snapshots_isolates_by_index_id(seeded_db: Path) -> None:
    """Design intent: querying one index's snapshots must never leak
    another index's ticks into the result, even though both share the
    same table.
    """
    request = _request_for(seeded_db)
    edufin = await _call_index_snapshots(
        request, _readonly_session(), index_id="EDUFIN"
    )
    assert edufin["count"] == 1
    assert all(row["index_id"] == "EDUFIN" for row in edufin["snapshots"])


@pytest.mark.anyio
async def test_index_snapshots_time_window_filters(seeded_db: Path) -> None:
    request = _request_for(seeded_db)
    result = await _call_index_snapshots(
        request,
        _readonly_session(),
        index_id="EDU100",
        from_ts="2026-06-14T12:00:00+00:00",
        to_ts="2026-06-14T23:59:59+00:00",
    )
    assert result["count"] == 1
    assert result["snapshots"][0]["session_state"] == "CLOSED"


@pytest.mark.anyio
async def test_index_snapshots_chronological_order(seeded_db: Path) -> None:
    request = _request_for(seeded_db)
    result = await _call_index_snapshots(
        request, _readonly_session(), index_id="EDU100"
    )
    timestamps = [row["ts"] for row in result["snapshots"]]
    assert timestamps == sorted(timestamps)


@pytest.mark.anyio
async def test_index_snapshots_invalid_time_range_rejected(seeded_db: Path) -> None:
    request = _request_for(seeded_db)
    with pytest.raises(HTTPException) as exc_info:
        await _call_index_snapshots(
            request, _readonly_session(), index_id="EDU100", from_ts="garbage"
        )
    assert exc_info.value.status_code == 422


@pytest.mark.anyio
async def test_index_snapshots_empty_db_returns_empty_not_error(
    empty_db: Path,
) -> None:
    request = _request_for(empty_db)
    result = await _call_index_snapshots(
        request, _readonly_session(), index_id="EDU100"
    )
    assert result == {"snapshots": [], "count": 0, "has_more": False}


# ---------------------------------------------------------------------------
# index-ids
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_index_ids_readonly_key_is_sufficient(seeded_db: Path) -> None:
    request = _request_for(seeded_db)
    result = await history.history_index_ids(request, _readonly_session())
    assert set(result["index_ids"]) == {"EDU100", "EDUFIN"}
    assert result["count"] == 2


@pytest.mark.anyio
async def test_index_ids_filters_by_date(seeded_db: Path) -> None:
    """2026-06-15 only has EDU100 data (EDUFIN's only rows are on
    2026-06-14) — filtering by date must narrow the id list accordingly,
    not just filter the underlying rows some other endpoint returns.
    """
    request = _request_for(seeded_db)
    result = await history.history_index_ids(
        request, _readonly_session(), date="2026-06-15"
    )
    assert result["index_ids"] == ["EDU100"]


@pytest.mark.anyio
async def test_index_ids_invalid_date_rejected_with_422(seeded_db: Path) -> None:
    request = _request_for(seeded_db)
    with pytest.raises(HTTPException) as exc_info:
        await history.history_index_ids(request, _readonly_session(), date="06/14/2026")
    assert exc_info.value.status_code == 422


@pytest.mark.anyio
async def test_index_ids_empty_db_returns_empty_list_not_error(
    empty_db: Path,
) -> None:
    request = _request_for(empty_db)
    result = await history.history_index_ids(request, _readonly_session())
    assert result == {"index_ids": [], "count": 0}


# ---------------------------------------------------------------------------
# Cross-cutting: trading credentials work too (auth is "any valid key",
# not "read-only key only")
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_index_endpoints_also_accept_trading_credentials(
    seeded_db: Path,
) -> None:
    """'Any valid key' means any valid key — a trading gateway's own
    credential should work here too, not just dedicated read-only keys.
    """
    request = _request_for(seeded_db)
    session = _trading_session()
    assert (await _call_index_daily(request, session, index_id="EDU100"))["count"] >= 0
    assert (await _call_index_snapshots(request, session, index_id="EDU100"))[
        "count"
    ] >= 0
    ids_result = await history.history_index_ids(request, session)
    assert isinstance(ids_result["count"], int)
    assert ids_result["count"] >= 0


@pytest.mark.anyio
async def test_missing_stats_db_returns_503(tmp_path: Path) -> None:
    """Matches the existing /history/* contract: a missing stats.db file
    is a 503 STATS_DB error, not a 500 or an empty-looking success.
    """
    request = _request_for(tmp_path / "does_not_exist.db")
    with pytest.raises(HTTPException) as exc_info:
        await _call_index_daily(request, _readonly_session(), index_id="EDU100")
    assert exc_info.value.status_code == 503
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error"]["code"] == "STATS_DB"
