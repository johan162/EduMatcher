/** The pure header, ladder and formatting rules — pm-viewer's arithmetic, one case at a time. */

import { describe, expect, it } from "vitest";
import type { SessionStats } from "@edumatcher/book-types";
import { clock, hhmm, isoDate, pct, price, qty, signedPrice, tradeTime } from "../src/lib/format.js";
import { barPct, capacity, maxQty, tapeRows } from "../src/lib/ladder.js";
import { basis, change, changePct, range, reference, spread, trend } from "../src/lib/stats.js";
import { matches } from "../src/components/SymbolPicker.js";

const stats = (s: Partial<SessionStats>): SessionStats => ({
  volume: 0,
  tradeCount: 0,
  partial: false,
  timezone: "UTC",
  ...s,
});

describe("header arithmetic", () => {
  it("measures change against the previous close, else the session open", () => {
    expect(reference(stats({ prevClose: 10, open: 12 }))).toBe(10);
    expect(reference(stats({ open: 12 }))).toBe(12);
    expect(reference(null)).toBeUndefined();
  });

  it("derives change, percentage and trend", () => {
    expect(change(10.5, 10)).toBe(0.5);
    expect(changePct(10.5, 10)).toBeCloseTo(5);
    expect(changePct(1, 0)).toBeUndefined();
    expect(change(undefined, 10)).toBeUndefined();
    expect(trend(11, 10)).toBe("up");
    expect(trend(9, 10)).toBe("down");
    expect(trend(10, 10)).toBe("flat");
    expect(trend(10, undefined)).toBe("flat");
  });

  it("derives spread, range and basis", () => {
    expect(spread(9.9, 10.1)).toBeCloseTo(0.2);
    expect(spread(undefined, 10)).toBeUndefined();
    expect(range(stats({ high: 12, low: 9 }))).toBe(3);
    expect(range(stats({ high: 12 }))).toBeUndefined();
    expect(basis(stats({ prevClose: 1 }))).toBe("prev-close");
    expect(basis(stats({}))).toBe("session-open");
    expect(basis(stats({ prevClose: 1, partial: true }))).toBe("live-since");
  });
});

describe("formatting", () => {
  it("renders absent values as a dash and prices at the given precision", () => {
    expect(price(undefined, 2)).toBe("—");
    expect(price(1.5, 4)).toBe("1.5000");
    expect(price(412, 0)).toBe("412");
    expect(signedPrice(0.5, 2)).toBe("+0.50");
    expect(signedPrice(-0.5, 2)).toBe("-0.50");
    expect(pct(-1.234)).toBe("-1.23%");
    expect(qty(12400)).toBe("12,400");
    expect(qty(null)).toBe("—");
  });

  it("renders times in the session timezone, not the browser's", () => {
    const ms = Date.parse("2026-09-27T20:00:05.007Z");
    expect(clock(ms, "UTC")).toBe("20:00:05");
    expect(clock(ms, "Asia/Kolkata")).toBe("01:30:05");
    expect(hhmm(ms, "Europe/Stockholm")).toBe("22:00");
    expect(isoDate(ms, "UTC")).toBe("2026-09-27");
    expect(isoDate(ms, "Asia/Kolkata")).toBe("2026-09-28");
    expect(tradeTime(ms, "Asia/Kolkata")).toBe("01:30:05.007");
    expect(tradeTime(0, "UTC")).toBe("—");
  });
});

describe("ladder", () => {
  it("caps the fitted rows by the max-levels setting", () => {
    expect(capacity(30, "fit")).toBe(30);
    expect(capacity(30, 10)).toBe(10);
    expect(capacity(8, 20)).toBe(8);
  });

  it("scales bars to the largest visible level, with a sliver for tiny ones", () => {
    const levels = [
      { price: 1, qty: 10, count: 1 },
      { price: 2, qty: 1000, count: 1 },
    ];
    expect(maxQty(levels, 1)).toBe(10);
    expect(maxQty(levels, 2)).toBe(1000);
    expect(barPct(1000, 1000)).toBe(100);
    expect(barPct(1, 1000)).toBe(2);
    expect(barPct(0, 1000)).toBe(0);
    expect(barPct(5, 0)).toBe(0);
  });

  it("lists the tape newest first, coloured against the next-older print", () => {
    const t = (n: number, px: number) => ({ id: String(n), tsMs: n, px, qty: 1, side: "" as const });
    const rows = tapeRows([t(1, 10), t(2, 11), t(3, 11), t(4, 9)], 3);
    expect(rows.map((r) => [r.trade.id, r.trend])).toEqual([
      ["4", "down"],
      ["3", "flat"],
      ["2", "up"],
    ]);
    expect(tapeRows([t(1, 10)], 5).map((r) => r.trend)).toEqual(["flat"]);
  });
});

describe("symbol picker filter", () => {
  it("matches by prefix, sorted and de-duplicated — pm-viewer's rule", () => {
    const syms = ["MSFT", "AAPL", "AMD", "ABNB", "AAPL"];
    expect(matches(syms, "")).toEqual(["AAPL", "ABNB", "AMD", "MSFT"]);
    expect(matches(syms, "A")).toEqual(["AAPL", "ABNB", "AMD"]);
    expect(matches(syms, "AM")).toEqual(["AMD"]);
    expect(matches(syms, "D")).toEqual([]);
  });
});
