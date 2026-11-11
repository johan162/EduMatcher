"""CG2: the clearing operational-evidence routes.

Session events, gateway sessions, reconciliation and health: what an operator
needs to judge whether the ledger is complete, instead of taking it as
infallible. Timestamps here are clearing's own observation times;
reconciliation can only compare the raw trades clearing still holds; health
reports the database and the receive loop as separate facts.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
import zmq

from edumatcher.api_gateway.routers import clearing as clearing_router
from edumatcher.clearing.cli import main as cli_main
from edumatcher.healthcheck import answer_health_ping
from tests.api_gateway_harness import call
from tests.clearing_api_fixture import (
    ADMIN_KEY,
    DAY1,
    DAY2,
    MM_KEY,
    READ_ONLY_KEY,
    SILENT_HEALTH_ADDR,
    TRADER_KEY,
    Venue,
    build_venue,
    make_clearing_app,
    ns,
    rows,
)


@pytest.fixture(scope="module")
def venue(tmp_path_factory: pytest.TempPathFactory) -> Venue:
    return build_venue(tmp_path_factory.mktemp("venue"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _silent_clearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never ping a real pm-clearing a developer may be running."""
    monkeypatch.setattr(clearing_router, "_HEALTH_ADDR", SILENT_HEALTH_ADDR)
    monkeypatch.setattr(clearing_router, "_HEALTH_TIMEOUT_MS", 100)


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


# ---------------------------------------------------------------------------
# session events
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_session_events_decode_each_payload(venue: Venue) -> None:
    status, body = await _get(venue, "/session-events")
    assert status == 200
    events = body["events"]
    # Newest first: the gap is stamped with the 10:00 trade after it.
    assert [e["event_type"] for e in events] == [
        "EOD",
        "PHASE",
        "GAP",
        "PHASE",
        "PHASE",
        "PHASE",
    ]
    eod, close2, gap, open2 = events[:4]
    assert gap == {
        "id": gap["id"],
        "event_type": "GAP",
        "ts_ns": rows(
            venue.clearing_db,
            "SELECT ts_ns FROM trade_events WHERE id = ?",
            "000007-000000006",
        )[0]["ts_ns"],
        "trade_date": DAY2,
        "gap": {"run_seq": 7, "last_seq": 3, "next_seq": 6, "missing_trades": 2},
    }
    assert close2["phase"] == {"state": "CLOSED", "prev_state": "CONTINUOUS"}
    assert close2["ts_ns"] == ns(DAY2, "17:00")
    assert "gap" not in close2 and "eod" not in close2
    assert open2["phase"]["state"] == "CONTINUOUS"
    assert eod["eod"] == {"symbols_count": 0, "marked_symbols": []}
    assert "payload_json" not in eod


@pytest.mark.anyio
async def test_session_events_filter_by_type_and_dates(venue: Venue) -> None:
    _, body = await _get(venue, "/session-events?type=gap")
    assert [e["event_type"] for e in body["events"]] == ["GAP"]
    _, body = await _get(venue, f"/session-events?type=PHASE&from={DAY1}&to={DAY1}")
    assert [e["phase"]["state"] for e in body["events"]] == ["CLOSED", "CONTINUOUS"]
    assert {e["trade_date"] for e in body["events"]} == {DAY1}
    status, body = await _get(venue, "/session-events?type=HALT")
    assert (status, _code(body)) == (400, "VALIDATION")
    assert body["error"]["field"] == "type"


@pytest.mark.anyio
async def test_session_events_are_bounded(venue: Venue) -> None:
    _, body = await _get(venue, "/session-events?limit=2")
    assert (body["count"], body["has_more"]) == (2, True)


# ---------------------------------------------------------------------------
# gateway sessions
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_gateway_sessions_for_the_venue(venue: Venue) -> None:
    status, body = await _get(venue, "/gateway-sessions")
    assert status == 200
    by_gateway = {s["gateway_id"]: s for s in body["sessions"]}
    assert set(by_gateway) == {"OPS01", "TRADER01", "MM01"}
    mm = by_gateway["MM01"]
    assert mm["connected_at_ns"] == ns(DAY1, "08:00")
    assert mm["disconnected_at_ns"] == ns(DAY2, "12:00")
    assert mm["disconnect_reason"] == "logout"
    assert by_gateway["TRADER01"]["disconnected_at_ns"] is None


@pytest.mark.anyio
async def test_connected_only_drops_closed_sessions(venue: Venue) -> None:
    _, body = await _get(venue, "/gateway-sessions?connected_only=true")
    assert {s["gateway_id"] for s in body["sessions"]} == {"OPS01", "TRADER01"}


@pytest.mark.anyio
async def test_gateway_sessions_filter_on_the_connect_day(venue: Venue) -> None:
    _, body = await _get(venue, f"/gateway-sessions?from={DAY2}")
    assert body["sessions"] == []
    _, body = await _get(venue, f"/gateway-sessions?from={DAY1}&to={DAY1}")
    assert body["count"] == 3


