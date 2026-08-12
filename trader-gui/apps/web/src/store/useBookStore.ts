import { create } from "zustand";
import type {
  BookData,
  DepthData,
  Side,
  AuctionResult,
  AuctionIndicative,
  TradeData,
} from "@/types/index.js";

/** How many prints per symbol the tape keeps in memory. */
const RECENT_TRADES_LIMIT = 50;

export interface BookEntry {
  symbol: string;
  bids: { price: number; qty: number; count: number }[];
  asks: { price: number; qty: number; count: number }[];
  depth: DepthData | null;
  lastPrice: number | null;
  lastQty: number | null;
  lastBuyPrice: number | null;
  lastSellPrice: number | null;
  /** Most recent prints first, bounded to RECENT_TRADES_LIMIT. */
  recentTrades: TradeData[];
  /** Decimals for price rendering, carried on the book snapshot. */
  tickDecimals: number | null;
  auction: {
    eqPrice: number | null;
    eqQty: number;
    imbalanceSide: Side | null;
    imbalanceQty: number;
    /** true if this is a live indicative from the engine */
    indicative: boolean;
    /** "engine" = from auction channel; "client" = local approximation */
    source: "engine" | "client";
  } | null;
  updatedAt: number; // Unix ms
}

interface BookStore {
  books: Record<string, BookEntry>;
  updateBook: (symbol: string, data: BookData) => void;
  updateDepth: (symbol: string, data: DepthData) => void;
  updateLastPrice: (symbol: string, price: number, qty: number) => void;
  /** Fold one public print into the tape and the last-price fields. */
  recordTrade: (data: TradeData) => void;
  /** Drop the cached tape for a symbol after a `trades.reset` (§26.3.2). */
  clearRecentTrades: (symbol: string) => void;
  /** Drop all cached state for a symbol after an unrepairable gap. */
  clearSymbol: (symbol: string) => void;
  /**
   * Accepts both a final AuctionResult (type:"auction") and a running
   * AuctionIndicative (type:"auction.indicative"). opts.indicative flags the latter.
   */
  updateAuction: (
    symbol: string,
    data: AuctionResult | AuctionIndicative,
    opts?: { indicative?: boolean },
  ) => void;
}

function defaultEntry(symbol: string): BookEntry {
  return {
    symbol,
    bids: [],
    asks: [],
    depth: null,
    lastPrice: null,
    lastQty: null,
    lastBuyPrice: null,
    lastSellPrice: null,
    recentTrades: [],
    tickDecimals: null,
    auction: null,
    updatedAt: 0,
  };
}

export const useBookStore = create<BookStore>((set, get) => ({
  books: {},

  updateBook: (symbol, data) => {
    const prev = get().books[symbol] ?? defaultEntry(symbol);
    set((s) => ({
      books: {
        ...s.books,
        [symbol]: {
          ...prev,
          bids: data.bids,
          asks: data.asks,
          lastPrice: data.last_price,
          lastQty: data.last_qty,
          lastBuyPrice: data.last_buy_price,
          lastSellPrice: data.last_sell_price,
          tickDecimals: data.tick_decimals ?? prev.tickDecimals,
          updatedAt: Date.now(),
        },
      },
    }));
  },

  updateDepth: (symbol, data) => {
    set((s) => ({
      books: {
        ...s.books,
        [symbol]: {
          ...(s.books[symbol] ?? defaultEntry(symbol)),
          depth: data,
          updatedAt: Date.now(),
        },
      },
    }));
  },

  updateLastPrice: (symbol, price, qty) => {
    set((s) => ({
      books: {
        ...s.books,
        [symbol]: {
          ...(s.books[symbol] ?? defaultEntry(symbol)),
          lastPrice: price,
          lastQty: qty,
          updatedAt: Date.now(),
        },
      },
    }));
  },

  recordTrade: (data) => {
    const symbol = data.symbol;
    set((s) => {
      const prev = s.books[symbol] ?? defaultEntry(symbol);
      return {
        books: {
          ...s.books,
          [symbol]: {
            ...prev,
            lastPrice: data.price,
            lastQty: data.quantity,
            tickDecimals: data.tick_decimals ?? prev.tickDecimals,
            recentTrades: [data, ...prev.recentTrades].slice(0, RECENT_TRADES_LIMIT),
            updatedAt: Date.now(),
          },
        },
      };
    });
  },

  clearRecentTrades: (symbol) => {
    set((s) => {
      const prev = s.books[symbol];
      if (!prev) return s;
      return {
        books: { ...s.books, [symbol]: { ...prev, recentTrades: [] } },
      };
    });
  },

  clearSymbol: (symbol) => {
    set((s) => {
      if (!s.books[symbol]) return s;
      const next = { ...s.books };
      delete next[symbol];
      return { books: next };
    });
  },

  updateAuction: (symbol, data, opts) => {
    const indicative = opts?.indicative ?? false;
    const entry = get().books[symbol] ?? defaultEntry(symbol);
    set((s) => ({
      books: {
        ...s.books,
        [symbol]: {
          ...entry,
          auction: {
            eqPrice: data.eq_price,
            eqQty: data.eq_qty,
            imbalanceSide: data.imbalance_side,
            imbalanceQty: data.imbalance_qty,
            indicative,
            source: "engine",
          },
          updatedAt: Date.now(),
        },
      },
    }));
  },
}));
