/**
 * Builds the Market Overview grid's rows (design §8.4).
 *
 * Pure on purpose: the column semantics here carry most of the view's real
 * logic — which source wins for LAST, when a change figure is meaningful at
 * all — and that is far easier to pin down as a function than through a
 * rendered grid.
 */

import type { DailyBar, TopOfBook } from "@edumatcher/terminal-types";
import { spread, turnover } from "./quote.js";

/**
 * What `chg`/`pctChg` were measured against.
 *
 * `open` is the fallback, not an equal alternative: it means no previous close
 * was on record for that symbol, and the row is saying so rather than silently
 * changing what its own percentage means.
 */
export type ChangeBaseline = "prevClose" | "open";

export interface OverviewRow {
  sym: string;
  pinned: boolean;
  halted: boolean;
  last?: number;
  bid?: number;
  bidSz?: number;
  ask?: number;
  askSz?: number;
  /** `ask − bid`; negative on a crossed book, which is left visible. */
  spread?: number;
  /** Today's opening print, kept as its own figure rather than as the baseline. */
  open?: number;
  /** `last − prevClose`, or `last − open` where no previous close is known. */
  chg?: number;
  pctChg?: number;
  /** Which reference the two above used. Absent exactly when they are. */
  baseline?: ChangeBaseline;
  volume?: number;
  /** Shares × VWAP — value traded, comparable across price levels. */
  turnover?: number;
  /** When this symbol last printed. Absent until it prints in this session. */
  lastTradeTs?: string;
}

