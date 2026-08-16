/**
 * Market Overview row model (§10.3).
 *
 * Kept as pure functions over plain data — no React, no store access — so the
 * change-% definition and the halt/auction precedence are testable without
 * mounting a table, and so the board can be re-derived from a throttled
 * snapshot rather than on every one of the ~200 book snapshots per second a
 * 100-symbol venue produces (§17.3.4).
 */
import type { BookEntry } from "@/store/useBookStore.js";
import type { DailyStat, HaltEntry, SessionState, Symbol } from "@/types/index.js";

export interface MarketRow {
  symbol: string;
  tickDecimals: number;
  bid: number | null;
  ask: number | null;
  last: number | null;
  /** Today's open, from the daily rollup; null before the first print. */
  open: number | null;
  /** (last − open) / open × 100, or null when either side is unusable. */
  changePct: number | null;
  /** Daily rollup volume topped up with prints seen since the last poll. */
  volume: number | null;
  halted: boolean;
  haltLevel: string | null;
  /** Indicative or final uncross, shown while the venue is in a call phase. */
  auctionPrice: number | null;
  auctionIndicative: boolean;
  watched: boolean;
}

/**
 * Change against **today's open** — the canonical definition (§10.3), not
 * against the previous close. Returns null rather than 0 when the open is
 * missing or zero, so the cell renders "—" instead of a fabricated 0.00%.
 */
export function changePct(last: number | null, open: number | null): number | null {
  if (last === null || open === null || open === 0) return null;
  return ((last - open) / open) * 100;
}

export interface BuildRowsInput {
  symbols: Symbol[];
  books: Record<string, BookEntry>;
  daily: Record<string, DailyStat>;
  halts: Record<string, HaltEntry>;
  watchlist: readonly string[];
}

export function buildMarketRows({
  symbols,
  books,
  daily,
  halts,
  watchlist,
}: BuildRowsInput): MarketRow[] {
  const watched = new Set(watchlist);
  return symbols.map((meta) => {
    const book = books[meta.symbol];
    const day = daily[meta.symbol];
    const halt = halts[meta.symbol];
    const last = book?.lastPrice ?? day?.close_price ?? null;
    const open = day?.open_price ?? null;

    const dayVolume = day?.volume ?? null;
    const live = book?.liveVolume ?? 0;
    const volume = dayVolume === null ? (live > 0 ? live : null) : dayVolume + live;

    return {
      symbol: meta.symbol,
      // The book snapshot carries its own tick_decimals and is the fresher of
      // the two; reference data is the fallback before the first snapshot.
      tickDecimals: book?.tickDecimals ?? meta.tick_decimals ?? 2,
      bid: book?.bids[0]?.price ?? null,
      ask: book?.asks[0]?.price ?? null,
      last,
      open,
      changePct: changePct(last, open),
      volume,
      halted: halt !== undefined,
      haltLevel: halt?.level ?? null,
      auctionPrice: book?.auction?.eqPrice ?? null,
      auctionIndicative: book?.auction?.indicative ?? false,
      watched: watched.has(meta.symbol),
    };
  });
}

/** Case-insensitive substring match on the symbol name (§10.4). */
export function filterRows(rows: MarketRow[], query: string): MarketRow[] {
  const q = query.trim().toUpperCase();
  if (q === "") return rows;
  return rows.filter((r) => r.symbol.includes(q));
}

/** True while the venue is in a call phase, when auction badges are shown. */
export function isAuctionPhase(phase: SessionState): boolean {
  return phase === "OPENING_AUCTION" || phase === "CLOSING_AUCTION";
}
