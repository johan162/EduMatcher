"""The run under inspection: its data dir, ATTACHed read-only, and the cut."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

#: Stores the checks may need, ATTACHed under these schema names.
STORES = ("stats", "clearing", "metrics", "log")


@dataclass
class Dataset:
    data_dir: Path
    #: In-memory connection with every present store ATTACHed read-only.
    conn: sqlite3.Connection
    stores: frozenset[str]
    session_tz: ZoneInfo
    #: Highest trade id present in every trade store. Stores are flushed at
    #: different moments, so cross-store checks only compare trades up to it.
    cut_trade_id: str | None
    #: Results several checks derive from the same expensive pass.
    cache: dict[str, object] = field(default_factory=dict)

    @classmethod
    def open(cls, data_dir: Path) -> Dataset:
        # URI mode, so the ATTACHes below can open each store read-only.
        conn = sqlite3.connect("file::memory:", uri=True)
        present = set()
        for name in STORES:
            path = data_dir / f"{name}.db"
            if path.is_file():
                conn.execute(f"ATTACH DATABASE ? AS {name}", (f"file:{path}?mode=ro",))
                present.add(name)
        stores = frozenset(present)
        tz = ZoneInfo(_session_timezone(conn, stores))
        conn.create_function(
            "session_date", 1, lambda ts: _session_date(ts, tz), deterministic=True
        )
        return cls(data_dir, conn, stores, tz, _cut(conn, stores))

    def __enter__(self) -> Dataset:
        return self

    def __exit__(self, *exc: object) -> None:
        self.conn.close()


def _session_timezone(conn: sqlite3.Connection, stores: frozenset[str]) -> str:
    for table in ("stats.stats_meta", "clearing.clearing_meta"):
        if table.split(".")[0] in stores:
            row = conn.execute(
                f"SELECT value FROM {table} WHERE key = 'session_timezone'"
            ).fetchone()
            if row is not None:
                return str(row[0])
    return "UTC"


def iso_ns(ts: str) -> int:
    """Nanoseconds since the epoch of an ISO timestamp ("Z" or an offset)."""
    moment = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return int(moment.timestamp()) * 1_000_000_000 + moment.microsecond * 1000


def _session_date(ts: str, tz: ZoneInfo) -> str:
    """Trading date of a UTC ISO timestamp, in the session timezone."""
    return datetime.fromisoformat(ts).astimezone(tz).date().isoformat()


def _cut(conn: sqlite3.Connection, stores: frozenset[str]) -> str | None:
    highs = []
    if "stats" in stores:
        highs.append(conn.execute("SELECT max(trade_id) FROM stats.trade_log"))
    if "clearing" in stores:
        highs.append(conn.execute("SELECT max(id) FROM clearing.trade_events"))
    # Trade ids are fixed-width "run_seq-counter", so text order is trade order.
    values = [row[0] for cursor in highs if (row := cursor.fetchone())[0]]
    return min(values) if values else None
