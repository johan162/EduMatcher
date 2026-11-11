/**
 * Timestamps.
 *
 * Every `*_ns` field is epoch nanoseconds. JSON numbers are doubles, so such a
 * value arrives rounded to a few hundred nanoseconds: fine for display, never
 * to be compared for equality. They are shown in UTC, labelled, because the
 * GUI is not told the venue's session timezone; trading days (`trade_date`)
 * come from the server already resolved in it.
 */

const DASH = "—";

/** `2026-11-03 10:00:01 UTC`, or a dash for a missing time. */
export function formatNs(ns: number | null | undefined): string {
  if (ns === null || ns === undefined) return DASH;
  const iso = new Date(Math.floor(ns / 1_000_000)).toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)} UTC`;
}

/** `HH:MM:SS UTC`, for a freshness line. */
export function formatClock(ns: number | null | undefined): string {
  if (ns === null || ns === undefined) return DASH;
  return `${new Date(Math.floor(ns / 1_000_000)).toISOString().slice(11, 19)} UTC`;
}
