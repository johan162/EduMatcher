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

// ---------------------------------------------------------------------------
// Movers (design §12)
// ---------------------------------------------------------------------------

export type MoversTab = "gainers" | "losers" | "active";

/**
 * Rank rows for the Movers board.
 *
 * A separate sort over the same rows the Overview already builds — §12.2 is
 * explicit that Movers opens no new subscriptions. Rows with nothing to rank
 * on are dropped rather than sorted to one end: a symbol that has not traded
 * has no percentage change, and showing it as `0.00%` would claim it was flat
 * when the truth is that it is unknown.
 *
 * `pinned` is deliberately *not* honoured here. On the Overview a starred
 * symbol is pinned to the top because that view is a watchlist; on Movers the
 * ordering is the entire content, and floating a favourite above a bigger
 * mover would misreport the market.
 */
export function rankMovers(
  rows: readonly OverviewRow[],
  tab: MoversTab,
  limit = 25,
): OverviewRow[] {
  if (tab === "active") {
    return rows
      .filter((r) => r.volume !== undefined && r.volume > 0)
      .sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0))
      .slice(0, limit);
  }

  const ranked = rows.filter((r) => r.pctChg !== undefined);
  if (tab === "gainers") {
    return ranked
      .filter((r) => (r.pctChg ?? 0) > 0)
      .sort((a, b) => (b.pctChg ?? 0) - (a.pctChg ?? 0))
      .slice(0, limit);
  }
  return ranked
    .filter((r) => (r.pctChg ?? 0) < 0)
    .sort((a, b) => (a.pctChg ?? 0) - (b.pctChg ?? 0))
    .slice(0, limit);
}

/**
 * Bar width as a 0..1 fraction, scaled against the largest mover on screen.
 *
 * Scaled to the visible set rather than a fixed percentage so a quiet session
 * still shows structure — with a fixed scale a day where nothing moved more
 * than 0.3% would render as a column of empty bars.
 */
export function moverBarFraction(
  row: OverviewRow,
  rows: readonly OverviewRow[],
  tab: MoversTab,
): number {
  const value = tab === "active" ? (row.volume ?? 0) : Math.abs(row.pctChg ?? 0);
  const peak = rows.reduce(
    (max, r) =>
      Math.max(max, tab === "active" ? (r.volume ?? 0) : Math.abs(r.pctChg ?? 0)),
    0,
  );
  return peak > 0 ? value / peak : 0;
}
