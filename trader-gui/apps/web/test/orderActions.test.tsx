// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
  useOrderStore.getState().clear();
});

describe("AmendDialog (§13.2)", () => {
  it("PATCHes only the changed quantity", async () => {
    wrap(<AmendDialog order={ORDER} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Amend quantity"), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("button", { name: "Amend order" }));
    await waitFor(() => expect(callFor("/api/v1/orders/o1")).toBeTruthy());
    const [path, init] = callFor("/api/v1/orders/o1")!;
    expect(path).toBe("/api/v1/orders/o1");
    expect(init.method).toBe("PATCH");
    const body = JSON.parse(init.body!);
    expect(body).toEqual({ quantity: 50 });
  });

  it("rejects a quantity below the already-filled amount", () => {
    const partial = normalizeOrder({ ...ORDER, remaining_qty: 30 }); // 70 filled
    wrap(<AmendDialog order={partial} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Amend quantity"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Amend order" }));
    expect(screen.getByText(/cannot be below/)).toBeTruthy();
    expect(callFor("/api/v1/orders/o1")).toBeUndefined();
  });
});

describe("ReplaceDialog (§13.2)", () => {
  it("POSTs a full replacement order with the edited price", async () => {
    wrap(<ReplaceDialog order={ORDER} onClose={vi.fn()} />);
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
