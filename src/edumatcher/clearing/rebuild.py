"""Rebuild ``clearing.db`` from the audit trail (For-Later L023).

pm-clearing reports a trade it never received as a ``GAP``, but its
positions and P&L stay without it, and applying the trade late is not the
same thing: average cost and realised P&L depend on the order of the trades.
pm-audit holds every ``trade.executed`` the engine published, in order. This
replays them into a *fresh* database through pm-clearing's own code, and
reports where the result differs from the live ledger. Replacing the live
file with it stays an explicit operator step.

The rebuild starts from flat, so it needs every trade since the live ledger's
first one: ``gateway_daily_summary``, which is never pruned, says which day
that was. The close snapshots pm-eod settled from are copied over unchanged.
"""

from __future__ import annotations

import itertools
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from edumatcher.audit.rawlines import audit_files, lines
from edumatcher.clearing.ledger import trade_date
from edumatcher.clearing.main import ClearingProcess
from edumatcher.clearing.query import session_timezone
from edumatcher.clearing.store import open_readonly_connection
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.message import make_trade_msg

#: The position columns a rebuild is compared on.
_COMPARED = ("net_qty", "avg_cost", "realized_pnl")
#: Trades applied between writes: pm-clearing buffers until it flushes.
_FLUSH_EVERY = 10_000


class RebuildError(Exception):
    """The rebuild cannot be made, or must not be."""


@dataclass
class RebuildReport:
    #: ``trade.executed`` lines read from the audit (duplicates included).
    trades: int = 0
    #: Holes in the audit's own trade ids, recorded as GAPs in the new DB.
    gaps: int = 0
    #: One row per (gateway, symbol) whose position differs, live and rebuilt.
    differences: list[dict[str, Any]] = field(default_factory=list)


def rebuild_from_audit(audit_dir: Path, live_db: Path, output: Path) -> RebuildReport:
    """Replay the audit trail under *audit_dir* (a data directory holding
    ``audit.log`` and ``audit/``) into a new database at *output*, and
    compare it with *live_db*. Raises :class:`RebuildError` before writing
    anything when the rebuild cannot be trusted."""
    if output.resolve() == live_db.resolve():
        raise RebuildError(f"refusing to write over the live database {live_db}")
    if output.exists():
        raise RebuildError(f"{output} exists; the rebuild writes a new database")

    live = open_readonly_connection(live_db)
    try:
        tz = session_timezone(live)
        first_day = live.execute(
            "SELECT MIN(trade_date) FROM gateway_daily_summary"
        ).fetchone()[0]
    finally:
        live.close()

    payloads = (
        json.loads(ln.body)
        for ln in lines(audit_files(audit_dir), topics=(TOPIC_TRADE_EXECUTED,))
        if ln.topic == TOPIC_TRADE_EXECUTED
    )
    first = next(payloads, None)
    if first is None:
        raise RebuildError(f"the audit trail under {audit_dir} holds no trade")
    reach = trade_date(int(first["ts_ns"]), tz)
    if first_day is not None and reach > first_day:
        raise RebuildError(
            f"the audit trail reaches back to {reach}, but the live ledger's "
            f"first trading day is {first_day}: a rebuild would miss the "
            "trades in between"
        )

    report = RebuildReport()
    proc = ClearingProcess(
        pub_addr="inproc://unused", db_path=output, print_every=0, session_tz=tz
    )
    try:
        for payload in itertools.chain((first,), payloads):
            proc.replay(make_trade_msg(payload))
            report.trades += 1
            if report.trades % _FLUSH_EVERY == 0:
                proc.flush_now()
        proc.flush_now()
        report.gaps = proc.gap_count
    finally:
        proc.close_db()

    # URI mode, so the live database is attached read-only.
    conn = sqlite3.connect(output.resolve().as_uri(), uri=True)
    try:
        conn.execute(
            "ATTACH DATABASE ? AS live", (live_db.resolve().as_uri() + "?mode=ro",)
        )
        with conn:
            conn.execute(
                "INSERT INTO position_close_snapshot"
                " SELECT * FROM live.position_close_snapshot"
            )
        report.differences = _differences(conn)
        conn.execute("DETACH DATABASE live")
    finally:
        conn.close()
    return report


def _differences(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every (gateway, symbol) whose compared columns differ between the
    rebuilt (``main``) and the live (``live``) positions, or that only one
    of them has."""

    def positions(schema: str) -> dict[tuple[str, str], tuple[Any, ...]]:
        cols = ", ".join(_COMPARED)
        return {
            (row[0], row[1]): tuple(row[2:])
            for row in conn.execute(
                f"SELECT gateway_id, symbol, {cols} FROM {schema}.gateway_symbol_positions"
            )
        }

    rebuilt, live = positions("main"), positions("live")
    out: list[dict[str, Any]] = []
    for key in sorted(rebuilt.keys() | live.keys()):
        new, old = rebuilt.get(key), live.get(key)
        if new == old:
            continue
        row: dict[str, Any] = {"gateway_id": key[0], "symbol": key[1]}
        for i, col in enumerate(_COMPARED):
            row[f"live_{col}"] = old[i] if old is not None else None
            row[f"rebuilt_{col}"] = new[i] if new is not None else None
        out.append(row)
    return out
