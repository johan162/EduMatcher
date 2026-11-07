import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

vi.mock("@/api/endpoints.js", () => ({ getAdminOrders: vi.fn() }));

import { getAdminOrders } from "@/api/endpoints.js";
import {
  FLUSH_MS,
  MAX_ORDERS,
  RESYNC_MIN_MS,
  useMonitorStore,
  selectActiveOrderCount,
  selectOrderCountsBySymbol,
} from "@/store/useMonitorStore";
import type { AdminOrder, WsEnvelope } from "@/types/index";

function env(type: string, data: unknown, extra: Partial<WsEnvelope<unknown>> = {}): WsEnvelope<unknown> {
  return { type, topic: extra.topic ?? "", ts: extra.ts ?? "2026-08-14T10:00:00.000Z", data, ...extra } as WsEnvelope<unknown>;
}

const ingest = (e: WsEnvelope<unknown>) => useMonitorStore.getState().ingest(e);
const flush = () => useMonitorStore.getState().flush();

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
    flush();
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
    flush();
    expect(selectOrderCountsBySymbol(useMonitorStore.getState().orders)).toEqual({ AAPL: 1, MSFT: 1 });
  });

  it("ignores market-data frames in the log", () => {
    ingest(env("trade", { symbol: "AAPL", price: 150 }, { seq: 5 }));
    ingest(env("book", { symbol: "AAPL" }, { seq: 6 }));
    flush();
    expect(useMonitorStore.getState().events).toHaveLength(0);
  });

  it("inserts a GAP marker when a snapshot arrives after prior events (reconnect)", () => {
    ingest(env("order.ack", { order_id: "o1", accepted: true, symbol: "AAPL" }, { gateway_id: "GW01" }));
    ingest(env("monitor.snapshot", { orders: [], halts: null, gateways: null, last_seq: {}, incomplete: [] }));
    // The snapshot flushed the queued ack first, then added the gap marker.
    const kinds = useMonitorStore.getState().events.map((e) => e.kind);
    expect(kinds).toEqual(["GAP", "ACK"]);
  });

  it("does not insert a GAP on the first snapshot", () => {
    ingest(env("monitor.snapshot", { orders: [], halts: null, gateways: null, last_seq: {}, incomplete: [] }));
    expect(useMonitorStore.getState().events.some((e) => e.kind === "GAP")).toBe(false);
  });

  it("does not publish live frames until the flush interval elapses", () => {
    vi.useFakeTimers();
    try {
      ingest(env("order.ack", { order_id: "o1", accepted: true, symbol: "AAPL" }, { gateway_id: "GW01" }));
      expect(useMonitorStore.getState().events).toHaveLength(0);
      vi.advanceTimersByTime(FLUSH_MS);
      expect(useMonitorStore.getState().events).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("applies a burst of frames in a single store write, newest first", () => {
    const writes: number[] = [];
    const unsub = useMonitorStore.subscribe((s) => writes.push(s.events.length));
    for (let i = 0; i < 50; i++) {
      ingest(env("order.ack", { order_id: `o${i}`, accepted: true, symbol: "AAPL" }, { gateway_id: "GW01", seq: i }));
    }
    flush();
    unsub();
    expect(writes).toEqual([50]);
    const s = useMonitorStore.getState();
    expect(s.events[0]!.seq).toBe(49);
    expect(s.events[49]!.seq).toBe(0);
  });

  it("clear() drops frames still queued", () => {
    ingest(env("order.ack", { order_id: "o1", accepted: true, symbol: "AAPL" }, { gateway_id: "GW01" }));
    useMonitorStore.getState().clear();
    flush();
    expect(useMonitorStore.getState().events).toHaveLength(0);
  });

  describe("seq gaps (gateway dropped events)", () => {
    const mockOrders = vi.mocked(getAdminOrders);
    const ack = (id: string, seq: number, topic = "order.ack.GW01") =>
      env(
        "order.ack",
        { order_id: id, accepted: true, symbol: "AAPL" },
        { gateway_id: "GW01", topic, seq },
      );
    /** The gateway answers each status query from this working set. */
    const serve = (working: AdminOrder[]) =>
      mockOrders.mockImplementation(async (params) => {
        const orders = working.filter((o) => o.status === params?.status);
        return { count: orders.length, orders, retention_sec: 300 };
      });

    beforeEach(() => {
      vi.useFakeTimers();
      mockOrders.mockReset();
      serve([]);
    });
    afterEach(() => {
      useMonitorStore.getState().clear();
      vi.useRealTimers();
    });

    it("contiguous seq triggers nothing", async () => {
      ingest(ack("o1", 1));
      ingest(ack("o2", 2));
      await vi.advanceTimersByTimeAsync(RESYNC_MIN_MS);
      expect(mockOrders).not.toHaveBeenCalled();
      expect(useMonitorStore.getState().events.some((e) => e.kind === "GAP")).toBe(false);
    });

    it("logs one GAP row per flush with the missed count, behind the batch", () => {
      ingest(ack("o1", 1));
      ingest(ack("o2", 5)); // 2..4 dropped
      ingest(ack("o3", 8, "order.ack.GW02"));
      ingest(ack("o4", 10, "order.ack.GW02")); // 9 dropped
      flush();
      const events = useMonitorStore.getState().events;
      expect(events.map((e) => e.kind)).toEqual(["ACK", "ACK", "ACK", "ACK", "GAP"]);
      expect(events[4]!.detail).toMatch(/^4 events dropped/);
    });

    it("a gap on a frame the log ignores still reports and resyncs", async () => {
      const q = (seq: number) =>
        env("quote.status", { quote_id: "q1" }, { topic: "quote.status.GW01", seq });
      ingest(q(1));
      ingest(q(3));
      await vi.advanceTimersByTimeAsync(FLUSH_MS);
      expect(useMonitorStore.getState().events.map((e) => e.kind)).toEqual(["GAP"]);
      expect(mockOrders).toHaveBeenCalledTimes(3); // NEW, PARTIAL, AMENDED
    });

    it("removes a working order the gateway no longer has (its fill was dropped)", async () => {
      serve([
        { order_id: "o2", gateway_id: "GW01", status: "PARTIAL", symbol: "AAPL" },
        { order_id: "o3", gateway_id: "GW01", status: "NEW", symbol: "AAPL" },
      ]);
      ingest(ack("o1", 1));
      ingest(ack("o2", 2));
      ingest(ack("o3", 9)); // gap; o1's fill and o2's partial were among the dropped
      await vi.advanceTimersByTimeAsync(FLUSH_MS);
      const orders = useMonitorStore.getState().orders;
      expect(orders.o1).toBeUndefined();
      expect(orders.o2!.status).toBe("PARTIAL"); // gateway state wins
      expect(orders.o3!.status).toBe("NEW");
      expect(selectActiveOrderCount(orders)).toBe(2);
    });

    it("leaves terminal orders alone", async () => {
      ingest(
        env(
          "order.fill",
          { order_id: "f1", status: "FILLED", symbol: "AAPL" },
          { gateway_id: "GW01", topic: "order.fill.GW01", seq: 1 },
        ),
      );
      ingest(
        env(
          "order.fill",
          { order_id: "f2", status: "FILLED", symbol: "AAPL" },
          { gateway_id: "GW01", topic: "order.fill.GW01", seq: 4 },
        ),
      );
      await vi.advanceTimersByTimeAsync(FLUSH_MS);
      expect(Object.keys(useMonitorStore.getState().orders).sort()).toEqual(["f1", "f2"]);
    });

    it("keeps an order updated live while the fetch was in flight", async () => {
      const pending: (() => void)[] = [];
      const release = () => pending.forEach((r) => r());
      mockOrders.mockImplementation(
        () =>
          new Promise((resolve) => {
            pending.push(() => resolve({ count: 0, orders: [], retention_sec: 300 }));
          }),
      );
      ingest(ack("o1", 1));
      flush();
      ingest(ack("o2", 5)); // gap -> resync starts (fetch pending)
      await vi.advanceTimersByTimeAsync(0);
      ingest(
        env(
          "order.fill",
          { order_id: "o1", status: "PARTIAL", symbol: "AAPL" },
          { gateway_id: "GW01", topic: "order.fill.GW01", seq: 1 },
        ),
      );
      release();
      await vi.advanceTimersByTimeAsync(0);
      const orders = useMonitorStore.getState().orders;
      // o1 changed during the fetch: live state is newer than the answer.
      expect(orders.o1!.status).toBe("PARTIAL");
      // o2 was applied before the fetch began, so the gateway's answer wins.
      expect(orders.o2).toBeUndefined();
    });

    it("resyncs at most once per RESYNC_MIN_MS however many gaps arrive", async () => {
      ingest(ack("a", 1));
      ingest(ack("b", 3));
      await vi.advanceTimersByTimeAsync(0);
      expect(mockOrders).toHaveBeenCalledTimes(3);
      for (let i = 0; i < 20; i++) ingest(ack(`c${i}`, 10 + 2 * i));
      await vi.advanceTimersByTimeAsync(RESYNC_MIN_MS - 1);
      expect(mockOrders).toHaveBeenCalledTimes(3);
      await vi.advanceTimersByTimeAsync(1);
      expect(mockOrders).toHaveBeenCalledTimes(6);
    });

    it("a snapshot resets seq baselines and cancels a pending resync", async () => {
      ingest(ack("a", 1));
      ingest(ack("b", 3));
      await vi.advanceTimersByTimeAsync(0); // first resync runs
      ingest(ack("c", 5)); // second one is now pending (throttled)
      ingest(
        env("monitor.snapshot", {
          orders: [],
          halts: null,
          gateways: null,
          last_seq: {},
          incomplete: [],
        }),
      );
      ingest(ack("d", 100)); // first seq after reconnect is a baseline, not a gap
      await vi.advanceTimersByTimeAsync(RESYNC_MIN_MS * 2);
      expect(mockOrders).toHaveBeenCalledTimes(3);
    });
  });

  describe("order map bound", () => {
    afterEach(() => useMonitorStore.getState().clear());

    it("evicts the oldest terminal orders above MAX_ORDERS and keeps working ones", () => {
      // The oldest order is still working; the next MAX_ORDERS are filled.
      ingest(env("order.ack", { order_id: "working", accepted: true, symbol: "AAPL" }, { gateway_id: "GW01" }));
      for (let i = 0; i < MAX_ORDERS; i++) {
        ingest(env("order.fill", { order_id: `f${i}`, status: "FILLED", symbol: "AAPL" }, { gateway_id: "GW01" }));
      }
      flush();
      const ids = Object.keys(useMonitorStore.getState().orders);
      expect(ids).toHaveLength(MAX_ORDERS);
      expect(ids).toContain("working");
      expect(ids).not.toContain("f0"); // oldest terminal went first
      expect(ids).toContain(`f${MAX_ORDERS - 1}`);
    });

    it("never evicts working orders, even over the cap", () => {
      for (let i = 0; i < MAX_ORDERS + 10; i++) {
        ingest(env("order.ack", { order_id: `w${i}`, accepted: true, symbol: "AAPL" }, { gateway_id: "GW01" }));
      }
      flush();
      expect(Object.keys(useMonitorStore.getState().orders)).toHaveLength(MAX_ORDERS + 10);
    });

    it("applies the cap to a snapshot too", () => {
      const orders = Array.from({ length: MAX_ORDERS + 5 }, (_, i) => ({
        order_id: `s${i}`,
        gateway_id: "GW01",
        status: "FILLED",
        symbol: "AAPL",
      }));
      ingest(env("monitor.snapshot", { orders, halts: null, gateways: null, last_seq: {}, incomplete: [] }));
      const ids = Object.keys(useMonitorStore.getState().orders);
      expect(ids).toHaveLength(MAX_ORDERS);
      expect(ids).not.toContain("s0");
    });
  });
});