export interface BuildRowsInput {
  symbols: string[];
  top: Record<string, TopOfBook>;
  daily: Record<string, DailyBar>;
  /** Previous session's close per symbol (`lib/prev-close.ts`). */
  prevClose: Record<string, number>;
  /** When each symbol last printed, from the live store's trade stream. */
  lastTradeTs: Record<string, string>;
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
 * from up to `snapshot_interval_sec` ago. `LAST`, `BID` and `ASK` describe the
 * same moment as each other. The rest of the row does not: `volume`,
 * `turnover` and `open` come from a ten-second history poll, and `chg`/
 * `pctChg` are measured against a previous close on a five-minute poll of its
 * own. A row is three clocks, not one — individual prints belong on the Trade
 * Tape (§11).
 *
 * Change is measured from the **previous close**, not from today's open. An
 * open cannot show a gap: a symbol that opened well below yesterday's close
 * and has since recovered a little reads as a gainer against its own open
 * while being down on the day — the wrong answer on the grid, and the wrong
 * answer again on the Movers board that ranks these same rows. `open` stays
 * available as its own column, because traders want both; it is simply no
 * longer the reference. See `lib/prev-close.ts`.
 */
export function buildRows(input: BuildRowsInput): OverviewRow[] {
  const pinned = new Set(input.watchlist);
  const symbols =
    input.filter === "watchlist" ? input.symbols.filter((sym) => pinned.has(sym)) : input.symbols;

  return symbols.map((sym) => {
    const top = input.top[sym];
    const daily = input.daily[sym];
    const last = top?.last;
    const open = daily?.open_price ?? undefined;

    const row: OverviewRow = {
      sym,
      pinned: pinned.has(sym),
      halted: sym in input.halted,
    };

    if (last !== undefined) row.last = last;
    if (top?.bid !== undefined) row.bid = top.bid;
    if (top?.bidSz !== undefined) row.bidSz = top.bidSz;
    if (top?.ask !== undefined) row.ask = top.ask;
    if (top?.askSz !== undefined) row.askSz = top.askSz;
    if (open !== undefined) row.open = open;

    const width = spread(top?.bid, top?.ask);
    if (width !== undefined) row.spread = width;

    const volume = daily?.volume;
    if (volume !== null && volume !== undefined) row.volume = volume;

    const traded = turnover(daily?.volume, daily?.vwap);
    if (traded !== undefined) row.turnover = traded;

    const printed = input.lastTradeTs[sym];
    if (printed !== undefined) row.lastTradeTs = printed;

    // A change figure needs both ends. A symbol with neither a previous close
    // nor an open has no baseline at all, and showing "0.00 (0.00%)" would
    // claim it was flat rather than untraded. A baseline of exactly zero is
    // likewise no basis for a percentage.
    const prevClose = input.prevClose[sym];
    const baseline: ChangeBaseline | undefined =
      prevClose !== undefined ? "prevClose" : open !== undefined ? "open" : undefined;
    const reference = baseline === "prevClose" ? prevClose : open;

    if (last !== undefined && baseline !== undefined && reference !== undefined) {
      row.baseline = baseline;
      row.chg = last - reference;
      if (reference !== 0) row.pctChg = ((last - reference) / reference) * 100;
    }

    return row;
  });
}

/** Column sets per density preset (design §7.5). */
export type OverviewColumn =
  | "star"
  | "symbol"
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
  | "lastTrade"
  | "indic"
  | "indicQty"
  | "imbalance";

const LOBBY_COLUMNS: OverviewColumn[] = ["symbol", "last", "pctChg", "volume"];

/**
 * Ordered in three reading groups rather than by importance:
 *
 *   what happened   symbol, last, chg, %chg
 *   what is there   bid size, bid, ask, ask size, spread
 *   how much        volume, turnover
 *
 * The quote group is laid out inside-out from the price — `BidSz | Bid | Ask |
 * AskSz` — so the two prices sit adjacent in the middle and the spread between
 * them can be read without the eye crossing a size column. A quote without its
 * size is half a quote: a penny wide in a hundred shares and a penny wide in
 * fifty thousand are not the same market, and only the size column says which
 * one this is.
 *
 * The print time comes last, on the far right, because it qualifies the whole
 * row rather than any one figure in it: everything to its left is only as good
 * as the moment it describes.
 */
const FULL_COLUMNS: OverviewColumn[] = [
  "star",
  "symbol",
  "last",
  "chg",
  "pctChg",
  "bidSz",
  "bid",
  "ask",
  "askSz",
  "spread",
  "volume",
  "turnover",
  "lastTrade",
];

/**
 * Lobby drops to four columns and loses the star: an unattended classroom
 * display has nobody to click it, and the space buys larger type instead. It
 * keeps none of the quote detail for the same reason — sizes and spread are
 * for somebody deciding whether to trade, and nobody is doing that from
 * across a room.
 */
/**
 * The quote group, replaced by the auction group during a call phase.
 *
 * Not added alongside: bid, ask, size and spread describe what is
 * *available*, and during a call phase nothing is — they are already dimmed
 * as non-executable (T-M2). The indicative price, the size that would
 * match, and the surplus are what carry meaning at that moment, and they
 * take the same space rather than pushing the grid wider (T-M1).
 *
 * The swap is a mode, not a layout preference: the reader is looking at a
 * different kind of market, and the columns follow.
 */
const AUCTION_QUOTE_COLUMNS: OverviewColumn[] = ["indic", "indicQty", "imbalance"];

const QUOTE_COLUMNS: ReadonlySet<OverviewColumn> = new Set<OverviewColumn>([
  "bidSz",
  "bid",
  "ask",
  "askSz",
  "spread",
]);

export function columnsFor(
  density: "lobby" | "standard" | "dense",
  sessionPhase?: string | null,
): OverviewColumn[] {
  const base = density === "lobby" ? LOBBY_COLUMNS : FULL_COLUMNS;
  if (!sessionPhase?.endsWith("AUCTION")) return base;

  // Lobby swaps rather than adds, and stays at four columns. Its whole
  // rationale is that the space buys larger type for a room to read from a
  // distance; growing it to six during an auction would trade that away at
  // exactly the moment most people are looking. `last` is a pre-auction
  // print and `%Chg` is computed from it, so both are the stale pair worth
  // giving up for the two figures that describe the auction itself.
  if (density === "lobby") {
    return ["symbol", "indic", "imbalance", "volume"];
  }

  const swapped: OverviewColumn[] = [];
  let inserted = false;
  for (const column of base) {
    if (!QUOTE_COLUMNS.has(column)) {
      swapped.push(column);
      continue;
    }
    if (!inserted) {
      swapped.push(...AUCTION_QUOTE_COLUMNS);
      inserted = true;
    }
  }
  return swapped;
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
export function rankMovers(rows: readonly OverviewRow[], tab: MoversTab, limit = 25): OverviewRow[] {
  // Value traded, not share count. A share count ranks whatever is cheapest to
  // the top: a hundred thousand shares of a 2.00 instrument would outrank ten
  // thousand of a 200.00 one, though the second is ten times the event. A
  // symbol whose turnover cannot be computed is dropped rather than ranked at
  // zero, on the same reasoning as the percentage tabs below.
  if (tab === "active") {
    return rows
      .filter((r) => r.turnover !== undefined && r.turnover > 0)
      .sort((a, b) => (b.turnover ?? 0) - (a.turnover ?? 0))
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
export function moverBarFraction(row: OverviewRow, rows: readonly OverviewRow[], tab: MoversTab): number {
  const measure = (r: OverviewRow): number =>
    tab === "active" ? (r.turnover ?? 0) : Math.abs(r.pctChg ?? 0);

  const peak = rows.reduce((max, r) => Math.max(max, measure(r)), 0);
  return peak > 0 ? measure(row) / peak : 0;
}
