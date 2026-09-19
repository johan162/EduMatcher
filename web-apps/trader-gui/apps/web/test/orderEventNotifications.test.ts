// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";
import { toast } from "sonner";
import { useOrderEventNotifications } from "@/hooks/useOrderEventNotifications";
import { useNotificationStore } from "@/store/useNotificationStore";
import { useOrderStore } from "@/store/useOrderStore";
import { __privateMessageForTest } from "@/ws/WebSocketManager";
import type { WsEnvelope, OrderAckData, OrderTerminalData } from "@/types/index";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

/**
 * C1 (docs-design/reviews/EduMatcher-Trader-GUI-Review.md): a rejected
 * cancel or amend used to give the trader no feedback at all — the ticket's
 * own `?wait=ack` only covers the synchronous NEW-order verdict, and
 * `DELETE /orders/{id}?wait=ack` timed out on a reject rather than
 * reporting it (fixed server-side in api_gateway/routers/orders.py). This
 * hook is the only place a trader now learns their cancel/amend failed, so
 * these tests drive it through the real WebSocketManager private-event path
 * (`__privateMessageForTest`, the same test-only hook `wsRouting.test.ts`
 * uses for market data) rather than calling internals directly.
 */
function emitOrderAck(data: Partial<OrderAckData> & { order_id: string; accepted: boolean }): void {
  const envelope: WsEnvelope<OrderAckData> = {
    type: "order.ack",
    topic: `order.ack.${data.gateway_id ?? "GW1"}`,
    ts: "2026-09-18T10:00:00Z",
    data: { gateway_id: "GW1", reason: "", ...data },
  };
  __privateMessageForTest(envelope);
}

function emitOrderCancelled(data: Partial<OrderTerminalData> & { order_id: string }): void {
  const envelope: WsEnvelope<OrderTerminalData> = {
    type: "order.cancelled",
    topic: `order.cancelled.${data.gateway_id ?? "GW1"}`,
    ts: "2026-09-19T10:00:00Z",
    data: { gateway_id: "GW1", ...data },
  };
  __privateMessageForTest(envelope);
}

beforeEach(() => {
  useNotificationStore.getState().clear();
  useOrderStore.getState().clear();
  vi.mocked(toast).mockClear();
  vi.mocked(toast.error).mockClear();
});

afterEach(() => {
  // The hook subscribes via useWsEvent's useEffect; without unmounting, its
  // cleanup (which unsubscribes from the ws bus) never runs and later
  // tests' emitted events fire every earlier test's still-mounted listener.
  cleanup();
});

describe("useOrderEventNotifications — order.ack (C1)", () => {
  it("surfaces a rejected cancel/amend (request_tag present) as a toast and Event Center entry", () => {
    renderHook(() => useOrderEventNotifications());

    emitOrderAck({
      order_id: "ORD1",
      accepted: false,
      reason: "collar breach",
      reject_code: "COLLAR_BREACH",
      request_tag: "amend-abc123",
    });

    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(vi.mocked(toast.error).mock.calls[0]![0]).toContain("collar breach");

    const entries = useNotificationStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0]!.kind).toBe("REJECT");
    expect(entries[0]!.detail).toBe("collar breach");
    expect(entries[0]!.orderId).toBe("ORD1");
  });

  it("ignores an accepted order.ack (the ticket's own ?wait=ack already surfaced it)", () => {
    renderHook(() => useOrderEventNotifications());

    emitOrderAck({ order_id: "ORD1", accepted: true, request_tag: "cancel-xyz" });

    expect(toast.error).not.toHaveBeenCalled();
    expect(useNotificationStore.getState().entries).toHaveLength(0);
  });

  it("ignores a rejected NEW-order ack (no request_tag) — the ticket's ?wait=ack owns that", () => {
    renderHook(() => useOrderEventNotifications());

    emitOrderAck({
      order_id: "ORD2",
      accepted: false,
      reason: "collar breach",
      reject_code: "COLLAR_BREACH",
      // request_tag omitted: order.new carries no such field, so the
      // engine never sets one on a genuine new-order reject.
    });

    expect(toast.error).not.toHaveBeenCalled();
    expect(useNotificationStore.getState().entries).toHaveLength(0);
  });

  it("falls back to a generic message when the engine sends no reason", () => {
    renderHook(() => useOrderEventNotifications());

    emitOrderAck({
      order_id: "ORD3",
      accepted: false,
      reason: "",
      request_tag: "cancel-def456",
    });

    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(vi.mocked(toast.error).mock.calls[0]![0]).toContain("rejected");
    expect(useNotificationStore.getState().entries[0]!.detail).toBe("rejected");
  });
});