def _honolulu_copy(venue: Venue, tmp_path: Path) -> Path:
    """The venue's clearing.db, recorded by a pm-clearing in Honolulu."""
    copy = tmp_path / "honolulu.db"
    with closing(sqlite3.connect(venue.clearing_db)) as src:
        with closing(sqlite3.connect(copy)) as dst:
            src.backup(dst)
            dst.execute(
                "UPDATE clearing_meta SET value = 'Pacific/Honolulu'"
                " WHERE key = 'session_timezone'"
            )
            dst.commit()
    return copy


@pytest.mark.anyio
async def test_the_connect_day_is_the_session_timezone_day(
    venue: Venue, tmp_path: Path
) -> None:
    """08:00 UTC on DAY1 is 22:00 on 2026-11-01 in Honolulu: a venue there
    filters it under the 1st, not under the UTC date."""
    copy = _honolulu_copy(venue, tmp_path)
    _, body = await _get(venue, f"/gateway-sessions?from={DAY1}", clearing_db=copy)
    assert body["sessions"] == []
    _, body = await _get(
        venue, "/gateway-sessions?from=2026-11-01&to=2026-11-01", clearing_db=copy
    )
    assert body["count"] == 3


@pytest.mark.anyio
async def test_the_cli_selects_the_same_connect_days_as_the_api(
    venue: Venue,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CG12: `pm-clearing-cli sessions` reads trading days in the session
    timezone, as the API does, and shows the connect's venue day."""
    copy = _honolulu_copy(venue, tmp_path)
    cases = [
        (f"from={DAY1}", ["--from", DAY1]),
        (
            "from=2026-11-01&to=2026-11-01",
            ["--from", "2026-11-01", "--to", "2026-11-01"],
        ),
    ]
    found: list[dict[str, Any]] = []
    for query, args in cases:
        _, body = await _get(venue, f"/gateway-sessions?{query}", clearing_db=copy)
        monkeypatch.setattr(
            "sys.argv",
            ["pm-clearing-cli", "--datapath", str(copy), "--format", "json"]
            + ["sessions", *args],
        )
        cli_main()
        out = capsys.readouterr().out
        found = json.loads(out) if out.strip() else []
        assert [(r["gateway_id"], r["connected_at_ns"]) for r in found] == [
            (s["gateway_id"], s["connected_at_ns"]) for s in body["sessions"]
        ]
    assert len(found) == 3
    assert {r["connect_date"] for r in found} == {"2026-11-01"}


@pytest.mark.anyio
async def test_a_participant_sees_only_its_own_sessions(venue: Venue) -> None:
    status, body = await _get(venue, "/gateway-sessions", MM_KEY)
    assert status == 200
    assert [s["gateway_id"] for s in body["sessions"]] == ["MM01"]
    status, body = await _get(venue, "/gateway-sessions?gateway=OPS01", MM_KEY)
    assert (status, _code(body)) == (403, "SCOPE_DENIED")


# ---------------------------------------------------------------------------
# reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_consistent_ledger_has_no_discrepancy(venue: Venue) -> None:
    status, body = await _get(venue, f"/reconciliation?from={DAY1}&to={DAY2}")
    assert status == 200
    assert body["discrepancies"] == []
    assert body["count"] == 0
    assert body["retained_from"] == DAY1
    assert (body["compared_from"], body["compared_to"]) == (DAY1, DAY2)


def _tampered(venue: Venue, tmp_path: Path) -> Path:
    """A copy of the venue's ledger with one daily row short by 10 shares."""
    copy = tmp_path / "clearing.db"
    with closing(sqlite3.connect(venue.clearing_db)) as src:
        with closing(sqlite3.connect(copy)) as dst:
            src.backup(dst)
            dst.execute(
                "UPDATE gateway_daily_summary SET buy_qty = buy_qty - 10,"
                " buy_notional = buy_notional - 10 * 18750"
                " WHERE trade_date = ? AND gateway_id = 'TRADER01'"
                " AND symbol = 'AAPL'",
                (DAY1,),
            )
            dst.commit()
    return copy


@pytest.mark.anyio
async def test_a_discrepancy_is_reported_with_units(
    venue: Venue, tmp_path: Path
) -> None:
    status, body = await _get(
        venue,
        f"/reconciliation?from={DAY1}&to={DAY2}",
        clearing_db=_tampered(venue, tmp_path),
    )
    assert status == 200
    (row,) = body["discrepancies"]
    assert (row["side"], row["trade_date"], row["gateway_id"], row["symbol"]) == (
        "BUY",
        DAY1,
        "TRADER01",
        "AAPL",
    )
    assert (row["raw_qty"], row["summary_qty"], row["qty_diff"]) == (150, 140, 10)
    assert row["tick_decimals"] == 2
    assert row["notional_diff_ticks"] == 10 * 18750
    assert row["notional_diff"] == pytest.approx(1875.0)
    assert row["raw_notional"] == pytest.approx(100 * 187.25 + 50 * 187.5)


@pytest.mark.anyio
async def test_reconciliation_filters_by_gateway_and_symbol(
    venue: Venue, tmp_path: Path
) -> None:
    tampered = _tampered(venue, tmp_path)
    for query in ("gateway=MM01", "symbol=EURUSD"):
        _, body = await _get(
            venue,
            f"/reconciliation?from={DAY1}&to={DAY2}&{query}",
            clearing_db=tampered,
        )
        assert body["discrepancies"] == [], query


@pytest.mark.anyio
async def test_reconciliation_needs_an_explicit_date_range(venue: Venue) -> None:
    for query in ("", f"?from={DAY1}", f"?to={DAY1}"):
        status, body = await _get(venue, f"/reconciliation{query}")
        assert (status, _code(body)) == (400, "VALIDATION"), query
    status, body = await _get(venue, f"/reconciliation?from={DAY2}&to={DAY1}")
    assert (status, body["error"]["field"]) == (400, "from")


@pytest.mark.anyio
async def test_days_before_the_retained_raw_trades_are_not_compared(
    venue: Venue, tmp_path: Path
) -> None:
    """Pruned raw days keep their summaries; comparing them would flag every
    one. The range is clamped to `retained_from`, and the reply says so."""
    copy = tmp_path / "pruned.db"
    with closing(sqlite3.connect(venue.clearing_db)) as src:
        with closing(sqlite3.connect(copy)) as dst:
            src.backup(dst)
            dst.execute("DELETE FROM trade_events WHERE trade_date = ?", (DAY1,))
            dst.commit()
    _, body = await _get(
        venue, f"/reconciliation?from={DAY1}&to={DAY2}", clearing_db=copy
    )
    assert body["discrepancies"] == []
    assert body["retained_from"] == DAY2
    assert (body["compared_from"], body["compared_to"]) == (DAY2, DAY2)
    _, body = await _get(
        venue, f"/reconciliation?from={DAY1}&to={DAY1}", clearing_db=copy
    )
    assert (body["compared_from"], body["compared_to"]) == (None, None)


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_readable_db_and_a_silent_process_are_reported_apart(
    venue: Venue,
) -> None:
    status, body = await _get(venue, "/health")
    assert status == 200
    database = body["database"]
    assert database["available"] is True
    assert database["wal_mode"] == "wal"
    assert database["trade_events_rows"] == 5
    assert database["gateway_symbol_positions_rows"] == 4
    stored = rows(venue.clearing_db, "SELECT MAX(ts_ns) AS ts FROM trade_events")
    assert database["last_trade_ts_ns"] == stored[0]["ts"]
    assert database["last_flush_ts_ns"] is not None
    assert body["process"]["alive"] is False
    assert "no reply" in body["process"]["detail"]
    # No path or address reaches the client.
    text = str(body)
    assert str(venue.clearing_db) not in text and "127.0.0.1" not in text


@pytest.mark.anyio
async def test_a_live_receive_loop_is_alive(
    venue: Venue, monkeypatch: pytest.MonkeyPatch
) -> None:
    addr = f"inproc://clearing-health-{uuid.uuid4().hex}"
    rep: zmq.Socket[bytes] = zmq.Context.instance().socket(zmq.REP)
    rep.bind(addr)

    def _answer() -> None:
        if rep.poll(5000):
            answer_health_ping(rep)

    thread = threading.Thread(target=_answer, daemon=True)
    thread.start()
    monkeypatch.setattr(clearing_router, "_HEALTH_ADDR", addr)
    monkeypatch.setattr(clearing_router, "_HEALTH_TIMEOUT_MS", 3000)
    try:
        status, body = await _get(venue, "/health")
    finally:
        thread.join(timeout=5)
        rep.close(0)
    assert status == 200
    assert body["process"]["alive"] is True
    assert body["process"]["detail"].startswith("replied at ")


@pytest.mark.anyio
async def test_a_missing_db_keeps_the_process_answer(
    venue: Venue, tmp_path: Path
) -> None:
    status, body = await _get(venue, "/health", clearing_db=tmp_path / "gone.db")
    assert status == 200
    assert body["database"]["available"] is False
    assert body["database"]["detail"] == "not found"
    assert body["database"]["trade_events_rows"] is None
    assert body["process"]["alive"] is False


# ---------------------------------------------------------------------------
# access
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    ["/session-events", f"/reconciliation?from={DAY1}&to={DAY2}", "/health"],
)
async def test_venue_wide_evidence_is_admin_only(venue: Venue, path: str) -> None:
    for key, code in (
        (TRADER_KEY, "ROLE_DENIED"),
        (MM_KEY, "ROLE_DENIED"),
        (READ_ONLY_KEY, "READ_ONLY"),
    ):
        status, body = await _get(venue, path, key)
        assert (status, _code(body)) == (403, code), (path, key)


@pytest.mark.anyio
async def test_a_missing_ledger_is_503_for_the_evidence_lists(
    venue: Venue, tmp_path: Path
) -> None:
    for path in (
        "/session-events",
        "/gateway-sessions",
        f"/reconciliation?from={DAY1}&to={DAY2}",
    ):
        status, body = await _get(venue, path, clearing_db=tmp_path / "gone.db")
        assert (status, _code(body)) == (503, "CLEARING_DB"), path
