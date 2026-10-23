/**
 * Per-minute activity from raw trade prints, for the book drawer's bar charts.
 *
 * Buckets are aligned to the epoch minute, like `bucketTrades`, and a minute
 * without a print has no bar at all: a gap is honest, a zero bar is a claim
 * that the market was open and quiet.
 */

import type { TradeRow } from "@edumatcher/terminal-types";
import type { LinePoint } from "./bars.js";

export interface MinuteActivity {
  /** Prints per minute. */
  trades: LinePoint[];
  /** Traded value (price x quantity) per minute. */
  value: LinePoint[];
}

export function perMinute(trades: readonly TradeRow[]): MinuteActivity {
  const byMinute = new Map<number, { count: number; value: number }>();
  for (const trade of trades) {
    const ms = Date.parse(trade.ts);
    if (Number.isNaN(ms) || !Number.isFinite(trade.price)) continue;
    const time = Math.floor(ms / 60_000) * 60;
    const slot = byMinute.get(time) ?? { count: 0, value: 0 };
    slot.count += 1;
    slot.value += trade.price * (trade.quantity ?? 0);
    byMinute.set(time, slot);
  }
  const ordered = [...byMinute.entries()].sort((a, b) => a[0] - b[0]);
  return {
    trades: ordered.map(([time, slot]) => ({ time, value: slot.count })),
    value: ordered.map(([time, slot]) => ({ time, value: slot.value })),
  };
}
