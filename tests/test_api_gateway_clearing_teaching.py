"""CG26 and CG28: the clearing figures the teaching pictures need.

- ``/clearing/symbols`` reports the long and the short side of each symbol
  separately (decision D8 in the clearing-GUI workplan): every share held
  long is held short by someone else.
- ``/clearing/netting`` reports one trading day's trades against the one net
  amount each gateway is left with (D11): the venue for ADMIN, the caller's
  own gateway for a participant.
- ``/clearing/position-replay`` replays one gateway's position in one symbol
  through one day, fill by fill, by pm-clearing's own rules (D9), and says
  whether it ends where the ledger does.

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

from edumatcher.clearing import replay
from edumatcher.clearing.query import open_readonly_connection
from edumatcher.clearing.store import apply_schema, query_netting
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


def _plans(db: Path, work: Any) -> list[str]:
    """The query plan of every statement *work* runs against ``trade_events``."""
    with closing(open_readonly_connection(db, 5000)) as conn:
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        work(conn)
        conn.set_trace_callback(None)
        return [
            " | ".join(r[3] for r in conn.execute(f"EXPLAIN QUERY PLAN {sql}"))
            for sql in statements
            if "trade_events" in sql and sql.lstrip().upper().startswith("SELECT")
            # query_retained_from: one look at the index's first entry.
            and "MIN(trade_date)" not in sql
        ]


def test_netting_counts_trades_from_the_gateway_indexes(venue: Venue) -> None:
    # Review of CG25-CG32 (P1): netting is polled every 30 s on every open
    # Settlement and Overview in Explain mode. Counting a gateway's trades
    # must read its own index entries, never walk the whole day's trades:
    # on a 100 000-trade day that walk cost 150 ms per call.
    def own(conn: sqlite3.Connection) -> None:
        query_netting(conn, trade_date=DAY1, gateway="TRADER01")

    def venue_wide(conn: sqlite3.Connection) -> None:
        query_netting(conn, trade_date=DAY1)

    for plan in _plans(venue.clearing_db, own):
        assert (
            "ix_trade_events_buy_gw_date" in plan
            or "ix_trade_events_sell_gw_date" in plan
        ), plan
    venue_plans = _plans(venue.clearing_db, venue_wide)
    # One count of the day's trades; every per-gateway count from its index.
    assert sum("ix_trade_events_date_ts" in p for p in venue_plans) <= 1, venue_plans
    assert not any("TEMP B-TREE" in p for p in venue_plans), venue_plans


@pytest.mark.anyio
async def test_netting_counts_a_trade_with_itself_once(
    venue: Venue, tmp_path: Path
) -> None:
    db = _copy(venue.clearing_db, tmp_path / "clearing.db")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(
            "INSERT INTO trade_events (id, ts_ns, trade_date, symbol, quantity,"
            " price, tick_decimals, buy_gateway_id, sell_gateway_id, ingest_ts_ns)"
            " VALUES ('SELF1', 1, ?, 'AAPL', 1, 18700, 2, 'TRADER01', 'TRADER01', 1)",
            (DAY1,),
        )
        conn.commit()
    _, own = await _get(venue, f"/netting?date={DAY1}", TRADER_KEY, clearing_db=db)
    assert own["trade_count"] == 4
    _, whole = await _get(venue, f"/netting?date={DAY1}", clearing_db=db)
    assert whole["trade_count"] == 4
    trader = next(g for g in whole["gateways"] if g["gateway_id"] == "TRADER01")
    assert trader["trade_count"] == 4


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


# ---------------------------------------------------------------------------
# position replay (CG28)
# ---------------------------------------------------------------------------

#: A day in a hand-made ledger, for the step kinds the venue does not have.
REPLAY_DAY = "2026-11-10"


def _trade_row(
    conn: sqlite3.Connection,
    seq: int,
    side: str,
    qty: int,
    price: int,
    tick_decimals: int = 2,
    day: str = REPLAY_DAY,
) -> None:
    """One raw trade of T1 in XYZ against a counterparty, in feed order."""
    buyer, seller = ("T1", "CP") if side == "BUY" else ("CP", "T1")
    conn.execute(
        "INSERT INTO trade_events (id, ts_ns, trade_date, symbol, quantity, price,"
        " tick_decimals, buy_gateway_id, sell_gateway_id, ingest_ts_ns)"
        " VALUES (?, ?, ?, 'XYZ', ?, ?, ?, ?, ?, ?)",
        (f"T{seq}", seq, day, qty, price, tick_decimals, buyer, seller, seq),
    )


def _daily_row(
    conn: sqlite3.Connection,
    day: str,
    end_net_qty: int,
    end_avg_cost: float,
    tick_decimals: int,
    realized: float = 0.0,
) -> None:
    conn.execute(
        "INSERT INTO gateway_daily_summary (trade_date, gateway_id, symbol,"
        " traded_qty, traded_notional, buy_qty, sell_qty, buy_notional,"
        " sell_notional, net_amount, realized_pnl, end_net_qty, end_avg_cost,"
        " end_unrealized_pnl, tick_decimals, updated_ts_ns)"
        " VALUES (?, 'T1', 'XYZ', 0, 0, 0, 0, 0, 0, 0, ?, ?, ?, 0, ?, 0)",
        (day, realized, end_net_qty, end_avg_cost, tick_decimals),
    )


def _ledger(tmp_path: Path, fill: Any) -> Path:
    db = tmp_path / "clearing.db"
    with closing(sqlite3.connect(db)) as conn:
        apply_schema(conn)
        fill(conn)
        conn.commit()
    return db


def _steps(body: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (s["kind"], s["net_qty"], s["avg_cost"], s["realized_delta"])
        for s in body["steps"]
    ]


@pytest.mark.anyio
async def test_a_replay_builds_the_day_by_clearing_s_own_rules(venue: Venue) -> None:
    status, body = await _get(
        venue, f"/position-replay?symbol=AAPL&date={DAY1}", TRADER_KEY
    )
    assert status == 200
    assert (body["gateway_id"], body["symbol"], body["trade_date"]) == (
        "TRADER01",
        "AAPL",
        DAY1,
    )
    assert body["start"] == {
        "net_qty": 0,
        "avg_cost": 0.0,
        "avg_cost_ticks": 0.0,
        "tick_decimals": 2,
    }
    assert _steps(body) == [
        ("open", 100, 187.25, 0.0),
        ("add", 150, pytest.approx((18725 * 100 + 18750 * 50) / 150 / 100), 0.0),
    ]
    first = body["steps"][0]
    assert (first["side"], first["quantity"], first["price"], first["price_ticks"]) == (
        "BUY",
        100,
        187.25,
        18725,
    )
    assert body["matches_daily_row"] is True


@pytest.mark.anyio
async def test_a_replay_starts_from_the_previous_day_and_ends_on_the_ledger(
    venue: Venue,
) -> None:
    # The latest day by default; DAY1 left TRADER01 long 150 AAPL.
    status, body = await _get(venue, "/position-replay?symbol=aapl", TRADER_KEY)
    assert status == 200
    assert body["trade_date"] == DAY2
    assert body["start"]["net_qty"] == 150
    ((kind, net, avg, realized),) = _steps(body)
    assert (kind, net) == ("reduce", 110)
    assert avg == pytest.approx(187.3333333)
    assert realized == pytest.approx((188.0 - 187.3333333) * 40)
    assert body["steps"][0]["realized_day"] == pytest.approx(realized)
    assert body["steps"][0]["unrealized"] == pytest.approx(110 * (188.0 - avg))
    assert body["matches_daily_row"] is True
    assert body["matches_position"] is True
    assert body["daily_row"]["end_net_qty"] == 110


@pytest.mark.anyio
async def test_every_day_of_the_recorded_venue_replays_onto_the_ledger(
    venue: Venue,
) -> None:
    # The ledger recorded these days itself: a replay by its rules must agree.
    for gateway in ("TRADER01", "MM01"):
        for symbol in ("AAPL", "EURUSD"):
            for day in (DAY1, DAY2):
                _, body = await _get(
                    venue,
                    f"/position-replay?gateway={gateway}&symbol={symbol}&date={day}",
                )
                assert body["steps"], (gateway, symbol, day)
                assert body["matches_daily_row"] is True, (gateway, symbol, day)
                expected = True if day == DAY2 else None
                assert body["matches_position"] is expected, (gateway, symbol, day)


@pytest.mark.anyio
async def test_every_kind_of_step(venue: Venue, tmp_path: Path) -> None:
    def fill(conn: sqlite3.Connection) -> None:
        for seq, (side, qty, price) in enumerate(
            [
                ("BUY", 100, 1000),  # open long 100 at 10.00
                ("BUY", 100, 1200),  # add: average 11.00
                ("SELL", 50, 1300),  # reduce: +2.00 × 50
                ("SELL", 150, 900),  # close: −2.00 × 150
                ("SELL", 30, 800),  # open short 30 at 8.00
                ("BUY", 50, 700),  # flip: +1.00 × 30, then long 20 at 7.00
            ],
            start=1,
        ):
            _trade_row(conn, seq, side, qty, price)

    db = _ledger(tmp_path, fill)
    status, body = await _get(
        venue,
        f"/position-replay?gateway=T1&symbol=XYZ&date={REPLAY_DAY}",
        clearing_db=db,
    )
    assert status == 200
    assert _steps(body) == [
        ("open", 100, 10.0, 0.0),
        ("add", 200, 11.0, 0.0),
        ("reduce", 150, 11.0, 100.0),
        ("close", 0, 0.0, -300.0),
        ("open", -30, 8.0, 0.0),
        ("flip", 20, 7.0, 30.0),
    ]
    assert body["steps"][-1]["realized_day"] == pytest.approx(100 - 300 + 30)
    # No daily row to compare with: not a mismatch, just no check.
    assert body["matches_daily_row"] is None
    assert body["daily_row"] is None


@pytest.mark.anyio
async def test_a_replay_converts_a_carried_position_to_a_new_precision(
    venue: Venue, tmp_path: Path
) -> None:
    def fill(conn: sqlite3.Connection) -> None:
        _daily_row(conn, "2026-11-09", 100, 1000.0, 2)  # long 100 at 10.00
        _trade_row(conn, 1, "SELL", 100, 110000, tick_decimals=4)  # 11.0000

    db = _ledger(tmp_path, fill)
    _, body = await _get(
        venue,
        f"/position-replay?gateway=T1&symbol=XYZ&date={REPLAY_DAY}",
        clearing_db=db,
    )
    assert body["start"] == {
        "net_qty": 100,
        "avg_cost": 10.0,
        "avg_cost_ticks": 1000.0,
        "tick_decimals": 2,
    }
    (step,) = body["steps"]
    assert (step["kind"], step["tick_decimals"]) == ("close", 4)
    assert step["realized_delta"] == pytest.approx(100.0)
    assert step["realized_delta_ticks"] == pytest.approx(1_000_000)


@pytest.mark.anyio
async def test_a_replay_that_disagrees_with_the_ledger_says_so(
    venue: Venue, tmp_path: Path
) -> None:
    db = _copy(venue.clearing_db, tmp_path / "clearing.db")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(
            "UPDATE gateway_daily_summary SET end_net_qty = 111"
            " WHERE trade_date = ? AND gateway_id = 'TRADER01' AND symbol = 'AAPL'",
            (DAY2,),
        )
        conn.commit()
    _, body = await _get(
        venue, f"/position-replay?symbol=AAPL&date={DAY2}", TRADER_KEY, clearing_db=db
    )
    assert body["steps"][-1]["net_qty"] == 110
    assert body["matches_daily_row"] is False
    assert body["daily_row"]["end_net_qty"] == 111


@pytest.mark.anyio
async def test_a_pruned_day_has_no_steps(venue: Venue, tmp_path: Path) -> None:
    db = _copy(venue.clearing_db, tmp_path / "clearing.db")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("DELETE FROM trade_events WHERE trade_date = ?", (DAY1,))
        conn.commit()
    _, body = await _get(
        venue, f"/position-replay?symbol=AAPL&date={DAY1}", TRADER_KEY, clearing_db=db
    )
    assert body["trades_retained"] is False
    assert body["steps"] == []
    assert body["matches_daily_row"] is None


@pytest.mark.anyio
async def test_a_long_day_is_capped_and_not_checked(
    venue: Venue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(replay, "MAX_STEPS", 1)
    _, body = await _get(venue, f"/position-replay?symbol=AAPL&date={DAY1}", TRADER_KEY)
    assert (len(body["steps"]), body["has_more"]) == (1, True)
    assert body["matches_daily_row"] is None


@pytest.mark.anyio
async def test_a_pair_that_never_traded_has_no_day(venue: Venue) -> None:
    status, body = await _get(venue, "/position-replay?symbol=TSLA", TRADER_KEY)
    assert status == 200
    assert (body["trade_date"], body["steps"], body["start"]["net_qty"]) == (
        None,
        [],
        0,
    )


@pytest.mark.anyio
async def test_a_replay_is_scoped_and_needs_a_symbol(venue: Venue) -> None:
    status, body = await _get(
        venue, "/position-replay?gateway=MM01&symbol=AAPL", TRADER_KEY
    )
    assert (status, _code(body)) == (403, "SCOPE_DENIED")
    status, body = await _get(venue, "/position-replay?symbol=AAPL", READ_ONLY_KEY)
    assert (status, _code(body)) == (403, "READ_ONLY")
    status, body = await _get(venue, "/position-replay", TRADER_KEY)
    assert (status, _code(body), body["error"]["field"]) == (
        400,
        "VALIDATION",
        "symbol",
    )
    status, body = await _get(
        venue, "/position-replay?symbol=AAPL&date=2026-02-30", TRADER_KEY
    )
    assert (status, body["error"]["field"]) == (400, "date")
    # An ADMIN replays the gateway it names.
    _, body = await _get(
        venue, f"/position-replay?gateway=MM01&symbol=AAPL&date={DAY1}"
    )
    assert [s["net_qty"] for s in body["steps"]] == [-100, -150]


# ---------------------------------------------------------------------------
# who traded with whom (CG30)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_flows_pair_each_buyer_with_each_seller(venue: Venue) -> None:
    status, body = await _get(venue, f"/flows?date={DAY1}")
    assert status == 200
    assert (body["trade_date"], body["symbol"], body["trades_retained"]) == (
        DAY1,
        None,
        True,
    )
    # Largest value first; each trade counted once, on its one pair.
    assert [
        (p["buyer"], p["seller"], p["trades"], p["quantity"]) for p in body["pairs"]
    ] == [("TRADER01", "MM01", 2, 150), ("MM01", "TRADER01", 1, 1000)]
    assert body["pairs"][0]["value"] == pytest.approx(AAPL_BOUGHT_DAY1)
    assert body["pairs"][1]["value"] == pytest.approx(EURUSD_DAY1)


@pytest.mark.anyio
async def test_flows_default_to_the_latest_day_and_filter_by_symbol(
    venue: Venue,
) -> None:
    _, body = await _get(venue, "/flows?symbol=eurusd")
    assert (body["trade_date"], body["symbol"]) == (DAY2, "EURUSD")
    ((pair),) = body["pairs"]
    assert (pair["buyer"], pair["seller"], pair["value"]) == (
        "TRADER01",
        "MM01",
        pytest.approx(EURUSD_DAY2),
    )


@pytest.mark.anyio
async def test_flows_of_a_pruned_or_quiet_day(venue: Venue, tmp_path: Path) -> None:
    db = _copy(venue.clearing_db, tmp_path / "clearing.db")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("DELETE FROM trade_events WHERE trade_date = ?", (DAY1,))
        conn.commit()
    _, body = await _get(venue, f"/flows?date={DAY1}", clearing_db=db)
    assert (body["trades_retained"], body["pairs"]) == (False, [])
    _, body = await _get(venue, "/flows?date=2026-12-01")
    assert (body["trades_retained"], body["pairs"]) == (True, [])


@pytest.mark.anyio
async def test_flows_are_admin_only(venue: Venue) -> None:
    for key, code in (
        (TRADER_KEY, "ROLE_DENIED"),
        (MM_KEY, "ROLE_DENIED"),
        (READ_ONLY_KEY, "READ_ONLY"),
    ):
        status, body = await _get(venue, "/flows", key)
        assert (status, _code(body)) == (403, code)
    status, body = await _get(venue, "/flows?date=2026-13-01")
    assert (status, body["error"]["field"]) == (400, "date")


@pytest.mark.anyio
async def test_a_participant_may_name_itself_where_the_gui_does(venue: Venue) -> None:
    # CG31's trade timeline and CG29's replay pass the participant's own
    # gateway explicitly (the row's gateway id); the API must accept it.
    for path in (
        f"/position-replay?gateway=TRADER01&symbol=AAPL&date={DAY2}",
        f"/settlements?gateway=TRADER01&date={DAY2}",
        "/netting?gateway=TRADER01",
    ):
        status, body = await _get(venue, path, TRADER_KEY)
        assert status == 200, (path, body)
