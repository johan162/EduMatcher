"""H — ops signals and statistics: pointers to look at, not proofs.

Every check here has the "statistical" oracle, so it reports INFO: its count
says how many pointers it found, never that the run failed.
"""

from __future__ import annotations

import bisect
import json
import statistics
from collections import defaultdict, deque
from collections.abc import Sequence
from typing import Any

from sim_forensics.dataset import Dataset, iso_ns
from sim_forensics.registry import Outcome, Sample, Skipped, check, failed_outcomes

SEC = 1_000_000_000
#: An ops event this close to a finding is listed with it (H1).
_NEAR_S = 30
#: Samples of one failed check H1 places in time.
_PER_CHECK = 50
#: |robust z| beyond which a gateway or symbol is an outlier (H2).
_Z = 5.0
#: A print this far from the prevailing price (the median of the symbol's
#: last _PREVAILING continuous trades) is a jump (H2) ...
_JUMP_PCT = 5.0
_PREVAILING = 20
#: ... unless news on the symbol (or the market) came this long before it.
_NEWS_BEFORE_S = 15 * 60
#: An engine p99 this many times the run's median minute is a spike (H3).
_SPIKE = 10.0
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid_ns(ulid: str) -> int:
    """Creation time of a ULID (its first 10 characters: milliseconds)."""
    ms = 0
    for ch in ulid[:10]:
        ms = ms * 32 + _CROCKFORD.index(ch)
    return ms * 1_000_000


# ---------------------------------------------------------------------------
# H1
# ---------------------------------------------------------------------------


def _ops_events(ds: Dataset) -> list[tuple[int, str]]:
    """(ns, description) of every ops event the stores hold, in time order."""
    events: list[tuple[int, str]] = []
    if "metrics" in ds.stores:
        for ts, kind, severity, subject, detail in ds.conn.execute(
            "SELECT ts, kind, severity, subject, detail FROM metrics.events"
        ):
            events.append((iso_ns(ts), f"{kind} {severity} {subject}: {detail}"))
    if "clearing" in ds.stores:
        for gw, at, reason in ds.conn.execute(
            "SELECT gateway_id, disconnected_at_ns, disconnect_reason "
            "FROM clearing.gateway_sessions WHERE disconnected_at_ns IS NOT NULL"
        ):
            events.append((at, f"disconnect {gw}: {reason}"))
    if "log" in ds.stores:
        for ts, level, process, message in ds.conn.execute(
            "SELECT server_ts, level, process, message FROM log.log_events "
            "WHERE level NOT IN ('DEBUG', 'INFO')"
        ):
            events.append((iso_ns(ts), f"log {level} {process}: {message[:120]}"))
    return sorted(events)


class _Clock:
    """Resolves a finding's sample to a time from the keys it carries."""

    def __init__(self, ds: Dataset) -> None:
        self.ds = ds

    def __call__(self, sample: Sample) -> int | None:
        ts = sample.get("ts")
        if isinstance(ts, str):
            return iso_ns(ts)
        chain = sample.get("chain")
        if isinstance(chain, str) and len(chain) == 26:
            return ulid_ns(chain)
        for key, sql, store in (
            ("trade_id", "SELECT ts FROM stats.trade_log WHERE trade_id = ?", "stats"),
            ("order_id", "SELECT min(ts) FROM stats.order_events WHERE order_id = ?", "stats"),  # fmt: skip
        ):
            value = sample.get(key)
            if isinstance(value, str) and store in self.ds.stores:
                row = self.ds.conn.execute(sql, (value,)).fetchone()
                if row and row[0]:
                    return iso_ns(row[0])
        return None


def _covered(events: list[tuple[int, str]], lo: int, hi: int) -> float:
    """Share of [lo, hi] within _NEAR_S of some ops event."""
    if hi <= lo:
        return 0.0
    total, reach = 0, lo
    for t, _ in events:
        a, b = max(t - _NEAR_S * SEC, reach), min(t + _NEAR_S * SEC, hi)
        if b > a:
            total += b - a
            reach = b
    return total / (hi - lo)


