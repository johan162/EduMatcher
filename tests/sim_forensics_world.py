"""A small, internally consistent sim run for the tools/sim_forensics tests.

``build`` writes stats.db, clearing.db and metrics.db for TRADES the way the
recorders would: real schemas, and clearing's stored positions and daily
summaries produced by the production ``Ledger``. Every check passes on it;
tests then plant one violation with plain SQL and expect exactly that finding.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from sim_forensics.dataset import Dataset  # noqa: E402

from edumatcher.clearing.ledger import Ledger, trade_date  # noqa: E402
from edumatcher.clearing.store import (  # noqa: E402
    TradeEventRow,
    apply_schema,
    flush_batch,
    record_session_event,
)
from edumatcher.monitor.store import initialize_schema  # noqa: E402
from edumatcher.stats.main import SCHEMA as STATS_SCHEMA  # noqa: E402

TZ = ZoneInfo("Europe/Stockholm")
SEC = 1_000_000_000


def ns(hhmmss: str) -> int:
    """UTC time on 2026-06-15 (CEST, so 09:30 local is 07:30Z)."""
    moment = datetime.fromisoformat(f"2026-06-15T{hhmmss}+00:00")
    return int(moment.timestamp()) * SEC + moment.microsecond * 1000


class Trade(NamedTuple):
    id: str
    ts_ns: int
    symbol: str
    price: int
    qty: int
    buy_oid: str
    sell_oid: str
    buy_gw: str
    sell_gw: str
    aggressor: str


#: GW1 opens long 100 in the auction, reduces by 30 at a profit, then sells
#: 120 and crosses to short 50; GW2 mirrors it; GW3 only trades MSFT.
TRADES = [
    Trade("000001-000000001", ns("07:29:59.900"), "AAPL", 15000, 100, "O1", "O2", "GW1", "GW2", "AUCTION"),  # fmt: skip
    Trade("000001-000000002", ns("08:00:00"), "AAPL", 15100, 30, "O3", "O4", "GW2", "GW1", "BUY"),  # fmt: skip
    Trade("000001-000000003", ns("09:00:00"), "AAPL", 14900, 120, "O5", "O6", "GW2", "GW1", "SELL"),  # fmt: skip
    Trade("000001-000000004", ns("09:30:00"), "MSFT", 30000, 10, "O7", "O8", "GW1", "GW3", "SELL"),  # fmt: skip
]

PHASES = [
    (ns("07:00:00"), "PRE_OPEN"),
    (ns("07:25:00"), "OPENING_AUCTION"),
    (ns("07:30:00"), "CONTINUOUS"),
]

#: When pm-monitor last sampled the counters: one second after the tape ends.
COUNTER_TS_NS = TRADES[-1].ts_ns + SEC


def iso(ts_ns: int) -> str:
    moment = datetime.fromtimestamp(ts_ns // SEC, timezone.utc).replace(
        microsecond=(ts_ns % SEC) // 1000
    )
    return moment.isoformat(timespec="milliseconds")


def build(data: Path) -> Path:
    data.mkdir(parents=True, exist_ok=True)
    _stats(data)
    _clearing(data)
    _metrics(data)
    return data


def _stats(data: Path) -> None:
    conn = sqlite3.connect(data / "stats.db")
    conn.executescript(STATS_SCHEMA)
    conn.execute(
        "INSERT INTO stats_meta VALUES ('session_timezone', 'Europe/Stockholm')"
    )
    conn.executemany(
        "INSERT INTO trade_log (ts, trade_id, symbol, price, quantity, "
        "buy_gateway_id, sell_gateway_id, aggressor_side) VALUES (?,?,?,?,?,?,?,?)",
        [
            (iso(t.ts_ns), t.id, t.symbol, t.price, t.qty, t.buy_gw, t.sell_gw, t.aggressor)  # fmt: skip
            for t in TRADES
        ],
    )
    events: list[tuple[object, ...]] = []
    for t in TRADES:
        for oid, gw in ((t.buy_oid, t.buy_gw), (t.sell_oid, t.sell_gw)):
            events.append((iso(t.ts_ns - SEC), "ACK", oid, gw, t.symbol, None, None, None))  # fmt: skip
            events.append((iso(t.ts_ns), "FILL", oid, gw, t.symbol, t.qty, t.price / 100, json.dumps([t.id])))  # fmt: skip
    conn.executemany(
        "INSERT INTO order_events (ts, event_type, order_id, gateway_id, symbol, "
        "fill_qty, fill_price, trade_ids) VALUES (?,?,?,?,?,?,?,?)",
        sorted(events),
    )
    conn.commit()
    conn.close()


def _clearing(data: Path) -> None:
    conn = sqlite3.connect(data / "clearing.db")
    apply_schema(conn)
    conn.execute(
        "INSERT INTO clearing_meta VALUES ('session_timezone', 'Europe/Stockholm')"
    )
    for ts_ns, state in PHASES:
        record_session_event(
            conn,
            event_type="PHASE",
            ts_ns=ts_ns,
            trade_date=trade_date(ts_ns, TZ),
            payload_json=json.dumps({"state": state}),
        )
    ledger = Ledger(tz=TZ)
    rows = []
    for t in TRADES:
        ledger.apply_trade(
            symbol=t.symbol,
            buy_gateway_id=t.buy_gw,
            sell_gateway_id=t.sell_gw,
            price=t.price,
            quantity=t.qty,
            ts_ns=t.ts_ns,
            ingest_ts_ns=t.ts_ns + 1_000_000,
        )
        rows.append(
            TradeEventRow(
                id=t.id,
                ts_ns=t.ts_ns,
                trade_date=trade_date(t.ts_ns, TZ),
                symbol=t.symbol,
                quantity=t.qty,
                price=t.price,
                buy_order_id=t.buy_oid,
                sell_order_id=t.sell_oid,
                buy_gateway_id=t.buy_gw,
                sell_gateway_id=t.sell_gw,
                aggressor_side=t.aggressor,
                ingest_ts_ns=t.ts_ns + 1_000_000,
            )
        )
    positions, daily = ledger.get_flush_rows(updated_ts_ns=COUNTER_TS_NS)
    flush_batch(conn, rows, positions, daily)
    conn.close()


def _metrics(data: Path) -> None:
    conn = sqlite3.connect(data / "metrics.db")
    initialize_schema(conn)
    trades = Counter(t.symbol for t in TRADES)
    fills = Counter(gw for t in TRADES for gw in (t.buy_gw, t.sell_gw))
    counters = (
        [("pm-engine@h", "engine.trades", s, n) for s, n in trades.items()]
        + [("pm-engine@h", "engine.fills", gw, n) for gw, n in fills.items()]
        + [("pm-clearing@h", "clearing.trades_settled", "", len(TRADES))]
        + [("pm-stats@h", "stats.records_dropped", "", 0)]
    )
    ts = iso(COUNTER_TS_NS).replace("+00:00", "Z")
    for source, name, label, value in counters:
        conn.execute(
            "INSERT INTO counter_last (source, name, label, boot_id, value, ts) "
            "VALUES (?, ?, ?, 'boot', ?, ?)",
            (source, name, label, value, ts),
        )
        conn.execute(
            "INSERT INTO daily_totals (date, source, name, label, total) "
            "VALUES ('2026-06-15', ?, ?, ?, ?)",
            (source, name, label, value),
        )
    conn.execute(
        "INSERT INTO series (id, source, name, label) "
        "VALUES (1, 'pm-stats@h', 'stats.records_dropped', '')"
    )
    conn.execute(
        "INSERT INTO samples_1m (series, ts, v_min, v_avg, v_max, v_last, n, delta) "
        "VALUES (1, '2026-06-15T09:30:00Z', 0, 0, 0, 0, 1, 0)"
    )
    conn.commit()
    conn.close()


def sql(path: Path, statement: str, *params: object) -> None:
    """Plant a violation: run one statement against a fixture store."""
    conn = sqlite3.connect(path)
    conn.execute(statement, params)
    conn.commit()
    conn.close()


OpenDataset = Callable[[Path], Dataset]


def opener() -> Iterator[OpenDataset]:
    """Body of each test module's ``open_ds`` fixture: Dataset.open, closing
    every dataset at teardown."""
    opened: list[Dataset] = []

    def _open(path: Path) -> Dataset:
        opened.append(Dataset.open(path))
        return opened[-1]

    yield _open
    for ds in opened:
        ds.conn.close()
