"""``eod.db`` — the settlement ledger.

One row per account per settled trading date.  The rows of a date add up to
exactly zero (the rounding residual sits on the ``EXCHANGE`` account), which
:func:`record_day` checks before it commits and :func:`check_zero_sum` can
re-check across all dates.  Amounts are integer minor units (2 decimals).
Balances are never stored: they are the sum of the amounts, so correcting a
day means :func:`redo_from` and recording again.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from edumatcher.eod.settle import EXCHANGE, Settlement

SCHEMA = """
CREATE TABLE IF NOT EXISTS eod_settlement (
  trade_date   TEXT    NOT NULL,
  -- A gateway id, or 'EXCHANGE' for the rounding residual.
  account      TEXT    NOT NULL,
  amount_minor INTEGER NOT NULL,
  -- {symbol: day P&L in display currency} for the statement.
  detail_json  TEXT    NOT NULL,
  PRIMARY KEY (trade_date, account)
);

-- One row per trading date pm-eod has run.  'ok' means settled and reported;
-- housekeeping warnings do not change it (they are in steps_json).
CREATE TABLE IF NOT EXISTS eod_runs (
  trade_date  TEXT PRIMARY KEY,
  status      TEXT NOT NULL,   -- ok | failed | report-failed
  started_at  TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  steps_json  TEXT NOT NULL    -- [{"step", "status", "message"}, ...]
);
"""

_PRAGMAS = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
"""


class LedgerError(Exception):
    """A write the ledger refuses to make."""


def open_ledger(path: Path) -> sqlite3.Connection:
    """Open (or create) ``eod.db`` for read/write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_PRAGMAS)
        conn.executescript(SCHEMA)
    except Exception:
        conn.close()
        raise
    return conn


def settled_dates(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM eod_settlement ORDER BY trade_date"
    )
    return [r[0] for r in rows]


def record_day(conn: sqlite3.Connection, trade_date: str, result: Settlement) -> None:
    """Write one day's settlement in a single transaction."""
    rows = dict(result.amounts_minor)
    if result.rounding_minor:
        rows[EXCHANGE] = result.rounding_minor
    if sum(rows.values()) != 0:
        raise LedgerError(f"{trade_date}: amounts do not sum to zero")
    dates = settled_dates(conn)
    if trade_date in dates:
        raise LedgerError(f"{trade_date} is already settled")
    if dates and dates[-1] > trade_date:
        raise LedgerError(f"{dates[-1]} is settled, which is later than {trade_date}")
    with conn:
        conn.executemany(
            "INSERT INTO eod_settlement (trade_date, account, amount_minor, detail_json)"
            " VALUES (?, ?, ?, ?)",
            [
                (
                    trade_date,
                    account,
                    amount,
                    json.dumps(
                        {s: str(v) for s, v in result.detail.get(account, {}).items()}
                    ),
                )
                for account, amount in rows.items()
            ],
        )


def day_amounts(conn: sqlite3.Connection, trade_date: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT account, amount_minor FROM eod_settlement WHERE trade_date = ?",
        (trade_date,),
    )
    return {r[0]: r[1] for r in rows}


def day_detail(
    conn: sqlite3.Connection, trade_date: str
) -> dict[str, dict[str, Decimal]]:
    """Per account, the day's result by symbol in display currency."""
    rows = conn.execute(
        "SELECT account, detail_json FROM eod_settlement WHERE trade_date = ?",
        (trade_date,),
    )
    return {
        r[0]: {sym: Decimal(v) for sym, v in json.loads(r[1]).items()} for r in rows
    }


def balances(
    conn: sqlite3.Connection,
    as_of: str | None = None,
    openings: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Running balance per account up to and including ``as_of``.

    ``openings`` (minor units) are added once; accounts that appear only there
    are included.
    """
    result = dict(openings or {})
    rows = conn.execute(
        "SELECT account, SUM(amount_minor) FROM eod_settlement"
        " WHERE (:as_of IS NULL OR trade_date <= :as_of) GROUP BY account",
        {"as_of": as_of},
    )
    for account, total in rows:
        result[account] = result.get(account, 0) + total
    return result


def redo_from(conn: sqlite3.Connection, trade_date: str) -> list[str]:
    """Delete ``trade_date`` and every later date; return the dates removed.

    Balances are cumulative, so a corrected day invalidates everything after it.
    """
    gone = [d for d in settled_dates(conn) if d >= trade_date]
    with conn:
        conn.execute("DELETE FROM eod_settlement WHERE trade_date >= ?", (trade_date,))
        conn.execute("DELETE FROM eod_runs WHERE trade_date >= ?", (trade_date,))
    return gone


def record_run(
    conn: sqlite3.Connection,
    trade_date: str,
    status: str,
    started_at: str,
    finished_at: str,
    steps: list[dict[str, str]],
) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO eod_runs"
            " (trade_date, status, started_at, finished_at, steps_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (trade_date, status, started_at, finished_at, json.dumps(steps)),
        )


def runs(conn: sqlite3.Connection, limit: int = 30) -> list[dict[str, str]]:
    """Recorded runs, newest date first."""
    rows = conn.execute(
        "SELECT trade_date, status, started_at, finished_at, steps_json"
        " FROM eod_runs ORDER BY trade_date DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def check_zero_sum(conn: sqlite3.Connection) -> list[str]:
    """Dates whose amounts do not add up to zero (should be none)."""
    rows = conn.execute(
        "SELECT trade_date FROM eod_settlement GROUP BY trade_date"
        " HAVING SUM(amount_minor) != 0 ORDER BY trade_date"
    )
    return [r[0] for r in rows]
