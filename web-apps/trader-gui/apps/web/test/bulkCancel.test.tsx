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
  return {};
});

vi.mock("@/api/apiFetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...(args as [string, { body?: string }])),
  ApiError: class ApiError extends Error {
    constructor(
      public status = 0,
      public code = "UNKNOWN",
      message = "",
    ) {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { ActiveOrdersPage } from "@/pages/ActiveOrdersPage";
import { useOrderStore } from "@/store/useOrderStore";
import { useSettingsStore } from "@/store/useSettingsStore";
import { ApiError } from "@/api/apiFetch";
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
    ([p, i]) =>
      String(p).startsWith("/api/v1/orders/") && (i as { method?: string })?.method === "DELETE",
  );

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  vi.clearAllMocks();
  useSettingsStore.setState({ confirmCancellations: true });
  useOrderStore.setState({
    orders: {
      o1: order({ order_id: "o1" }),
      o2: order({ order_id: "o2" }),
    },
    syncedAt: null,
  });
});

/**
 * M3: bulk cancel looped `mutation.mutate(...)` on a single `useMutation`,
 * whose onSuccess/onError only ever fire for the *latest* call (TanStack v5's
 * MutationObserver keeps one #mutateOptions, overwritten on every mutate()).
 * A cancel that failed for all but the last selected order was silently
 * dropped -- no toast, no indication anything went wrong.
 */
describe("Bulk cancel (M3)", () => {
  it("cancels every selected order and reports one summary toast reflecting every outcome", async () => {
    wrap(<ActiveOrdersPage />);
    fireEvent.click(screen.getByLabelText("Select all orders"));
    fireEvent.click(screen.getByRole("button", { name: /Cancel all selected/ }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel 2" }));

    await waitFor(() => expect(deleteCalls()).toHaveLength(2));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Cancelled 2 orders"));
  });

  it("reports a mixed summary when one of several cancels fails, not just the last call's outcome", async () => {
    apiFetchMock.mockImplementation(
      async (path: string, init?: { method?: string; body?: string }) => {
        if (path.startsWith("/api/v1/orders/o1") && init?.method === "DELETE") {
          throw new ApiError(400, "UNKNOWN_ORDER", "already gone");
        }
        if (path.startsWith("/api/v1/orders/") && init?.method === "DELETE") return {};
        return {};
      },
    );

    wrap(<ActiveOrdersPage />);
    fireEvent.click(screen.getByLabelText("Select all orders"));
    fireEvent.click(screen.getByRole("button", { name: /Cancel all selected/ }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel 2" }));

    await waitFor(() => expect(deleteCalls()).toHaveLength(2));
    // Both o1 (failed) and o2 (succeeded) are reflected in one summary --
    // the pre-fix code only ever surfaced the last-called order's outcome.
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Cancelled 1 order, 1 failed"));
  });
});
