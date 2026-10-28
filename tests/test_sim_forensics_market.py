"""tools/sim_forensics checks F2-F4 (market data against the trades and books).

``build`` writes a two-trade run on AAPL: an audit with the engine's book
messages and trades, pm-stats's price_snapshots and daily_stats rows made
from those messages, and the engine's book_stats.json. Every check passes on
it; each failure test changes one record.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from edumatcher.stats.main import SCHEMA as STATS_SCHEMA
from tests.sim_forensics_world import OpenDataset, ns, opener, sql
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, Outcome, run_checks  # noqa: E402

F = ["F2", "F3", "F4"]

T1 = {"id": "000001-000000001", "symbol": "AAPL", "buy_order_id": "B1", "sell_order_id": "S1", "buy_gateway_id": "GW1", "sell_gateway_id": "GW2", "price": 100.0, "quantity": 10, "aggressor_side": "AUCTION", "ts_ns": ns("07:30:00"), "tick_decimals": 2}  # fmt: skip
T2 = {**T1, "id": "000001-000000002", "buy_order_id": "B2", "price": 100.5, "quantity": 5, "aggressor_side": "BUY", "ts_ns": ns("08:00:00")}  # fmt: skip


def recent(*trades: dict[str, Any]) -> list[dict[str, Any]]:
    keys = ("id", "symbol", "buy_order_id", "sell_order_id", "buy_gateway_id", "sell_gateway_id", "price", "quantity", "ts_ns")  # fmt: skip
    return [{k: t[k] for k in keys} for t in trades]


def book(at: str, bid: float, ask: float, **fields: Any) -> dict[str, Any]:
    """A book.AAPL payload as OrderBook.snapshot() writes it."""
    return {
        "symbol": "AAPL",
        "tick_decimals": 2,
        "ts_ns": ns(at),
        "bids": [{"price": bid, "qty": 10, "count": 1}],
        "asks": [{"price": ask, "qty": 10, "count": 1}],
        # Restored at startup: neither comes from this run's trades.
        "last_price": None,
        "last_qty": None,
        "last_buy_price": 100.25,
        "last_sell_price": 99.5,
        "recent_trades": [],
        **fields,
    }


def tape() -> list[tuple[str, str, dict[str, Any]]]:
    """(audit time, topic, payload). The auction print moves last_price but
    neither side price; the BUY trade moves last_buy_price."""
    return [
        ("07:00:00.000", "system.startup", {"run_seq": 1}),
        ("07:00:00.100", "book.AAPL", book("07:00:00.100", 99.0, 101.0)),
        ("07:30:00.000", "trade.executed", T1),
        ("08:00:00.000", "trade.executed", T2),
        (
            "08:00:01.000",
            "book.AAPL",
            book("08:00:01.000", 99.5, 101.0, last_price=100.5, last_qty=5, last_buy_price=100.5, recent_trades=recent(T1, T2)),  # fmt: skip
        ),
    ]


def write_audit(data: Path, lines: list[tuple[str, str, dict[str, Any]]]) -> None:
    (data / "audit.log").write_text(
        "".join(
            f"[2026-06-15T{at}+00:00] [{topic}] [seq={i} msg=M{i} chain=M{i}] "
            f"{json.dumps(p)}\n"
            for i, (at, topic, p) in enumerate(lines, 1)
        )
    )


def build(data: Path) -> Path:
    data.mkdir()
    write_audit(data, tape())
    conn = sqlite3.connect(data / "stats.db")
    conn.executescript(STATS_SCHEMA)
    conn.execute(
        "INSERT INTO stats_meta VALUES ('session_timezone', 'Europe/Stockholm')"
    )
    conn.execute(
        "INSERT INTO instruments (symbol, tick_decimals, tick_size, source, "
        "updated_ts) VALUES ('AAPL', 2, 0.01, 'config', '2026-06-15T07:00:00Z')"
    )
    conn.executemany(
        "INSERT INTO trade_log (ts, trade_id, symbol, price, quantity, "
        "aggressor_side) VALUES (?, ?, 'AAPL', ?, ?, ?)",
        [
            ("2026-06-15T07:30:00.000+00:00", T1["id"], 10000, 10, "AUCTION"),
            ("2026-06-15T08:00:00.000+00:00", T2["id"], 10050, 5, "BUY"),
        ],
    )
    # pm-stats's rows for the two book messages, stamped at receipt.
    conn.executemany(
        "INSERT INTO price_snapshots VALUES (?, 'AAPL', ?, ?, ?, ?, 2)",
        [
            ("2026-06-15T07:00:00+00:00", 10000.0, 9900, 10100, None),
            ("2026-06-15T08:00:01+00:00", 10025.0, 9950, 10100, 0.25),
        ],
    )
    conn.execute(
        "INSERT INTO daily_stats (date, symbol, close_price, open_bid, open_ask) "
        "VALUES ('2026-06-15', 'AAPL', 10050, 9900, 10100)"
    )
    conn.commit()
    conn.close()
    stats = {"AAPL": {"last_buy_price": 100.5, "last_sell_price": 99.5, "prev_close": 100.5}}  # fmt: skip
    (data / "book_stats.json").write_text(json.dumps(stats))
    return data


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


@pytest.fixture
def data(tmp_path: Path) -> Path:
    return build(tmp_path / "data")


def run(open_ds: OpenDataset, data: Path, check_id: str) -> Outcome:
    return REGISTRY[check_id].fn(open_ds(data))


def errors(out: Outcome) -> list[object]:
    return [s.get("error") for s in out.samples]


def test_every_f2_f4_check_passes_on_a_consistent_run(
    data: Path, open_ds: OpenDataset
) -> None:
    results = run_checks(open_ds(data), [REGISTRY[i] for i in F], 10)
    assert {r.check.id: (r.status, r.violations) for r in results} == {
        i: ("PASS", 0) for i in F
    }, [r.samples for r in results]
    assert results[0].note.startswith("2 price_snapshots rows checked")


# --- F2 ----------------------------------------------------------------------


def test_f2_finds_a_snapshot_no_book_message_had(
    data: Path, open_ds: OpenDataset
) -> None:
    sql(data / "stats.db", "UPDATE price_snapshots SET best_bid = 9940, mid_price = 10020.0 WHERE pct_change = 0.25")  # fmt: skip
    sql(data / "stats.db", "UPDATE price_snapshots SET pct_change = 0.2 WHERE best_bid = 9940")  # fmt: skip
    out = run(open_ds, data, "F2")
    assert errors(out) == ["no book message in the audit has this bid/ask"]


def test_f2_matches_on_the_book_messages_time_not_just_its_prices(
    data: Path, open_ds: OpenDataset
) -> None:
    """Stamped 08:00:10, the row cannot come from the message the engine
    published at 08:00:01 even though its audit line is near."""
    sql(data / "stats.db", "UPDATE price_snapshots SET ts = '2026-06-15T08:00:10+00:00' WHERE best_bid = 9950")  # fmt: skip
    assert errors(run(open_ds, data, "F2")) == [
        "no book message in the audit has this bid/ask"
    ]


def test_f2_finds_a_wrong_mid_and_pct_change(data: Path, open_ds: OpenDataset) -> None:
    sql(data / "stats.db", "UPDATE price_snapshots SET mid_price = 10030.0, pct_change = 0.3 WHERE best_bid = 9950")  # fmt: skip
    assert errors(run(open_ds, data, "F2")) == ["mid"]
    sql(data / "stats.db", "UPDATE price_snapshots SET mid_price = 10025.0 WHERE best_bid = 9950")  # fmt: skip
    assert errors(run(open_ds, data, "F2")) == ["pct_change"]


def test_f2_finds_a_wrong_open_bid(data: Path, open_ds: OpenDataset) -> None:
    sql(data / "stats.db", "UPDATE daily_stats SET open_bid = 9950")
    (sample,) = run(open_ds, data, "F2").samples
    assert sample["error"] == "open bid/ask"
    assert sample["audit"] == [9900, 10100]


def test_f2_checks_close_bid_ask_against_system_eod(
    data: Path, open_ds: OpenDataset
) -> None:
    """After the close every DAY order has expired: the EOD books are empty,
    so a stored close bid is wrong."""
    eod = {"books": [{"symbol": "AAPL", "tick_decimals": 2, "bids": [], "asks": []}]}
    write_audit(data, tape() + [("16:00:00.000", "system.eod", eod)])
    out = run(open_ds, data, "F2")
    assert out.violations == 0, out.samples
    assert "system.eod in the audit" in out.note
    sql(data / "stats.db", "UPDATE daily_stats SET close_bid = 9950")
    assert errors(run(open_ds, data, "F2")) == ["close bid/ask"]


# --- F3 ----------------------------------------------------------------------


def last_book(data: Path, **fields: Any) -> None:
    lines = tape()
    at, topic, payload = lines[-1]
    lines[-1] = (at, topic, {**payload, **fields})
    write_audit(data, lines)


@pytest.mark.parametrize(
    "fields, wrong",
    [
        ({"last_qty": 10}, ["last_qty"]),
        # The auction print must not move a side price (L9).
        ({"last_sell_price": 100.0}, ["last_sell_price"]),
        ({"recent_trades": recent(T2)}, ["recent_trades"]),
        ({"last_price": 100.0, "last_qty": 10}, ["last_price", "last_qty"]),
    ],
)
def test_f3_finds_a_book_message_that_disagrees_with_the_trades(
    data: Path, open_ds: OpenDataset, fields: dict[str, Any], wrong: list[str]
) -> None:
    last_book(data, **fields)
    (sample,) = run(open_ds, data, "F3").samples
    diffs = sample["diffs"]
    assert isinstance(diffs, dict)
    assert sorted(diffs) == wrong


def test_f3_takes_the_first_snapshot_as_given_when_the_audit_starts_mid_run(
    data: Path, open_ds: OpenDataset
) -> None:
    """Without the engine's start, earlier trades are unknown: a last_price
    already set at the first snapshot is not a violation."""
    lines = tape()[1:]
    at, topic, payload = lines[0]
    lines[0] = (at, topic, {**payload, "last_price": 98.0, "last_qty": 1})
    write_audit(data, lines)
    out = run(open_ds, data, "F3")
    assert out.violations == 0, out.samples
    assert "starts mid-run" in out.note


def test_f2_f3_skip_without_an_audit(data: Path, open_ds: OpenDataset) -> None:
    (data / "audit.log").unlink()
    results = run_checks(open_ds(data), [REGISTRY["F2"], REGISTRY["F3"]], 10)
    assert {r.status for r in results} == {"SKIPPED"}


# --- F4 ----------------------------------------------------------------------


def book_stats(data: Path, **fields: Any) -> None:
    path = data / "book_stats.json"
    stats = json.loads(path.read_text())
    stats["AAPL"].update(fields)
    path.write_text(json.dumps(stats))


def test_f4_finds_a_prev_close_that_is_not_the_last_trade(
    data: Path, open_ds: OpenDataset
) -> None:
    book_stats(data, prev_close=100.0)
    assert run(open_ds, data, "F4").samples == [
        {"symbol": "AAPL", "field": "prev_close", "book_stats": 10000, "trade_log": 10050}  # fmt: skip
    ]


def test_f4_finds_a_lost_prev_close(data: Path, open_ds: OpenDataset) -> None:
    """A symbol that did not trade this run keeps no last trade price, so
    its persisted prev_close goes empty although it has closed before."""
    sql(data / "stats.db", "DELETE FROM trade_log")
    book_stats(data, prev_close=None)
    assert errors(run(open_ds, data, "F4")) == ["empty, but daily_stats has a close"]


def test_f4_finds_a_traded_symbol_missing_from_book_stats(
    data: Path, open_ds: OpenDataset
) -> None:
    (data / "book_stats.json").write_text("{}")
    assert errors(run(open_ds, data, "F4")) == ["traded, not in book_stats.json"]


# --- F6 -------------------------------------------------------------------------


def real_book_and_depth(tolerance: int = 100) -> tuple[dict[str, Any], dict[str, Any]]:
    """book.AAPL and depth.AAPL as the engine builds them from one real
    OrderBook: levels inside and outside the window, an iceberg showing
    only its slice, a trade to anchor the window."""
    from edumatcher.engine.order_book import OrderBook
    from edumatcher.models.order import OrderType, Side
    from tests.conftest import make_order

    b = OrderBook("AAPL")
    for side, price, qty, peak in (
        (Side.BUY, 9990, 30, None), (Side.BUY, 9950, 20, None), (Side.BUY, 9800, 99, None),
        (Side.SELL, 10010, 40, 10), (Side.SELL, 10060, 25, None), (Side.SELL, 10300, 7, None),
        (Side.SELL, 10000, 5, None),
    ):  # fmt: skip
        otype = OrderType.ICEBERG if peak else OrderType.LIMIT
        b.process(make_order(side=side, order_type=otype, qty=qty, gateway_id="GW1", price=price, visible_qty=peak))  # fmt: skip
    b.process(make_order(side=Side.BUY, order_type=OrderType.LIMIT, qty=5, gateway_id="GW2", price=10000))  # fmt: skip
    return b.snapshot(), b.depth_snapshot(tolerance)


def f6(open_ds: OpenDataset, tmp_path: Path, lines: list[tuple[str, str, dict[str, Any]]]) -> Outcome:  # fmt: skip
    data = tmp_path / "data"
    data.mkdir()
    write_audit(data, lines)
    return REGISTRY["F6"].fn(open_ds(data))


def test_f6_passes_the_engines_own_book_and_depth(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    book_p, depth_p = json.loads(json.dumps(real_book_and_depth(), default=str))
    assert depth_p["bid_depth"] == 50 and depth_p["ask_depth"] == 35  # iceberg: 10
    out = f6(open_ds, tmp_path, [("07:00:00.000", "book.AAPL", book_p), ("07:00:00.000", "depth.AAPL", depth_p)])  # fmt: skip
    assert out.violations == 0, out.samples
    assert out.note == "1 depth messages, 0 not right after their book"


@pytest.mark.parametrize(
    "field, value",
    [("bid_depth", 51), ("ask_depth", 75), ("imbalance", 0.5), ("microprice", 100.0), ("cost_to_move", 1.0), ("mid_price_ticks", 10010)],  # fmt: skip
)
def test_f6_finds_a_depth_figure_its_book_does_not_give(
    tmp_path: Path, open_ds: OpenDataset, field: str, value: object
) -> None:
    book_p, depth_p = json.loads(json.dumps(real_book_and_depth(), default=str))
    depth_p[field] = value
    out = f6(open_ds, tmp_path, [("07:00:00.000", "book.AAPL", book_p), ("07:00:00.000", "depth.AAPL", depth_p)])  # fmt: skip
    (sample,) = out.samples
    assert field in sample["diffs"]  # type: ignore[operator]


def test_f6_counts_a_depth_not_right_after_its_book(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    book_p, depth_p = json.loads(json.dumps(real_book_and_depth(), default=str))
    out = f6(open_ds, tmp_path, [("07:00:00.000", "book.AAPL", book_p), ("07:00:00.000", "trade.executed", T1), ("07:00:00.000", "depth.AAPL", depth_p)])  # fmt: skip
    assert out.violations == 1
    assert out.note.endswith("1 not right after their book")
