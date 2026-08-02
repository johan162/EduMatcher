import { describe, expect, it } from "vitest";
import type { OverviewRow } from "../src/lib/overview-rows.js";
import { filterBySymbol, isAttended, nextSort, sortRows, type SortState } from "../src/lib/overview-sort.js";

const row = (sym: string, over: Partial<OverviewRow> = {}): OverviewRow => ({
  sym,
  pinned: false,
  halted: false,
  ...over,
});

describe("nextSort", () => {
  it("opens numeric columns descending, because the question is 'what is biggest'", () => {
    expect(nextSort(null, "pctChg")).toEqual({ key: "pctChg", direction: "desc" });
    expect(nextSort(null, "turnover")).toEqual({ key: "turnover", direction: "desc" });
  });

  it("opens the symbol column ascending, because the question is 'where is X'", () => {
    expect(nextSort(null, "sym")).toEqual({ key: "sym", direction: "asc" });
  });

  it("flips direction on a second click of the same column", () => {
    expect(nextSort({ key: "pctChg", direction: "desc" }, "pctChg")).toEqual({
      key: "pctChg",
      direction: "asc",
    });
  });

  it("returns to unsorted on the third click, so a header can be un-clicked", () => {
    // Unsorted is not the absence of a sort here — it is the order the
    // gateway lists its universe in, and there must be a way back to it.
    expect(nextSort({ key: "pctChg", direction: "asc" }, "pctChg")).toBeNull();
  });

  it("switching columns starts that column's own cycle", () => {
    expect(nextSort({ key: "pctChg", direction: "asc" }, "volume")).toEqual({
      key: "volume",
      direction: "desc",
    });
  });
});

describe("sortRows", () => {
  const rows = [
    row("AAPL", { pctChg: 1.5, turnover: 100 }),
    row("MSFT", { pctChg: -2.5, turnover: 300 }),
    row("TSLA", { pctChg: 4.0, turnover: 200 }),
  ];

  it("ranks descending by default for a numeric column", () => {
    expect(sortRows(rows, { key: "pctChg", direction: "desc" }).map((r) => r.sym)).toEqual([
      "TSLA",
      "AAPL",
      "MSFT",
    ]);
  });

  it("ranks ascending when asked", () => {
    expect(sortRows(rows, { key: "turnover", direction: "asc" }).map((r) => r.sym)).toEqual([
      "AAPL",
      "TSLA",
      "MSFT",
    ]);
  });

  it("sorts symbols alphabetically", () => {
    const shuffled = [row("TSLA"), row("AAPL"), row("MSFT")];
    expect(sortRows(shuffled, { key: "sym", direction: "asc" }).map((r) => r.sym)).toEqual([
      "AAPL",
      "MSFT",
      "TSLA",
    ]);
  });

  it("leaves rows that lack the column at the bottom, both directions", () => {
    // Absent is the lack of a value, not a small one. A symbol that has not
    // traded has no change; floating it to the top of an ascending sort
    // would present "unknown" as "worst faller" — the same error as
    // rendering it 0.00%.
    const withGaps = [row("AAPL", { pctChg: 1.5 }), row("NEWCO"), row("MSFT", { pctChg: -2.5 })];

    expect(sortRows(withGaps, { key: "pctChg", direction: "desc" }).map((r) => r.sym)).toEqual([
      "AAPL",
      "MSFT",
      "NEWCO",
    ]);
    expect(sortRows(withGaps, { key: "pctChg", direction: "asc" }).map((r) => r.sym)).toEqual([
      "MSFT",
      "AAPL",
      "NEWCO",
    ]);
  });

  it("keeps the feed's own order when unsorted", () => {
    expect(sortRows(rows, null).map((r) => r.sym)).toEqual(["AAPL", "MSFT", "TSLA"]);
  });

  it("does not mutate the caller's array, which is a memoised result", () => {
    const original = [...rows];
    sortRows(rows, { key: "pctChg", direction: "desc" });
    expect(rows).toEqual(original);
  });

  it("orders print times chronologically", () => {
    const timed = [
      row("AAPL", { lastTradeTs: "2026-07-30T10:00:00Z" }),
      row("MSFT", { lastTradeTs: "2026-07-30T14:00:00Z" }),
    ];
    expect(sortRows(timed, { key: "lastTradeTs", direction: "desc" }).map((r) => r.sym)).toEqual([
      "MSFT",
      "AAPL",
    ]);
  });
});

describe("filterBySymbol", () => {
  const rows = [row("AAPL"), row("MSFT"), row("TSLA"), row("MSTR")];

  it("matches a prefix, which is how a trader reaches for a ticker", () => {
    expect(filterBySymbol(rows, "MS").map((r) => r.sym)).toEqual(["MSFT", "MSTR"]);
  });

  it("ignores case, since nobody means a lower-case ticker", () => {
    expect(filterBySymbol(rows, "tsla").map((r) => r.sym)).toEqual(["TSLA"]);
  });

  it("puts prefix matches above mere substring matches", () => {
    const withSubstring = [row("XMSY"), row("MSFT")];
    expect(filterBySymbol(withSubstring, "MS").map((r) => r.sym)).toEqual(["MSFT", "XMSY"]);
  });

  it("returns everything for an empty or whitespace query", () => {
    expect(filterBySymbol(rows, "")).toHaveLength(4);
    expect(filterBySymbol(rows, "   ")).toHaveLength(4);
  });

  it("returns nothing when nothing matches, rather than falling back to all", () => {
    expect(filterBySymbol(rows, "ZZZZ")).toEqual([]);
  });
});

describe("isAttended", () => {
  it("treats sorting or searching as proof somebody is at the screen", () => {
    // Auto-paging exists to serve the absence of a reader. Either
    // interaction is evidence there is one.
    expect(isAttended(null, "")).toBe(false);
    expect(isAttended({ key: "pctChg", direction: "desc" } as SortState, "")).toBe(true);
    expect(isAttended(null, "TS")).toBe(true);
  });

  it("does not count whitespace as an interaction", () => {
    expect(isAttended(null, "  ")).toBe(false);
  });
});
