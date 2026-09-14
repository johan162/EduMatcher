import { describe, it, expect, beforeEach } from "vitest";
import { useOrderStore, isTerminal } from "@/store/useOrderStore";
import { normalizeOrder, toOrderStatus } from "@/types/index";
import type { OrderAckData, Fill, OrderAmendedData, OrderTerminalData } from "@/types/index";

const ack = (o: Partial<OrderAckData> & { order_id: string; accepted: boolean }): OrderAckData => ({
  gateway_id: "GW1",
  reason: "",
  ...o,
});
const fill = (o: Partial<Fill> & { order_id: string }): Fill => ({
  gateway_id: "GW1",
  fill_qty: 0,
  fill_price: 0,
  remaining_qty: 0,
  status: "PARTIAL",
  trade_ids: [],
  ...o,
});
const terminal = (order_id: string): OrderTerminalData => ({ gateway_id: "GW1", order_id });

beforeEach(() => useOrderStore.getState().clear());

describe("normalizeOrder (phase-7 additions)", () => {
  it("falls back to qty when quantity is absent (event rows)", () => {
    const o = normalizeOrder({ order_id: "o1", qty: 500, remaining_qty: 500, status: "NEW" });
    expect(o.quantity).toBe(500);
    expect(o.remaining_qty).toBe(500);
  });

  it("resolves the cache-only AMENDED marker to a working status", () => {
    expect(normalizeOrder({ order_id: "o1", qty: 100, remaining_qty: 100, status: "AMENDED" }).status).toBe("NEW");
    expect(normalizeOrder({ order_id: "o2", qty: 100, remaining_qty: 40, status: "AMENDED" }).status).toBe("PARTIAL");
  });
});

describe("toOrderStatus", () => {
  it("passes a status this union contains straight through", () => {
    expect(toOrderStatus("FILLED", 0, 100)).toBe("FILLED");
    expect(toOrderStatus("PARTIAL", 40, 100)).toBe("PARTIAL");
  });

  it("resolves a status it does not know from the quantities", () => {
    // PARTIAL_FILL is what order.fill.status carried from two of the engine's
    // eight publish sites while the field was an unconstrained string. It used
    // to be cast into this union unchecked, so it reached the store as a value
    // no screen could match and a partially filled order vanished from every
    // group summary.
    expect(toOrderStatus("PARTIAL_FILL", 40, 100)).toBe("PARTIAL");
    expect(toOrderStatus("PARTIAL_FILL", 0, 100)).toBe("NEW");
    expect(toOrderStatus("SOMETHING_NEW", 40, 100)).toBe("PARTIAL");
  });

  it("treats an absent status as not yet acked", () => {
    expect(toOrderStatus(undefined, 100, 100)).toBe("PENDING");
    expect(toOrderStatus(null, 100, 100)).toBe("PENDING");
  });
});

