import { create } from "zustand";
import type { BookData, DepthData, Side, AuctionResult, AuctionIndicative } from "@/types/index.js";

export interface BookEntry {
  symbol: string;
  bids: { price: number; qty: number; count: number }[];
  asks: { price: number; qty: number; count: number }[];
  depth: DepthData | null;
  lastPrice: number | null;
  lastQty: number | null;
  lastBuyPrice: number | null;
  lastSellPrice: number | null;
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
