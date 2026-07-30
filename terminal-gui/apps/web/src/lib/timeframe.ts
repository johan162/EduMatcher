/**
 * Chart timeframe presets (design §9.4).
 *
 * Bar granularity follows the window, the same rule `pm-trading-ui` uses:
 * short windows bucket raw trades into intraday bars, long ones read the
 * daily rollup pm-stats already computed. Rendering ninety days as
 * one-minute bars would be both unreadable and an enormous download.
 */

export const PRESETS = ["1D", "5D", "1M", "3M", "YTD", "All", "Live"] as const;
export type Preset = (typeof PRESETS)[number];

export interface TimeframeSpec {
  /** Which history endpoint answers this window. */
  source: "trades" | "daily";
  /** Bucket width for `trades`; absent for `daily`, whose bars are per-day. */
  bucketSec?: number;
  /** Inclusive lower bound: ISO timestamp for `trades`, `YYYY-MM-DD` for `daily`. */
  from?: string;
  /**
   * Pin the right edge to now and scroll with incoming ticks.
   *
   * `Live` is the 1D window with this set, rather than a window of its own —
   * "live" describes how the chart tracks, not how much history it shows.
   */
  follow: boolean;
}

const DAY_MS = 86_400_000;

const isoAt = (now: number, daysBack: number): string => new Date(now - daysBack * DAY_MS).toISOString();
const dateAt = (now: number, daysBack: number): string => isoAt(now, daysBack).slice(0, 10);

/**
 * Resolve a preset to the query that fills it.
 *
 * `now` is injected so this stays pure and testable; callers pass
 * `Date.now()`.
 */
export function timeframeSpec(preset: Preset, now: number = Date.now()): TimeframeSpec {
  switch (preset) {
    case "1D":
      return { source: "trades", bucketSec: 60, from: isoAt(now, 1), follow: false };
    case "Live":
      return { source: "trades", bucketSec: 60, from: isoAt(now, 1), follow: true };
    case "5D":
      return { source: "trades", bucketSec: 300, from: isoAt(now, 5), follow: false };
    case "1M":
      return { source: "daily", from: dateAt(now, 30), follow: false };
    case "3M":
      return { source: "daily", from: dateAt(now, 90), follow: false };
    case "YTD":
      return { source: "daily", from: `${new Date(now).getUTCFullYear()}-01-01`, follow: false };
    case "All":
      // No lower bound — the endpoint returns everything pm-stats retains.
      return { source: "daily", follow: false };
  }
}
