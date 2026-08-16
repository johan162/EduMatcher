import { describe, it, expect } from "vitest";
import { legFill, normalizeQuoteLegRows, quotesBySymbol, spreadInfo } from "@/lib/quotes";
import type { ActiveQuote } from "@/types/index";

function aq(patch: Partial<ActiveQuote> & { quote_id: string; symbol: string }): ActiveQuote {
  return {
    gateway_id: "MM",
    state: "ACTIVE",
    bid_order_id: "b",
    ask_order_id: "a",
    bid_price: 149.9,
    ask_price: 150.1,
    bid_qty: 500,
    ask_qty: 500,
    bid_remaining_qty: 500,
    ask_remaining_qty: 500,
    bid_status: "RESTING",
    ask_status: "RESTING",
    ...patch,
  };
}

describe("quotesBySymbol", () => {
  it("indexes by symbol, last write wins", () => {
    const map = quotesBySymbol([aq({ quote_id: "q1", symbol: "AAPL" }), aq({ quote_id: "q2", symbol: "MSFT" })]);
    expect(map.AAPL!.quote_id).toBe("q1");
    expect(map.MSFT!.quote_id).toBe("q2");
  });
});

describe("legFill (§14.1.1)", () => {
  it("computes filled = qty - remaining and pct", () => {
    expect(legFill(500, 200)).toEqual({ filled: 300, pct: 60 });
  });
  it("clamps a remaining larger than qty to 0 filled", () => {
    expect(legFill(100, 150)).toEqual({ filled: 0, pct: 0 });
  });
  it("returns 0 for a zero-qty (MISSING) leg", () => {
    expect(legFill(0, 0)).toEqual({ filled: 0, pct: 0 });
  });
});

describe("spreadInfo (§14.2)", () => {
  it("returns currency and whole-tick spread when ask > bid", () => {
    const s = spreadInfo(149.9, 150.1, 2);
    expect(s).not.toBeNull();
    expect(s!.currency).toBeCloseTo(0.2, 6);
    expect(s!.ticks).toBe(20);
  });
  it("returns null when ask <= bid (engine rejects that quote)", () => {
    expect(spreadInfo(150.1, 150.1, 2)).toBeNull();
    expect(spreadInfo(150.2, 150.1, 2)).toBeNull();
  });
  it("returns null when a price is missing", () => {
    expect(spreadInfo(null, 150.1, 2)).toBeNull();
    expect(spreadInfo(149.9, null, 2)).toBeNull();
  });
});

describe("normalizeQuoteLegRows (§14.3 dual shape)", () => {
  it("maps a full QuoteLeg record (engine path)", () => {
    const rows = normalizeQuoteLegRows([
      {
        quote_id: "q1",
        order_id: "o1",
        symbol: "AAPL",
        leg_side: "BUY",
        qty: 500,
        remaining: 200,
        filled: 300,
        status: "PARTIAL",
        quote_status: "ACTIVE",
        price: 149.9,
      },
    ]);
    expect(rows[0]).toMatchObject({
      shape: "leg",
      quote_id: "q1",
      order_id: "o1",
      leg_side: "BUY",
      price: 149.9,
      qty: 500,
      filled: 300,
      quote_status: "ACTIVE",
    });
  });

  it("derives filled from qty-remaining when the leg omits it", () => {
    const rows = normalizeQuoteLegRows([
      {
        quote_id: "q1",
        order_id: "o1",
        symbol: "AAPL",
        leg_side: "SELL",
        qty: 100,
        remaining: 40,
        status: "PARTIAL",
        quote_status: "ACTIVE",
      },
    ]);
    expect(rows[0]!.filled).toBe(60);
  });

  it("maps a warm-cache quote-level ack/status dict to a quote-shape row", () => {
    const rows = normalizeQuoteLegRows([
      { quote_id: "q1", accepted: true, reason: "", bid_order_id: "b", ask_order_id: "a", status: "ACTIVE" },
    ]);
    expect(rows[0]).toMatchObject({
      shape: "quote",
      quote_id: "q1",
      leg_side: null,
      order_id: null,
      qty: null,
      status: "ACTIVE",
    });
  });

  it("skips non-object entries defensively", () => {
    expect(normalizeQuoteLegRows([null, 42, "x"])).toHaveLength(0);
  });
});
