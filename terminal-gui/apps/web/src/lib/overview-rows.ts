/**
 * Builds the Market Overview grid's rows (design §8.4).
 *
 * Pure on purpose: the column semantics here carry most of the view's real
 * logic — which source wins for LAST, when a change figure is meaningful at
 * all — and that is far easier to pin down as a function than through a
 * rendered grid.
 */

import type { DailyBar, TopOfBook } from "@edumatcher/terminal-types";

export interface OverviewRow {
  sym: string;
  pinned: boolean;
  halted: boolean;
  last?: number;
  bid?: number;
  ask?: number;
  /** `last − open`; absent when either side is unknown. */
  chg?: number;
  pctChg?: number;
  volume?: number;
}

export interface BuildRowsInput {
  symbols: string[];
  top: Record<string, TopOfBook>;
  daily: Record<string, DailyBar>;
  halted: Record<string, unknown>;
  watchlist: string[];
  filter: "all" | "watchlist";
}

/**
 * `LAST`, `BID` and `ASK` all come from the same `TOP` frame.
 *
 * An earlier revision preferred the `TRADE` channel here, because the gateway
 * used to never refresh `TOP.LAST` after a trade. That is fixed, and taking
 * all three from one frame is now the better answer anyway: `BID`/`ASK` only
 * change on a book republish, so sourcing `LAST` from trade prints made a row
 * internally inconsistent — a last price from this instant beside a spread
 * from up to `snapshot_interval_sec` ago. Every figure in a row now describes
 * the same moment. Individual prints belong on the Trade Tape (§11).
 */
export function buildRows(input: BuildRowsInput): OverviewRow[] {
  const pinned = new Set(input.watchlist);
  const symbols =
    input.filter === "watchlist" ? input.symbols.filter((sym) => pinned.has(sym)) : input.symbols;

  return symbols.map((sym) => {
    const top = input.top[sym];
    const last = top?.last;
    const open = input.daily[sym]?.open_price ?? undefined;

    const row: OverviewRow = {
      sym,
      pinned: pinned.has(sym),
      halted: sym in input.halted,
    };

    if (last !== undefined) row.last = last;
    if (top?.bid !== undefined) row.bid = top.bid;
    if (top?.ask !== undefined) row.ask = top.ask;

    const volume = input.daily[sym]?.volume;
    if (volume !== null && volume !== undefined) row.volume = volume;

    // A change figure needs both ends. A symbol that has not traded today has
    // no open, and showing "0.00 (0.00%)" would claim it was flat rather than
    // untraded. An open of exactly zero is likewise no basis for a percentage.
    if (last !== undefined && open !== undefined && open !== null) {
      row.chg = last - open;
      if (open !== 0) row.pctChg = ((last - open) / open) * 100;
    }

    return row;
  });
}

/** Column sets per density preset (design §7.5). */
export type OverviewColumn = "star" | "symbol" | "last" | "chg" | "pctChg" | "bid" | "ask" | "volume";

const LOBBY_COLUMNS: OverviewColumn[] = ["symbol", "last", "pctChg", "volume"];
const FULL_COLUMNS: OverviewColumn[] = ["star", "symbol", "last", "chg", "pctChg", "bid", "ask", "volume"];

/**
 * Lobby drops to four columns and loses the star: an unattended classroom
 * display has nobody to click it, and the space buys larger type instead.
 */
export function columnsFor(density: "lobby" | "standard" | "dense"): OverviewColumn[] {
  return density === "lobby" ? LOBBY_COLUMNS : FULL_COLUMNS;
}
