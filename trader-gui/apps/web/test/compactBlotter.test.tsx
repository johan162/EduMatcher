// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const apiFetchMock = vi.fn(async (path: string, init?: { method?: string }) => {
  if (path.startsWith("/api/v1/orders/") && init?.method === "DELETE") return {};
  return {};
});

vi.mock("@/api/apiFetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...(args as [string, { method?: string }])),
  ApiError: class ApiError extends Error {
    constructor(public status = 0, public code = "UNKNOWN", message = "") {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { CompactBlotter } from "@/components/workspace/CompactBlotter";
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
  useOrderStore.setState({ orders: { o1: order({ order_id: "o1" }) }, syncedAt: null });
});

describe("CompactBlotter cancel honours power-user mode (§20.3)", () => {
  it("confirms by default before cancelling", () => {
    useSettingsStore.setState({ confirmCancellations: true });
    wrap(<CompactBlotter symbol="AAPL" tickDecimals={2} />);
    fireEvent.click(screen.getByLabelText("Cancel order o1"));
    expect(screen.getByText("Cancel order?")).toBeTruthy();
    expect(deleteCalls()).toHaveLength(0);
  });

  it("cancels immediately with no dialog in power-user mode", async () => {
    useSettingsStore.setState({ confirmCancellations: false });
    wrap(<CompactBlotter symbol="AAPL" tickDecimals={2} />);
    fireEvent.click(screen.getByLabelText("Cancel order o1"));
    expect(screen.queryByText("Cancel order?")).toBeNull();
    await waitFor(() => expect(deleteCalls()).toHaveLength(1));
  });
});
