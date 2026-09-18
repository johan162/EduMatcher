// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";
import type { ReactNode } from "react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const apiFetchMock = vi.fn(async (path: string, init?: { method?: string; body?: string }) => {
  if (path.includes("/replace")) {
    return { cancelled_order_id: "o1", replacement_order_id: "r9", status: "PENDING" };
  }
  if (path.includes("/history/orders/")) {
    return {
      count: 2,
      events: [
        { seq: 1, ts: "2026-07-27T10:00:00.000Z", event_type: "ACK", order_id: "o1", gateway_id: "GW1", symbol: "AAPL", price: 150, quantity: 100 },
        { seq: 2, ts: "2026-07-27T10:01:00.000Z", event_type: "FILL", order_id: "o1", gateway_id: "GW1", symbol: "AAPL", fill_qty: 40, fill_price: 150, remaining_qty: 60 },
      ],
    };
  }
  void init;
  return {};
});

vi.mock("@/api/apiFetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...(args as [string, { method?: string; body?: string }])),
  ApiError: class ApiError extends Error {
    constructor(public status = 0, public code = "UNKNOWN", message = "") {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { AmendDialog } from "@/components/orders/AmendDialog";
import { ReplaceDialog } from "@/components/orders/ReplaceDialog";
import { OrderDetailDrawer } from "@/components/orders/OrderDetailDrawer";
import { useOrderStore } from "@/store/useOrderStore";
import { normalizeOrder } from "@/types/index";
import type { Order } from "@/types/index";

const ORDER: Order = normalizeOrder({
  order_id: "o1",
  symbol: "AAPL",
  side: "BUY",
  order_type: "LIMIT",
  tif: "DAY",
  quantity: 100,
  remaining_qty: 100,
  price: 150,
  status: "NEW",
});

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function callFor(pathPart: string) {
  const call = apiFetchMock.mock.calls.find(([p]) => String(p).includes(pathPart));
  return call as [string, { method?: string; body?: string }] | undefined;
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  vi.mocked(toast).mockClear();
  useOrderStore.getState().clear();
});

// AmendDialog and ReplaceDialog now read the order live from useOrderStore by
// id (M6, docs-design/reviews/EduMatcher-Trader-GUI-Review.md) instead of a
// snapshot prop, so every test seeds the store with the order under test
// before rendering.

describe("AmendDialog (§13.2)", () => {
  it("PATCHes only the changed quantity", async () => {
    useOrderStore.getState().seed([ORDER]);
    wrap(<AmendDialog orderId={ORDER.order_id} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Amend quantity"), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("button", { name: "Amend order" }));
    await waitFor(() => expect(callFor("/api/v1/orders/o1")).toBeTruthy());
    const [path, init] = callFor("/api/v1/orders/o1")!;
    expect(path).toBe("/api/v1/orders/o1");
    expect(init.method).toBe("PATCH");
    const body = JSON.parse(init.body!);
    // useAmendOrderMutation stamps a generated `request_tag` on every amend --
    // it is the key the engine echoes on `order.amended`, so the reply can be
    // tied back to this request. It is not a field the dialog "changed", so
    // lift it out before asserting on what the dialog actually sent.
    const { request_tag, ...changed } = body;
    expect(changed).toEqual({ quantity: 50 });
    expect(request_tag).toMatch(/^amend-/);
  });

  it("rejects a quantity below the already-filled amount", () => {
    const partial = normalizeOrder({ ...ORDER, remaining_qty: 30 }); // 70 filled
    useOrderStore.getState().seed([partial]);
    wrap(<AmendDialog orderId={partial.order_id} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Amend quantity"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Amend order" }));
    expect(screen.getByText(/must exceed the 70 already filled/)).toBeTruthy();
    expect(callFor("/api/v1/orders/o1")).toBeUndefined();
  });

  // The engine requires the new quantity to exceed the filled quantity, not
  // merely to reach it (engine/order_book.py::amend), so the dialog must stop
  // an amend down to exactly the filled amount rather than let it round-trip.
  it("rejects a quantity equal to the already-filled amount", () => {
    const partial = normalizeOrder({ ...ORDER, remaining_qty: 30 }); // 70 filled
    useOrderStore.getState().seed([partial]);
    wrap(<AmendDialog orderId={partial.order_id} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Amend quantity"), { target: { value: "70" } });
    fireEvent.click(screen.getByRole("button", { name: "Amend order" }));
    expect(screen.getByText(/must exceed the 70 already filled/)).toBeTruthy();
    expect(callFor("/api/v1/orders/o1")).toBeUndefined();
  });

  // M6: the dialog reads the order live, so a fill landing while it's open
  // updates Filled and is what validateAmend checks against -- not the
  // filled amount at the moment the dialog was opened.
  it("validates against the live filled amount, not a stale snapshot (M6)", () => {
    const partial = normalizeOrder({ ...ORDER, remaining_qty: 60 }); // 40 filled
    useOrderStore.getState().seed([partial]);
    wrap(<AmendDialog orderId={partial.order_id} onClose={vi.fn()} />);
    expect(screen.getByText("40")).toBeTruthy(); // Filled, before the extra fill

    act(() => {
      useOrderStore.getState().applyFill({
        gateway_id: "GW1",
        order_id: partial.order_id,
        fill_qty: 50,
        fill_price: 150,
        remaining_qty: 10,
        status: "PARTIAL",
        trade_ids: [],
      });
    });
    expect(screen.getByText("90")).toBeTruthy(); // Filled, live after the fill

    // 70 would have been valid against the stale 40-filled snapshot, but not
    // against the live 90 filled.
    fireEvent.change(screen.getByLabelText("Amend quantity"), { target: { value: "70" } });
    fireEvent.click(screen.getByRole("button", { name: "Amend order" }));
    expect(screen.getByText(/must exceed the 90 already filled/)).toBeTruthy();
    expect(callFor("/api/v1/orders/o1")).toBeUndefined();
  });

  // M6: no snapshot to go stale against once the order is gone.
  it("closes itself with a notice when the order goes terminal while open (M6)", () => {
    useOrderStore.getState().seed([ORDER]);
    const onClose = vi.fn();
    wrap(<AmendDialog orderId={ORDER.order_id} onClose={onClose} />);

    act(() => {
      useOrderStore.getState().applyCancelled({ gateway_id: "GW1", order_id: ORDER.order_id });
    });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledTimes(1);
    expect(vi.mocked(toast).mock.calls[0]![0]).toContain("no longer open");
  });
});

describe("ReplaceDialog (§13.2)", () => {
  it("POSTs a full replacement order with the edited price", async () => {
    useOrderStore.getState().seed([ORDER]);
    wrap(<ReplaceDialog orderId={ORDER.order_id} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Replace price"), { target: { value: "151" } });
    fireEvent.click(screen.getByRole("button", { name: "Replace order" }));
    await waitFor(() => expect(callFor("/replace")).toBeTruthy());
    const [path, init] = callFor("/replace")!;
    expect(path).toBe("/api/v1/orders/o1/replace");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body!);
    expect(body).toMatchObject({
      symbol: "AAPL",
      side: "BUY",
      order_type: "LIMIT",
      quantity: 100,
      tif: "DAY",
      price: 151,
    });
  });

  // C2: defaulting to the original total would silently re-establish size
  // already filled -- the replacement must default to what's still resting.
  it("defaults the replacement quantity to what's still resting, not the original total (C2)", async () => {
    const partial = normalizeOrder({ ...ORDER, remaining_qty: 40 }); // 60 filled
    useOrderStore.getState().seed([partial]);
    wrap(<ReplaceDialog orderId={partial.order_id} onClose={vi.fn()} />);

    const qtyInput = screen.getByLabelText("Replace quantity") as HTMLInputElement;
    expect(qtyInput.value).toBe("40");

    fireEvent.click(screen.getByRole("button", { name: "Replace order" }));
    await waitFor(() => expect(callFor("/replace")).toBeTruthy());
    const [, init] = callFor("/replace")!;
    const body = JSON.parse(init.body!);
    expect(body.quantity).toBe(40);
  });

  // C2: filled-so-far is shown read-only alongside the editable quantity.
  it("shows filled-so-far read-only", () => {
    const partial = normalizeOrder({ ...ORDER, remaining_qty: 40 }); // 60 filled
    useOrderStore.getState().seed([partial]);
    wrap(<ReplaceDialog orderId={partial.order_id} onClose={vi.fn()} />);
    expect(screen.getByText("Filled")).toBeTruthy();
    expect(screen.getByText("60")).toBeTruthy();
  });

  it("closes itself with a notice when the order goes terminal while open (M6)", () => {
    useOrderStore.getState().seed([ORDER]);
    const onClose = vi.fn();
    wrap(<ReplaceDialog orderId={ORDER.order_id} onClose={onClose} />);

    act(() => {
      useOrderStore.getState().applyCancelled({ gateway_id: "GW1", order_id: ORDER.order_id });
    });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledTimes(1);
    expect(vi.mocked(toast).mock.calls[0]![0]).toContain("no longer open");
  });
});

describe("OrderDetailDrawer (§13.4)", () => {
  it("renders the lifecycle timeline from GET /history/orders/{id}", async () => {
    useOrderStore.getState().seed([{ order_id: "o1", symbol: "AAPL", side: "BUY", order_type: "LIMIT", status: "PARTIAL", quantity: 100, remaining_qty: 60 }]);
    wrap(<OrderDetailDrawer orderId="o1" onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("ACK")).toBeTruthy());
    expect(screen.getByText("FILL")).toBeTruthy();
    // Fill detail line shows qty @ price and remaining.
    expect(screen.getByText(/40 @ 150/)).toBeTruthy();
  });
});
