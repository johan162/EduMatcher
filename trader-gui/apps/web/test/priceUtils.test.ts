import { describe, it, expect } from "vitest";
import { bucketTimestamp, flattenPayload, spreadTicks } from "@/lib/priceUtils";

describe("bucketTimestamp", () => {
  const ts = 1700000090; // some epoch second

  it("buckets to 1-minute bars", () => {
    const bucketed = bucketTimestamp(ts, "1m");
    expect(bucketed % 60).toBe(0);
    expect(bucketed).toBeLessThanOrEqual(ts);
  });

  it("buckets to 5-minute bars", () => {
    const bucketed = bucketTimestamp(ts, "5m");
    expect(bucketed % (5 * 60)).toBe(0);
  });

  it("buckets to 1-hour bars", () => {
    const bucketed = bucketTimestamp(ts, "1h");
    expect(bucketed % 3600).toBe(0);
  });
});

describe("flattenPayload", () => {
  it("builds a SELL MARKET for a long position", () => {
    const payload = flattenPayload("AAPL", 500);
    expect(payload).toMatchObject({
      symbol: "AAPL",
      side: "SELL",
      order_type: "MARKET",
      quantity: 500,
    });
  });

  it("builds a BUY MARKET for a short position", () => {
    const payload = flattenPayload("AAPL", -200);
    expect(payload).toMatchObject({
      symbol: "AAPL",
      side: "BUY",
      order_type: "MARKET",
      quantity: 200,
    });
  });

  it("returns null for zero position", () => {
    expect(flattenPayload("AAPL", 0)).toBeNull();
  });
});

describe("spreadTicks", () => {
  it("computes correct spread in ticks", () => {
    expect(spreadTicks(149.9, 150.1, 1)).toBe(2);
    expect(spreadTicks(150.0, 150.2, 2)).toBe(20);
  });
});
