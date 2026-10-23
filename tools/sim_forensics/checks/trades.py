"""A — trade identity and completeness across the trade stores."""

from __future__ import annotations

import json
from datetime import datetime

from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Sample, Skipped, check

#: Phases a print may carry a timestamp in. Auction prints are stamped during
#: the uncross, just before the phase moves on; CONTINUOUS also allows them
#: for intraday re-opening auctions (circuit breaker, ACE).
_AUCTION_PHASES = ("OPENING_AUCTION", "CLOSING_AUCTION", "CONTINUOUS")
_CONTINUOUS_PHASES = ("CONTINUOUS",)

#: trade_log.ts is the engine timestamp truncated to milliseconds.
_TS_TOLERANCE_NS = 1_000_000


def _cut(ds: Dataset) -> str:
    if ds.cut_trade_id is None:
        raise Skipped("no trades in the trade stores")
    return ds.cut_trade_id


@check(
    "A1",
    "cross-store",
    "Same trade ids in stats.trade_log and clearing.trade_events",
    needs=("stats", "clearing"),
)
def same_trade_ids(ds: Dataset) -> Outcome:
    cut = _cut(ds)
    rows = ds.conn.execute(
        "SELECT 'clearing only', e.id FROM clearing.trade_events e "
        "WHERE e.id <= ? AND NOT EXISTS "
        "(SELECT 1 FROM stats.trade_log t WHERE t.trade_id = e.id) "
        "UNION ALL "
        "SELECT 'stats only', t.trade_id FROM stats.trade_log t "
        "WHERE t.trade_id <= ? AND NOT EXISTS "
        "(SELECT 1 FROM clearing.trade_events e WHERE e.id = t.trade_id) "
        "ORDER BY 2",
        (cut, cut),
    ).fetchall()
    beyond = ds.conn.execute(
        "SELECT (SELECT count(*) FROM stats.trade_log WHERE trade_id > ?), "
        "(SELECT count(*) FROM clearing.trade_events WHERE id > ?)",
        (cut, cut),
    ).fetchone()
    note = f"beyond the cut (not compared): stats {beyond[0]}, clearing {beyond[1]}"
    samples: list[Sample] = [{"store": s, "trade_id": t} for s, t in rows]
    return Outcome(len(samples), samples, note)


@check(
    "A2",
    "cross-store",
    "Trade counter has no gaps within a run_seq",
    needs=("stats", "clearing"),
)
def no_counter_gaps(ds: Dataset) -> Outcome:
    """Counters are dense per run_seq (ids "RRRRRR-CCCCCCCCC"); retention may
    have pruned the start of the range, so only internal gaps count."""
    samples: list[Sample] = []
    for store, table, col in (
        ("stats", "stats.trade_log", "trade_id"),
        ("clearing", "clearing.trade_events", "id"),
    ):
        gaps = ds.conn.execute(
            f"SELECT run_seq, prev + 1, counter - 1 FROM ("
            f" SELECT substr({col}, 1, instr({col}, '-') - 1) AS run_seq,"
            f"  CAST(substr({col}, instr({col}, '-') + 1) AS INTEGER) AS counter,"
            f"  lag(CAST(substr({col}, instr({col}, '-') + 1) AS INTEGER))"
            f"   OVER (PARTITION BY substr({col}, 1, instr({col}, '-') - 1)"
            f"   ORDER BY {col}) AS prev"
            f" FROM {table}) WHERE counter <> prev + 1"
        )
        found: list[Sample] = [
            {"store": store, "run_seq": r, "missing_from": a, "missing_to": b}
            for r, a, b in gaps
        ]
        samples += found
    return Outcome(len(samples), samples)


_A3_FIELDS = (
    "symbol",
    "price",
    "quantity",
    "tick_decimals",
    "buy_gateway_id",
    "sell_gateway_id",
    "aggressor_side",
)


@check(
    "A3",
    "cross-store",
    "Each trade identical in stats and clearing (fields and engine timestamp)",
    needs=("stats", "clearing"),
)
def same_trade_fields(ds: Dataset) -> Outcome:
    cut = _cut(ds)
    cols = ", ".join(f"t.{f}, e.{f}" for f in _A3_FIELDS)
    samples: list[Sample] = []
    rows = ds.conn.execute(
        f"SELECT t.trade_id, t.ts, e.ts_ns, {cols} FROM stats.trade_log t "
        "JOIN clearing.trade_events e ON e.id = t.trade_id WHERE t.trade_id <= ?",
        (cut,),
    )
    for trade_id, ts, ts_ns, *pairs in rows:
        diffs: dict[str, object] = {
            name: {"stats": pairs[2 * i], "clearing": pairs[2 * i + 1]}
            for i, name in enumerate(_A3_FIELDS)
            if pairs[2 * i] != pairs[2 * i + 1]
        }
        if abs(_epoch_ns(ts) - ts_ns) >= _TS_TOLERANCE_NS:
            diffs["ts"] = {"stats": ts, "clearing_ts_ns": ts_ns}
        if diffs:
            samples.append({"trade_id": trade_id, "diffs": diffs})
    return Outcome(len(samples), samples)


@check(
    "A4",
    "cross-store",
    "Trade timestamps rise with the counter and fall in a matching phase",
    needs=("clearing",),
)
def trade_times(ds: Dataset) -> Outcome:
    phases = [
        (ts_ns, json.loads(payload)["state"])
        for ts_ns, payload in ds.conn.execute(
            "SELECT ts_ns, payload_json FROM clearing.session_events "
            "WHERE event_type = 'PHASE' ORDER BY ts_ns, id"
        )
    ]
    if not phases:
        raise Skipped("clearing.session_events has no PHASE rows")
    samples: list[Sample] = []
    prev_ts = None
    i = -1  # index of the phase in force
    rows = ds.conn.execute(
        "SELECT id, ts_ns, aggressor_side FROM clearing.trade_events ORDER BY id"
    )
    for trade_id, ts_ns, aggressor in rows:
        if prev_ts is not None and ts_ns < prev_ts:
            samples.append(
                {"trade_id": trade_id, "error": "ts before previous trade's"}
            )
        prev_ts = ts_ns
        while i + 1 < len(phases) and phases[i + 1][0] <= ts_ns:
            i += 1
        phase = phases[i][1] if i >= 0 else None
        allowed = _AUCTION_PHASES if aggressor == "AUCTION" else _CONTINUOUS_PHASES
        if phase not in allowed:
            samples.append(
                {"trade_id": trade_id, "aggressor_side": aggressor, "phase": phase}
            )
    return Outcome(len(samples), samples)


def _epoch_ns(ts: str) -> int:
    moment = datetime.fromisoformat(ts)
    return int(moment.timestamp()) * 1_000_000_000 + moment.microsecond * 1000
