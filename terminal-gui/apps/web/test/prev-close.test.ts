import { describe, expect, it } from "vitest";
import type { DailyBar } from "@edumatcher/terminal-types";
import { previousCloses } from "../src/lib/prev-close.js";

const bar = (date: string, symbol: string, close: number | null): DailyBar => ({
  date,
  symbol,
  open_price: 100,
  high_price: 101,
  low_price: 99,
  close_price: close,
  vwap: 100,
  volume: 1000,
  trade_count: 10,
});

describe("previousCloses", () => {
  it("takes the close from the day before the current session", () => {
    const closes = previousCloses([bar("2026-07-29", "AAPL", 148.0), bar("2026-07-30", "AAPL", 150.12)]);

    expect(closes.AAPL).toBe(148.0);
  });

  it("reaches back past a gap to the most recent close on record", () => {
    // A long weekend, a holiday, or a symbol that simply did not print.
    const closes = previousCloses([
      bar("2026-07-24", "AAPL", 145.0),
      bar("2026-07-27", "AAPL", null),
      bar("2026-07-30", "AAPL", 150.12),
    ]);

    expect(closes.AAPL).toBe(145.0);
  });

  it("takes the current session from the whole window, not from each symbol", () => {
    // pm-stats writes a row for every listed symbol every day, including ones
    // that never traded. A per-symbol maximum would treat MSFT's own stale
    // row as "today" and hand back the day before that as its previous close.
    const closes = previousCloses([
      bar("2026-07-29", "MSFT", 420.0),
      bar("2026-07-29", "AAPL", 148.0),
      bar("2026-07-30", "AAPL", 150.12),
    ]);

    expect(closes.MSFT).toBe(420.0);
  });

  it("omits a symbol that only appears in the current session", () => {
    // Listed today. The caller marks the fallback rather than being handed an
    // invented reference price.
    expect(previousCloses([bar("2026-07-30", "NEWCO", 10.0)])).toEqual({});
  });

  it("returns nothing for an empty window", () => {
    expect(previousCloses([])).toEqual({});
  });
});