@check(
    "H1",
    "statistical",
    "Ops events (thresholds, process status, disconnects, log warnings) near findings",
    needs=(),
)
def ops_events_near_findings(ds: Dataset) -> Outcome:
    """For each failed check's samples, the ops events within ±30 s. Counts
    findings near an event; the note gives, per check, how many samples had
    a time and how many of those were near one, and how much of the run is
    near an event at all -- the share a finding lands near one by chance."""
    failed = {k: v for k, v in failed_outcomes(ds).items() if not k.startswith("H")}
    events = _ops_events(ds)
    if not events:
        raise Skipped("no ops events in metrics.db, clearing.db or log.db")
    times = [t for t, _ in events]
    clock = _Clock(ds)
    samples: list[Sample] = []
    parts = []
    near_total = 0
    for cid, out in sorted(failed.items()):
        timed = near = 0
        for sample in out.samples[:_PER_CHECK]:
            at = clock(sample)
            if at is None:
                continue
            timed += 1
            i = bisect.bisect_left(times, at - _NEAR_S * SEC)
            j = bisect.bisect_right(times, at + _NEAR_S * SEC)
            if i == j:
                continue
            near += 1
            samples.append(
                {
                    "check": cid,
                    "sample": sample,
                    "events": [
                        f"{(t - at) / SEC:+.1f}s {what}" for t, what in events[i:j][:5]
                    ],
                }
            )
        near_total += near
        parts.append(f"{cid}: {near} of {timed} timed samples")
    span = _span(ds)
    chance = f"{_covered(events, *span):.0%} of the run" if span else "unknown"
    note = (
        f"{len(events)} ops events; {'; '.join(parts) or 'no failed checks'}; "
        f"near an event by chance: {chance}"
    )
    return Outcome(near_total, samples, note)


def _span(ds: Dataset) -> tuple[int, int] | None:
    if "stats" not in ds.stores:
        return None
    lo, hi = ds.conn.execute("SELECT min(ts), max(ts) FROM stats.trade_log").fetchone()
    return (iso_ns(lo), iso_ns(hi)) if lo else None


# ---------------------------------------------------------------------------
# H2
# ---------------------------------------------------------------------------


def _robust_z(values: dict[str, float]) -> dict[str, float]:
    """(x - median) / (1.4826 MAD) per key; empty when the spread is zero."""
    if len(values) < 5:
        return {}
    med = statistics.median(values.values())
    mad = statistics.median(abs(v - med) for v in values.values())
    if mad == 0:
        return {}
    return {k: (v - med) / (1.4826 * mad) for k, v in values.items()}


def _group(gateway_id: str) -> str:
    """Gateways of one kind (AI001.., MM01..) are compared with each other."""
    return gateway_id.rstrip("0123456789")


def _gateway_figures(ds: Dataset) -> dict[str, dict[str, float]]:
    """Figure → gateway → value."""
    figures: dict[str, dict[str, float]] = defaultdict(dict)
    if "clearing" in ds.stores:
        for gw, pnl in ds.conn.execute(
            "SELECT gateway_id, sum(realized_pnl + unrealized_pnl) "
            "FROM clearing.gateway_symbol_positions GROUP BY gateway_id"
        ):
            figures["pnl"][gw] = pnl
    counts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for gw, et, n, qty, filled in ds.conn.execute(
        "SELECT gateway_id, event_type, count(*), sum(quantity), sum(fill_qty) "
        "FROM stats.order_events GROUP BY gateway_id, event_type"
    ):
        c = counts[gw]
        c[et] = n
        if et == "ACK":
            c["acked_qty"] = qty or 0
        elif et == "FILL":
            c["filled_qty"] = filled or 0
    for gw, c in counts.items():
        if c["ACK"]:
            figures["fill_ratio"][gw] = c["filled_qty"] / c["acked_qty"] if c["acked_qty"] else 0  # fmt: skip
            figures["reject_rate"][gw] = c["REJECT"] / (c["ACK"] + c["REJECT"])
        if c["FILL"]:
            figures["cancel_to_fill"][gw] = c["CANCEL"] / c["FILL"]
    return figures


