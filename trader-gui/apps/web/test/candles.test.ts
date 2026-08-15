import { describe, it, expect } from "vitest";
import {
  candlesToLine,
  dailyToCandles,
  foldTick,
  isIntraday,
  tradesToCandles,
  type Candle,
  type Tick,
} from "@/lib/candles";
import type { DailyStat } from "@/types/index";

const tick = (timestamp: number, price: number, quantity: number): Tick => ({
  timestamp,
  price,
  quantity,
});

function daily(partial: Partial<DailyStat> & { symbol: string; date: string }): DailyStat {
  return {
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

describe("isIntraday", () => {
  it("is true only for trade-derived timeframes", () => {
    expect(isIntraday("1m")).toBe(true);
    expect(isIntraday("5m")).toBe(true);
    expect(isIntraday("1h")).toBe(true);
    expect(isIntraday("1D")).toBe(false);
    expect(isIntraday("All")).toBe(false);
  });
});

describe("tradesToCandles", () => {
  it("buckets ticks into OHLCV bars for the timeframe", () => {
    // Two ticks inside the same 1m bucket (t=0..59), one in the next.
    const candles = tradesToCandles(
      [tick(10, 100, 5), tick(40, 102, 3), tick(70, 101, 2)],
      "1m",
    );
    expect(candles).toHaveLength(2);
    expect(candles[0]).toEqual({ time: 0, open: 100, high: 102, low: 100, close: 102, volume: 8 });
    expect(candles[1]).toEqual({ time: 60, open: 101, high: 101, low: 101, close: 101, volume: 2 });
  });

  it("sorts unsorted input and stays ascending by time", () => {
    const candles = tradesToCandles([tick(120, 5, 1), tick(10, 4, 1), tick(65, 6, 1)], "1m");
    expect(candles.map((c) => c.time)).toEqual([0, 60, 120]);
  });

  it("tracks the high and low across a bucket", () => {
    const candles = tradesToCandles(
      [tick(1, 100, 1), tick(2, 110, 1), tick(3, 90, 1), tick(4, 105, 1)],
      "5m",
    );
    expect(candles[0]).toMatchObject({ open: 100, high: 110, low: 90, close: 105, volume: 4 });
  });

  it("returns nothing for no ticks", () => {
    expect(tradesToCandles([], "1h")).toEqual([]);
  });
});

describe("dailyToCandles", () => {
  it("maps rollup rows to candles and drops half-formed rows", () => {
    const candles = dailyToCandles([
      daily({ symbol: "AAPL", date: "2026-08-12", open_price: 100, high_price: 110, low_price: 95, close_price: 108, volume: 5000 }),
      // No close → dropped rather than rendered as a flat bar.
      daily({ symbol: "AAPL", date: "2026-08-13", open_price: 108 }),
    ]);
    expect(candles).toHaveLength(1);
    expect(candles[0]).toEqual({
      time: "2026-08-12",
      open: 100,
      high: 110,
      low: 95,
      close: 108,
      volume: 5000,
    });
  });

  it("falls back to open when high/low are missing", () => {
    const candles = dailyToCandles([
      daily({ symbol: "AAPL", date: "2026-08-12", open_price: 100, close_price: 100 }),
    ]);
    expect(candles[0]).toMatchObject({ high: 100, low: 100 });
  });

  it("sorts by date ascending", () => {
    const candles = dailyToCandles([
      daily({ symbol: "AAPL", date: "2026-08-13", open_price: 1, close_price: 2 }),
      daily({ symbol: "AAPL", date: "2026-08-11", open_price: 1, close_price: 2 }),
    ]);
    expect(candles.map((c) => c.time)).toEqual(["2026-08-11", "2026-08-13"]);
  });
});

describe("foldTick", () => {
  const base: Candle = { time: 60, open: 100, high: 105, low: 99, close: 102, volume: 10 };

  it("merges a tick that falls in the same bucket", () => {
    const { bar, isNew } = foldTick(base, tick(90, 108, 4), "1m");
    expect(isNew).toBe(false);
    expect(bar).toEqual({ time: 60, open: 100, high: 108, low: 99, close: 108, volume: 14 });
  });

  it("lowers the low when the tick prints below it", () => {
    const { bar } = foldTick(base, tick(70, 95, 1), "1m");
    expect(bar.low).toBe(95);
    expect(bar.close).toBe(95);
  });

  it("opens a fresh bar when the tick crosses into the next bucket", () => {
    const { bar, isNew } = foldTick(base, tick(125, 103, 7), "1m");
    expect(isNew).toBe(true);
    expect(bar).toEqual({ time: 120, open: 103, high: 103, low: 103, close: 103, volume: 7 });
  });

  it("opens the first bar when there is no prior bar", () => {
    const { bar, isNew } = foldTick(null, tick(30, 50, 2), "1m");
    expect(isNew).toBe(true);
    expect(bar).toEqual({ time: 0, open: 50, high: 50, low: 50, close: 50, volume: 2 });
  });
});

describe("candlesToLine", () => {
  it("projects each candle onto its close", () => {
    const line = candlesToLine([
      { time: 0, open: 1, high: 2, low: 1, close: 1.5, volume: 3 },
      { time: 60, open: 1.5, high: 3, low: 1.4, close: 2.8, volume: 4 },
    ]);
    expect(line).toEqual([
      { time: 0, value: 1.5 },
      { time: 60, value: 2.8 },
    ]);
  });
});
