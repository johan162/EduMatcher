"""tools/sim_forensics checks A (trade identity) and B (book-keeping).

Each test plants exactly one kind of violation into the consistent world of
sim_forensics_world and expects the check to find it, and only it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.sim_forensics_world import (
    COUNTER_TS_NS,
    SEC,
    TRADES,
    OpenDataset,
    build,
    iso,
    opener,
    sql,
)
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, Outcome, run_checks  # noqa: E402

T1, T2, T3, T4 = (t.id for t in TRADES)
AB = ["A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"]


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


@pytest.fixture
def world(tmp_path: Path) -> Path:
    return build(tmp_path / "data")


def run(open_ds: OpenDataset, data: Path, check_id: str) -> Outcome:
    return REGISTRY[check_id].fn(open_ds(data))


def test_every_a_and_b_check_passes_on_a_consistent_run(
    world: Path, open_ds: OpenDataset
) -> None:
    """Also pins that the independent position replay agrees with the
    production clearing Ledger that wrote the fixture's positions."""
    assert sorted(i for i in REGISTRY if i[0] in "AB") == AB
    results = run_checks(open_ds(world), [REGISTRY[i] for i in AB], 10)
    assert {r.check.id: (r.status, r.samples) for r in results} == {
        i: ("PASS", []) for i in AB
    }


# --- A -------------------------------------------------------------------------