describe("useOrderStore reducers", () => {
  it("seed replaces the working set", () => {
    useOrderStore.getState().seed([{ order_id: "a", symbol: "AAPL", status: "NEW" }]);
    useOrderStore.getState().seed([{ order_id: "b", symbol: "MSFT", status: "NEW" }]);
    const { orders } = useOrderStore.getState();
    expect(Object.keys(orders)).toEqual(["b"]);
  });

  it("ack accept marks NEW with full remaining; reject marks REJECTED", () => {
    useOrderStore.getState().applyAck(
      ack({ order_id: "o1", accepted: true, symbol: "AAPL", side: "BUY", order_type: "LIMIT", qty: 100, price: 150 }),
    );
    const o1 = useOrderStore.getState().orders["o1"]!;
    expect(o1.status).toBe("NEW");
    expect(o1.quantity).toBe(100);
    expect(o1.remaining_qty).toBe(100);
    expect(o1.symbol).toBe("AAPL");
    expect(o1.price).toBe(150);

    useOrderStore.getState().applyAck(ack({ order_id: "o2", accepted: false, reason: "collar breach" }));
    expect(useOrderStore.getState().orders["o2"]!.status).toBe("REJECTED");
  });

  it("keeps a fill whose status is not in the union out of the store", () => {
    useOrderStore.getState().applyAck(ack({ order_id: "o9", accepted: true, qty: 100 }));
    useOrderStore
      .getState()
      .applyFill(
        fill({ order_id: "o9", fill_qty: 40, fill_price: 150, remaining_qty: 60, qty: 100, status: "PARTIAL_FILL" as never }),
      );
    expect(useOrderStore.getState().orders["o9"]!.status).toBe("PARTIAL");
  });

  it("fill updates remaining and status (PARTIAL then FILLED)", () => {
    useOrderStore.getState().applyAck(ack({ order_id: "o1", accepted: true, qty: 100 }));
    useOrderStore.getState().applyFill(fill({ order_id: "o1", fill_qty: 40, fill_price: 150, remaining_qty: 60, status: "PARTIAL" }));
    expect(useOrderStore.getState().orders["o1"]!.status).toBe("PARTIAL");
    expect(useOrderStore.getState().orders["o1"]!.remaining_qty).toBe(60);
    useOrderStore.getState().applyFill(fill({ order_id: "o1", fill_qty: 60, fill_price: 150, remaining_qty: 0, status: "FILLED" }));
    expect(useOrderStore.getState().orders["o1"]!.status).toBe("FILLED");
    expect(isTerminal(useOrderStore.getState().orders["o1"]!.status)).toBe(true);
  });

  it("amend updates price/qty/remaining and derives status", () => {
    useOrderStore.getState().applyAck(ack({ order_id: "o1", accepted: true, qty: 100, price: 150 }));
    const amend = (d: Partial<OrderAmendedData>): OrderAmendedData => ({
      gateway_id: "GW1", order_id: "o1", qty: 100, remaining_qty: 100, priority_reset: false, price: 150, ...d,
    });
    useOrderStore.getState().applyAmended(amend({ qty: 80, remaining_qty: 80, price: 151 }));
    let o1 = useOrderStore.getState().orders["o1"]!;
    expect(o1.quantity).toBe(80);
    expect(o1.price).toBe(151);
    expect(o1.status).toBe("NEW");
    useOrderStore.getState().applyAmended(amend({ qty: 80, remaining_qty: 30 }));
    o1 = useOrderStore.getState().orders["o1"]!;
    expect(o1.status).toBe("PARTIAL");
  });

  it("a fill after an amend does not resurrect the pre-amend quantity", () => {
    useOrderStore.getState().applyAck(ack({ order_id: "o1", accepted: true, qty: 100 }));
    useOrderStore.getState().applyAmended({
      gateway_id: "GW1", order_id: "o1", qty: 80, remaining_qty: 80, priority_reset: false, price: 150,
    });
    // Engine fill carries the *original* qty (100); the amended 80 must stand.
    useOrderStore.getState().applyFill(fill({ order_id: "o1", fill_qty: 30, fill_price: 150, remaining_qty: 50, status: "PARTIAL", qty: 100 }));
    const o1 = useOrderStore.getState().orders["o1"]!;
    expect(o1.quantity).toBe(80);
    expect(o1.remaining_qty).toBe(50);
  });

  it("cancelled / expired mark terminal", () => {
    useOrderStore.getState().applyAck(ack({ order_id: "o1", accepted: true, qty: 100 }));
    useOrderStore.getState().applyCancelled(terminal("o1"));
    expect(useOrderStore.getState().orders["o1"]!.status).toBe("CANCELLED");
    useOrderStore.getState().applyAck(ack({ order_id: "o2", accepted: true, qty: 100 }));
    useOrderStore.getState().applyExpired(terminal("o2"));
    expect(useOrderStore.getState().orders["o2"]!.status).toBe("EXPIRED");
  });

  it("hydrate never resurrects a locally-terminal order", () => {
    useOrderStore.getState().applyAck(ack({ order_id: "o1", accepted: true, qty: 100 }));
    useOrderStore.getState().applyCancelled(terminal("o1"));
    // A stale GET /orders row still shows it working — must be ignored.
    useOrderStore.getState().hydrate([{ order_id: "o1", symbol: "AAPL", status: "NEW", quantity: 100 }]);
    expect(useOrderStore.getState().orders["o1"]!.status).toBe("CANCELLED");
  });
});
