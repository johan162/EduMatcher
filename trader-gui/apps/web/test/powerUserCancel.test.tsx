// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";
import type { ReactNode } from "react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const apiFetchMock = vi.fn(async (path: string, init?: { method?: string; body?: string }) => {
  if (path.startsWith("/api/v1/orders/") && init?.method === "DELETE") return {};
  if (path === "/api/v1/orders" && init?.method === "POST") {
    return { order_id: "resub-1", status: "PENDING", accepted: null, event: null };
  }
  return {};
});

vi.mock("@/api/apiFetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...(args as [string, { body?: string }])),
  ApiError: class ApiError extends Error {
    constructor(public status = 0, public code = "UNKNOWN", message = "") {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { ActiveOrdersPage } from "@/pages/ActiveOrdersPage";
import { useOrderStore } from "@/store/useOrderStore";
import { useSettingsStore } from "@/store/useSettingsStore";
import { normalizeOrder } from "@/types/index";
import type { Order } from "@/types/index";

function order(patch: Partial<Order> & { order_id: string }): Order {
  return normalizeOrder({
    symbol: "AAPL",
    side: "BUY",
    order_type: "LIMIT",
    tif: "DAY",
    quantity: 100,
    remaining_qty: 100,
    price: 150,
    status: "NEW",
    ...patch,
  });
}

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const deleteCalls = () =>
  apiFetchMock.mock.calls.filter(
    ([p, i]) => String(p).startsWith("/api/v1/orders/") && (i as { method?: string })?.method === "DELETE",
  );

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  vi.clearAllMocks();
  useOrderStore.setState({ orders: { o1: order({ order_id: "o1" }) }, syncedAt: null });
});

describe("Blotter cancel — confirmation mode (§20.3 default)", () => {
  it("shows a confirmation dialog and does not cancel until confirmed", () => {
    useSettingsStore.setState({ confirmCancellations: true });
    wrap(<ActiveOrdersPage />);
    fireEvent.click(screen.getByLabelText("Cancel order o1"));
    expect(screen.getByText("Cancel order?")).toBeTruthy();
    expect(deleteCalls()).toHaveLength(0);
  });
});

describe("Blotter cancel — power-user mode (§20.3)", () => {
  it("cancels immediately with no dialog and offers an undo-toast that re-submits", async () => {
    useSettingsStore.setState({ confirmCancellations: false });
    wrap(<ActiveOrdersPage />);
    fireEvent.click(screen.getByLabelText("Cancel order o1"));

    // No confirmation dialog; cancel fired immediately.
    expect(screen.queryByText("Cancel order?")).toBeNull();
    await waitFor(() => expect(deleteCalls()).toHaveLength(1));

    // An undo-toast with an action was raised.
    const undoCall = (toast as unknown as { mock: { calls: unknown[][] } }).mock.calls.find(
      (c) => (c[1] as { action?: unknown })?.action,
    );
    expect(undoCall).toBeTruthy();
    const opts = undoCall![1] as { action: { onClick: () => void } };

    // Invoking Undo re-submits an equivalent order.
    opts.action.onClick();
    await waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some(
          ([p, i]) => p === "/api/v1/orders" && (i as { method?: string })?.method === "POST",
        ),
      ).toBe(true),
    );
    const postCall = apiFetchMock.mock.calls.find(([p]) => p === "/api/v1/orders")!;
    expect(JSON.parse((postCall[1] as { body: string }).body)).toMatchObject({
      symbol: "AAPL",
      side: "BUY",
      order_type: "LIMIT",
      quantity: 100,
      price: 150,
    });
  });
});