def test_a1_and_a2_find_a_trade_missing_from_stats(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(world / "stats.db", "DELETE FROM trade_log WHERE trade_id = ?", T2)
    assert run(open_ds, world, "A1").samples == [
        {"store": "clearing only", "trade_id": T2}
    ]
    assert run(open_ds, world, "A2").samples == [
        {"store": "stats", "run_seq": "000001", "missing_from": 2, "missing_to": 2}
    ]


def test_a1_does_not_compare_trades_beyond_the_cut(
    world: Path, open_ds: OpenDataset
) -> None:
    # Clearing stopped one trade early: T4 is in stats only, beyond the cut.
    sql(world / "clearing.db", "DELETE FROM trade_events WHERE id = ?", T4)
    out = run(open_ds, world, "A1")
    assert out.violations == 0
    assert "stats 1, clearing 0" in out.note


def test_a3_finds_a_field_and_a_timestamp_mismatch(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(world / "stats.db", "UPDATE trade_log SET price = 1 WHERE trade_id = ?", T2)
    sql(
        world / "stats.db",
        "UPDATE trade_log SET ts = ? WHERE trade_id = ?",
        iso(TRADES[2].ts_ns + 5_000_000),
        T3,
    )
    out = run(open_ds, world, "A3")
    assert [(s["trade_id"], sorted(s["diffs"])) for s in out.samples] == [
        (T2, ["price"]),
        (T3, ["ts"]),
    ]


def test_a4_finds_a_continuous_print_in_the_auction_and_time_going_back(
    world: Path, open_ds: OpenDataset
) -> None:
    db = world / "clearing.db"
    sql(db, "UPDATE trade_events SET aggressor_side = 'BUY' WHERE id = ?", T1)
    sql(db, "UPDATE trade_events SET ts_ns = ? WHERE id = ?", TRADES[1].ts_ns - 1, T3)
    assert run(open_ds, world, "A4").samples == [
        {"trade_id": T1, "aggressor_side": "BUY", "phase": "OPENING_AUCTION"},
        {"trade_id": T3, "error": "ts before previous trade's"},
    ]


def test_a4_allows_the_uncross_stop_cascade_but_not_another_symbol(
    world: Path, open_ds: OpenDataset
) -> None:
    """A stop the opening print triggers trades at once, still inside
    OPENING_AUCTION; a continuous print in a symbol that did not uncross is
    still a violation."""
    db = world / "clearing.db"
    sql(db, "UPDATE trade_events SET ts_ns = ? WHERE id = ?", TRADES[0].ts_ns, T2)
    sql(db, "UPDATE trade_events SET ts_ns = ? WHERE id = ?", TRADES[0].ts_ns, T3)
    sql(db, "UPDATE trade_events SET symbol = 'MSFT' WHERE id = ?", T3)
    out = run(open_ds, world, "A4")
    assert out.samples == [
        {"trade_id": T3, "aggressor_side": "SELL", "phase": "OPENING_AUCTION"}
    ]
    assert out.note == "1 stop-cascade prints after an uncross"


def test_a4_is_skipped_without_phase_rows(world: Path, open_ds: OpenDataset) -> None:
    sql(world / "clearing.db", "DELETE FROM session_events")
    (result,) = run_checks(open_ds(world), [REGISTRY["A4"]], 10)
    assert result.status == "SKIPPED"


# --- B1/B2: fills against trades -----------------------------------------------


def test_b1_and_b2_find_a_trade_side_without_its_fill(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(
        world / "stats.db",
        "DELETE FROM order_events WHERE order_id = 'O3' AND event_type = 'FILL'",
    )
    assert run(open_ds, world, "B1").samples == [
        {"trade_id": T2, "order_id": "O3", "fills": 0}
    ]
    out = run(open_ds, world, "B2")
    assert out.samples == [
        {
            "order_id": "O3",
            "gateway_id": "GW2",
            "symbol": "AAPL",
            "traded_qty": 30,
            "filled_qty": 0,
            "trades": 1,
            "fill_events": 0,
        }
    ]
    assert "total +30" in out.note


def test_b8_finds_a_fill_reported_at_a_price_its_trades_did_not_print(
    world: Path, open_ds: OpenDataset
) -> None:
    """X8c's shape: a stop's fill reported at the last print, not its VWAP."""
    sql(world / "stats.db", "UPDATE order_events SET fill_price = 151.5 WHERE order_id = 'O3' AND event_type = 'FILL'")  # fmt: skip
    (sample,) = run(open_ds, world, "B8").samples
    assert (sample["order_id"], sample["fill_price"], sample["trades_vwap"]) == ("O3", 151.5, 151.0)  # fmt: skip


def test_b8_finds_a_fill_quantity_that_is_not_its_trades_total(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(world / "stats.db", "UPDATE order_events SET fill_qty = 29 WHERE order_id = 'O3' AND event_type = 'FILL'")  # fmt: skip
    (sample,) = run(open_ds, world, "B8").samples
    assert (sample["fill_qty"], sample["trades_qty"]) == (29, 30)


def test_b1_finds_a_fill_naming_a_trade_its_order_is_not_in(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(
        world / "stats.db",
        "UPDATE order_events SET trade_ids = ? "
        "WHERE order_id = 'O1' AND event_type = 'FILL'",
        f'["{T1}", "{T2}"]',
    )
    assert run(open_ds, world, "B1").samples == [
        {"trade_id": T2, "order_id": "O1", "error": "not a side of the trade"}
    ]


def test_b1_is_skipped_on_a_stats_db_before_schema_8(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(world / "stats.db", "ALTER TABLE order_events DROP COLUMN trade_ids")
    (result,) = run_checks(open_ds(world), [REGISTRY["B1"]], 10)
    assert (result.status, "R2" in result.note) == ("SKIPPED", True)


def test_b2_finds_an_overfill(world: Path, open_ds: OpenDataset) -> None:
    sql(
        world / "stats.db",
        "UPDATE order_events SET fill_qty = 31 "
        "WHERE order_id = 'O4' AND event_type = 'FILL'",
    )
    assert [(s["order_id"], s["filled_qty"]) for s in run(open_ds, world, "B2").samples] == [  # fmt: skip
        ("O4", 31)
    ]


def test_b1_b2_ignore_trades_older_than_a_gateways_retained_events(
    world: Path, open_ds: OpenDataset
) -> None:
    # pm-stats pruned GW3's events (it keeps order events per gateway class).
    sql(world / "stats.db", "DELETE FROM order_events WHERE gateway_id = 'GW3'")
    sql(
        world / "stats.db",
        "INSERT INTO order_events (ts, event_type, order_id, gateway_id, symbol) "
        "VALUES (?, 'ACK', 'O99', 'GW3', 'MSFT')",
        iso(TRADES[-1].ts_ns + SEC),
    )
    assert run(open_ds, world, "B1").violations == 0
    assert run(open_ds, world, "B2").violations == 0


def test_b2_ignores_orders_with_trades_beyond_the_cut(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(world / "stats.db", "DELETE FROM trade_log WHERE trade_id = ?", T4)
    sql(
        world / "stats.db",
        "DELETE FROM order_events WHERE order_id = 'O7' AND event_type = 'FILL'",
    )
    assert run(open_ds, world, "B2").violations == 0


# --- B3/B4/B5: positions -------------------------------------------------------


@pytest.mark.parametrize(
    "assignment, field",
    [
        ("net_qty = net_qty + 1", "net_qty"),
        ("sell_notional = sell_notional + 1", "sell_notional"),
        ("avg_cost = avg_cost + 0.5", "avg_cost"),
        ("realized_pnl = realized_pnl + 0.5", "realized_pnl"),
        ("mark_price = mark_price + 1", "mark_price"),
    ],
)
def test_b3_finds_a_wrong_position_column(
    world: Path, open_ds: OpenDataset, assignment: str, field: str
) -> None:
    sql(
        world / "clearing.db",
        f"UPDATE gateway_symbol_positions SET {assignment} "
        "WHERE gateway_id = 'GW1' AND symbol = 'AAPL'",
    )
    out = run(open_ds, world, "B3")
    assert [s["gateway_id"] for s in out.samples] == ["GW1"]
    assert field in out.samples[0]["diffs"]  # type: ignore[operator]


def test_b3_finds_a_missing_position_row(world: Path, open_ds: OpenDataset) -> None:
    sql(
        world / "clearing.db",
        "DELETE FROM gateway_symbol_positions WHERE gateway_id = 'GW3'",
    )
    assert run(open_ds, world, "B3").samples == [
        {"gateway_id": "GW3", "symbol": "MSFT", "diffs": "no position row"}
    ]


def test_b3_b4_are_skipped_when_clearing_pruned_old_trades(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(world / "clearing.db", "DELETE FROM trade_events WHERE id = ?", T1)
    results = run_checks(open_ds(world), [REGISTRY["B3"], REGISTRY["B4"]], 10)
    assert [r.status for r in results] == ["SKIPPED", "SKIPPED"]


def test_b4_finds_a_wrong_summary_and_a_misdated_trade(
    world: Path, open_ds: OpenDataset
) -> None:
    db = world / "clearing.db"
    sql(
        db,
        "UPDATE gateway_daily_summary SET buy_qty = buy_qty + 1 "
        "WHERE gateway_id = 'GW2' AND symbol = 'AAPL'",
    )
    sql(db, "UPDATE trade_events SET trade_date = '2026-06-14' WHERE id = ?", T4)
    out = run(open_ds, world, "B4")
    assert out.samples == [
        {"trade_id": T4, "error": "trade_date 2026-06-14 but session date 2026-06-15"},
        {
            "key": ("2026-06-15", "GW2", "AAPL"),
            "diffs": {"buy_qty": {"stored": 151, "expected": 150}},
        },
    ]


def test_b5_finds_a_market_that_does_not_net_to_zero(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(
        world / "clearing.db",
        "UPDATE gateway_symbol_positions SET net_qty = net_qty + 1, "
        "unrealized_pnl = unrealized_pnl + mark_price "
        "WHERE gateway_id = 'GW1' AND symbol = 'AAPL'",
    )
    out = run(open_ds, world, "B5")
    assert [s.get("symbol") for s in out.samples] == ["AAPL"]
    assert out.samples[0]["net_qty"] == 1


def test_b5_finds_pnl_that_is_not_the_cash_flow(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(
        world / "clearing.db",
        "UPDATE gateway_symbol_positions SET realized_pnl = realized_pnl + 7 "
        "WHERE gateway_id = 'GW3'",
    )
    assert [s["gateway_id"] for s in run(open_ds, world, "B5").samples] == ["GW3"]


# --- B6/B7: counters -------------------------------------------------------------


def test_b6_finds_a_counter_ahead_of_the_rows(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(
        world / "metrics.db",
        "UPDATE daily_totals SET total = total + 1 WHERE label = 'AAPL'",
    )
    assert run(open_ds, world, "B6").samples == [
        {
            "counter": "engine.trades",
            "date": "2026-06-15",
            "label": "AAPL",
            "counter_total": 4.0,
            "rows_before_sample": 3,
            "rows_before_sample_minus_slack": 3,
        }
    ]


def test_b6_allows_a_counter_to_lag_by_the_reporting_slack(
    world: Path, open_ds: OpenDataset
) -> None:
    # The MSFT trade is 1 s before the sample: not yet counted is fine.
    sql(world / "metrics.db", "UPDATE daily_totals SET total = 0 WHERE label = 'MSFT'")
    assert run(open_ds, world, "B6").violations == 0
    # 20 s later the counter must have caught up.
    later = iso(COUNTER_TS_NS + 20 * SEC).replace("+00:00", "Z")
    sql(world / "metrics.db", "UPDATE counter_last SET ts = ?", later)
    assert [s["label"] for s in run(open_ds, world, "B6").samples] == ["MSFT"]


def test_b7_finds_dropped_records_and_feed_gaps(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(world / "metrics.db", "UPDATE samples_1m SET v_max = 3")
    sql(
        world / "stats.db",
        "INSERT INTO feed_gaps (ts, stream, expected_id, received_id, missing_count) "
        "VALUES ('2026-06-15T08:00:00Z', 'trade.executed', 5, 7, 2)",
    )
    assert run(open_ds, world, "B7").samples == [
        {
            "counter": "stats.records_dropped",
            "source": "pm-stats@h",
            "label": "",
            "max": 3.0,
        },
        {"feed_gap": "2026-06-15T08:00:00Z", "stream": "trade.executed", "missing": 2},
    ]
