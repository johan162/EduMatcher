"""CG1: the clearing current-state read routes.

Driven through the whole ASGI app against a ``clearing.db`` recorded by the
real pm-clearing process (``tests/clearing_api_fixture.py``). Money on a row
comes as the stored tick value (``*_ticks``) beside ``tick_decimals`` and the
row's own display value; only display values are ever summed across symbols.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from edumatcher.api_gateway.routers import clearing as clearing_router
from edumatcher.clearing.store import apply_schema
from tests.api_gateway_harness import call
from tests.clearing_api_fixture import (
    ADMIN_KEY,
    DAY1,
    DAY2,
    MM_KEY,
    READ_ONLY_KEY,
    TRADER_KEY,
    Venue,
    build_venue,
    make_clearing_app,
    rows,
)


@pytest.fixture(scope="module")
def venue(tmp_path_factory: pytest.TempPathFactory) -> Venue:
    return build_venue(tmp_path_factory.mktemp("venue"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _get(
    venue: Venue, path: str, key: str = ADMIN_KEY, **config: Any
) -> tuple[int, dict[str, Any]]:
    status, _, body = await call(
        make_clearing_app(venue, **config),
        "GET",
        f"/api/v1/clearing{path}",
        authorization=f"Bearer {key}",
    )
    return status, body


def _code(body: dict[str, Any]) -> str:
    return str(body["error"]["code"])


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return row["gateway_id"], row["symbol"]


# ---------------------------------------------------------------------------
# positions
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_positions_are_the_stored_rows_with_precision(
    venue: Venue,
) -> None:
    status, body = await _get(venue, "/positions")
    assert status == 200
    stored = rows(venue.clearing_db, "SELECT * FROM gateway_symbol_positions")
    assert body["count"] == len(stored) == 4
    assert body["has_more"] is False
    by_key = {_key(r): r for r in body["positions"]}
    for row in stored:
        got = by_key[_key(row)]
        scale = 10 ** row["tick_decimals"]
        assert got["tick_decimals"] == row["tick_decimals"]
        assert got["net_qty"] == row["net_qty"]
        assert got["avg_cost_ticks"] == pytest.approx(row["avg_cost"])
        assert got["avg_cost"] == pytest.approx(row["avg_cost"] / scale)
        assert got["mark_price_ticks"] == row["mark_price"]
        assert got["mark_price"] == pytest.approx(row["mark_price"] / scale)
        assert got["realized_pnl"] == pytest.approx(row["realized_pnl"] / scale)
        assert got["buy_notional_ticks"] == row["buy_notional"]
        assert got["sell_notional"] == pytest.approx(row["sell_notional"] / scale)
        assert got["updated_ts_ns"] == row["updated_ts_ns"]
    eurusd = by_key[("TRADER01", "EURUSD")]
    assert eurusd["tick_decimals"] == 4
    assert eurusd["net_qty"] == -500
    assert eurusd["mark_price"] == pytest.approx(1.0862)
    assert eurusd["realized_pnl"] == pytest.approx(-0.6)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("key", "gateway"), [(TRADER_KEY, "TRADER01"), (MM_KEY, "MM01")]
)
async def test_a_participant_sees_only_its_own_positions(
    venue: Venue, key: str, gateway: str
) -> None:
    status, body = await _get(venue, "/positions", key)
    assert status == 200
    assert {r["gateway_id"] for r in body["positions"]} == {gateway}
    assert body["count"] == 2


@pytest.mark.anyio
async def test_a_participant_naming_another_gateway_is_refused(venue: Venue) -> None:
    status, body = await _get(venue, "/positions?gateway=MM01", TRADER_KEY)
    assert status == 403
    assert _code(body) == "SCOPE_DENIED"


@pytest.mark.anyio
async def test_a_read_only_key_reads_no_clearing_data(venue: Venue) -> None:
    for path in ("/positions", "/exposure", "/trades", "/daily", "/close-snapshots"):
        status, body = await _get(venue, path, READ_ONLY_KEY)
        assert (status, _code(body)) == (403, "READ_ONLY"), path


@pytest.mark.anyio
async def test_filters_narrow_the_rows(venue: Venue) -> None:
    _, body = await _get(venue, "/positions?gateway=mm01&symbol=eurusd")
    assert [_key(r) for r in body["positions"]] == [("MM01", "EURUSD")]


@pytest.mark.anyio
async def test_no_rows_is_an_empty_list_not_an_error(venue: Venue) -> None:
    status, body = await _get(venue, "/positions?symbol=TSLA")
    assert status == 200
    assert body == {"positions": [], "count": 0, "has_more": False}


@pytest.mark.anyio
async def test_limit_bounds_the_rows_and_says_so(venue: Venue) -> None:
    status, body = await _get(venue, "/positions?limit=3")
    assert status == 200
    assert body["count"] == 3
    assert body["has_more"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("limit", ["0", "5001", "x"])
async def test_an_out_of_range_limit_is_a_validation_error(
    venue: Venue, limit: str
) -> None:
    status, body = await _get(venue, f"/positions?limit={limit}")
    assert (status, _code(body)) == (400, "VALIDATION")
    assert body["error"]["field"] == "limit"


# ---------------------------------------------------------------------------
# unavailable store
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_missing_clearing_db_is_503_not_an_empty_ledger(
    venue: Venue, tmp_path: Path
) -> None:
    status, body = await _get(venue, "/positions", clearing_db=tmp_path / "absent.db")
    assert (status, _code(body)) == (503, "CLEARING_DB")
    # The browser never learns where the file is.
    assert "absent.db" not in body["error"]["message"]


@pytest.mark.anyio
async def test_an_unreadable_clearing_db_is_503(venue: Venue, tmp_path: Path) -> None:
    garbage = tmp_path / "clearing.db"
    garbage.write_bytes(b"this is not a database" * 100)
    status, body = await _get(venue, "/positions", clearing_db=garbage)
    assert (status, _code(body)) == (503, "CLEARING_DB")


@pytest.mark.anyio
async def test_a_locked_clearing_db_is_503(
    venue: Venue, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "clearing.db"
    writer = sqlite3.connect(path)
    apply_schema(writer)
    writer.execute("PRAGMA journal_mode = DELETE")
    writer.execute("BEGIN EXCLUSIVE")
    monkeypatch.setattr(clearing_router, "_BUSY_TIMEOUT_MS", 50)
    try:
        status, body = await _get(venue, "/positions", clearing_db=path)
    finally:
        writer.rollback()
        writer.close()
    assert (status, _code(body)) == (503, "CLEARING_DB")


# ---------------------------------------------------------------------------
# exposure
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_exposure_normalizes_each_row(venue: Venue) -> None:
    status, body = await _get(venue, "/exposure")
    assert status == 200
    by_key = {_key(r): r for r in body["exposure"]}
    aapl = by_key[("TRADER01", "AAPL")]
    assert aapl["net_notional_ticks"] == 110 * 18800
    assert aapl["net_notional"] == pytest.approx(110 * 188.0)
    assert aapl["gross_notional"] == pytest.approx(110 * 188.0)
    short = by_key[("TRADER01", "EURUSD")]
    assert short["net_notional"] == pytest.approx(-500 * 1.0862)
    assert short["gross_notional"] == pytest.approx(500 * 1.0862)
    assert short["total_pnl"] == pytest.approx(-1.2)
    # Ranked in currency: AAPL's 20 680 above EURUSD's 543, whatever the ticks.
    ranked = [_key(r) for r in body["exposure"]]
    assert ranked.index(("TRADER01", "AAPL")) < ranked.index(("TRADER01", "EURUSD"))


@pytest.mark.anyio
async def test_exposure_sort_is_validated(venue: Venue) -> None:
    status, body = await _get(venue, "/exposure?sort=total_pnl")
    assert status == 200
    totals = [r["total_pnl"] for r in body["exposure"]]
    assert totals == sorted(totals, reverse=True)
    status, body = await _get(venue, "/exposure?sort=equity")
    assert (status, _code(body)) == (400, "VALIDATION")
    assert body["error"]["field"] == "sort"


# ---------------------------------------------------------------------------
# trades
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_trades_keep_every_stored_audit_field(venue: Venue) -> None:
    status, body = await _get(venue, "/trades")
    assert status == 200
    assert [t["trade_id"] for t in body["trades"]] == [
        "000007-000000007",
        "000007-000000006",
        "000007-000000003",
        "000007-000000002",
        "000007-000000001",
    ]
    stored = {r["id"]: r for r in rows(venue.clearing_db, "SELECT * FROM trade_events")}
    auction = next(t for t in body["trades"] if t["trade_id"].endswith("3"))
    row = stored[auction["trade_id"]]
    assert auction["match_type"] == "CLOSING_AUCTION"
    assert auction["msg_id"] == row["msg_id"] == "01JC0000000000000000000003"
    assert auction["ts_ns"] == row["ts_ns"]
    assert auction["ingest_ts_ns"] == row["ingest_ts_ns"] != row["ts_ns"]
    assert auction["trade_date"] == DAY1
    assert auction["price_ticks"] == 18750
    assert auction["price"] == pytest.approx(187.5)
    assert auction["tick_decimals"] == 2
    assert (auction["buy_gateway_id"], auction["sell_gateway_id"]) == (
        "TRADER01",
        "MM01",
    )
    assert (auction["buy_order_id"], auction["sell_order_id"]) == ("B3", "S3")
    assert auction["aggressor_side"] == "BUY"
    fx = next(t for t in body["trades"] if t["trade_id"].endswith("7"))
    assert (fx["price_ticks"], fx["tick_decimals"]) == (10862, 4)
    assert body["retained_from"] == DAY1


@pytest.mark.anyio
async def test_a_participant_does_not_see_its_counterparty(venue: Venue) -> None:
    status, body = await _get(venue, "/trades", TRADER_KEY)
    assert status == 200
    assert body["count"] == 5
    for trade in body["trades"]:
        if trade["buy_gateway_id"] == "TRADER01":
            assert trade["sell_gateway_id"] is None
            assert trade["sell_order_id"] is None
            assert trade["buy_order_id"] is not None
        else:
            assert trade["sell_gateway_id"] == "TRADER01"
            assert trade["buy_gateway_id"] is None
            assert trade["buy_order_id"] is None


@pytest.mark.anyio
async def test_trades_page_with_a_cursor(venue: Venue) -> None:
    seen: list[str] = []
    after = ""
    pages = 0
    while True:
        status, body = await _get(venue, f"/trades?limit=2{after}")
        assert status == 200
        seen += [t["trade_id"] for t in body["trades"]]
        pages += 1
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        after = f"&after={body['next_cursor']}"
    assert pages == 3
    assert len(seen) == len(set(seen)) == 5


@pytest.mark.anyio
async def test_trades_filter_by_date_symbol_and_range(venue: Venue) -> None:
    _, body = await _get(venue, f"/trades?date={DAY2}&symbol=eurusd")
    assert [t["trade_id"] for t in body["trades"]] == ["000007-000000007"]
    _, body = await _get(venue, f"/trades?from={DAY2}&to={DAY2}")
    assert body["count"] == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("date=2026-11-31", "date"),
        ("from=yesterday", "from"),
        ("to=2026-1-3", "to"),
        (f"from={DAY2}&to={DAY1}", "from"),
        ("after=not-a-cursor", "after"),
    ],
)
async def test_bad_trade_filters_are_validation_errors(
    venue: Venue, query: str, field: str
) -> None:
    status, body = await _get(venue, f"/trades?{query}")
    assert (status, _code(body)) == (400, "VALIDATION")
    assert body["error"]["field"] == field


# ---------------------------------------------------------------------------
# daily, close snapshots, symbols
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_daily_rows_carry_their_precision(venue: Venue) -> None:
    status, body = await _get(venue, f"/daily?symbol=EURUSD&date={DAY2}", TRADER_KEY)
    assert status == 200
    (row,) = body["daily"]
    assert (row["trade_date"], row["gateway_id"], row["tick_decimals"]) == (
        DAY2,
        "TRADER01",
        4,
    )
    assert row["buy_qty"] == 500
    assert row["buy_notional_ticks"] == 500 * 10862
    assert row["buy_notional"] == pytest.approx(500 * 1.0862)
    assert row["realized_pnl"] == pytest.approx(-0.6)
    assert row["end_net_qty"] == -500
    assert row["end_avg_cost"] == pytest.approx(1.085)


@pytest.mark.anyio
async def test_close_snapshots_cover_both_closes(venue: Venue) -> None:
    status, body = await _get(venue, "/close-snapshots?gateway=TRADER01")
    assert status == 200
    assert sorted({r["trade_date"] for r in body["snapshots"]}) == [DAY1, DAY2]
    day1 = {r["symbol"]: r for r in body["snapshots"] if r["trade_date"] == DAY1}
    assert day1["AAPL"]["net_qty"] == 150
    assert day1["AAPL"]["mark_price_ticks"] == 18750
    assert day1["AAPL"]["mark_price"] == pytest.approx(187.5)
    assert day1["AAPL"]["unrealized_pnl"] == pytest.approx(25.0)
    _, body = await _get(venue, f"/close-snapshots?from={DAY2}", MM_KEY)
    assert {(r["trade_date"], r["gateway_id"]) for r in body["snapshots"]} == {
        (DAY2, "MM01")
    }


@pytest.mark.anyio
async def test_symbols_is_admin_only_activity(venue: Venue) -> None:
    status, body = await _get(venue, "/symbols")
    assert status == 200
    by_symbol = {r["symbol"]: r for r in body["symbols"]}
    assert by_symbol["AAPL"]["traded_qty"] == 2 * (100 + 50 + 40)
    assert by_symbol["EURUSD"]["tick_decimals"] == 4
    # Every buy has a seller: the venue's net open quantity is zero.
    assert by_symbol["AAPL"]["open_net_qty"] == 0
    assert "open_interest" not in by_symbol["AAPL"]
    _, body = await _get(venue, f"/symbols?date={DAY1}")
    assert {r["symbol"]: r["traded_qty"] for r in body["symbols"]} == {
        "AAPL": 300,
        "EURUSD": 2000,
    }
    for key, code in ((TRADER_KEY, "ROLE_DENIED"), (READ_ONLY_KEY, "READ_ONLY")):
        status, body = await _get(venue, "/symbols", key)
        assert (status, _code(body)) == (403, code)


# ---------------------------------------------------------------------------
# participants and summary
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_participant_totals_are_normalized_per_row_before_summing(
    venue: Venue,
) -> None:
    status, body = await _get(venue, "/participants")
    assert status == 200
    by_gateway = {p["gateway_id"]: p for p in body["participants"]}
    assert set(by_gateway) == {"TRADER01", "MM01"}
    trader = by_gateway["TRADER01"]
    # AAPL +26.67 (2 decimals) and EURUSD -0.60 (4 decimals). Summing the raw
    # ticks instead (2666.67 - 6000) would read -33.33.
    assert trader["realized_pnl"] == pytest.approx(26.0667, abs=1e-4)
    assert trader["unrealized_pnl"] == pytest.approx(73.3333 - 0.6, abs=1e-4)
    assert trader["total_pnl"] == pytest.approx(
        trader["realized_pnl"] + trader["unrealized_pnl"]
    )
    assert trader["position_count"] == 2
    assert trader["open_position_count"] == 2
    assert "realized_pnl_ticks" not in trader
    stored = rows(
        venue.clearing_db,
        "SELECT MAX(updated_ts_ns) AS ts FROM gateway_symbol_positions"
        " WHERE gateway_id = 'TRADER01'",
    )
    assert trader["last_update_ts_ns"] == stored[0]["ts"]
    status, body = await _get(venue, "/participants", TRADER_KEY)
    assert (status, _code(body)) == (403, "ROLE_DENIED")


@pytest.mark.anyio
async def test_participant_detail_for_self_and_admin(venue: Venue) -> None:
    status, mine = await _get(venue, "/participants/TRADER01", TRADER_KEY)
    assert status == 200
    status, admins = await _get(venue, "/participants/trader01")
    assert status == 200
    assert mine == admins
    assert mine["gateway_id"] == "TRADER01"
    assert {p["symbol"] for p in mine["positions"]} == {"AAPL", "EURUSD"}
    assert mine["latest_close_date"] == DAY2
    assert mine["links"]["trades"] == "/api/v1/clearing/trades?gateway=TRADER01"
    assert mine["links"]["settlements"] == (
        "/api/v1/clearing/settlements?gateway=TRADER01"
    )
    status, body = await _get(venue, "/participants/MM01", TRADER_KEY)
    assert (status, _code(body)) == (403, "SCOPE_DENIED")


@pytest.mark.anyio
async def test_a_participant_without_activity_is_a_true_zero(venue: Venue) -> None:
    status, body = await _get(venue, "/participants/OPS01")
    assert status == 200
    assert body["positions"] == []
    assert (body["realized_pnl"], body["total_pnl"]) == (0.0, 0.0)
    assert body["last_update_ts_ns"] is None
    assert body["latest_close_date"] is None


@pytest.mark.anyio
async def test_the_summary_reports_only_stored_facts(venue: Venue) -> None:
    status, body = await _get(venue, "/summary")
    assert status == 200
    assert body["participant_count"] == 2
    assert body["open_position_count"] == 4
    health = rows(
        venue.clearing_db,
        "SELECT MAX(ts_ns) AS trade, (SELECT MAX(updated_ts_ns)"
        " FROM gateway_symbol_positions) AS flush FROM trade_events",
    )[0]
    assert body["last_trade_ts_ns"] == health["trade"]
    assert body["last_flush_ts_ns"] == health["flush"]
    assert body["session_date"] == DAY2
    assert body["gap_count"] == 1
    assert body["latest_gap"]["missing_trades"] == 2
    assert body["latest_gap"]["last_seq"] == 3
    assert body["latest_gap"]["next_seq"] == 6
    assert body["eod_db_available"] is True
    assert body["last_eod_run"]["trade_date"] == "2026-11-04"
    assert body["last_eod_run"]["status"] == "failed"
    for unsupported in ("equity", "margin", "net_notional", "open_interest"):
        assert not any(unsupported in field for field in body)
    status, body = await _get(venue, "/summary", MM_KEY)
    assert (status, _code(body)) == (403, "ROLE_DENIED")


@pytest.mark.anyio
async def test_the_summary_names_a_missing_eod_ledger(
    venue: Venue, tmp_path: Path
) -> None:
    status, body = await _get(venue, "/summary", eod_db=tmp_path / "eod.db")
    assert status == 200
    assert body["eod_db_available"] is False
    assert body["last_eod_run"] is None


# ---------------------------------------------------------------------------
# review regressions
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_polled_summary_never_reads_the_raw_trade_table(
    venue: Venue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`summary` is the five-second overview poll: it must stay on the small
    aggregate tables, not scan `trade_events` (no index on `ts_ns`)."""
    statements: list[str] = []
    from edumatcher.clearing.query import open_readonly_connection as opened

    def _traced(path: Path, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
        conn = opened(path, busy_timeout_ms)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(clearing_router, "open_readonly_connection", _traced)
    status, body = await _get(venue, "/summary")
    assert status == 200
    assert statements, "the trace saw no statement"
    assert not [s for s in statements if "trade_events" in s]
    stored = rows(
        venue.clearing_db,
        "SELECT MAX(ts_ns) AS trade FROM trade_events",
    )[0]
    assert body["last_trade_ts_ns"] == stored["trade"]


@pytest.mark.anyio
async def test_a_blank_filter_is_no_filter(venue: Venue) -> None:
    status, body = await _get(venue, "/positions?gateway=%20&symbol=", TRADER_KEY)
    assert status == 200
    assert {r["gateway_id"] for r in body["positions"]} == {"TRADER01"}
    assert body["count"] == 2
    _, body = await _get(venue, "/positions?gateway=%20&symbol=%20")
    assert body["count"] == 4


@pytest.mark.anyio
async def test_participant_links_are_url_encoded(venue: Venue) -> None:
    status, body = await _get(venue, "/participants/A&B")
    assert status == 200
    assert body["gateway_id"] == "A&B"
    assert body["links"]["trades"] == "/api/v1/clearing/trades?gateway=A%26B"
