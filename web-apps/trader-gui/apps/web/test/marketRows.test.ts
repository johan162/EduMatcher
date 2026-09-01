import { describe, it, expect, beforeEach } from "vitest";
import {
  buildMarketRows,
  changePct,
  filterRows,
  isAuctionPhase,
  type MarketRow,
} from "@/lib/marketRows";
import { useBookStore } from "@/store/useBookStore";
import type { BookEntry } from "@/store/useBookStore";
import type { DailyStat, HaltEntry, Symbol } from "@/types/index";

const SYMBOLS: Symbol[] = [
  { symbol: "AAPL", tick_decimals: 2, prev_close: 149, collar_reference_price: null, level: null },
  { symbol: "MSFT", tick_decimals: 2, prev_close: 400, collar_reference_price: null, level: null },
];

function book(partial: Partial<BookEntry>): BookEntry {
  return {
    symbol: "AAPL",
    bids: [],
    asks: [],
    depth: null,
    lastPrice: null,
    lastQty: null,
    lastBuyPrice: null,
    lastSellPrice: null,
    recentTrades: [],
    liveVolume: 0,
    tickDecimals: null,
    auction: null,
    updatedAt: 0,
    ...partial,
  };
}

function daily(partial: Partial<DailyStat> & { symbol: string }): DailyStat {
  return {
    date: "2026-08-12",
    open_price: null,
    high_price: null,
    low_price: null,
    close_price: null,
    open_bid: null,
    open_ask: null,
    close_bid: null,
    close_ask: null,
    volume: 0,
    trade_count: 0,
    turnover: 0,
    vwap: null,
    largest_trade_qty: null,
    largest_trade_price: null,
    tick_decimals: 2,
    ...partial,
  };
}

const EMPTY = { books: {}, daily: {}, halts: {}, watchlist: [] as string[] };
const row = (rows: MarketRow[], symbol: string) => rows.find((r) => r.symbol === symbol)!;

describe("changePct", () => {
  it("measures against today's open, not the previous close", () => {
    // §10.3 canonical definition — 149 is prev_close and must not be used.
    expect(changePct(151.5, 150)).toBeCloseTo(1, 10);
    expect(changePct(148.5, 150)).toBeCloseTo(-1, 10);
  });

  it("returns null rather than a fabricated 0.00%", () => {
    expect(changePct(150, null)).toBeNull();
    expect(changePct(null, 150)).toBeNull();
    // A zero open would divide by zero; "—" is the honest answer.
    expect(changePct(150, 0)).toBeNull();
  });
});

describe("buildMarketRows", () => {
  it("renders a symbol with no market data yet as all-blank, not zero", () => {
    const rows = buildMarketRows({ ...EMPTY, symbols: SYMBOLS });
    expect(rows).toHaveLength(2);
    expect(row(rows, "AAPL")).toMatchObject({
      bid: null,
      ask: null,
      last: null,
      changePct: null,
      volume: null,
      halted: false,
    });
  });

  it("takes top-of-book from the first level and change % from the rollup", () => {
    const rows = buildMarketRows({
      ...EMPTY,
      symbols: SYMBOLS,
      books: {
        AAPL: book({
          bids: [
            { price: 150.0, qty: 100, count: 1 },
            { price: 149.9, qty: 50, count: 1 },
          ],
          asks: [{ price: 150.2, qty: 80, count: 2 }],
          lastPrice: 150.1,
        }),
      },
      daily: { AAPL: daily({ symbol: "AAPL", open_price: 148, volume: 10_000 }) },
    });
    expect(row(rows, "AAPL")).toMatchObject({
      bid: 150.0,
      ask: 150.2,
      last: 150.1,
      open: 148,
      volume: 10_000,
    });
    expect(row(rows, "AAPL").changePct).toBeCloseTo(1.4189, 3);
  });

  it("prefers the book's tick_decimals over reference data", () => {
    const rows = buildMarketRows({
      ...EMPTY,
      symbols: SYMBOLS,
      books: { AAPL: book({ tickDecimals: 4 }) },
    });
    expect(row(rows, "AAPL").tickDecimals).toBe(4);
    expect(row(rows, "MSFT").tickDecimals).toBe(2);
  });

  it("falls back to the rollup close when no book snapshot has arrived", () => {
    const rows = buildMarketRows({
      ...EMPTY,
      symbols: SYMBOLS,
      daily: { AAPL: daily({ symbol: "AAPL", open_price: 100, close_price: 110 }) },
    });
    expect(row(rows, "AAPL").last).toBe(110);
    expect(row(rows, "AAPL").changePct).toBeCloseTo(10, 10);
  });

  it("tops the rollup volume up with prints seen since the last poll", () => {
    const rows = buildMarketRows({
      ...EMPTY,
      symbols: SYMBOLS,
      books: { AAPL: book({ liveVolume: 250 }) },
      daily: { AAPL: daily({ symbol: "AAPL", volume: 10_000 }) },
    });
    expect(row(rows, "AAPL").volume).toBe(10_250);
  });

  it("shows live volume alone when the rollup is unavailable", () => {
    const rows = buildMarketRows({
      ...EMPTY,
      symbols: SYMBOLS,
      books: { AAPL: book({ liveVolume: 250 }), MSFT: book({ symbol: "MSFT" }) },
    });
    expect(row(rows, "AAPL").volume).toBe(250);
    expect(row(rows, "MSFT").volume).toBeNull();
  });

  it("carries the halt level, and null for an ADMIN halt", () => {
    const halts: Record<string, HaltEntry> = {
      AAPL: { symbol: "AAPL", level: "L2" },
      MSFT: { symbol: "MSFT", level: null },
    };
    const rows = buildMarketRows({ ...EMPTY, symbols: SYMBOLS, halts });
    expect(row(rows, "AAPL")).toMatchObject({ halted: true, haltLevel: "L2" });
    expect(row(rows, "MSFT")).toMatchObject({ halted: true, haltLevel: null });
  });

  it("distinguishes an indicative uncross from a final one", () => {
    const rows = buildMarketRows({
      ...EMPTY,
      symbols: SYMBOLS,
      books: {
        AAPL: book({
          auction: {
            eqPrice: 150.5,
            eqQty: 5000,
            imbalanceSide: "BUY",
            imbalanceQty: 500,
            indicative: true,
            source: "engine",
          },
        }),
      },
    });
    expect(row(rows, "AAPL")).toMatchObject({
      auctionPrice: 150.5,
      auctionIndicative: true,
    });
  });

  it("marks watchlist membership", () => {
    const rows = buildMarketRows({ ...EMPTY, symbols: SYMBOLS, watchlist: ["MSFT"] });
    expect(row(rows, "AAPL").watched).toBe(false);
    expect(row(rows, "MSFT").watched).toBe(true);
  });
});

