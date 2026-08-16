import { describe, it, expect, beforeEach } from "vitest";
import { useAuthStore } from "@/store/useAuthStore";
import { useSessionStore } from "@/store/useSessionStore";
import { useBookStore } from "@/store/useBookStore";
import { useHaltStore } from "@/store/useHaltStore";
import { useNotificationStore } from "@/store/useNotificationStore";

beforeEach(() => {
  useAuthStore.setState({ apiKey: null, gatewayId: null, role: null, gatewayCount: null });
  useSessionStore.setState({
    phase: "CLOSED",
    prevPhase: null,
    phaseSince: null,
    nextTransitionAt: null,
  });
  useBookStore.setState({ books: {} });
  useHaltStore.setState({ halts: {} });
  useNotificationStore.setState({ entries: [], unread: 0 });
});

describe("useAuthStore", () => {
  it("stores credentials after login", () => {
    useAuthStore.getState().login("key-1", "GW01", "TRADER");
    const s = useAuthStore.getState();
    expect(s.apiKey).toBe("key-1");
    expect(s.gatewayId).toBe("GW01");
    expect(s.role).toBe("TRADER");
  });

  it("clears on logout", () => {
    useAuthStore.getState().login("key-1", "GW01", "TRADER");
    useAuthStore.getState().logout();
    expect(useAuthStore.getState().apiKey).toBeNull();
  });
});

describe("useSessionStore", () => {
  it("updates phase and records phaseSince", () => {
    const before = Date.now();
    useSessionStore.getState().setPhase("CONTINUOUS", "OPENING_AUCTION");
    const s = useSessionStore.getState();
    expect(s.phase).toBe("CONTINUOUS");
    expect(s.prevPhase).toBe("OPENING_AUCTION");
    expect(s.phaseSince).toBeGreaterThanOrEqual(before);
  });
});

describe("useBookStore", () => {
  it("stores book data keyed by symbol", () => {
    useBookStore.getState().updateBook("AAPL", {
      symbol: "AAPL",
      tick_decimals: 2,
      bids: [{ price: 150, qty: 100, count: 1 }],
      asks: [{ price: 150.1, qty: 200, count: 2 }],
      recent_trades: [],
      last_price: 150.05,
      last_qty: 50,
      last_buy_price: null,
      last_sell_price: null,
    });
    const entry = useBookStore.getState().books["AAPL"];
    expect(entry).toBeDefined();
    expect(entry!.bids[0]!.price).toBe(150);
    expect(entry!.lastPrice).toBe(150.05);
  });
});

describe("useHaltStore", () => {
  it("sets and clears halts", () => {
    useHaltStore.getState().setHalt("AAPL", { symbol: "AAPL", level: "L2", resume_at_ns: null });
    expect(useHaltStore.getState().halts["AAPL"]).toBeDefined();
    useHaltStore.getState().clearHalt("AAPL");
    expect(useHaltStore.getState().halts["AAPL"]).toBeUndefined();
  });
});

describe("useNotificationStore", () => {
  it("pushes entries and tracks unread count", () => {
    const { push } = useNotificationStore.getState();
    push({ ts: Date.now(), kind: "FILL", title: "Fill", detail: "50 @ 150" });
    push({ ts: Date.now(), kind: "FILL", title: "Fill", detail: "100 @ 151" });
    const s = useNotificationStore.getState();
    expect(s.entries).toHaveLength(2);
    expect(s.unread).toBe(2);
  });

  it("marks all as read", () => {
    const { push, markAllRead } = useNotificationStore.getState();
    push({ ts: Date.now(), kind: "SESSION", title: "Session", detail: "CONTINUOUS" });
    markAllRead();
    expect(useNotificationStore.getState().unread).toBe(0);
  });
});
