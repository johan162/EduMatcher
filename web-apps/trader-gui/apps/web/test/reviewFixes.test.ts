import { describe, it, expect, beforeEach } from "vitest";
import { normalizeOrder, type RawOrder } from "@/types/index";
import { useSessionStore } from "@/store/useSessionStore";

// ─────────────────────────────────────────────────────────────────────────────
// Fix A — /orders identity normalization (engine `id` vs fallback `order_id`)
// ─────────────────────────────────────────────────────────────────────────────
describe("normalizeOrder", () => {
  it("maps the engine OrderDisplay shape (id/timestamp/client_tag)", () => {
    // The bug: the engine reply keys the id as `id`, not `order_id`, so a
    // consumer reading `order_id` got undefined and cancel/keys broke.
    const raw: RawOrder = {
      id: "ORD-123",
      symbol: "AAPL",
      side: "BUY",
      order_type: "LIMIT",
      tif: "DAY",
      quantity: 100,
      remaining_qty: 40,
      price: 150.5,
      status: "PARTIAL",
      timestamp: 1_765_000_000, // epoch seconds
      client_tag: "ui-42",
    };
    const o = normalizeOrder(raw);
    expect(o.order_id).toBe("ORD-123");
    expect(o.client_tag).toBe("ui-42");
    expect(o.remaining_qty).toBe(40);
    expect(o.updated_at).toBe(new Date(1_765_000_000 * 1000).toISOString());
  });

  it("maps the thin timeout-fallback cache shape (order_id, no display fields)", () => {
    const raw: RawOrder = {
      order_id: "ORD-999",
      symbol: "MSFT",
      side: "SELL",
      order_type: "MARKET",
      quantity: 50,
      status: "PENDING",
      client_tag: "cli-7",
    };
    const o = normalizeOrder(raw);
    expect(o.order_id).toBe("ORD-999");
    expect(o.client_tag).toBe("cli-7");
    // No engine timestamp on the fallback row → null, not a bogus epoch.
    expect(o.updated_at).toBeNull();
    // remaining_qty defaults to quantity when the thin row omits it.
    expect(o.remaining_qty).toBe(50);
  });

  it("prefers `id` over `order_id` when both are somehow present", () => {
    expect(normalizeOrder({ id: "A", order_id: "B" }).order_id).toBe("A");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Fix B — session `next` uses wire field `state`, not `to_state`
// ─────────────────────────────────────────────────────────────────────────────
describe("useSessionStore session.next handling", () => {
  beforeEach(() => {
    useSessionStore.setState({
      phase: "CLOSED",
      prevPhase: null,
      phaseSince: null,
      nextTransitionAt: null,
      nextState: null,
      schedule: null,
    });
  });

  it("adopts the engine `next.state` as the countdown target", () => {
    const at = new Date(Date.now() + 60_000).toISOString();
    // Wire shape: { state, at } — NOT { to_state, at }.
    useSessionStore.getState().setPhase("OPENING_AUCTION", "PRE_OPEN", {
      state: "CONTINUOUS",
      at,
    });
    const s = useSessionStore.getState();
    expect(s.nextState).toBe("CONTINUOUS");
    expect(s.nextTransitionAt).toBe(new Date(at).getTime());

    const target = s.countdownTarget(Date.now());
    expect(target).not.toBeNull();
    expect(target!.toState).toBe("CONTINUOUS");
  });

  it("ignores a stale (past) engine target and falls back", () => {
    const past = new Date(Date.now() - 60_000).toISOString();
    useSessionStore.getState().setPhase("CONTINUOUS", "OPENING_AUCTION", {
      state: "CLOSING_AUCTION",
      at: past,
    });
    // No schedule configured → nothing to fall back to → null (not a pin at 0).
    expect(useSessionStore.getState().countdownTarget(Date.now())).toBeNull();
  });

  it("handles a manual transition with no `next` (elapsed-only clock)", () => {
    useSessionStore.getState().setPhase("CONTINUOUS", "OPENING_AUCTION", null);
    const s = useSessionStore.getState();
    expect(s.nextState).toBeNull();
    expect(s.nextTransitionAt).toBeNull();
  });
});
