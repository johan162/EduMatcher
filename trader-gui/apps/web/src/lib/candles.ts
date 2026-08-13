/**
 * Candle building for the Symbol Detail chart (§16.2).
 *
 * Pure functions over plain data — no React, no chart library — so the
 * bucketing and live-tick folding can be unit-tested without mounting
 * Lightweight Charts. Intraday timeframes (1m/5m/1h) are derived from
 * individual trade prints; 1D/All come straight from the daily rollup.
 */
import { bucketTimestamp } from "@/lib/priceUtils.js";
import type { DailyStat } from "@/types/index.js";

export type Timeframe = "1m" | "5m" | "1h" | "1D" | "All";
export type IntradayTimeframe = "1m" | "5m" | "1h";

/**
 * One OHLCV bar. `time` is epoch **seconds** for intraday bars (a Lightweight
 * Charts `UTCTimestamp`) and a `YYYY-MM-DD` string for daily bars.
 */
export interface Candle {
  time: number | string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** A single trade print normalised to what candle building needs. */
export interface Tick {
  timestamp: number; // epoch seconds
  price: number;
  quantity: number;
}

export function isIntraday(tf: Timeframe): tf is IntradayTimeframe {
  return tf === "1m" || tf === "5m" || tf === "1h";
}

/**
 * Bucket trade prints into OHLCV candles for an intraday timeframe.
 * Input need not be sorted; output is ascending by time and one bar per
 * bucket, as Lightweight Charts requires.
 */
export function tradesToCandles(ticks: Tick[], tf: IntradayTimeframe): Candle[] {
  const byBucket = new Map<number, Candle>();
  const sorted = [...ticks].sort((a, b) => a.timestamp - b.timestamp);
  for (const t of sorted) {
    const bucket = bucketTimestamp(t.timestamp, tf);
    const bar = byBucket.get(bucket);
    if (!bar) {
      byBucket.set(bucket, {
        time: bucket,
        open: t.price,
        high: t.price,
        low: t.price,
        close: t.price,
        volume: t.quantity,
      });
    } else {
      bar.high = Math.max(bar.high, t.price);
      bar.low = Math.min(bar.low, t.price);
      bar.close = t.price;
      bar.volume += t.quantity;
    }
  }
  return [...byBucket.values()].sort((a, b) => (a.time as number) - (b.time as number));
}

/**
 * Map daily-rollup rows to candles. Rows without both an open and a close are
 * dropped — a half-formed row would render as a spurious flat bar.
 */
export function dailyToCandles(rows: DailyStat[]): Candle[] {
  return rows
    .filter((r) => r.open_price !== null && r.close_price !== null)
    .map((r) => ({
      time: r.date,
      open: r.open_price as number,
      high: r.high_price ?? (r.open_price as number),
      low: r.low_price ?? (r.open_price as number),
      close: r.close_price as number,
      volume: r.volume,
    }))
    .sort((a, b) => (a.time as string).localeCompare(b.time as string));
}

/**
 * Fold one live tick into the current bar (§16.2.3).
 *
 * Returns the bar to hand to `series.update()` and whether it opens a new
 * bucket. When the tick falls in the same bucket as `last`, high/low/close and
 * volume are merged; otherwise a fresh bar is opened at the tick's price.
 */
export function foldTick(
  last: Candle | null,
  tick: Tick,
  tf: IntradayTimeframe,
): { bar: Candle; isNew: boolean } {
  const bucket = bucketTimestamp(tick.timestamp, tf);
  if (last && last.time === bucket) {
    return {
      bar: {
        time: bucket,
        open: last.open,
        high: Math.max(last.high, tick.price),
        low: Math.min(last.low, tick.price),
        close: tick.price,
        volume: last.volume + tick.quantity,
      },
      isNew: false,
    };
  }
  return {
    bar: {
      time: bucket,
      open: tick.price,
      high: tick.price,
      low: tick.price,
      close: tick.price,
      volume: tick.quantity,
    },
    isNew: true,
  };
}

/** Project candles onto the close-price line series. */
export function candlesToLine(candles: Candle[]): { time: number | string; value: number }[] {
  return candles.map((c) => ({ time: c.time, value: c.close }));
}
