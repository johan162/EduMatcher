// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";
import { toast } from "sonner";
import { useOrderEventNotifications } from "@/hooks/useOrderEventNotifications";
import { useNotificationStore } from "@/store/useNotificationStore";
import { __privateMessageForTest } from "@/ws/WebSocketManager";
import type { WsEnvelope, OrderAckData } from "@/types/index";

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

beforeEach(() => {
  useNotificationStore.getState().clear();
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
