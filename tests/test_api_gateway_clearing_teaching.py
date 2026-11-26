"""CG26: the clearing figures the teaching pictures need.

- ``/clearing/symbols`` reports the long and the short side of each symbol
  separately (decision D8 in the clearing-GUI workplan): every share held
  long is held short by someone else.
- ``/clearing/netting`` reports one trading day's trades against the one net
  amount each gateway is left with (D11): the venue for ADMIN, the caller's
  own gateway for a participant.

Driven through the whole ASGI app against the venue recorded by the real
pm-clearing process (``tests/clearing_api_fixture.py``):

* 2026-11-02: TRADER01 buys 100 AAPL at 187.25 and 50 at 187.50 from MM01,
  and sells 1000 EURUSD at 1.0850 to it.
* 2026-11-03: TRADER01 sells 40 AAPL at 188.00 to MM01 and buys 500 EURUSD
  at 1.0862 from it.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

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
)

#: DAY1's trade values, display currency.
AAPL_BOUGHT_DAY1 = 100 * 187.25 + 50 * 187.5
EURUSD_DAY1 = 1000 * 1.085
#: DAY2's.
AAPL_DAY2 = 40 * 188.0
EURUSD_DAY2 = 500 * 1.0862


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


def _copy(db: Path, to: Path) -> Path:
    """A private copy of *db* a test may change."""
    with closing(sqlite3.connect(db)) as source, closing(sqlite3.connect(to)) as dest:
        source.backup(dest)
    return to


# ---------------------------------------------------------------------------
# long and short per symbol
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_symbols_report_the_long_and_the_short_side(venue: Venue) -> None:
    status, body = await _get(venue, "/symbols")
    assert status == 200
    by_symbol = {r["symbol"]: r for r in body["symbols"]}
    # TRADER01 ends long 110 AAPL and short 500 EURUSD; MM01 the other side.
    assert {
        s: (
            r["open_long_qty"],
            r["open_short_qty"],
            r["long_holders"],
            r["short_holders"],
        )
        for s, r in by_symbol.items()
    } == {"AAPL": (110, 110, 1, 1), "EURUSD": (500, 500, 1, 1)}
    for r in by_symbol.values():
        assert r["open_long_qty"] - r["open_short_qty"] == r["open_net_qty"]


@pytest.mark.anyio
async def test_a_flat_position_is_on_neither_side(venue: Venue, tmp_path: Path) -> None:
    db = _copy(venue.clearing_db, tmp_path / "clearing.db")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(
            "INSERT INTO gateway_symbol_positions (gateway_id, symbol, net_qty,"
            " tick_decimals, avg_cost, mark_price, realized_pnl, unrealized_pnl,"
            " buy_qty, sell_qty, buy_notional, sell_notional, last_trade_ts_ns,"
            " updated_ts_ns) VALUES ('FLAT01', 'AAPL', 0, 2, 0, 18800, 500, 0,"
            " 10, 10, 187000, 187500, 1, 1)"
        )
        conn.commit()
    _, body = await _get(venue, "/symbols", clearing_db=db)
    aapl = next(r for r in body["symbols"] if r["symbol"] == "AAPL")
    assert (aapl["long_holders"], aapl["short_holders"]) == (1, 1)


# ---------------------------------------------------------------------------
# netting
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_venue_nets_a_day_of_trades_to_one_amount_per_gateway(
    venue: Venue,
) -> None:
    status, body = await _get(venue, f"/netting?date={DAY1}")
    assert status == 200
    assert body["trade_date"] == DAY1
    assert body["trades_retained"] is True
    assert body["trade_count"] == 3
    # Each trade counted once: 100 + 50 AAPL and 1000 EURUSD.
    assert body["traded_qty"] == 1150
    assert body["gross_value"] == pytest.approx(AAPL_BOUGHT_DAY1 + EURUSD_DAY1)
    gateways = {g["gateway_id"]: g for g in body["gateways"]}
    assert set(gateways) == {"TRADER01", "MM01"}
    trader = gateways["TRADER01"]
    assert trader["bought_value"] == pytest.approx(AAPL_BOUGHT_DAY1)
    assert trader["sold_value"] == pytest.approx(EURUSD_DAY1)
    assert trader["net_amount"] == pytest.approx(AAPL_BOUGHT_DAY1 - EURUSD_DAY1)
    assert trader["trade_count"] == 3
    assert gateways["MM01"]["net_amount"] == pytest.approx(
        -(AAPL_BOUGHT_DAY1 - EURUSD_DAY1)
    )
    # What one side pays, the other receives.
    assert sum(g["net_amount"] for g in body["gateways"]) == pytest.approx(0.0)
    assert body["payment_count"] == 2
    assert body["net_paid"] == pytest.approx(AAPL_BOUGHT_DAY1 - EURUSD_DAY1)
    assert body["net_received"] == pytest.approx(AAPL_BOUGHT_DAY1 - EURUSD_DAY1)


@pytest.mark.anyio
async def test_netting_defaults_to_the_latest_trading_day(venue: Venue) -> None:
    status, body = await _get(venue, "/netting")
    assert status == 200
    assert (body["trade_date"], body["trade_count"]) == (DAY2, 2)
    assert body["gross_value"] == pytest.approx(AAPL_DAY2 + EURUSD_DAY2)


@pytest.mark.anyio
async def test_a_participant_nets_only_its_own_day(venue: Venue) -> None:
    status, body = await _get(venue, f"/netting?date={DAY1}", TRADER_KEY)
    assert status == 200
    assert [g["gateway_id"] for g in body["gateways"]] == ["TRADER01"]
    # Its own trades, each once: what it bought and what it sold.
    assert body["trade_count"] == 3
    assert body["traded_qty"] == 1150
    assert body["gross_value"] == pytest.approx(AAPL_BOUGHT_DAY1 + EURUSD_DAY1)
    assert body["payment_count"] == 1
    assert body["net_paid"] == pytest.approx(AAPL_BOUGHT_DAY1 - EURUSD_DAY1)
    assert body["net_received"] == pytest.approx(0.0)
    _, body = await _get(venue, f"/netting?date={DAY2}", MM_KEY)
    (mm,) = body["gateways"]
    assert mm["gateway_id"] == "MM01"
    assert mm["net_amount"] == pytest.approx(AAPL_DAY2 - EURUSD_DAY2)


@pytest.mark.anyio
async def test_an_admin_may_net_one_gateway_and_a_participant_only_itself(
    venue: Venue,
) -> None:
    _, own = await _get(venue, f"/netting?date={DAY1}", TRADER_KEY)
    status, body = await _get(venue, f"/netting?date={DAY1}&gateway=trader01")
    assert status == 200
    assert body == own
    status, body = await _get(venue, "/netting?gateway=MM01", TRADER_KEY)
    assert (status, _code(body)) == (403, "SCOPE_DENIED")


@pytest.mark.anyio
async def test_a_pruned_day_still_nets_from_its_daily_rows(
    venue: Venue, tmp_path: Path
) -> None:
    db = _copy(venue.clearing_db, tmp_path / "clearing.db")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("DELETE FROM trade_events WHERE trade_date = ?", (DAY1,))
        conn.commit()
    status, body = await _get(venue, f"/netting?date={DAY1}", clearing_db=db)
    assert status == 200
    assert body["trades_retained"] is False
    assert body["trade_count"] is None
    assert all(g["trade_count"] is None for g in body["gateways"])
    assert body["gross_value"] == pytest.approx(AAPL_BOUGHT_DAY1 + EURUSD_DAY1)


@pytest.mark.anyio
async def test_a_day_without_trades_is_an_empty_netting(venue: Venue) -> None:
    status, body = await _get(venue, "/netting?date=2026-12-01")
    assert status == 200
    assert body == {
        "trade_date": "2026-12-01",
        "trades_retained": True,
        "trade_count": 0,
        "traded_qty": 0,
        "gross_value": 0.0,
        "payment_count": 0,
        "net_paid": 0.0,
        "net_received": 0.0,
        "gateways": [],
    }


@pytest.mark.anyio
async def test_an_empty_ledger_has_no_day_to_net(venue: Venue, tmp_path: Path) -> None:
    db = tmp_path / "clearing.db"
    with closing(sqlite3.connect(db)) as conn:
        apply_schema(conn)
    status, body = await _get(venue, "/netting", clearing_db=db)
    assert status == 200
    assert (body["trade_date"], body["trade_count"], body["gateways"]) == (
        None,
        0,
        [],
    )


@pytest.mark.anyio
async def test_netting_refuses_a_bad_date_and_a_read_only_key(venue: Venue) -> None:
    status, body = await _get(venue, "/netting?date=2026-13-01")
    assert (status, _code(body), body["error"]["field"]) == (400, "VALIDATION", "date")
    status, body = await _get(venue, "/netting", READ_ONLY_KEY)
    assert (status, _code(body)) == (403, "READ_ONLY")
