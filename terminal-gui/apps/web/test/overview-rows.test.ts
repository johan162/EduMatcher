import { describe, expect, it } from "vitest";
import type { DailyBar } from "@edumatcher/terminal-types";
import { buildRows, columnsFor, type BuildRowsInput } from "../src/lib/overview-rows.js";

const bar = (symbol: string, over: Partial<DailyBar> = {}): DailyBar => ({
  date: "2026-07-30",
  symbol,
  open_price: 149.7,
  high_price: 152.05,
  low_price: 148.1,
  close_price: 150.12,
  vwap: 149.94,
  volume: 184300,
  trade_count: 1204,
  ...over,
});

const input = (over: Partial<BuildRowsInput> = {}): BuildRowsInput => ({
  symbols: ["AAPL"],
  top: {},
  daily: {},
  halted: {},
  watchlist: [],
  filter: "all",
  ...over,
});

const only = (over: Partial<BuildRowsInput>) => buildRows(input(over))[0];

describe("last price", () => {
  it("reads the last price off the same frame as bid and ask", () => {
    // One frame for all three, so every figure in a row describes the same
    // moment rather than mixing a trade-instant price with an older spread.
    const row = only({ top: { AAPL: { last: 151.5, bid: 151.4, ask: 151.6 } } });
    expect(row?.last).toBe(151.5);
    expect(row?.bid).toBe(151.4);
  });

  it("leaves last absent for a symbol that has never traded", () => {
    expect(only({ top: { AAPL: { bid: 1, ask: 2 } } })?.last).toBeUndefined();
  });
});

describe("change columns", () => {
  it("computes change and percent against today's open", () => {
    const row = only({ top: { AAPL: { last: 150.12 } }, daily: { AAPL: bar("AAPL") } });
    expect(row?.chg).toBeCloseTo(0.42, 5);
    expect(row?.pctChg).toBeCloseTo(0.2806, 3);
  });

  it("goes negative below the open", () => {
    const row = only({ top: { AAPL: { last: 148.0 } }, daily: { AAPL: bar("AAPL") } });
    expect(row?.chg).toBeLessThan(0);
    expect(row?.pctChg).toBeLessThan(0);
  });

  it("leaves both absent when the symbol has not traded today", () => {
    // No daily row means no open. Reporting 0.00 would claim it was flat
    // rather than untraded.
    const row = only({ top: { AAPL: { last: 150.12 } } });
    expect(row?.chg).toBeUndefined();
    expect(row?.pctChg).toBeUndefined();
  });

  it("leaves both absent when no price is known yet", () => {
    const row = only({ daily: { AAPL: bar("AAPL") } });
    expect(row?.chg).toBeUndefined();
  });

  it("reports change but not a percentage against an open of zero", () => {
    const row = only({
      top: { AAPL: { last: 5 } },
      daily: { AAPL: bar("AAPL", { open_price: 0 }) },
    });
    expect(row?.chg).toBe(5);
    expect(row?.pctChg).toBeUndefined();
  });

  it("treats a null open from the history row as absent", () => {
    const row = only({
      top: { AAPL: { last: 5 } },
      daily: { AAPL: bar("AAPL", { open_price: null }) },
    });
    expect(row?.chg).toBeUndefined();
  });
});

describe("volume", () => {
  it("comes from the daily row, not from observed trades", () => {
    expect(only({ daily: { AAPL: bar("AAPL") } })?.volume).toBe(184300);
  });

  it("is absent rather than zero when the history row has none", () => {
    // Zero volume and unknown volume are different claims.
    expect(only({ daily: { AAPL: bar("AAPL", { volume: null }) } })?.volume).toBeUndefined();
  });
});

describe("halt badge", () => {
  it("marks a symbol the STATE stream reported halted", () => {
    expect(only({ halted: { AAPL: {} } })?.halted).toBe(true);
  });

  it("leaves other symbols unmarked", () => {
    expect(only({ halted: { TSLA: {} } })?.halted).toBe(false);
  });
});

describe("watchlist", () => {
  const three = { symbols: ["AAPL", "MSFT", "TSLA"] };

  it("marks pinned symbols without hiding the rest in All view", () => {
    const rows = buildRows(input({ ...three, watchlist: ["MSFT"] }));
    expect(rows.map((r) => r.pinned)).toEqual([false, true, false]);
  });

  it("shows only pinned symbols under the watchlist filter", () => {
    const rows = buildRows(input({ ...three, watchlist: ["TSLA", "AAPL"], filter: "watchlist" }));
    expect(rows.map((r) => r.sym)).toEqual(["AAPL", "TSLA"]);
  });

  it("keeps the gateway's symbol order rather than the pinning order", () => {
    // Otherwise rows would jump around as a viewer pins and unpins.
    const rows = buildRows(input({ ...three, watchlist: ["TSLA", "AAPL"], filter: "watchlist" }));
    expect(rows.map((r) => r.sym)).toEqual(["AAPL", "TSLA"]);
  });

  it("yields nothing when the filter is on and nothing is pinned", () => {
    expect(buildRows(input({ ...three, filter: "watchlist" }))).toEqual([]);
  });

  it("ignores a pinned symbol the exchange no longer lists", () => {
    const rows = buildRows(input({ ...three, watchlist: ["DELISTED"], filter: "watchlist" }));
    expect(rows).toEqual([]);
  });
});

describe("column sets", () => {
  it("drops to four columns for an unattended lobby display", () => {
    expect(columnsFor("lobby")).toEqual(["symbol", "last", "pctChg", "volume"]);
  });

  it("omits the star in lobby, where there is nobody to click it", () => {
    expect(columnsFor("lobby")).not.toContain("star");
  });

  it("shows the full set at standard and dense", () => {
    expect(columnsFor("standard")).toEqual(columnsFor("dense"));
    expect(columnsFor("standard")).toContain("bid");
    expect(columnsFor("standard")).toContain("star");
  });
});
