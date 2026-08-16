import { describe, it, expect } from "vitest";
import { buildResubmitOrder } from "@/lib/resubmit";
import { normalizeOrder } from "@/types/index";
import type { Order } from "@/types/index";

function order(patch: Partial<Order> & { order_id: string }): Order {
  return normalizeOrder({
    symbol: "AAPL",
    side: "BUY",
    order_type: "LIMIT",
    tif: "DAY",
    quantity: 100,
    remaining_qty: 100,
    price: 150,
    status: "NEW",
    ...patch,
  });
}

describe("buildResubmitOrder (§20.3 undo)", () => {
  it("re-creates an equivalent LIMIT for the remaining quantity", () => {
    const body = buildResubmitOrder(order({ order_id: "o1", quantity: 100, remaining_qty: 40 }));
    expect(body).toEqual({
      symbol: "AAPL",
      side: "BUY",
      order_type: "LIMIT",
      quantity: 40,
      tif: "DAY",
      price: 150,
    });
  });

  it("carries a STOP order's stop price and omits an absent limit price", () => {
    const body = buildResubmitOrder(
      order({ order_id: "o2", order_type: "STOP", price: null, stop_price: 145, remaining_qty: 100 }),
    );
    expect(body).toMatchObject({ order_type: "STOP", stop_price: 145 });
    expect(body).not.toHaveProperty("price");
  });

  it("carries an ICEBERG's visible qty", () => {
    const body = buildResubmitOrder(
      order({ order_id: "o3", order_type: "ICEBERG", visible_qty: 10, remaining_qty: 100 }),
    );
    expect(body).toMatchObject({ visible_qty: 10 });
  });

  it("returns null when there is no remaining quantity to re-submit", () => {
    expect(buildResubmitOrder(order({ order_id: "o4", remaining_qty: 0, status: "FILLED" }))).toBeNull();
  });
});
