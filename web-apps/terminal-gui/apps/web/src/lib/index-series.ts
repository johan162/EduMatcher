/**
 * Chart series for the Index View (design §10.4).
 *
 * `1D`/`5D` render raw intraday level ticks from `/history/index-snapshots` —
 * pm-index writes one row per `index.update`, already fine enough to chart
 * directly, so unlike Symbol Detail there is no bucketing step. `1M` and
 * longer render the daily bars from `/history/index-daily`.
 */

import type { IndexDailyRow, IndexEventRow, IndexSnapshotRow } from "@edumatcher/terminal-types";

export type IndexTimeframe = "1D" | "5D" | "1M" | "3M" | "YTD" | "All";

export const INDEX_TIMEFRAMES: IndexTimeframe[] = ["1D", "5D", "1M", "3M", "YTD", "All"];

/** Whether this preset charts intraday ticks or daily bars. */
export function usesSnapshots(tf: IndexTimeframe): boolean {
  return tf === "1D" || tf === "5D";
}

export interface IndexPoint {
  /** Epoch seconds — what the charting library wants on its time axis. */
  time: number;
  value: number;
}

/** Start of the window a preset needs, as an ISO date, or undefined for All. */
export function indexRangeStart(tf: IndexTimeframe, now = new Date()): string | undefined {
  const d = new Date(now);
  switch (tf) {
    case "1D":
      return d.toISOString().slice(0, 10);
    case "5D":
      d.setUTCDate(d.getUTCDate() - 5);
      break;
    case "1M":
      d.setUTCMonth(d.getUTCMonth() - 1);
      break;
    case "3M":
      d.setUTCMonth(d.getUTCMonth() - 3);
      break;
    case "YTD":
      return `${d.getUTCFullYear()}-01-01`;
    case "All":
      return undefined;
  }
  return d.toISOString().slice(0, 10);
}

function toEpochSeconds(iso: string): number | undefined {
  const ms = new Date(iso).getTime();
  return Number.isNaN(ms) ? undefined : Math.floor(ms / 1000);
}

/** Intraday level ticks, oldest first, with unparseable or empty rows dropped. */
export function snapshotSeries(rows: readonly IndexSnapshotRow[]): IndexPoint[] {
  const points: IndexPoint[] = [];
  for (const row of rows) {
    if (row.level === null || row.level === undefined) continue;
    const time = toEpochSeconds(row.timestamp);
    if (time === undefined) continue;
    points.push({ time, value: row.level });
  }
  return points.sort((a, b) => a.time - b.time);
}

/**
 * Daily closing levels, oldest first.
 *
 * The current trading date is deliberately included: §10.2a notes
 * `close_level` is only final once `close_session_state == "CLOSED"`, but the
 * chart's right-hand edge for today is overwritten by the live tick below, so
 * an unfinished close never survives to be read as one.
 */
export function dailySeries(rows: readonly IndexDailyRow[]): IndexPoint[] {
  const points: IndexPoint[] = [];
  for (const row of rows) {
    if (row.close_level === null || row.close_level === undefined) continue;
    const time = toEpochSeconds(`${row.date}T00:00:00Z`);
    if (time === undefined) continue;
    points.push({ time, value: row.close_level });
  }
  return points.sort((a, b) => a.time - b.time);
}

/**
 * Append the live level to a historical series.
 *
 * This is what keeps §10.2a's rule true in practice: for the current date the
 * right-hand edge of the chart is the live `IDX` tick, never the REST row's
 * provisional `close_level`. A point at the same timestamp is replaced rather
 * than appended, so a series that already reaches "now" does not grow a
 * duplicate on every tick.
 */
export function withLiveTail(
  history: readonly IndexPoint[],
  liveLevel: number | undefined,
  atSeconds: number,
): IndexPoint[] {
  if (liveLevel === undefined || !Number.isFinite(liveLevel)) return [...history];
  const out = history.filter((p) => p.time < atSeconds);
  out.push({ time: atSeconds, value: liveLevel });
  return out;
}

/**
 * Structural changes, most recent first, as one-line summaries (§10.2).
 *
 * `INIT` is filtered out: every index has one and it says nothing about a
 * *change*, so including it would push a real event off a strip that only
 * ever shows a handful.
 */
export function recentChanges(events: readonly IndexEventRow[], limit = 4): string[] {
  return events
    .filter((e) => e.type !== "INIT")
    .slice()
    .sort((a, b) => b.timestamp - a.timestamp)
    .slice(0, limit)
    .map((e) => {
      const date = new Date(e.timestamp * 1000).toISOString().slice(0, 10);
      const sym = e.symbol ?? "";
      switch (e.type) {
        case "ADD_CONSTITUENT":
          return `+ ${sym} added ${date}`;
        case "DELIST":
          return `− ${sym} delisted ${date}`;
        default:
          return `${sym} ${e.detail ?? "corporate action"} ${date}`.trim();
      }
    });
}
