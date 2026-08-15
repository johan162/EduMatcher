import { describe, it, expect } from "vitest";
import { buildFlattenOrder } from "@/lib/flatten";

describe("buildFlattenOrder (§13.6)", () => {
  it("flattens a long with a SELL MARKET for abs(qty)", () => {
    expect(buildFlattenOrder({ symbol: "AAPL", net_qty: 500 })).toEqual({
      symbol: "AAPL",
      side: "SELL",
      order_type: "MARKET",
      quantity: 500,
      tif: "DAY",
    });
  });

  it("flattens a short with a BUY MARKET for abs(qty)", () => {
    expect(buildFlattenOrder({ symbol: "MSFT", net_qty: -200 })).toEqual({
      symbol: "MSFT",
      side: "BUY",
      order_type: "MARKET",
      quantity: 200,
      tif: "DAY",
    });
  });

  it("returns null for a flat position", () => {
    expect(buildFlattenOrder({ symbol: "AAPL", net_qty: 0 })).toBeNull();
  });
});
