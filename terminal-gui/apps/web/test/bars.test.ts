import { describe, expect, it } from "vitest";
import type { DailyBar, PriceSnapshotRow, TradeRow } from "@edumatcher/terminal-types";
import { bucketTrades, dailyToBars, midOf, midpointSeries } from "../src/lib/bars.js";

const trade = (ts: string, price: number, quantity = 100): TradeRow => ({
  ts,
  trade_id: `T-${ts}-${price}`,
  symbol: "AAPL",
  price,
  quantity,
  buy_gateway_id: "GW1",
  sell_gateway_id: "GW2",
});

const at = (minute: number, second = 0) =>
  `2026-07-30T09:${String(minute).padStart(2, "0")}:${String(second).padStart(2, "0")}.000Z`;

const daily = (date: string, over: Partial<DailyBar> = {}): DailyBar => ({
  date,
  symbol: "AAPL",
  open_price: 100,
  high_price: 105,
  low_price: 99,
  close_price: 103,
  vwap: 102,
  volume: 1000,
  trade_count: 10,
  ...over,
});

const snapshot = (
  ts: string,
  mid: number | null,
  over: Partial<PriceSnapshotRow> = {},
): PriceSnapshotRow => ({
  ts,
  symbol: "AAPL",
  mid_price: mid,
  best_bid: null,
  best_ask: null,
  pct_change: null,
  ...over,
});

describe("bucketTrades", () => {
  it("takes open from the first print and close from the last", () => {
    const { bars } = bucketTrades([trade(at(0, 5), 100), trade(at(0, 30), 104), trade(at(0, 55), 101)], 60);

    expect(bars).toHaveLength(1);
    expect(bars[0]).toMatchObject({ open: 100, close: 101, high: 104, low: 100 });
  });

  it("splits prints across bucket boundaries", () => {
    const { bars } = bucketTrades([trade(at(0), 100), trade(at(1), 101), trade(at(2), 102)], 60);
    expect(bars.map((b) => b.close)).toEqual([100, 101, 102]);
  });

  it("groups a five-minute window into one bar", () => {
    const { bars } = bucketTrades([trade(at(0), 100), trade(at(3), 105), trade(at(4), 102)], 300);
    expect(bars).toHaveLength(1);
    expect(bars[0]).toMatchObject({ open: 100, high: 105, close: 102 });
  });

  it("aligns buckets to the epoch, not to the first trade", () => {
    // Two tabs opening at different moments must draw identical candles.
    const early = bucketTrades([trade(at(0, 30), 100)], 60).bars[0]?.time;
    const late = bucketTrades([trade(at(0, 10), 100), trade(at(0, 30), 100)], 60).bars[0]?.time;
    expect(early).toBe(late);
  });

  it("sums volume within a bucket", () => {
    const { volume } = bucketTrades([trade(at(0), 100, 40), trade(at(0, 30), 101, 60)], 60);
    expect(volume[0]?.value).toBe(100);
  });

  it("emits no bar for an interval with no trades", () => {
    // A flat synthetic bar would imply the price was held there.
    const { bars } = bucketTrades([trade(at(0), 100), trade(at(5), 101)], 60);
    expect(bars).toHaveLength(2);
  });

  it("returns bars oldest first", () => {
    const { bars } = bucketTrades([trade(at(5), 101), trade(at(0), 100)], 60);
    expect(bars.map((b) => b.time)).toEqual([...bars.map((b) => b.time)].sort((a, b) => a - b));
  });

  it("skips a print with an unparseable timestamp rather than dropping the series", () => {
    const { bars } = bucketTrades([trade("not a date", 100), trade(at(0), 101)], 60);
    expect(bars).toHaveLength(1);
    expect(bars[0]?.close).toBe(101);
  });

  it("returns nothing for a nonsensical bucket width", () => {
    expect(bucketTrades([trade(at(0), 100)], 0).bars).toEqual([]);
  });
});

describe("dailyToBars", () => {
  it("maps rollup rows to bars at UTC midnight", () => {
    const { bars } = dailyToBars([daily("2026-07-30")]);
    expect(bars[0]).toMatchObject({ open: 100, high: 105, low: 99, close: 103 });
    expect(bars[0]?.time).toBe(Date.parse("2026-07-30T00:00:00Z") / 1000);
  });

  it("orders by date regardless of the order rows arrive in", () => {
    const { bars } = dailyToBars([daily("2026-07-31"), daily("2026-07-29")]);
    expect(bars[0]?.time).toBeLessThan(bars[1]!.time);
  });

  it("skips a date the symbol did not trade", () => {
    // pm-stats still writes the row; drawing it at zero would be a lie.
    const { bars } = dailyToBars([daily("2026-07-30", { open_price: null, close_price: null })]);
    expect(bars).toEqual([]);
  });

  it("falls back to open/close when high or low is missing", () => {
    const { bars } = dailyToBars([daily("2026-07-30", { high_price: null, low_price: null })]);
    expect(bars[0]).toMatchObject({ high: 103, low: 100 });
  });

  it("omits a volume point when the row has none, rather than plotting zero", () => {
    const { volume } = dailyToBars([daily("2026-07-30", { volume: null })]);
    expect(volume).toEqual([]);
  });
});

describe("midpointSeries", () => {
  const live = [{ time: 1_000, value: 150.5 }];

  it("keeps recorded history before the live tail starts", () => {
    const series = midpointSeries([snapshot("1970-01-01T00:10:00Z", 149)], live);
    expect(series.historical).toHaveLength(1);
    expect(series.liveOnly).toBe(false);
  });

  it("trims history that overlaps the live tail, so the line does not fork", () => {
    const series = midpointSeries(
      [snapshot("1970-01-01T00:10:00Z", 149), snapshot("1970-01-01T00:30:00Z", 151)],
      live,
    );
    expect(series.historical.map((p) => p.value)).toEqual([149]);
  });

  it("reports live-only when nothing was recorded for the window", () => {
    const series = midpointSeries([], live);
    expect(series.liveOnly).toBe(true);
    expect(series.live).toEqual(live);
  });

  it("derives the midpoint from the recorded quote when mid_price is null", () => {
    const series = midpointSeries(
      [snapshot("1970-01-01T00:01:00Z", null, { best_bid: 100, best_ask: 102 })],
      [],
    );
    expect(series.historical[0]?.value).toBe(101);
  });

  it("skips a row with neither a mid nor both sides of the quote", () => {
    const series = midpointSeries([snapshot("1970-01-01T00:01:00Z", null, { best_bid: 100 })], []);
    expect(series.historical).toEqual([]);
  });

  it("sorts history even if the endpoint returned it out of order", () => {
    const series = midpointSeries(
      [snapshot("1970-01-01T00:05:00Z", 151), snapshot("1970-01-01T00:01:00Z", 149)],
      [],
    );
    expect(series.historical.map((p) => p.value)).toEqual([149, 151]);
  });
});

describe("midOf", () => {
  it("averages the two sides", () => {
    expect(midOf(150.1, 150.3)).toBeCloseTo(150.2, 6);
  });

  it("is absent when either side is missing, since a one-sided book has no midpoint", () => {
    expect(midOf(150.1, undefined)).toBeUndefined();
    expect(midOf(undefined, 150.3)).toBeUndefined();
  });
});
