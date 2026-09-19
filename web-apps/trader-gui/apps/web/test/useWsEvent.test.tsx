// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";
import { useState } from "react";
import { useWsEvent } from "@/hooks/useWsEvent";
import { __privateMessageForTest } from "@/ws/WebSocketManager";
import type { WsEnvelope, Fill } from "@/types/index";

function emitFill(orderId: string): void {
  const envelope: WsEnvelope<Fill> = {
    type: "order.fill",
    topic: "order.fill.GW1",
    ts: "2026-09-19T10:00:00Z",
    data: {
      order_id: orderId,
      gateway_id: "GW1",
      fill_qty: 10,
      fill_price: 100,
      remaining_qty: 0,
      status: "PARTIAL",
      trade_ids: ["t1"],
    },
  };
  __privateMessageForTest(envelope);
}

afterEach(() => {
  // useWsEvent subscribes via a useEffect; without unmounting, its cleanup
  // (unsubscribe from the ws bus) never runs and a later test's emitted
  // events would still fire this test's listener too.
  cleanup();
});

describe("useWsEvent (L6)", () => {
  it("always calls the latest handler, not a closure frozen at mount", () => {
    const seen: number[] = [];
    const { result, rerender } = renderHook(() => {
      const [multiplier, setMultiplier] = useState(1);
      useWsEvent("order.fill", () => {
        seen.push(multiplier);
      });
      return { setMultiplier };
    });

    emitFill("o1");
    expect(seen).toEqual([1]);

    // Re-render with new component state -- the mount-time closure over
    // `multiplier` is now stale. A handler frozen at mount would still push
    // 1; the fix must push the current value, 2.
    result.current.setMultiplier(2);
    rerender();
    emitFill("o2");
    expect(seen).toEqual([1, 2]);
  });

  it("does not resubscribe (and so does not double-fire) across re-renders with a fresh inline handler", () => {
    let calls = 0;
    const { rerender } = renderHook(() => {
      useWsEvent("order.fill", () => {
        calls++;
      });
    });

    rerender();
    rerender();
    rerender();

    emitFill("o1");
    // A naive fix that resubscribed on every render (each caller passes a
    // fresh inline arrow function) would have accumulated 4 listeners by
    // now, firing the same event 4 times instead of once.
    expect(calls).toBe(1);
  });

  it("unsubscribes on unmount", () => {
    let calls = 0;
    const { unmount } = renderHook(() => {
      useWsEvent("order.fill", () => {
        calls++;
      });
    });

    unmount();
    emitFill("o1");
    expect(calls).toBe(0);
  });
});
