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
  prevClose: {},
  lastTradeTs: {},
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
  it("computes change and percent against the previous close", () => {
    const row = only({
      top: { AAPL: { last: 150.12 } },
      daily: { AAPL: bar("AAPL") },
      prevClose: { AAPL: 148.0 },
    });
    expect(row?.chg).toBeCloseTo(2.12, 5);
    expect(row?.pctChg).toBeCloseTo(1.4324, 3);
    expect(row?.baseline).toBe("prevClose");
  });

  it("reports a symbol that gapped down and recovered as down on the day", () => {
    // The whole reason the baseline moved. Opening at 142.00 after a 149.70
    // close and trading back to 143.50 is +1.06% against the open and -4.14%
    // against the close — and only the second is the day's move. Against the
    // open this row would read green and rank onto the Gainers board.
    const row = only({
      top: { AAPL: { last: 143.5 } },
      daily: { AAPL: bar("AAPL", { open_price: 142.0 }) },
      prevClose: { AAPL: 149.7 },
    });
    expect(row?.chg).toBeLessThan(0);
    expect(row?.pctChg).toBeCloseTo(-4.1416, 3);
  });

  it("keeps the open as its own figure rather than as the baseline", () => {
    const row = only({
      top: { AAPL: { last: 143.5 } },
      daily: { AAPL: bar("AAPL", { open_price: 142.0 }) },
      prevClose: { AAPL: 149.7 },
    });
    expect(row?.open).toBe(142.0);
  });

  it("falls back to the open when no previous close is on record", () => {
    // A symbol listed today, or dormant longer than the lookback window.
    const row = only({ top: { AAPL: { last: 150.12 } }, daily: { AAPL: bar("AAPL") } });
    expect(row?.chg).toBeCloseTo(0.42, 5);
    expect(row?.baseline).toBe("open");
  });

  it("leaves both absent when there is no baseline at all", () => {
    // No daily row and no previous close. Reporting 0.00 would claim it was
    // flat rather than untraded.
    const row = only({ top: { AAPL: { last: 150.12 } } });
    expect(row?.chg).toBeUndefined();
    expect(row?.pctChg).toBeUndefined();
    expect(row?.baseline).toBeUndefined();
  });

  it("leaves both absent when no price is known yet", () => {
    const row = only({ daily: { AAPL: bar("AAPL") }, prevClose: { AAPL: 148 } });
    expect(row?.chg).toBeUndefined();
    expect(row?.baseline).toBeUndefined();
  });

  it("reports change but not a percentage against a baseline of zero", () => {
    const row = only({ top: { AAPL: { last: 5 } }, prevClose: { AAPL: 0 } });
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

describe("quote columns", () => {
  it("carries the size resting at each side of the touch", () => {
    const row = only({ top: { AAPL: { bid: 151.4, bidSz: 1200, ask: 151.6, askSz: 800 } } });
    expect(row?.bidSz).toBe(1200);
    expect(row?.askSz).toBe(800);
  });

  it("computes the spread from the same frame as the prices", () => {
    const row = only({ top: { AAPL: { bid: 151.4, ask: 151.6 } } });
    expect(row?.spread).toBeCloseTo(0.2, 5);
  });

  it("leaves the spread absent when only one side is quoted", () => {
    expect(only({ top: { AAPL: { bid: 151.4 } } })?.spread).toBeUndefined();
  });
});

describe("turnover", () => {
  it("is value traded, not share count", () => {
    const row = only({ daily: { AAPL: bar("AAPL", { volume: 1000, vwap: 150 }) } });
    expect(row?.turnover).toBe(150_000);
  });

  it("is a known zero for a symbol that has not traded", () => {
    // pm-stats leaves VWAP null until the first print, so requiring it would
    // blank the column for every quiet symbol.
    const row = only({ daily: { AAPL: bar("AAPL", { volume: 0, vwap: null }) } });
    expect(row?.turnover).toBe(0);
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

describe("last print time", () => {
  it("carries the timestamp of the symbol's most recent print", () => {
    const row = only({ lastTradeTs: { AAPL: "2026-07-30T10:15:00Z" } });
    expect(row?.lastTradeTs).toBe("2026-07-30T10:15:00Z");
  });

  it("is absent for a symbol that has not printed this session", () => {
    expect(only({ lastTradeTs: { MSFT: "2026-07-30T10:15:00Z" } })?.lastTradeTs).toBeUndefined();
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

  it("keeps the quote detail off the lobby wall", () => {
    // Sizes and spread are for somebody deciding whether to trade, and nobody
    // is doing that from across a room.
    for (const column of ["bidSz", "askSz", "spread", "turnover", "lastTrade"]) {
      expect(columnsFor("lobby")).not.toContain(column);
      expect(columnsFor("standard")).toContain(column);
    }
  });

  it("puts the two touch prices next to each other, sizes outside them", () => {
    // So the spread can be read without the eye crossing a size column.
    const columns = columnsFor("standard");
    expect(columns.slice(columns.indexOf("bidSz"), columns.indexOf("askSz") + 1)).toEqual([
      "bidSz",
      "bid",
      "ask",
      "askSz",
    ]);
  });
});

describe("auction columns (T-M1)", () => {
  it("keeps the quote columns outside a call phase", () => {
    expect(columnsFor("standard", "CONTINUOUS")).toContain("bid");
    expect(columnsFor("standard", "CONTINUOUS")).not.toContain("indic");
    expect(columnsFor("standard", null)).toContain("bid");
  });

  it.each(["OPENING_AUCTION", "CLOSING_AUCTION"])(
    "swaps the quote group for the auction group during %s",
    (phase) => {
      // Not added alongside: bid/ask/size/spread describe what is available,
      // and during a call phase nothing is. The indicative price, matched
      // size and surplus are what carry meaning at that moment.
      const columns = columnsFor("standard", phase);

      expect(columns).toEqual(expect.arrayContaining(["indic", "indicQty", "imbalance"]));
      for (const quote of ["bidSz", "bid", "ask", "askSz", "spread"]) {
        expect(columns).not.toContain(quote);
      }
    },
  );

  it("puts the auction group where the quote group was, not at the end", () => {
    // The eye tracks a column position down the grid; moving the meaningful
    // prices to the far right would cost the reader that.
    const columns = columnsFor("standard", "CLOSING_AUCTION");
    expect(columns.indexOf("indic")).toBeLessThan(columns.indexOf("volume"));
  });

  it("gives a lobby display the auction figures without growing the grid", () => {
    // Lobby is four columns so the space can buy larger type for a room to
    // read from a distance. Growing it during an auction would trade that
    // away at exactly the moment most people are looking, so it swaps the
    // stale pair (a pre-auction print and the change computed from it) for
    // the two figures that describe the auction.
    const columns = columnsFor("lobby", "OPENING_AUCTION");

    expect(columns).toEqual(["symbol", "indic", "imbalance", "volume"]);
    expect(columns).toHaveLength(columnsFor("lobby").length);
  });

  it("leaves the lobby columns alone outside a call phase", () => {
    expect(columnsFor("lobby", "CONTINUOUS")).toEqual(columnsFor("lobby"));
  });
});
