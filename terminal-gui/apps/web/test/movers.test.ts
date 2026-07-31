import { describe, expect, it } from "vitest";
import {
  moverBarFraction,
  rankMovers,
  type OverviewRow,
} from "../src/lib/overview-rows.js";

const row = (over: Partial<OverviewRow> & { sym: string }): OverviewRow => ({
  pinned: false,
  halted: false,
  ...over,
});

describe("rankMovers", () => {
  const rows = [
    row({ sym: "TSLA", pctChg: 1.49, volume: 900 }),
    row({ sym: "AAPL", pctChg: 0.28, volume: 5000 }),
    row({ sym: "MSFT", pctChg: -0.26, volume: 300 }),
    row({ sym: "NVDA", pctChg: -2.1, volume: 100 }),
  ];

  it("ranks gainers by descending percentage change", () => {
    expect(rankMovers(rows, "gainers").map((r) => r.sym)).toEqual(["TSLA", "AAPL"]);
  });

  it("ranks losers by the largest fall first", () => {
    expect(rankMovers(rows, "losers").map((r) => r.sym)).toEqual(["NVDA", "MSFT"]);
  });

  it("ranks active by session volume, not by movement", () => {
    expect(rankMovers(rows, "active").map((r) => r.sym)).toEqual([
      "AAPL",
      "TSLA",
      "MSFT",
      "NVDA",
    ]);
  });

  it("drops a symbol with no percentage change rather than ranking it flat", () => {
    // A symbol that has not traded has no change at all. Sorting it in as
    // 0.00% would claim it was unmoved when the truth is that it is unknown.
    const withUntraded = [...rows, row({ sym: "EDU01" })];

    expect(rankMovers(withUntraded, "gainers").map((r) => r.sym)).not.toContain("EDU01");
    expect(rankMovers(withUntraded, "losers").map((r) => r.sym)).not.toContain("EDU01");
    expect(rankMovers(withUntraded, "active").map((r) => r.sym)).not.toContain("EDU01");
  });

  it("excludes an exactly flat symbol from both directions", () => {
    const flat = [row({ sym: "EDU01", pctChg: 0, volume: 10 })];

    expect(rankMovers(flat, "gainers")).toHaveLength(0);
    expect(rankMovers(flat, "losers")).toHaveLength(0);
    // But it did trade, so it is legitimately active.
    expect(rankMovers(flat, "active").map((r) => r.sym)).toEqual(["EDU01"]);
  });

  it("ignores the watchlist pin", () => {
    // On Overview a starred symbol is pinned to the top because that view is a
    // watchlist. Here the ordering is the entire content, so floating a
    // favourite above a bigger mover would misreport the market.
    const pinned = [
      row({ sym: "AAPL", pctChg: 0.28, pinned: true }),
      row({ sym: "TSLA", pctChg: 1.49 }),
    ];

    expect(rankMovers(pinned, "gainers").map((r) => r.sym)).toEqual(["TSLA", "AAPL"]);
  });

  it("caps the board at the requested limit", () => {
    expect(rankMovers(rows, "active", 2)).toHaveLength(2);
  });
});

describe("moverBarFraction", () => {
  it("scales the largest mover on screen to a full bar", () => {
    const rows = [
      row({ sym: "TSLA", pctChg: 1.49 }),
      row({ sym: "AAPL", pctChg: 0.28 }),
    ];

    expect(moverBarFraction(rows[0]!, rows, "gainers")).toBeCloseTo(1, 6);
    expect(moverBarFraction(rows[1]!, rows, "gainers")).toBeCloseTo(0.28 / 1.49, 6);
  });

  it("scales a quiet session to itself rather than to a fixed percentage", () => {
    // With a fixed scale a day where nothing moved more than 0.3% would
    // render as a column of empty bars and show no structure at all.
    const quiet = [row({ sym: "A", pctChg: 0.3 }), row({ sym: "B", pctChg: 0.1 })];

    expect(moverBarFraction(quiet[0]!, quiet, "gainers")).toBeCloseTo(1, 6);
  });

  it("uses magnitude so losers render as positive-width bars", () => {
    const losers = [row({ sym: "A", pctChg: -2.1 }), row({ sym: "B", pctChg: -0.26 })];

    expect(moverBarFraction(losers[0]!, losers, "losers")).toBeCloseTo(1, 6);
    expect(moverBarFraction(losers[1]!, losers, "losers")).toBeGreaterThan(0);
  });

  it("returns zero rather than dividing by zero when nothing has moved", () => {
    const flat = [row({ sym: "A", pctChg: 0 })];

    expect(moverBarFraction(flat[0]!, flat, "gainers")).toBe(0);
  });
});
