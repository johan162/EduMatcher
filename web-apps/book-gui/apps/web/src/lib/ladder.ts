/**
 * Ladder and tape arithmetic (design §9.4), pure and tested.
 */

import type { Level, TapeTrade } from "@edumatcher/book-types";
import type { Trend } from "./stats.js";

export type MaxLevels = "fit" | 10 | 20 | 50;

/** Rows the three panels share: what fits the screen, capped by the "Max levels" setting. */
export function capacity(fits: number, maxLevels: MaxLevels): number {
  return maxLevels === "fit" ? fits : Math.min(fits, maxLevels);
}

/** The largest qty among the rows actually shown — pm-viewer scales its bars the same way. */
export function maxQty(levels: readonly Level[], shown: number): number {
  return levels.slice(0, shown).reduce((max, l) => Math.max(max, l.qty), 0);
}

/** Bar width in percent; any positive qty shows at least a sliver. */
export function barPct(qty: number, max: number): number {
  if (max <= 0 || qty <= 0) return 0;
  return Math.max(2, Math.min(100, (qty / max) * 100));
}

/** Newest first, each paired with its tick direction versus the next-older print. */
export function tapeRows(tape: readonly TapeTrade[], shown: number): { trade: TapeTrade; trend: Trend }[] {
  const newest = tape.slice(-shown - 1).reverse();
  return newest.slice(0, shown).map((trade, i) => {
    const older = newest[i + 1];
    const t: Trend = !older || older.px === trade.px ? "flat" : trade.px > older.px ? "up" : "down";
    return { trade, trend: t };
  });
}