describe("filterRows", () => {
  const rows = buildMarketRows({ ...EMPTY, symbols: SYMBOLS });

  it("matches case-insensitively on a substring", () => {
    expect(filterRows(rows, "aap").map((r) => r.symbol)).toEqual(["AAPL"]);
    expect(filterRows(rows, "S").map((r) => r.symbol)).toEqual(["MSFT"]);
  });

  it("returns everything for a blank query", () => {
    expect(filterRows(rows, "   ")).toHaveLength(2);
  });
});

describe("isAuctionPhase", () => {
  it("is true only during a call phase", () => {
    expect(isAuctionPhase("OPENING_AUCTION")).toBe(true);
    expect(isAuctionPhase("CLOSING_AUCTION")).toBe(true);
    expect(isAuctionPhase("CONTINUOUS")).toBe(false);
    expect(isAuctionPhase("PRE_OPEN")).toBe(false);
    expect(isAuctionPhase("CLOSED")).toBe(false);
  });
});

describe("live volume accumulation", () => {
  beforeEach(() => useBookStore.setState({ books: {} }));

  const trade = (symbol: string, quantity: number) => ({
    id: `000001-000000${quantity.toString().padStart(3, "0")}`,
    run_seq: 1,
    symbol,
    buy_order_id: "b",
    sell_order_id: "s",
    buy_gateway_id: "GW01",
    sell_gateway_id: "GW02",
    price: 150,
    quantity,
    aggressor_side: "BUY" as const,
    timestamp: 0,
    tick_decimals: 2,
  });

  it("sums prints per symbol and resets when a fresh rollup lands", () => {
    const store = useBookStore.getState();
    store.recordTrade(trade("AAPL", 100));
    store.recordTrade(trade("AAPL", 50));
    store.recordTrade(trade("MSFT", 10));
    expect(useBookStore.getState().books["AAPL"]!.liveVolume).toBe(150);

    useBookStore.getState().resetLiveVolume();
    expect(useBookStore.getState().books["AAPL"]!.liveVolume).toBe(0);
    expect(useBookStore.getState().books["MSFT"]!.liveVolume).toBe(0);
    // The tape itself survives the reset — only the accumulator is spent.
    expect(useBookStore.getState().books["AAPL"]!.recentTrades).toHaveLength(2);
  });

  it("leaves the store untouched when nothing has accumulated", () => {
    useBookStore.getState().recordTrade(trade("AAPL", 100));
    useBookStore.getState().resetLiveVolume();
    const before = useBookStore.getState().books;
    useBookStore.getState().resetLiveVolume();
    expect(useBookStore.getState().books).toBe(before);
  });
});
