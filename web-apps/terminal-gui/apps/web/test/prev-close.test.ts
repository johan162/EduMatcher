import { describe, expect, it } from "vitest";
import type { DailyBar } from "@edumatcher/terminal-types";
import { previousCloses } from "../src/lib/prev-close.js";
import { windowStart } from "../src/lib/usePrevCloses.js";

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

describe("windowStart", () => {
  it("moves at the UTC rollover, which is what makes the cache key expire", () => {
    // `usePrevCloses` uses this value as both the request bound and part of
    // its query key. If it did not move, a tab left open across midnight —
    // which the unattended display does by design — would keep serving the
    // window fetched for the previous session, and `previousCloses` reads
    // "today" off the newest date it is given, so every baseline on the board
    // would slip a session with nothing on screen saying so.
    const beforeMidnight = windowStart(Date.parse("2026-07-30T23:59:59Z"));
    const afterMidnight = windowStart(Date.parse("2026-07-31T00:00:01Z"));

    expect(beforeMidnight).toBe("2026-07-20");
    expect(afterMidnight).toBe("2026-07-21");
  });

  it("holds steady within one session, so the key is not churned hourly", () => {
    expect(windowStart(Date.parse("2026-07-30T00:00:01Z"))).toBe(
      windowStart(Date.parse("2026-07-30T23:59:59Z")),
    );
  });
});
