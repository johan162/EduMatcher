"""Read-only reader over ``clearing.db`` for the API gateway.

The gateway's own fill cache is in-memory, so the realized P&L it reports
reads flat after a restart even though the trades plainly happened. Clearing
already records realized P&L per ``(trade_date, gateway_id, symbol)`` in
``gateway_daily_summary`` and never prunes it -- retention only touches
``trade_events`` -- which makes it the durable source for a trader's
session, month-to-date and year-to-date numbers.

Nothing here writes. ``pm-clearing`` owns the file; the gateway opens it
read-only and treats its absence as "no numbers", not an error, so a venue
running without clearing keeps a working positions endpoint.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from urllib.parse import quote

from edumatcher.stats.trading_day import resolve_timezone

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PeriodRealizedPnl:
    """Realized P&L for one symbol over the three reported windows.

    Values are in display money, not integer ticks: callers put them
    alongside the engine's ``avg_cost``, which is already converted.
    """

    session: float
    mtd: float
    ytd: float


def open_readonly_connection(
    db_path: Path, busy_timeout_ms: int = 5000
) -> sqlite3.Connection:
    """Open the clearing ledger read-only.

    ``busy_timeout`` matters even for a reader: pm-clearing is writing in
    batches, and a checkpoint takes a brief exclusive lock that would
    otherwise turn a routine query into a spurious error.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Clearing DB not found: {db_path}")
    resolved_path = db_path.resolve()
    # Percent-encode before pasting into a URI: a path containing '?' would
    # otherwise terminate the path component early, and SQLite would open a
    # different file with mode=ro discarded.
    uri = f"file:{quote(str(resolved_path))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    return conn


def session_timezone(conn: sqlite3.Connection) -> tzinfo:
    """The timezone pm-clearing bucketed every ``trade_date`` with.

    Read from the ledger's own ``clearing_meta`` rather than from stats.db:
    it is the clock that actually decided which trading day a trade landed
    on, so period boundaries derived from it cannot disagree with the rows
    they filter. Falls back to UTC when unrecorded or unknown, which only
    shifts the boundary, never loses a row.
    """
    row = conn.execute(
        "SELECT value FROM clearing_meta WHERE key = 'session_timezone'"
    ).fetchone()
    if row is None:
        return timezone.utc
    resolved = resolve_timezone(str(row[0]))
    if resolved is None:
        log.warning("clearing: unknown session timezone %r, using UTC", row[0])
        return timezone.utc
    return resolved


def day_bounds_ns(
    conn: sqlite3.Connection, from_date: str | None, to_date: str | None
) -> tuple[int | None, int | None]:
    """Epoch-ns bounds of the inclusive trading days ``from_date..to_date``.

    The lower bound is inclusive, the upper exclusive (the midnight after
    ``to_date``); both are midnights in the session timezone, so a moment is
    filtered under the venue's day, not its UTC date. ``None`` is no bound.
    """
    tz = session_timezone(conn)

    def midnight_ns(day: date) -> int:
        return int(datetime.combine(day, time(0), tz).timestamp()) * 1_000_000_000

    def parse(day: str) -> date:
        return datetime.strptime(day, "%Y-%m-%d").date()

    return (
        midnight_ns(parse(from_date)) if from_date else None,
        midnight_ns(parse(to_date) + timedelta(days=1)) if to_date else None,
    )


def period_boundaries(today: date) -> tuple[str, str, str]:
    """The inclusive lower bound of each window as a ``trade_date`` string.

    ``trade_date`` is the venue's own calendar day, so the caller resolves
    ``today`` in the session timezone rather than the server's.
    """
    return (
        today.isoformat(),
        today.replace(day=1).isoformat(),
        today.replace(month=1, day=1).isoformat(),
    )


#: One pass over the year's rows yields all three windows. Filtering on the
#: widest bound (YTD) and summing the narrower ones conditionally avoids
#: three separate scans of the same partition.
_PERIOD_REALIZED_PNL = """
SELECT
  symbol,
  tick_decimals,
  SUM(CASE WHEN trade_date >= :session THEN realized_pnl ELSE 0 END) AS session_pnl,
  SUM(CASE WHEN trade_date >= :mtd THEN realized_pnl ELSE 0 END) AS mtd_pnl,
  SUM(realized_pnl) AS ytd_pnl
FROM gateway_daily_summary
WHERE gateway_id = :gateway_id AND trade_date >= :ytd
GROUP BY symbol, tick_decimals
"""


def query_period_realized_pnl(
    conn: sqlite3.Connection,
    *,
    gateway_id: str,
    now: datetime | None = None,
) -> dict[str, PeriodRealizedPnl]:
    """Realized P&L per symbol for today, month-to-date and year-to-date.

    The windows are resolved in the ledger's own session timezone, so they
    line up with the ``trade_date`` pm-clearing stamped on the trades
    rather than with the gateway host's local midnight.
    """
    moment = now or datetime.now(timezone.utc)
    tz = session_timezone(conn)
    session_from, mtd_from, ytd_from = period_boundaries(moment.astimezone(tz).date())
    rows = conn.execute(
        _PERIOD_REALIZED_PNL,
        {
            "gateway_id": gateway_id,
            "session": session_from,
            "mtd": mtd_from,
            "ytd": ytd_from,
        },
    ).fetchall()

    out: dict[str, PeriodRealizedPnl] = {}
    for row in rows:
        # Stored in integer ticks like every other money column in the
        # ledger; handing it over unscaled would read 100x high next to the
        # engine's already-converted avg_cost.
        scale = float(10 ** int(row["tick_decimals"]))
        out[str(row["symbol"])] = PeriodRealizedPnl(
            session=float(row["session_pnl"] or 0.0) / scale,
            mtd=float(row["mtd_pnl"] or 0.0) / scale,
            ytd=float(row["ytd_pnl"] or 0.0) / scale,
        )
    return out
