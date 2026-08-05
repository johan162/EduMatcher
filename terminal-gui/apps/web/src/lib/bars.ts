/**
 * Chart data preparation (design §9.3, §9.4).
 *
 * Pure, because this is where the chart's correctness actually lives —
 * bucketing boundaries, which end of a bucket is open versus close, and how
 * the historical and live midpoint series meet. Far easier to pin down here
 * than through a rendered canvas.
 *
 * Times are Unix seconds throughout, which is what Lightweight Charts wants.
 */

import type { DailyBar, PriceSnapshotRow, TradeRow } from "@edumatcher/terminal-types";

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface VolumePoint {
  time: number;
  value: number;
}

export interface LinePoint {
  time: number;
  value: number;
}

const toSeconds = (iso: string): number | undefined => {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? undefined : Math.floor(ms / 1000);
};

/**
 * Bucket raw trade prints into OHLC bars of `bucketSec`.
 *
 * Buckets are aligned to the epoch rather than to the first trade, so the
 * same window always produces the same boundaries no matter when the viewer
 * opened it — two tabs on one symbol must not draw subtly different candles.
 *
 * Empty intervals produce no bar at all. Lightweight Charts renders a gap,
 * which is honest: a flat synthetic bar would imply the price was held there,
 * when in fact nothing traded.
 */
export function bucketTrades(trades: TradeRow[], bucketSec: number): { bars: Bar[]; volume: VolumePoint[] } {
  if (bucketSec <= 0) return { bars: [], volume: [] };

  const byBucket = new Map<number, { bar: Bar; volume: number }>();

  for (const trade of trades) {
    const seconds = toSeconds(trade.ts);
    if (seconds === undefined || !Number.isFinite(trade.price)) continue;

    const time = Math.floor(seconds / bucketSec) * bucketSec;
    const existing = byBucket.get(time);

    if (!existing) {
      byBucket.set(time, {
        bar: { time, open: trade.price, high: trade.price, low: trade.price, close: trade.price },
        volume: trade.quantity ?? 0,
      });
      continue;
    }

    // Trades arrive oldest-first from the endpoint, so the first price seen in
    // a bucket is its open and the last is its close.
    existing.bar.high = Math.max(existing.bar.high, trade.price);
    existing.bar.low = Math.min(existing.bar.low, trade.price);
    existing.bar.close = trade.price;
    existing.volume += trade.quantity ?? 0;
  }

  const ordered = [...byBucket.values()].sort((a, b) => a.bar.time - b.bar.time);
  return {
    bars: ordered.map((entry) => entry.bar),
    volume: ordered.map((entry) => ({ time: entry.bar.time, value: entry.volume })),
  };
}

/**
 * Convert daily rollup rows into bars.
 *
 * A row with no open or close is a date the symbol did not trade — pm-stats
 * still writes the row. Those are skipped rather than drawn at zero.
 */
export function dailyToBars(rows: DailyBar[]): { bars: Bar[]; volume: VolumePoint[] } {
  const bars: Bar[] = [];
  const volume: VolumePoint[] = [];

  for (const row of [...rows].sort((a, b) => a.date.localeCompare(b.date))) {
    const time = toSeconds(`${row.date}T00:00:00Z`);
    const { open_price: open, close_price: close } = row;
    if (time === undefined || open === null || close === null) continue;

    bars.push({
      time,
      open,
      close,
      high: row.high_price ?? Math.max(open, close),
      low: row.low_price ?? Math.min(open, close),
    });
    if (row.volume !== null) volume.push({ time, value: row.volume });
  }

  return { bars, volume };
}

/** The bid/ask midpoint series, in two parts (design §9.3). */
export interface MidpointSeries {
  /**
   * From `/history/price-snapshots`. Rendered muted, because its 15-minute
   * recording interval is far coarser than the live tail and a viewer should
   * be able to see which part of the line is which.
   */
  historical: LinePoint[];
  /** Tick-by-tick from CALF `TOP`, full opacity. */
  live: LinePoint[];
  /**
   * True when there is no historical part at all — a symbol listed less than
   * one recording interval ago, or pm-stats not running. The chart marks
   * where the data begins rather than showing an error.
   */
  liveOnly: boolean;
}

/**
 * Splice the recorded midpoint history onto the live tail.
 *
 * The two overlap whenever the bridge has been observing longer than the last
 * snapshot, so the historical part is trimmed at the first live point. Without
 * that, the muted coarse line would be drawn over the top of the live one and
 * the chart would appear to fork.
 */
export function midpointSeries(snapshots: PriceSnapshotRow[], live: LinePoint[]): MidpointSeries {
  const historical: LinePoint[] = [];

  for (const row of snapshots) {
    const time = toSeconds(row.ts);
    if (time === undefined) continue;

    // mid_price is what pm-stats records; fall back to the midpoint of the
    // recorded quote only if it is ever null with both sides known.
    const value =
      row.mid_price ??
      (row.best_bid !== null && row.best_ask !== null ? (row.best_bid + row.best_ask) / 2 : null);
    if (value === null) continue;

    historical.push({ time, value });
  }

  historical.sort((a, b) => a.time - b.time);

  const firstLive = live[0]?.time;
  const trimmed = firstLive === undefined ? historical : historical.filter((p) => p.time < firstLive);

  return { historical: trimmed, live, liveOnly: trimmed.length === 0 };
}

/** Midpoint of a top-of-book, when both sides are present. */
export function midOf(bid: number | undefined, ask: number | undefined): number | undefined {
  if (bid === undefined || ask === undefined) return undefined;
  return (bid + ask) / 2;
}
