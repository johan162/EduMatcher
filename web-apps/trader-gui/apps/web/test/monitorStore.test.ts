import { describe, it, expect, beforeEach } from "vitest";
import {
  useMonitorStore,
  selectActiveOrderCount,
  selectOrderCountsBySymbol,
} from "@/store/useMonitorStore";
import type { WsEnvelope } from "@/types/index";

function env(type: string, data: unknown, extra: Partial<WsEnvelope<unknown>> = {}): WsEnvelope<unknown> {
  return { type, topic: extra.topic ?? "", ts: extra.ts ?? "2026-08-14T10:00:00.000Z", data, ...extra } as WsEnvelope<unknown>;
}

const ingest = (e: WsEnvelope<unknown>) => useMonitorStore.getState().ingest(e);

beforeEach(() => useMonitorStore.getState().clear());

describe("useMonitorStore (§6.9)", () => {
  it("seeds orders and last_seq from a monitor.snapshot", () => {
    ingest(
      env("monitor.snapshot", {
        orders: [
          { order_id: "o1", gateway_id: "GW01", status: "NEW", symbol: "AAPL" },
          { order_id: "o2", gateway_id: "GW02", status: "FILLED", symbol: "MSFT" },
        ],
        halts: null,
        gateways: null,
        last_seq: { GW01: 100, GW02: 88 },
        incomplete: ["halts", "gateways"],
      }),
    );
    const s = useMonitorStore.getState();
    expect(Object.keys(s.orders)).toHaveLength(2);
    expect(s.lastSeq).toEqual({ GW01: 100, GW02: 88 });
    expect(selectActiveOrderCount(s.orders)).toBe(1); // FILLED is terminal
  });

  it("folds live order events into the cross-gateway orders map and log", () => {
    ingest(env("order.ack", { order_id: "o1", accepted: true, symbol: "AAPL", side: "BUY", qty: 100 }, { gateway_id: "GW01", seq: 1 }));
    ingest(env("order.fill", { order_id: "o1", fill_qty: 100, fill_price: 150, remaining_qty: 0, status: "FILLED", symbol: "AAPL" }, { gateway_id: "GW01", seq: 2 }));
    const s = useMonitorStore.getState();
    expect(s.orders.o1!.status).toBe("FILLED");
    expect(selectActiveOrderCount(s.orders)).toBe(0); // now terminal
    // Newest-first log: fill is first, ack second.
    expect(s.events[0]!.kind).toBe("FILL");
    expect(s.events[1]!.kind).toBe("ACK");
  });

  it("counts non-terminal orders by symbol", () => {
    ingest(env("order.ack", { order_id: "a", accepted: true, symbol: "AAPL" }, { gateway_id: "GW01" }));
    ingest(env("order.ack", { order_id: "b", accepted: true, symbol: "AAPL" }, { gateway_id: "GW01" }));
    ingest(env("order.ack", { order_id: "c", accepted: true, symbol: "MSFT" }, { gateway_id: "GW02" }));
    ingest(env("order.cancelled", { order_id: "b", symbol: "AAPL" }, { gateway_id: "GW01" }));
    expect(selectOrderCountsBySymbol(useMonitorStore.getState().orders)).toEqual({ AAPL: 1, MSFT: 1 });
  });

  it("ignores market-data frames in the log", () => {
    ingest(env("trade", { symbol: "AAPL", price: 150 }, { seq: 5 }));
    ingest(env("book", { symbol: "AAPL" }, { seq: 6 }));
    expect(useMonitorStore.getState().events).toHaveLength(0);
  });

  it("inserts a GAP marker when a snapshot arrives after prior events (reconnect)", () => {
    ingest(env("order.ack", { order_id: "o1", accepted: true, symbol: "AAPL" }, { gateway_id: "GW01" }));
    ingest(env("monitor.snapshot", { orders: [], halts: null, gateways: null, last_seq: {}, incomplete: [] }));
    expect(useMonitorStore.getState().events[0]!.kind).toBe("GAP");
  });

  it("does not insert a GAP on the first snapshot", () => {
    ingest(env("monitor.snapshot", { orders: [], halts: null, gateways: null, last_seq: {}, incomplete: [] }));
    expect(useMonitorStore.getState().events.some((e) => e.kind === "GAP")).toBe(false);
  });
});