/**
 * M2 (docs-design/reviews/EduMatcher-Trader-GUI-Review.md): the ticket
 * toasts "accepted" from the *first* order.ack, but for FOK/MARKET/IOC that
 * is not the final word — a second, later event can kill the order and the
 * trader never learns it. `?wait=ack` (gateway `_await_order_event`)
 * resolves on the first order.ack matching the order_id with no filter on
 * `accepted`, so it cannot see this second event either; this hook is the
 * only place it reaches. FOK's kill is a second request_tag-less
 * `order.ack accepted=false`; MARKET/IOC's is an `order.cancelled` with
 * `cancel_reason` set and zero fills (engine `order_book.py::_match_market`/
 * `_match_limit`, both default `cancel_reason` to INSUFFICIENT_LIQUIDITY).
 */
describe("useOrderEventNotifications — FOK/MARKET/IOC kill outcome (M2)", () => {
  it("toasts FOK's second, request_tag-less reject ack as a kill once the order is resting", () => {
    renderHook(() => useOrderEventNotifications());

    // The first ack (accepted=true) is what seeds the store row — mirrors
    // useOrderStream's applyAck, which every accepted ack already flows
    // through in the app.
    useOrderStore.getState().applyAck({
      gateway_id: "GW1",
      order_id: "ORD1",
      accepted: true,
      reason: "",
      order_type: "FOK",
      qty: 100,
    });
    vi.mocked(toast.error).mockClear();
    useNotificationStore.getState().clear();

    emitOrderAck({
      order_id: "ORD1",
      accepted: false,
      reason: "Insufficient liquidity",
      reject_code: "INSUFFICIENT_LIQUIDITY",
      order_type: "FOK",
      // request_tag omitted, same as a genuine new-order reject -- the
      // distinguishing signal is that the store already has this order.
    });

    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(vi.mocked(toast.error).mock.calls[0]![0]).toContain("killed");
    const entries = useNotificationStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0]!.kind).toBe("REJECT");
    expect(entries[0]!.orderId).toBe("ORD1");
  });

  it("toasts a zero-fill order.cancelled (MARKET/IOC remainder) as a kill", () => {
    renderHook(() => useOrderEventNotifications());

    useOrderStore.getState().applyAck({
      gateway_id: "GW1",
      order_id: "ORD2",
      accepted: true,
      reason: "",
      order_type: "MARKET",
      qty: 100,
    });
    vi.mocked(toast.error).mockClear();

    emitOrderCancelled({ order_id: "ORD2", cancel_reason: "INSUFFICIENT_LIQUIDITY" });

    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(vi.mocked(toast.error).mock.calls[0]![0]).toContain("killed");
  });

  it("does not toast a kill when the order had at least one fill before the cancel", () => {
    renderHook(() => useOrderEventNotifications());

    useOrderStore.getState().applyAck({
      gateway_id: "GW1",
      order_id: "ORD3",
      accepted: true,
      reason: "",
      order_type: "IOC",
      qty: 100,
    });
    useOrderStore.getState().applyFill({
      gateway_id: "GW1",
      order_id: "ORD3",
      fill_qty: 40,
      fill_price: 150,
      remaining_qty: 60,
      status: "PARTIAL",
      trade_ids: ["t1"],
    });
    vi.mocked(toast.error).mockClear();

    // The IOC remainder is still discarded once the sweep ends.
    emitOrderCancelled({ order_id: "ORD3", cancel_reason: "INSUFFICIENT_LIQUIDITY" });

    expect(toast.error).not.toHaveBeenCalled();
  });

  it("does not toast a kill for a trader-requested cancel (no cancel_reason)", () => {
    renderHook(() => useOrderEventNotifications());

    useOrderStore.getState().applyAck({
      gateway_id: "GW1",
      order_id: "ORD4",
      accepted: true,
      reason: "",
      order_type: "LIMIT",
      qty: 100,
    });
    vi.mocked(toast.error).mockClear();

    emitOrderCancelled({ order_id: "ORD4" });

    expect(toast.error).not.toHaveBeenCalled();
  });

  it("does not toast a kill for a genuine new-order reject (no prior accepted ack)", () => {
    renderHook(() => useOrderEventNotifications());

    // No applyAck seeded first -- the store has no row for ORD5, matching a
    // brand-new order the engine rejected outright.
    emitOrderAck({
      order_id: "ORD5",
      accepted: false,
      reason: "collar breach",
      order_type: "FOK",
    });

    expect(toast.error).not.toHaveBeenCalled();
    expect(useNotificationStore.getState().entries).toHaveLength(0);
  });
});
