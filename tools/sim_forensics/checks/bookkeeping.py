"""B — double-entry book-keeping: fills, positions, P&L and counters balance."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction

from sim_forensics.dataset import Dataset, iso_ns
from sim_forensics.registry import Outcome, Sample, Skipped, check

#: One row per trade side: the order, its gateway, and the trade it is in.
_LEGS = """
    SELECT buy_order_id AS oid, buy_gateway_id AS gw, symbol, quantity AS q,
           id, ts_ns FROM clearing.trade_events
    UNION ALL
    SELECT sell_order_id, sell_gateway_id, symbol, quantity, id, ts_ns
    FROM clearing.trade_events
"""

#: A counter sample is taken up to this long before the monitor stamps it.
_COUNTER_SLACK_NS = 15 * 1_000_000_000

#: Float P&L columns against exact recomputation.
_REL_TOL = 1e-9
_ABS_TOL = 1e-6


def _cut(ds: Dataset) -> str:
    if ds.cut_trade_id is None:
        raise Skipped("no trades in the trade stores")
    return ds.cut_trade_id


def _session_date_ns(ts_ns: int, ds: Dataset) -> str:
    moment = datetime.fromtimestamp(ts_ns / 1e9, timezone.utc)
    return moment.astimezone(ds.session_tz).date().isoformat()


def _horizons(ds: Dataset) -> dict[str, int]:
    """Per gateway, the oldest order event pm-stats still holds.

    pm-stats prunes order events by age, per gateway class. A trade older than
    its gateway's horizon cannot have a retained fill, so it is not compared.
    """
    return {
        gw: iso_ns(ts)
        for gw, ts in ds.conn.execute(
            "SELECT gateway_id, min(ts) FROM stats.order_events GROUP BY gateway_id"
        )
    }


@check(
    "B1",
    "conservation",
    "Every trade side named by exactly one FILL of that order, and nothing else",
    needs=("stats", "clearing"),
)
def fills_name_their_trades(ds: Dataset) -> Outcome:
    columns = {r[1] for r in ds.conn.execute("PRAGMA stats.table_info(order_events)")}
    if "trade_ids" not in columns:
        raise Skipped("stats.db before schema 8: FILL rows carry no trade ids (R2)")
    cut = _cut(ds)
    horizon = _horizons(ds)
    ds.conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS fill_links AS "
        "SELECT oe.order_id, oe.gateway_id, j.value AS tid "
        "FROM stats.order_events oe, json_each(oe.trade_ids) j "
        "WHERE oe.event_type = 'FILL'"
    )
    ds.conn.execute("CREATE INDEX IF NOT EXISTS temp.fl_tid ON fill_links(tid)")
    samples: list[Sample] = []
    sides = ds.conn.execute(
        f"SELECT legs.oid, legs.gw, legs.id, legs.ts_ns, count(fl.order_id) "
        f"FROM ({_LEGS}) legs LEFT JOIN fill_links fl "
        f"ON fl.tid = legs.id AND fl.order_id = legs.oid "
        f"WHERE legs.id <= ? GROUP BY legs.oid, legs.id "
        f"HAVING count(fl.order_id) <> 1",
        (cut,),
    )
    for oid, gw, trade_id, ts_ns, n in sides:
        if ts_ns >= horizon.get(gw, ts_ns + 1):
            samples.append({"trade_id": trade_id, "order_id": oid, "fills": n})
    strays = ds.conn.execute(
        "SELECT fl.order_id, fl.tid, e.id IS NULL FROM fill_links fl "
        "LEFT JOIN clearing.trade_events e ON e.id = fl.tid "
        "WHERE fl.tid <= ? AND (e.id IS NULL "
        "OR fl.order_id NOT IN (e.buy_order_id, e.sell_order_id))",
        (cut,),
    )
    for oid, tid, unknown in strays:
        error = "names an unknown trade" if unknown else "not a side of the trade"
        samples.append({"trade_id": tid, "order_id": oid, "error": error})
    return Outcome(len(samples), samples)


@check(
    "B2",
    "conservation",
    "Per order, FILL quantity equals the quantity it traded",
    needs=("stats", "clearing"),
)
def fills_equal_trades_per_order(ds: Dataset) -> Outcome:
    """Works without trade ids: Σ fill_qty per order vs Σ trade qty per order."""
    cut = _cut(ds)
    horizon = _horizons(ds)
    # Materialised and indexed: a FULL OUTER JOIN of two CTEs is quadratic.
    ds.conn.executescript(f"""
        DROP TABLE IF EXISTS temp.b2_traded;
        DROP TABLE IF EXISTS temp.b2_filled;
        CREATE TEMP TABLE b2_traded AS
            SELECT oid, gw, symbol, sum(q) AS q, count(*) AS n,
                   max(id) AS last_id, min(ts_ns) AS first_ns
            FROM ({_LEGS}) GROUP BY oid;
        CREATE TEMP TABLE b2_filled AS
            SELECT order_id AS oid, gateway_id AS gw, symbol,
                   sum(fill_qty) AS q, count(*) AS n
            FROM stats.order_events WHERE event_type = 'FILL' GROUP BY order_id;
        CREATE INDEX temp.b2_traded_oid ON b2_traded(oid);
        CREATE INDEX temp.b2_filled_oid ON b2_filled(oid);
        """)
    rows = ds.conn.execute(
        "SELECT coalesce(t.oid, f.oid), coalesce(t.gw, f.gw), "
        " coalesce(t.symbol, f.symbol), coalesce(t.q, 0), coalesce(f.q, 0), "
        " coalesce(t.n, 0), coalesce(f.n, 0), t.last_id, t.first_ns "
        "FROM b2_traded t FULL OUTER JOIN b2_filled f ON f.oid = t.oid "
        "WHERE coalesce(t.q, 0) <> coalesce(f.q, 0)"
    )
    first = ds.conn.execute("SELECT min(id) FROM clearing.trade_events").fetchone()[0]
    clearing_pruned = first is not None and not first.endswith("-000000001")
    samples: list[Sample] = []
    missing: Counter[str] = Counter()
    for oid, gw, symbol, traded, filled, n_trades, n_fills, last_id, first_ns in rows:
        if last_id is not None and last_id > cut:
            continue  # its fills may legitimately be ahead of the cut
        if last_id is None and clearing_pruned:
            continue  # its trades may be older than clearing's retention
        if first_ns is not None and first_ns < horizon.get(gw, first_ns + 1):
            continue  # pruned from order_events
        missing[gw] += traded - filled
        samples.append(
            {
                "order_id": oid,
                "gateway_id": gw,
                "symbol": symbol,
                "traded_qty": traded,
                "filled_qty": filled,
                "trades": n_trades,
                "fill_events": n_fills,
            }
        )
    note = ""
    if missing:
        top = ", ".join(f"{gw} {q:+d}" for gw, q in missing.most_common(10))
        note = (
            f"traded minus filled qty, total {sum(missing.values()):+d}; "
            f"by gateway (top 10): {top}"
        )
    return Outcome(len(samples), samples, note)


# --- B3/B4: positions and daily summaries replayed from the trade tape -------


@dataclass
class _Pos:
    net_qty: int = 0
    avg_cost: Fraction = Fraction(0)
    realized: Fraction = Fraction(0)
    buy_qty: int = 0
    sell_qty: int = 0
    buy_notional: int = 0
    sell_notional: int = 0


@dataclass
class _DaySummary:
    buy_qty: int = 0
    sell_qty: int = 0
    buy_notional: int = 0
    sell_notional: int = 0
    realized: Fraction = Fraction(0)
    end_net_qty: int = 0


@dataclass
class _Replay:
    positions: dict[tuple[str, str], _Pos] = field(default_factory=dict)
    last_price: dict[str, int] = field(default_factory=dict)
    days: dict[tuple[str, str, str], _DaySummary] = field(default_factory=dict)
    #: (trade id, stored trade_date, session date of ts_ns) where they differ.
    misdated: list[tuple[str, str, str]] = field(default_factory=list)


def _apply(pos: _Pos, qty: int, price: int, is_buy: bool) -> Fraction:
    """Average-cost position update; returns the realized P&L of this leg."""
    signed = qty if is_buy else -qty
    if is_buy:
        pos.buy_qty += qty
        pos.buy_notional += qty * price
    else:
        pos.sell_qty += qty
        pos.sell_notional += qty * price
    if pos.net_qty == 0 or (pos.net_qty > 0) == is_buy:
        held = abs(pos.net_qty)
        pos.avg_cost = (pos.avg_cost * held + price * qty) / (held + qty)
        pos.net_qty += signed
        return Fraction(0)
    closed = min(qty, abs(pos.net_qty))
    direction = 1 if pos.net_qty > 0 else -1
    realized = (price - pos.avg_cost) * closed * direction
    pos.realized += realized
    pos.net_qty += signed
    if pos.net_qty == 0:
        pos.avg_cost = Fraction(0)
    elif (pos.net_qty > 0) == is_buy:
        pos.avg_cost = Fraction(price)  # crossed zero: the rest opens anew
    return realized


def _replay(ds: Dataset) -> _Replay:
    cached = ds.cache.get("bookkeeping.replay")
    if isinstance(cached, _Replay):
        return cached
    first = ds.conn.execute("SELECT min(id) FROM clearing.trade_events").fetchone()[0]
    if first is None:
        raise Skipped("clearing.trade_events is empty")
    if not first.endswith("-000000001"):
        # Positions are cumulative over every trade ever; pruned trades
        # cannot be replayed.
        raise Skipped(f"clearing.trade_events pruned (first trade {first})")
    r = _Replay()
    rows = ds.conn.execute(
        "SELECT id, ts_ns, trade_date, symbol, price, quantity, buy_gateway_id, "
        "sell_gateway_id FROM clearing.trade_events ORDER BY id"
    )
    for trade_id, ts_ns, stored_date, symbol, price, qty, buy_gw, sell_gw in rows:
        date = _session_date_ns(ts_ns, ds)
        if date != stored_date:
            r.misdated.append((trade_id, stored_date, date))
        for gw, is_buy in ((buy_gw, True), (sell_gw, False)):
            pos = r.positions.setdefault((gw, symbol), _Pos())
            realized = _apply(pos, qty, price, is_buy)
            day = r.days.setdefault((date, gw, symbol), _DaySummary())
            if is_buy:
                day.buy_qty += qty
                day.buy_notional += qty * price
            else:
                day.sell_qty += qty
                day.sell_notional += qty * price
            day.realized += realized
            day.end_net_qty = pos.net_qty
        r.last_price[symbol] = price
    ds.cache["bookkeeping.replay"] = r
    return r


def _close(stored: float, expected: Fraction) -> bool:
    return math.isclose(stored, float(expected), rel_tol=_REL_TOL, abs_tol=_ABS_TOL)


@check(
    "B3",
    "conservation",
    "gateway_symbol_positions equal an average-cost replay of trade_events",
    needs=("clearing",),
)
def positions_match_replay(ds: Dataset) -> Outcome:
    r = _replay(ds)
    samples: list[Sample] = []
    seen = set()
    rows = ds.conn.execute(
        "SELECT gateway_id, symbol, net_qty, buy_qty, sell_qty, buy_notional, "
        "sell_notional, avg_cost, realized_pnl, unrealized_pnl, mark_price "
        "FROM clearing.gateway_symbol_positions"
    )
    for gw, symbol, net, bq, sq, bn, sn, avg, realized, unrealized, mark in rows:
        seen.add((gw, symbol))
        pos = r.positions.get((gw, symbol))
        if pos is None:
            samples.append({"gateway_id": gw, "symbol": symbol, "diffs": "no trades"})
            continue
        diffs: dict[str, object] = {}
        for name, stored, expected in (
            ("net_qty", net, pos.net_qty),
            ("buy_qty", bq, pos.buy_qty),
            ("sell_qty", sq, pos.sell_qty),
            ("buy_notional", bn, pos.buy_notional),
            ("sell_notional", sn, pos.sell_notional),
        ):
            if stored != expected:
                diffs[name] = {"stored": stored, "expected": expected}
        exp_unrealized = Fraction(0)
        if pos.net_qty:
            exp_mark = r.last_price[symbol]
            if mark != exp_mark:
                diffs["mark_price"] = {"stored": mark, "expected": exp_mark}
            exp_unrealized = pos.net_qty * (exp_mark - pos.avg_cost)
        for name, value, exact in (
            ("avg_cost", avg, pos.avg_cost),
            ("realized_pnl", realized, pos.realized),
            ("unrealized_pnl", unrealized, exp_unrealized),
        ):
            if not _close(value, exact):
                diffs[name] = {"stored": value, "expected": float(exact)}
        if diffs:
            samples.append({"gateway_id": gw, "symbol": symbol, "diffs": diffs})
    for gw, symbol in sorted(r.positions.keys() - seen):
        samples.append({"gateway_id": gw, "symbol": symbol, "diffs": "no position row"})
    return Outcome(len(samples), samples, f"{len(r.positions)} positions replayed")


@check(
    "B4",
    "conservation",
    "gateway_daily_summary equals the replay per (trade date, gateway, symbol)",
    needs=("clearing",),
)
def daily_summary_matches_replay(ds: Dataset) -> Outcome:
    r = _replay(ds)
    samples: list[Sample] = [
        {"trade_id": t, "error": f"trade_date {stored} but session date {actual}"}
        for t, stored, actual in r.misdated
    ]
    seen = set()
    rows = ds.conn.execute(
        "SELECT trade_date, gateway_id, symbol, traded_qty, traded_notional, "
        "buy_qty, sell_qty, buy_notional, sell_notional, net_amount, "
        "realized_pnl, end_net_qty FROM clearing.gateway_daily_summary"
    )
    for date, gw, symbol, tq, tn, bq, sq, bn, sn, net_amount, realized, end in rows:
        key = (date, gw, symbol)
        seen.add(key)
        day = r.days.get(key)
        if day is None:
            samples.append({"key": key, "diffs": "no trades that day"})
            continue
        diffs: dict[str, object] = {
            name: {"stored": stored, "expected": expected}
            for name, stored, expected in (
                ("traded_qty", tq, day.buy_qty + day.sell_qty),
                ("traded_notional", tn, day.buy_notional + day.sell_notional),
                ("buy_qty", bq, day.buy_qty),
                ("sell_qty", sq, day.sell_qty),
                ("buy_notional", bn, day.buy_notional),
                ("sell_notional", sn, day.sell_notional),
                ("net_amount", net_amount, day.buy_notional - day.sell_notional),
                ("end_net_qty", end, day.end_net_qty),
            )
            if stored != expected
        }
        if not _close(realized, day.realized):
            diffs["realized_pnl"] = {
                "stored": realized,
                "expected": float(day.realized),
            }
        if diffs:
            samples.append({"key": key, "diffs": diffs})
    for key in sorted(r.days.keys() - seen):
        samples.append({"key": key, "diffs": "no summary row"})
    return Outcome(len(samples), samples)


@check(
    "B5",
    "conservation",
    "Positions net to zero per symbol and each position's P&L equals its cash flow",
    needs=("clearing",),
)
def positions_conserve(ds: Dataset) -> Outcome:
    """Method-independent: needs no replay, so it holds even after pruning.

    Per symbol the market is closed: Σnet_qty = 0, Σbuy = Σsell. Per position,
    whatever the cost method, realized + unrealized = sell_notional −
    buy_notional + net_qty · mark.
    """
    samples: list[Sample] = [
        {"symbol": s, "net_qty": n, "buy_qty": bq, "sell_qty": sq, "notional": bn - sn}
        for s, n, bq, sq, bn, sn in ds.conn.execute(
            "SELECT symbol, sum(net_qty), sum(buy_qty), sum(sell_qty), "
            "sum(buy_notional), sum(sell_notional) "
            "FROM clearing.gateway_symbol_positions GROUP BY symbol "
            "HAVING sum(net_qty) <> 0 OR sum(buy_qty) <> sum(sell_qty) "
            "OR sum(buy_notional) <> sum(sell_notional)"
        )
    ]
    rows = ds.conn.execute(
        "SELECT gateway_id, symbol, net_qty, realized_pnl, unrealized_pnl, "
        "mark_price, buy_notional, sell_notional "
        "FROM clearing.gateway_symbol_positions"
    )
    for gw, symbol, net, realized, unrealized, mark, bn, sn in rows:
        cash = Fraction(sn - bn) + (net * mark if net else 0)
        if not _close(realized + unrealized, cash):
            samples.append(
                {
                    "gateway_id": gw,
                    "symbol": symbol,
                    "pnl": realized + unrealized,
                    "cash_flow_at_mark": float(cash),
                }
            )
    return Outcome(len(samples), samples)


# --- B6/B7: pm-monitor counters ----------------------------------------------

#: (counter, source prefix, query giving one (ts_ns, label) row per counted event).
_COUNTED = (
    (
        "engine.trades",
        "pm-engine",
        "SELECT ts_ns, symbol FROM clearing.trade_events",
    ),
    ("engine.fills", "pm-engine", f"SELECT ts_ns, gw FROM ({_LEGS})"),
    (
        "clearing.trades_settled",
        "pm-clearing",
        "SELECT ingest_ts_ns, '' FROM clearing.trade_events",
    ),
)


@check(
    "B6",
    "cross-store",
    "pm-monitor's daily counters agree with the rows they count",
    needs=("metrics", "clearing"),
)
def counters_match_rows(ds: Dataset) -> Outcome:
    samples: list[Sample] = []
    for name, source, query in _COUNTED:
        samples += counter_mismatches(ds, name, source, ds.conn.execute(query))
    return Outcome(len(samples), samples)


def counter_mismatches(
    ds: Dataset, name: str, source: str, events: Iterable[tuple[int, str]]
) -> list[Sample]:
    """Compare counter *name* per (session date, label) with *events*.

    A counter covers events up to its last sample (counter_last.ts), minus up
    to _COUNTER_SLACK_NS of reporting delay, so its daily total must lie
    between the events before ts − slack and the events before ts. A counter
    still at zero has a counter_last row but no daily_totals row.
    """
    (reported,) = ds.conn.execute(
        "SELECT max(ts) FROM metrics.counter_last WHERE name = ? AND source LIKE ?",
        (name, f"{source}%"),
    ).fetchone()
    if reported is None:
        return [{"counter": name, "error": "never reported"}]
    last_ts = iso_ns(reported)
    totals = {
        (date, label): (total, iso_ns(ts))
        for date, label, total, ts in ds.conn.execute(
            "SELECT d.date, d.label, sum(d.total), max(c.ts) "
            "FROM metrics.daily_totals d JOIN metrics.counter_last c "
            "ON c.source = d.source AND c.name = d.name AND c.label = d.label "
            "WHERE d.name = ? AND d.source LIKE ? GROUP BY d.date, d.label",
            (name, f"{source}%"),
        )
    }
    by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    for ts_ns, label in events:
        by_key[(_session_date_ns(ts_ns, ds), label)].append(ts_ns)
    samples: list[Sample] = []
    for key in sorted(totals.keys() | by_key.keys()):
        total, ts = totals.get(key, (0, last_ts))
        times = by_key.get(key, [])
        upper = sum(1 for t in times if t <= ts)
        lower = sum(1 for t in times if t <= ts - _COUNTER_SLACK_NS)
        if not lower <= total <= upper:
            samples.append(
                {
                    "counter": name,
                    "date": key[0],
                    "label": key[1],
                    "counter_total": total,
                    "rows_before_sample": upper,
                    "rows_before_sample_minus_slack": lower,
                }
            )
    return samples


#: Counters that count lost or rejected data; any non-zero sample is a finding.
_LOSS_COUNTERS = (
    "stats.records_dropped",
    "stats.feed_gaps",
    "audit.decode_errors",
    "health.beacons_dropped",
    "health.samples_rejected",
    "monitor.beacons_invalid",
    "monitor.engine_events_invalid",
    "monitor.loop_errors",
    "monitor.snapshot_errors",
    "monitor.store_errors",
)


@check(
    "B7",
    "conservation",
    "Loss and error counters stayed at zero; no feed gaps recorded",
    needs=("metrics", "stats"),
)
def loss_counters_are_zero(ds: Dataset) -> Outcome:
    marks = ", ".join("?" * len(_LOSS_COUNTERS))
    samples: list[Sample] = [
        {"counter": name, "source": source, "label": label, "max": peak}
        for name, source, label, peak in ds.conn.execute(
            "SELECT name, source, label, max(peak) FROM ("
            " SELECT s.name, s.source, s.label, x.v_max AS peak"
            " FROM metrics.samples_1m x JOIN metrics.series s ON s.id = x.series"
            " UNION ALL SELECT name, source, label, value FROM metrics.counter_last)"
            f" WHERE name IN ({marks}) GROUP BY name, source, label"
            " HAVING max(peak) > 0",
            _LOSS_COUNTERS,
        )
    ]
    samples += [
        {"feed_gap": ts, "stream": stream, "missing": n}
        for ts, stream, n in ds.conn.execute(
            "SELECT ts, stream, missing_count FROM stats.feed_gaps"
        )
    ]
    return Outcome(len(samples), samples)