def _gateway_outliers(ds: Dataset) -> list[Sample]:
    out: list[Sample] = []
    for figure, by_gw in sorted(_gateway_figures(ds).items()):
        groups: dict[str, dict[str, float]] = defaultdict(dict)
        for gw, v in by_gw.items():
            groups[_group(gw)][gw] = v
        for values in groups.values():
            med = statistics.median(values.values()) if values else 0
            for gw, z in _robust_z(values).items():
                if abs(z) > _Z:
                    out.append(
                        {"kind": "gateway", "figure": figure, "gateway_id": gw, "value": round(values[gw], 4), "group_median": round(med, 4), "z": round(z, 1)}  # fmt: skip
                    )
    return out


def _news(ds: Dataset) -> dict[str, list[int]]:
    """Symbol → news times; "*" holds sector and market news, which explain a
    jump on any symbol (the data holds no sector map)."""
    news: dict[str, list[int]] = defaultdict(list)
    if "market_sim_news" not in ds.stores:
        return news
    for ts_ns, scope, targets in ds.conn.execute(
        "SELECT ts_ns, scope, targets FROM market_sim_news.news_events"
    ):
        for symbol in json.loads(targets) if scope == "SYMBOL" else ["*"]:
            news[symbol].append(ts_ns)
    for times in news.values():
        times.sort()
    return news


def _explained(news: dict[str, list[int]], symbol: str, at: int) -> bool:
    for times in (news.get(symbol, []), news.get("*", [])):
        i = bisect.bisect_right(times, at)
        if i and at - times[i - 1] <= _NEWS_BEFORE_S * SEC:
            return True
    return False


def _jumps(ds: Dataset) -> tuple[list[Sample], int]:
    """Continuous prints more than _JUMP_PCT from the prevailing price (the
    median of the symbol's last _PREVAILING continuous trades that day), one
    per excursion; and how many such excursions news explains.

    Not trade-to-trade sigmas: the tape is dominated by bid-ask bounce (a
    one-tick median move, a spread-wide move whenever an order crosses), so
    "10 sigma" flagged ~19 000 ordinary spread crossings on the 2026-10-24 run.
    """
    news = _news(ds)
    out: list[Sample] = []
    explained = 0
    recent: dict[str, deque[int]] = {}
    away: dict[str, bool] = {}
    day_of: dict[str, str] = {}
    for symbol, trade_id, ts, price in ds.conn.execute(
        "SELECT symbol, trade_id, ts, price FROM stats.trade_log "
        "WHERE aggressor_side != 'AUCTION' ORDER BY symbol, trade_id"
    ):
        if day_of.get(symbol) != ts[:10]:
            day_of[symbol], away[symbol] = ts[:10], False
            recent[symbol] = deque(maxlen=_PREVAILING)
        window = recent[symbol]
        if len(window) == _PREVAILING:
            prevailing = statistics.median(window)
            move = price / prevailing - 1
            if abs(move) <= _JUMP_PCT / 100:
                away[symbol] = False
            elif not away[symbol]:
                away[symbol] = True
                if _explained(news, symbol, iso_ns(ts)):
                    explained += 1
                else:
                    out.append(
                        {"kind": "jump", "symbol": symbol, "trade_id": trade_id, "ts": ts, "move_pct": round(move * 100, 2), "prevailing": prevailing}  # fmt: skip
                    )
        window.append(price)
    return out, explained


def _spread_outliers(ds: Dataset) -> list[Sample]:
    spreads: dict[str, list[float]] = defaultdict(list)
    for symbol, bid, ask in ds.conn.execute(
        "SELECT symbol, best_bid, best_ask FROM stats.price_snapshots "
        "WHERE best_bid IS NOT NULL AND best_ask IS NOT NULL"
    ):
        spreads[symbol].append((ask - bid) / ((ask + bid) / 2))
    medians = {s: statistics.median(v) for s, v in spreads.items()}
    return [
        {"kind": "spread", "symbol": s, "median_spread_bps": round(medians[s] * 1e4, 1), "z": round(z, 1)}  # fmt: skip
        for s, z in sorted(_robust_z(medians).items())
        if abs(z) > _Z
    ]


