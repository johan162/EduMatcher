/**
 * Sorting and symbol search for the Overview grid (design §8, T-M5).
 *
 * Auto-paging is right for the unattended display this view was built for
 * and wrong for a person at a desk, who wants to see the biggest movers, the
 * widest spreads, or one particular symbol — and wants them to stay still
 * while being read. Both are the same underlying fact: *somebody is here*.
 * Sorting and searching are therefore treated as evidence of that, and the
 * view suspends its unattended behaviour while either is active.
 *
 * Neither is persisted. A wallboard left with a sort applied would sit
 * paused indefinitely with nobody to notice, which is a worse failure than
 * a trader having to click a column header again after a reload.
 */

import type { OverviewRow } from "./overview-rows.js";

export type SortKey =
  | "sym"
  | "last"
  | "chg"
  | "pctChg"
  | "bidSz"
  | "bid"
  | "ask"
  | "askSz"
  | "spread"
  | "volume"
  | "turnover"
  | "lastTradeTs";

export type SortDirection = "asc" | "desc";

export interface SortState {
  key: SortKey;
  direction: SortDirection;
}

/**
 * Which way a column sorts when first clicked.
 *
 * Numeric columns open descending because the question a trader is asking
 * by clicking them is "what are the biggest?" — biggest movers, most
 * turnover, widest spread. The symbol column opens ascending because the
 * question there is "where is X?", and A-Z is how anyone looks that up.
 */
function initialDirection(key: SortKey): SortDirection {
  return key === "sym" ? "asc" : "desc";
}

/**
 * The sort state after clicking a column header.
 *
 * Cycles through both directions and then back to unsorted, so a header can
 * always be un-clicked. Without the third step there would be no way back
 * to the feed's own order except a reload — and on this view unsorted is not
 * an absence of a sort, it is the order the gateway lists its universe in.
 */
export function nextSort(current: SortState | null, key: SortKey): SortState | null {
  const opening = initialDirection(key);
  if (current === null || current.key !== key) return { key, direction: opening };
  if (current.direction === opening) {
    return { key, direction: opening === "asc" ? "desc" : "asc" };
  }
  return null;
}

/** Pull the comparable value for a key, or `undefined` when the row lacks it. */
function valueOf(row: OverviewRow, key: SortKey): number | string | undefined {
  if (key === "sym") return row.sym;
  if (key === "lastTradeTs") return row.lastTradeTs;
  return row[key];
}

/**
 * Sort rows by one column, leaving rows that lack it at the bottom.
 *
 * Absent is not a value, it is the lack of one, so it sorts last in *both*
 * directions rather than being treated as a very small number. A symbol that
 * has not traded has no percentage change; letting it float to the top of an
 * ascending sort would present "unknown" as "worst faller", which is the
 * same error as rendering it `0.00%`.
 *
 * Returns a new array; the input is left alone because it is the memoised
 * result the rest of the view reads.
 */
export function sortRows(rows: readonly OverviewRow[], sort: SortState | null): OverviewRow[] {
  if (sort === null) return [...rows];

  const factor = sort.direction === "asc" ? 1 : -1;

  return [...rows].sort((a, b) => {
    const left = valueOf(a, sort.key);
    const right = valueOf(b, sort.key);

    if (left === undefined && right === undefined) return 0;
    if (left === undefined) return 1;
    if (right === undefined) return -1;

    if (typeof left === "string" && typeof right === "string") {
      return left.localeCompare(right) * factor;
    }
    return ((left as number) - (right as number)) * factor;
  });
}

/**
 * Narrow rows to those whose symbol matches what has been typed.
 *
 * Prefix-first, then substring: typing `TS` should put `TSLA` above
 * `MSFT-TS` if both exist, because a trader reaching for a symbol is almost
 * always starting to spell it. Case-insensitive, since nobody types tickers
 * in lower case by mistake and being strict about it would only ever refuse
 * a match the reader can see is right.
 */
export function filterBySymbol(rows: readonly OverviewRow[], query: string): OverviewRow[] {
  const needle = query.trim().toUpperCase();
  if (needle === "") return [...rows];

  const prefix: OverviewRow[] = [];
  const contains: OverviewRow[] = [];
  for (const row of rows) {
    const sym = row.sym.toUpperCase();
    if (sym.startsWith(needle)) prefix.push(row);
    else if (sym.includes(needle)) contains.push(row);
  }
  return [...prefix, ...contains];
}

/**
 * Whether the view should stop paging itself.
 *
 * Either interaction means somebody is present and reading, which is the one
 * circumstance auto-paging exists to serve the absence of.
 */
export function isAttended(sort: SortState | null, query: string): boolean {
  return sort !== null || query.trim() !== "";
}
