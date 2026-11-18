// @vitest-environment jsdom
/** The order-audit modal shows how far the audit index reaches (For-Later L018, WP-FL18). */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { FakeApiError, apiFetchMock } = vi.hoisted(() => {
  class FakeApiError extends Error {
    constructor(
      public status = 0,
      public code = "UNKNOWN",
      message = "",
    ) {
      super(message);
      this.name = "ApiError";
    }
  }
  return { FakeApiError, apiFetchMock: vi.fn() };
});

vi.mock("@/api/apiFetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  ApiError: FakeApiError,
}));

import { AdminOrderDetailModal } from "@/components/admin/AdminOrderDetailModal";

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AdminOrderDetailModal orderId="o1" onClose={() => {}} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  apiFetchMock.mockReset();
});

describe("AdminOrderDetailModal", () => {
  it("shows the server's 404 message, which names the index's reach", async () => {
    const message =
      "No audited events for order o1 in the audit index, which reaches up to 2026-08-29T15:10:41.207+00:00";
    apiFetchMock.mockRejectedValue(new FakeApiError(404, "UNKNOWN_ORDER", message));
    show();
    expect(await screen.findByText(message)).toBeTruthy();
  });

  it("shows how far the index reaches next to the events", async () => {
    apiFetchMock.mockResolvedValue({
      order_id: "o1",
      indexed_through: "2026-08-29T15:10:41.207+00:00",
      count: 1,
      events: [
        {
          timestamp: "2026-08-29T10:00:00.000Z",
          topic: "order.ack.GW01",
          gateway_id: "GW01",
          symbol: "AAPL",
          order_id: "o1",
          payload: { status: "NEW" },
        },
      ],
    });
    show();
    expect(await screen.findByText(/indexed through 2026-08-29T15:10:41.207\+00:00/)).toBeTruthy();
  });
});
