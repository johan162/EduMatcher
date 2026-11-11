"""CG13 (F9): reconciliation across a ``tick_decimals`` change.

K6 keeps a symbol's daily row in ticks of the *latest* trade's precision: the
row already stored is converted when a trade at a new precision lands on the
same trading day. The raw trades keep their own precision, so comparing raw
``quantity * price`` with that row reported false notional discrepancies.
Each raw trade is now converted to the daily row's precision first.

The ledger is written by pm-clearing's own ``ClearingProcess`` from generated
``TradeExecuted`` messages, one flush per trade, so the daily row is converted
by the real upsert and not by the test. ``pm-clearing-cli reconcile`` and
``GET /api/v1/clearing/reconciliation`` must agree with the store.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import timezone
from pathlib import Path

import pytest

from edumatcher.clearing.cli import main as cli_main
from edumatcher.clearing.main import ClearingProcess
from edumatcher.clearing.query import open_readonly_connection
from edumatcher.clearing.store import query_reconcile
from tests.api_gateway_harness import call
from tests.clearing_api_fixture import (
    ADMIN_KEY,
    DAY1,
    Venue,
    _Feed,
    _trade,
    build_venue,
    make_clearing_app,
    ns,
)

#: (seq, time, symbol, buyer, seller, qty, price, tick_decimals). AAPL's
#: precision grows during DAY1 (exact), MSFT's shrinks on prices that the
#: coarser precision still represents.
_TRADES = [
    (1, "10:00", "AAPL", "TRADER01", "MM01", 100, 187.25, 2),
    (2, "11:00", "AAPL", "MM01", "TRADER01", 30, 187.2512, 4),
    (3, "12:00", "AAPL", "TRADER01", "MM01", 20, 187.3, 4),
    (4, "10:30", "MSFT", "TRADER01", "MM01", 10, 410.5, 4),
    (5, "11:30", "MSFT", "MM01", "TRADER01", 10, 410.25, 2),
]


@pytest.fixture(scope="module")
def venue(tmp_path_factory: pytest.TempPathFactory) -> Venue:
    return build_venue(tmp_path_factory.mktemp("venue"))


@pytest.fixture(scope="module")
def changed_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A clearing.db holding one trading day across two precision changes."""
    path = tmp_path_factory.mktemp("precision") / "clearing.db"
    process = ClearingProcess(
        pub_addr="inproc://unused",
        db_path=path,
        print_every=0,
        retention_days=0,
        session_tz=timezone.utc,
    )
    feed = _Feed(process)
    try:
        feed.phase(ns(DAY1, "09:00"), "CONTINUOUS", "PRE_OPEN")
        for seq, hhmm, symbol, buyer, seller, qty, price, decimals in sorted(
            _TRADES, key=lambda t: t[1]
        ):
            trade = _trade(
                seq, ns(DAY1, hhmm), symbol, buyer, seller, qty, price, decimals
            )
            feed.trade(trade, f"01JC00000000000000000000{seq:02d}")
    finally:
        process._conn.close()
    return path


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_the_daily_rows_were_converted(changed_db: Path) -> None:
    """The precondition: K6 converted each day's row to the last precision."""
    with closing(open_readonly_connection(changed_db)) as conn:
        found = {
            r["symbol"]: r["tick_decimals"]
            for r in conn.execute(
                "SELECT symbol, tick_decimals FROM gateway_daily_summary"
            )
        }
    assert found == {"AAPL": 4, "MSFT": 2}


def test_a_precision_change_is_not_a_discrepancy(changed_db: Path) -> None:
    with closing(open_readonly_connection(changed_db)) as conn:
        assert query_reconcile(conn) == []


def test_a_real_discrepancy_is_still_reported_in_the_row_precision(
    changed_db: Path, tmp_path: Path
) -> None:
    """Losing the 11:00 AAPL print shows its notional at 4 decimals."""
    copy = tmp_path / "lost.db"
    copy.write_bytes(changed_db.read_bytes())
    with closing(sqlite3.connect(copy)) as conn:
        conn.execute("DELETE FROM trade_events WHERE id = '000007-000000002'")
        conn.commit()
    with closing(open_readonly_connection(copy)) as conn:
        found = query_reconcile(conn, symbol="AAPL")
    assert {(r["side"], r["gateway_id"]) for r in found} == {
        ("BUY", "MM01"),
        ("SELL", "TRADER01"),
    }
    for r in found:
        assert (r["qty_diff"], r["notional_diff"], r["tick_decimals"]) == (
            -30,
            -30 * 1_872_512,
            4,
        )


def test_the_cli_reports_no_discrepancy(
    changed_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["pm-clearing-cli", "--datapath", str(changed_db), "reconcile"],
    )
    cli_main()
    assert "OK — no discrepancies found." in capsys.readouterr().out


@pytest.mark.anyio
async def test_the_api_reports_no_discrepancy(venue: Venue, changed_db: Path) -> None:
    status, _, body = await call(
        make_clearing_app(venue, clearing_db=changed_db),
        "GET",
        f"/api/v1/clearing/reconciliation?from={DAY1}&to={DAY1}",
        authorization=f"Bearer {ADMIN_KEY}",
    )
    assert status == 200, json.dumps(body)
    assert body["discrepancies"] == []
