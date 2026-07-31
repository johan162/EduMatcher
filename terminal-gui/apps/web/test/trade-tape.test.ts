import { describe, expect, it } from "vitest";
import type { TradeFrame } from "@edumatcher/terminal-types";
import { filterTape } from "../src/views/TradeTape.js";

const print = (sym: string, seq: number): TradeFrame => ({
  type: "trade",
  sym,
  seq,
  ts: "2026-07-30T14:32:07.000Z",
  px: 150.12,
  qty: 100,
  side: "BUY",
});

describe("filterTape", () => {
  const tape = [print("TSLA", 4), print("AAPL", 3), print("MSFT", 2), print("AAPL", 1)];

  it("shows every symbol when unfiltered", () => {
    expect(filterTape(tape, "__all__").map((t) => t.sym)).toEqual([
      "TSLA",
      "AAPL",
      "MSFT",
      "AAPL",
    ]);
  });

  it("narrows to one symbol without reordering", () => {
    expect(filterTape(tape, "AAPL").map((t) => t.seq)).toEqual([3, 1]);
  });

  it("caps the rendered rows", () => {
    expect(filterTape(tape, "__all__", 2)).toHaveLength(2);
  });

  it("applies the cap after filtering, not before", () => {
    // Capping first would hide older prints for the chosen symbol behind
    // newer ones for symbols the reader has filtered out.
    expect(filterTape(tape, "AAPL", 2).map((t) => t.seq)).toEqual([3, 1]);
  });

  it("returns nothing for a symbol that has not printed", () => {
    expect(filterTape(tape, "NVDA")).toEqual([]);
  });
});
