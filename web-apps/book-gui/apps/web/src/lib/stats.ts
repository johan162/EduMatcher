/**
 * Header derivations (design §7.4) — the same formulas as pm-viewer's
 * `_build_header`, kept pure so each is tested on its own.
 */

import type { SessionStats } from "@edumatcher/book-types";

export type Trend = "up" | "down" | "flat";

/** Previous close when known, else the session open. */
export function reference(stats: SessionStats | null): number | undefined {
  return stats?.prevClose ?? stats?.open;
}

export function trend(value: number | undefined, ref: number | undefined): Trend {
  if (value === undefined || ref === undefined || value === ref) return "flat";
  return value > ref ? "up" : "down";
}

export const ARROW: Record<Trend, string> = { up: "▲", down: "▼", flat: "▬" };

export function change(last: number | undefined, ref: number | undefined): number | undefined {
  return last === undefined || ref === undefined ? undefined : last - ref;
}

/** Undefined for a zero or missing reference, where a percentage means nothing. */
export function changePct(last: number | undefined, ref: number | undefined): number | undefined {
  const diff = change(last, ref);
  return diff === undefined || !ref ? undefined : (diff / ref) * 100;
}

export function spread(bid: number | undefined, ask: number | undefined): number | undefined {
  return bid === undefined || ask === undefined ? undefined : ask - bid;
}

export function range(stats: SessionStats | null): number | undefined {
  return stats?.high === undefined || stats.low === undefined ? undefined : stats.high - stats.low;
}

/** What the change is measured against, as pm-viewer's `BASIS` field names it. */
export function basis(stats: SessionStats | null): "prev-close" | "session-open" | "live-since" {
  if (stats?.partial) return "live-since";
  return stats?.prevClose !== undefined ? "prev-close" : "session-open";
}
