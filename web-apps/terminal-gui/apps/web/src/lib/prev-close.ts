/**
 * Each symbol's previous close, derived from a multi-day window of daily rows.
 *
 * This exists because the exchange publishes no "previous close" anywhere: it
 * is not on the CALF wire, and `/history/daily` has no such column. The only
 * way to it is to look at the day before, which the ranged form of that
 * endpoint returns for every symbol in a single request.
 *
 * Why it matters enough to be worth the request: change measured from the
 * session's open makes a gap invisible. A symbol that opened 5% below
 * yesterday's close and has since recovered 1% is *down on the day*, but
 * against the open it reads +1.00%, in green, and sorts onto the Gainers
 * board. Every terminal quotes change against the previous close for exactly
 * that reason.
 */

import type { DailyBar } from "@edumatcher/terminal-types";

/**
 * The most recent close *before* the current session, per symbol.
 *
 * The current session is the newest date anywhere in the window rather than
 * each symbol's own newest row: pm-stats writes a row for every listed symbol
 * every day, including ones that never traded, so a per-symbol maximum would
 * quietly treat an untraded symbol's own stale row as "today" and compare it
 * against the day before that.
 *
 * A symbol whose window holds nothing but the current session — listed today,
 * or dormant for longer than the window — is simply absent from the result.
 * The caller decides what to do about that; this function does not invent a
 * reference price.
 */
export function previousCloses(rows: readonly DailyBar[]): Record<string, number> {
  let session: string | undefined;
  for (const row of rows) {
    if (session === undefined || row.date > session) session = row.date;
  }
  if (session === undefined) return {};

  const newest: Record<string, { date: string; close: number }> = {};
  for (const row of rows) {
    // Dates are ISO `YYYY-MM-DD`, so string ordering is date ordering.
    if (row.date >= session) continue;
    if (row.close_price === null || !Number.isFinite(row.close_price)) continue;

    const held = newest[row.symbol];
    if (held === undefined || row.date > held.date) {
      newest[row.symbol] = { date: row.date, close: row.close_price };
    }
  }

  const closes: Record<string, number> = {};
  for (const [symbol, entry] of Object.entries(newest)) closes[symbol] = entry.close;
  return closes;
}
