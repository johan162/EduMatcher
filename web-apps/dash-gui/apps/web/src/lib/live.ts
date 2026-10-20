/**
 * The figures the overview's sparklines draw, one small sample per
 * snapshot, kept for the last minute (RECENT): metrics.db stores counters
 * and vitals, not these derived figures, so their short history is the
 * page's own.
 */

import type { HealthSnapshot } from "@edumatcher/dash-types";

/** Samples kept: a minute at pm-monitor's 1 Hz. */
export const RECENT = 60;

export interface LiveSample {
  ts: number;
  ordersPerSec: number;
  p99Us: number;
  participantsConnected: number;
}

export function liveSample(s: HealthSnapshot): LiveSample {
  return {
    ts: Date.parse(s.ts),
    ordersPerSec: s.trading.orders.per_sec_now,
    p99Us: s.trading.handle_p99_us,
    participantsConnected: s.participants.filter((p) => p.connected).length,
  };
}

/** `recent` with `next` appended, the oldest dropped past RECENT; a repeated `ts` replaces. */
export function pushRecent(recent: readonly LiveSample[], next: LiveSample): LiveSample[] {
  const kept = recent.at(-1)?.ts === next.ts ? recent.slice(0, -1) : recent;
  return [...kept, next].slice(-RECENT);
}
