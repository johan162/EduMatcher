import { describe, expect, it } from "vitest";
import type { GapFrame, TradeFrame } from "@edumatcher/terminal-types";
import { filterTape, mergeTapeRows } from "../src/views/TradeTape.js";

const print = (sym: string, seq: number, ts = "2026-07-30T14:32:07.000Z"): TradeFrame => ({
  type: "trade",
  sym,
  seq,
  ts,
  px: 150.12,
  qty: 100,
  side: "BUY",
});

const gap = (sym: string, ts: string, ch = "TRADE"): GapFrame => ({ type: "gap", ch, sym, ts });

describe("filterTape", () => {
  const tape = [print("TSLA", 4), print("AAPL", 3), print("MSFT", 2), print("AAPL", 1)];

  it("shows every symbol when unfiltered", () => {
    expect(filterTape(tape, "__all__").map((t) => t.sym)).toEqual(["TSLA", "AAPL", "MSFT", "AAPL"]);
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

describe("mergeTapeRows (T-H4/T-H5)", () => {
  it("places a gap between the prints either side of it, by time", () => {
    const trades = [
      print("AAPL", 4, "2026-07-30T14:32:09.000Z"),
      print("AAPL", 1, "2026-07-30T14:32:06.000Z"),
    ];
    const gaps = [gap("AAPL", "2026-07-30T14:32:07.500Z")];

    const rows = mergeTapeRows(trades, gaps, "AAPL");

    // Newest first: the SEQ=4 print, then the gap (it happened after SEQ=1
    // but before SEQ=4), then SEQ=1 — a timestamp is the only ordering a
    // GapFrame and a TradeFrame share, since a gap has no SEQ of its own.
    expect(rows.map((r) => (r.type === "gap" ? "gap" : r.seq))).toEqual([4, "gap", 1]);
  });

  it("keeps the newest-first convention across both series combined", () => {
    const trades = [print("AAPL", 1, "2026-07-30T14:32:06.000Z")];
    const gaps = [gap("AAPL", "2026-07-30T14:32:08.000Z")];

    const rows = mergeTapeRows(trades, gaps, "AAPL");
    expect(rows[0]?.type).toBe("gap");
    expect(rows[1]?.type).toBe("trade");
  });

  it("filters gaps by symbol exactly like prints", () => {
    const trades = [print("AAPL", 1)];
    const gaps = [gap("AAPL", "t1"), gap("MSFT", "t2")];

    expect(mergeTapeRows(trades, gaps, "AAPL").filter((r) => r.type === "gap")).toHaveLength(1);
    expect(mergeTapeRows(trades, gaps, "__all__").filter((r) => r.type === "gap")).toHaveLength(2);
  });

  it("caps the combined total, not each series separately", () => {
    const trades = [print("AAPL", 1, "t1")];
    const gaps = [gap("AAPL", "t2")];

    expect(mergeTapeRows(trades, gaps, "__all__", 1)).toHaveLength(1);
  });

  it("returns the prints untouched when there is no gap to place", () => {
    // The overwhelmingly common case, and the one on the hot path: the view
    // re-renders on every print, so it must not walk or copy the buffer to
    // discover there was nothing to interleave.
    const trades = [print("AAPL", 2, "t2"), print("AAPL", 1, "t1")];
    expect(mergeTapeRows(trades, [], "__all__")).toEqual(trades);
  });

  it("interleaves without reordering either series", () => {
    // Both inputs arrive newest-first; the merge must preserve that rather
    // than rely on a sort to rediscover it.
    const trades = [
      print("AAPL", 3, "2026-07-30T14:32:09.000Z"),
      print("AAPL", 2, "2026-07-30T14:32:05.000Z"),
      print("AAPL", 1, "2026-07-30T14:32:01.000Z"),
    ];
    const gaps = [gap("AAPL", "2026-07-30T14:32:07.000Z"), gap("AAPL", "2026-07-30T14:32:03.000Z")];

    const rows = mergeTapeRows(trades, gaps, "AAPL");
    expect(rows.map((r) => (r.type === "gap" ? "gap" : r.seq))).toEqual([3, "gap", 2, "gap", 1]);
  });

  it("puts a gap below the print sharing its timestamp, which is the side it falls on", () => {
    // A gap is stamped with the TS of the message that revealed it, so that
    // print is the hole's upper bound and belongs above it on a newest-first
    // tape.
    const trades = [print("AAPL", 2, "t9"), print("AAPL", 1, "t1")];
    const rows = mergeTapeRows(trades, [gap("AAPL", "t9")], "AAPL");
    expect(rows.map((r) => (r.type === "gap" ? "gap" : r.seq))).toEqual([2, "gap", 1]);
  });
});
