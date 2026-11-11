"""CG0: the clearing fixture, and the scope policy every clearing route applies.

ADMIN reads the venue, a TRADER or MARKET_MAKER reads its own gateway only, a
foreign gateway is refused rather than quietly replaced, and a read-only key
(no gateway) reads no clearing data at all. The policy is enforced at the
server: tests call the resolver with the authenticated session, never with a
UI-supplied role.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from edumatcher.api_gateway.clearing_scope import ClearingScope, clearing_scope
from edumatcher.api_gateway.config import ApiGatewayConfig, TimeoutConfig
from edumatcher.api_gateway.sessions import Session
from edumatcher.clearing.query import open_readonly_connection
from edumatcher.eod.ledger import open_ledger_readonly
from edumatcher.eod.roster import load_roster
from tests.clearing_api_fixture import (
    DAY1,
    DAY2,
    FakeEngine,
    OPENINGS,
    Venue,
    build_venue,
    rows,
)


@pytest.fixture(scope="module")
def venue(tmp_path_factory: pytest.TempPathFactory) -> Venue:
    return build_venue(tmp_path_factory.mktemp("venue"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _request() -> Any:
    state = SimpleNamespace(
        engine=FakeEngine(), config=ApiGatewayConfig(timeouts=TimeoutConfig())
    )
    return SimpleNamespace(app=SimpleNamespace(state=state), client=None)


def _session(gateway_id: str | None) -> Session:
    return Session(api_key="k", gateway_id=gateway_id, description="")


async def _scope(gateway_id: str | None, requested: str | None = None) -> Any:
    return await clearing_scope(_request(), _session(gateway_id), requested)


async def _refusal(gateway_id: str | None, requested: str | None = None) -> Any:
    with pytest.raises(HTTPException) as caught:
        await _scope(gateway_id, requested)
    return caught.value


# ---------------------------------------------------------------------------
# Scope policy
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_reads_the_whole_venue() -> None:
    assert await _scope("OPS01") == ClearingScope(
        caller="OPS01", admin=True, gateway=None
    )


@pytest.mark.anyio
async def test_admin_may_narrow_to_any_gateway() -> None:
    scope = await _scope("OPS01", "mm01")
    assert scope == ClearingScope(caller="OPS01", admin=True, gateway="MM01")


@pytest.mark.anyio
@pytest.mark.parametrize("gateway_id", ["TRADER01", "MM01"])
async def test_a_participant_is_scoped_to_itself(gateway_id: str) -> None:
    expected = ClearingScope(caller=gateway_id, admin=False, gateway=gateway_id)
    assert await _scope(gateway_id) == expected
    assert await _scope(gateway_id, gateway_id.lower()) == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("gateway_id", "foreign"),
    [("TRADER01", "MM01"), ("MM01", "TRADER01"), ("TRADER01", "EXCHANGE")],
)
async def test_a_participant_asking_for_another_gateway_is_refused(
    gateway_id: str, foreign: str
) -> None:
    refusal = await _refusal(gateway_id, foreign)
    assert refusal.status_code == 403
    assert refusal.detail["error"]["code"] == "SCOPE_DENIED"
    assert foreign in refusal.detail["error"]["message"]


@pytest.mark.anyio
async def test_a_read_only_key_has_no_clearing_scope() -> None:
    for requested in (None, "TRADER01"):
        refusal = await _refusal(None, requested)
        assert refusal.status_code == 403
        assert refusal.detail["error"]["code"] == "READ_ONLY"


@pytest.mark.anyio
async def test_an_unanswered_role_lookup_fails_closed() -> None:
    """EngineClient.resolve_role answers TRADER when the engine is silent: an
    ADMIN then sees only its own gateway, never more."""
    request = _request()
    request.app.state.engine.roles = {}
    scope = await clearing_scope(request, _session("OPS01"), None)
    assert scope == ClearingScope(caller="OPS01", admin=False, gateway="OPS01")


# ---------------------------------------------------------------------------
# The fixture: realistic data, opened the way the gateway opens it
# ---------------------------------------------------------------------------


def test_the_gateway_paths_open_both_stores_read_only(venue: Venue) -> None:
    config = ApiGatewayConfig(clearing_db=venue.clearing_db, eod_db=venue.eod_db)
    assert config.eod_roster == venue.roster
    with closing(open_readonly_connection(config.clearing_db)) as clearing:
        assert clearing.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0] == 5
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            clearing.execute("DELETE FROM trade_events")
    with closing(open_ledger_readonly(config.eod_db)) as ledger:
        assert ledger.execute("SELECT COUNT(*) FROM eod_runs").fetchone()[0] == 3
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            ledger.execute("DELETE FROM eod_runs")
    roster = load_roster(config.eod_roster)
    assert {g: t.opening_minor for g, t in roster.items()} == OPENINGS


def test_a_missing_ledger_is_not_created(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_ledger_readonly(tmp_path / "eod.db")
    assert not (tmp_path / "eod.db").exists()


def test_the_fixture_covers_cross_symbol_precision(venue: Venue) -> None:
    precision = rows(
        venue.clearing_db,
        "SELECT DISTINCT symbol, tick_decimals FROM gateway_symbol_positions",
    )
    assert {(r["symbol"], r["tick_decimals"]) for r in precision} == {
        ("AAPL", 2),
        ("EURUSD", 4),
    }
    signs = rows(
        venue.clearing_db,
        "SELECT gateway_id, symbol, net_qty FROM gateway_symbol_positions",
    )
    by_key = {(r["gateway_id"], r["symbol"]): r["net_qty"] for r in signs}
    assert by_key == {
        ("TRADER01", "AAPL"): 110,
        ("MM01", "AAPL"): -110,
        ("TRADER01", "EURUSD"): -500,
        ("MM01", "EURUSD"): 500,
    }


def test_the_fixture_keeps_trade_audit_fields(venue: Venue) -> None:
    stored = rows(
        venue.clearing_db,
        "SELECT id, match_type, msg_id FROM trade_events ORDER BY id",
    )
    assert stored[2] == {
        "id": "000007-000000003",
        "match_type": "CLOSING_AUCTION",
        "msg_id": "01JC0000000000000000000003",
    }


def test_the_fixture_has_every_session_event_type(venue: Venue) -> None:
    events = rows(
        venue.clearing_db,
        "SELECT event_type, trade_date, payload_json FROM session_events",
    )
    assert {e["event_type"] for e in events} == {"PHASE", "GAP", "EOD"}
    (gap,) = [e for e in events if e["event_type"] == "GAP"]
    assert gap["trade_date"] == DAY2
    assert '"missing_trades": 2' in gap["payload_json"]
    closes = rows(
        venue.clearing_db,
        "SELECT DISTINCT trade_date FROM position_close_snapshot ORDER BY 1",
    )
    assert [c["trade_date"] for c in closes] == [DAY1, DAY2]


def test_the_fixture_has_open_and_closed_gateway_sessions(venue: Venue) -> None:
    sessions = rows(
        venue.clearing_db,
        "SELECT gateway_id, disconnected_at_ns, disconnect_reason"
        " FROM gateway_sessions ORDER BY gateway_id",
    )
    assert [(s["gateway_id"], s["disconnect_reason"]) for s in sessions] == [
        ("MM01", "logout"),
        ("OPS01", None),
        ("TRADER01", None),
    ]


def test_the_fixture_settles_zero_sum_with_a_rounding_line(venue: Venue) -> None:
    settled = rows(
        venue.eod_db,
        "SELECT trade_date, account, amount_minor FROM eod_settlement",
    )
    by_date: dict[str, dict[str, int]] = {}
    for row in settled:
        by_date.setdefault(row["trade_date"], {})[row["account"]] = row["amount_minor"]
    assert set(by_date) == {DAY1, DAY2}
    assert "EXCHANGE" in by_date[DAY2] and "EXCHANGE" not in by_date[DAY1]
    for amounts in by_date.values():
        assert sum(amounts.values()) == 0
        assert {a for a in amounts if a != "EXCHANGE"} == {"TRADER01", "MM01"}
    runs = rows(venue.eod_db, "SELECT trade_date, status FROM eod_runs ORDER BY 1")
    assert [r["status"] for r in runs] == ["ok", "report-failed", "failed"]
