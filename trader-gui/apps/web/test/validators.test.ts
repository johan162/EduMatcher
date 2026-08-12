import { describe, it, expect } from "vitest";
import { orderSchema, quoteSchema } from "@/lib/validators";

describe("orderSchema", () => {
  const base = {
    symbol: "AAPL",
    side: "BUY",
    order_type: "LIMIT",
    quantity: 100,
    price: 150.25,
  };

  it("accepts a valid LIMIT order", () => {
    const result = orderSchema.safeParse(base);
    expect(result.success).toBe(true);
  });

  it("rejects LIMIT without price", () => {
    const result = orderSchema.safeParse({ ...base, price: undefined });
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i: { path: (string | number)[] }) => i.path.join("."));
      expect(paths).toContain("price");
    }
  });

  it("rejects ICEBERG when visible_qty >= quantity", () => {
    const result = orderSchema.safeParse({
      ...base,
      order_type: "ICEBERG",
      visible_qty: 100,
    });
    expect(result.success).toBe(false);
  });

  it("rejects STOP without stop_price", () => {
    const result = orderSchema.safeParse({ ...base, order_type: "STOP" });
    expect(result.success).toBe(false);
  });

  it("rejects TRAILING_STOP without trail_offset", () => {
    const result = orderSchema.safeParse({
      symbol: "AAPL",
      side: "SELL",
      order_type: "TRAILING_STOP",
      quantity: 50,
    });
    expect(result.success).toBe(false);
  });

  it("accepts MARKET without price", () => {
    const result = orderSchema.safeParse({
      symbol: "AAPL",
      side: "BUY",
      order_type: "MARKET",
      quantity: 100,
    });
    expect(result.success).toBe(true);
  });
});

describe("quoteSchema", () => {
  it("rejects when ask <= bid", () => {
    const result = quoteSchema.safeParse({
      symbol: "AAPL",
      bid_price: 150.1,
      bid_qty: 100,
      ask_price: 150.0, // not strictly greater
      ask_qty: 100,
      quote_id: "q1",
    });
    expect(result.success).toBe(false);
  });

  it("accepts a valid two-sided quote", () => {
    const result = quoteSchema.safeParse({
      symbol: "AAPL",
      bid_price: 149.9,
      bid_qty: 500,
      ask_price: 150.1,
      ask_qty: 500,
      quote_id: "mm-aapl-1",
    });
    expect(result.success).toBe(true);
  });
});
