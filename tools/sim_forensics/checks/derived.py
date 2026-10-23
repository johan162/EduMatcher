"""F — derived data recomputed from the per-trade records."""

from __future__ import annotations

import math
from dataclasses import dataclass

from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Sample, check


@dataclass
class _Day:
    trade_count: int = 0
    volume: int = 0
    turnover: int = 0
    open_price: int | None = None
    close_price: int | None = None
    high_price: int | None = None
    low_price: int | None = None
    largest_trade_qty: int = 0
    largest_trade_price: int | None = None


_FIELDS = (
    "trade_count",
    "volume",
    "turnover",
    "open_price",
    "close_price",
    "high_price",
    "low_price",
    "largest_trade_qty",
    "largest_trade_price",
)


@check(
    "F1",
    "cross-store",
    "daily_stats OHLCV/turnover/VWAP recomputed from trade_log",
    needs=("stats",),
)
def daily_stats_match_trade_log(ds: Dataset) -> Outcome:
    """Recompute every (date, symbol) row from all of trade_log.

    Trades are taken in engine order (trade id), not pm-stats's receive
    order, so open/close also prove the recorder saw trades in sequence.
    Not bounded by the cut: both tables are pm-stats's own.
    """
    days: dict[tuple[str, str], _Day] = {}
    rows = ds.conn.execute(
        "SELECT session_date(ts), symbol, price, quantity "
        "FROM stats.trade_log ORDER BY trade_id"
    )
    for date, symbol, price, qty in rows:
        d = days.setdefault((date, symbol), _Day())
        d.trade_count += 1
        d.volume += qty
        d.turnover += price * qty
        if d.open_price is None:
            d.open_price = price
        d.close_price = price
        d.high_price = price if d.high_price is None else max(d.high_price, price)
        d.low_price = price if d.low_price is None else min(d.low_price, price)
        if qty > d.largest_trade_qty:
            d.largest_trade_qty, d.largest_trade_price = qty, price

    samples: list[Sample] = []
    stored = ds.conn.execute(
        "SELECT date, symbol, vwap, " + ", ".join(_FIELDS) + " FROM stats.daily_stats"
    )
    seen = set()
    for date, symbol, vwap, *values in stored:
        seen.add((date, symbol))
        expected = days.get((date, symbol), _Day())
        diffs = {
            name: {"stored": value, "expected": getattr(expected, name)}
            for name, value in zip(_FIELDS, values)
            if value != getattr(expected, name)
        }
        exp_vwap = expected.turnover / expected.volume if expected.volume else None
        if not _same_vwap(vwap, exp_vwap):
            diffs["vwap"] = {"stored": vwap, "expected": exp_vwap}
        if diffs:
            samples.append({"date": date, "symbol": symbol, "diffs": diffs})
    for date, symbol in sorted(days.keys() - seen):
        samples.append({"date": date, "symbol": symbol, "diffs": "no daily_stats row"})
    return Outcome(len(samples), samples, f"{len(days)} (date, symbol) days traded")


def _same_vwap(stored: float | None, expected: float | None) -> bool:
    if stored is None or expected is None:
        return stored is expected
    return math.isclose(stored, expected, rel_tol=1e-12)
