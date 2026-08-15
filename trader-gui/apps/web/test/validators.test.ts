import { describe, it, expect } from "vitest";
import { orderSchema, quoteSchema, validateAmend } from "@/lib/validators";

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

describe("validateAmend", () => {
  // A LIMIT order: 100 total, 40 filled, resting at 150.
  const target = { quantity: 100, filled: 40, price: 150 };

  it("sends only the fields that actually changed", () => {
    expect(validateAmend(target, { price: "150", quantity: "80" })).toEqual({
      ok: true,
      body: { quantity: 80 },
    });
    expect(validateAmend(target, { price: "151", quantity: "100" })).toEqual({
      ok: true,
      body: { price: 151 },
    });
    expect(validateAmend(target, { price: "151", quantity: "80" })).toEqual({
      ok: true,
      body: { price: 151, quantity: 80 },
    });
  });

  it("refuses an amend that changes nothing (engine: 'Amend requires at least PRICE or QTY')", () => {
    const r = validateAmend(target, { price: "150", quantity: "100" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/No changes/);
  });

  // The engine requires qty > filled, not qty >= filled — this boundary is
  // the one the dialog used to get wrong.
  it("rejects a quantity equal to the filled quantity", () => {
    const r = validateAmend(target, { price: "150", quantity: "40" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/must exceed the 40 already filled/);
  });

  it("rejects a quantity below the filled quantity", () => {
    expect(validateAmend(target, { price: "150", quantity: "39" }).ok).toBe(false);
  });

  it("accepts the smallest quantity the engine allows (filled + 1)", () => {
    expect(validateAmend(target, { price: "150", quantity: "41" })).toEqual({
      ok: true,
      body: { quantity: 41 },
    });
  });

  it("allows a quantity increase above the original", () => {
    expect(validateAmend(target, { price: "150", quantity: "250" })).toEqual({
      ok: true,
      body: { quantity: 250 },
    });
  });

  it("rejects a non-integer, zero or negative quantity", () => {
    for (const quantity of ["80.5", "0", "-10", ""]) {
      const r = validateAmend(target, { price: "150", quantity });
      expect(r.ok).toBe(false);
      if (!r.ok) expect(r.error).toMatch(/positive integer/);
    }
  });

  it("rejects a non-positive or unparseable price", () => {
    for (const price of ["0", "-1", "abc"]) {
      const r = validateAmend(target, { price, quantity: "80" });
      expect(r.ok).toBe(false);
      if (!r.ok) expect(r.error).toMatch(/positive number/);
    }
  });

  it("ignores the price field entirely for an order that carries no price", () => {
    const noPrice = { quantity: 100, filled: 0, price: null };
    expect(validateAmend(noPrice, { price: "nonsense", quantity: "50" })).toEqual({
      ok: true,
      body: { quantity: 50 },
    });
  });
});