@check(
    "H2",
    "statistical",
    "Outliers: gateway P&L/fill/reject/cancel rates, price jumps without news, spreads",
    needs=("stats",),
)
def outliers(ds: Dataset) -> Outcome:
    """Gateways are compared within their kind (AI*, MM*, TRADER*) by robust
    z-score (> 5); a continuous print more than 5 % from the prevailing
    price, with no news on the symbol or the market in the 15 min before,
    starts a jump; symbols are compared by median relative spread in
    price_snapshots."""
    gateways = _gateway_outliers(ds)
    jumps, explained = _jumps(ds)
    spreads = _spread_outliers(ds)
    by_size = sorted(jumps, key=lambda s: -abs(float(str(s["move_pct"]))))
    samples = gateways + by_size + spreads
    note = (
        f"{len(gateways)} gateway outliers, {len(jumps)} unexplained jumps "
        f"(> {_JUMP_PCT:g} % off the prevailing price; {explained} more after "
        f"news), {len(spreads)} spread outliers"
    )
    if "market_sim_news" not in ds.stores:
        note += "; no market_sim_news.db: no jump is explained by news"
    return Outcome(len(samples), samples, note)


# ---------------------------------------------------------------------------
# H3
# ---------------------------------------------------------------------------

#: Per-minute covariates of the engine's p99: (name, column, aggregate over
#: the series' labels).
_COVARIATES = (
    ("engine.msgs_in", "delta", "sum"),
    ("engine.book_resting_orders", "v_last", "sum"),
    ("engine.book_heap_garbage_pct", "v_avg", "avg"),
    ("engine.busy_pct", "v_avg", "avg"),
    ("health.gc_gen2", "delta", "sum"),
    ("host.cpu_pct", "v_avg", "avg"),
)


def _per_minute(ds: Dataset, name: str, column: str, agg: str) -> dict[str, float]:
    source = "pm-engine%" if name.startswith(("engine.", "health.")) else "%"
    label = "" if name == "host.cpu_pct" else "%"
    return {
        ts: v
        for ts, v in ds.conn.execute(
            f"SELECT m.ts, {agg}(m.{column}) FROM metrics.samples_1m m "
            "JOIN metrics.series s ON s.id = m.series "
            "WHERE s.name = ? AND s.source LIKE ? AND s.label LIKE ? "
            f"AND m.{column} IS NOT NULL GROUP BY m.ts",
            (name, source, label),
        )
    }


def _ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3:
        return None
    try:
        return statistics.correlation(_ranks(xs), _ranks(ys))
    except statistics.StatisticsError:
        return None  # a constant series


@check(
    "H3",
    "statistical",
    "Engine p99 latency against load, book size, garbage, GC and CPU",
    needs=("metrics",),
)
def latency_vs_load(ds: Dataset) -> Outcome:
    """Per minute: the engine's handle p99 (the minute's max) and its
    Spearman rank correlation with each covariate; minutes whose p99 is
    more than 10x the median minute are spikes, listed with the covariates.
    For the perf plan, not a correctness verdict."""
    p99 = _per_minute(ds, "engine.handle_us_p99", "v_max", "max")
    if not p99:
        raise Skipped("no engine.handle_us_p99 samples in metrics.db")
    covariates = {
        name: _per_minute(ds, name, col, agg) for name, col, agg in _COVARIATES
    }
    median = statistics.median(p99.values())
    parts = []
    for name, series in covariates.items():
        common = sorted(p99.keys() & series.keys())
        rho = spearman([p99[t] for t in common], [series[t] for t in common])
        parts.append(f"{name} {'n/a' if rho is None else f'{rho:+.2f}'}")
    spikes = sorted(
        (t for t, v in p99.items() if v > _SPIKE * median), key=lambda t: -p99[t]
    )
    samples: list[Sample] = [
        {
            "ts": t,
            "p99_us": round(p99[t]),
            **{name: _round(series.get(t)) for name, series in covariates.items()},
        }
        for t in spikes
    ]
    note = (
        f"{len(p99)} minutes, median p99 {median:.0f} us, "
        f"{len(spikes)} spikes (> {_SPIKE:g}x); Spearman with p99: {', '.join(parts)}"
    )
    return Outcome(len(samples), samples, note)


def _round(v: Any) -> Any:
    return round(v, 1) if isinstance(v, float) else v
