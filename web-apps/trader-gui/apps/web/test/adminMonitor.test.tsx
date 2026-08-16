// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const apiFetchMock = vi.fn(async (path: string) => {
  if (path.startsWith("/api/v1/admin/orders/")) {
    return {
      order_id: "o1",
      count: 1,
      events: [
        { timestamp: "2026-08-14T10:00:00.000Z", topic: "order.ack.GW01", gateway_id: "GW01", symbol: "AAPL", order_id: "o1", payload: { status: "NEW", side: "BUY" } },
      ],
    };
  }
  return {};
});

vi.mock("@/api/apiFetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...(args as [string])),
  ApiError: class ApiError extends Error {
    constructor(public status = 0, public code = "UNKNOWN", message = "") {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { AdminMonitorPage } from "@/pages/AdminMonitorPage";
import { useMonitorStore } from "@/store/useMonitorStore";
import type { MonitorEvent } from "@/types/index";

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function ev(patch: Partial<MonitorEvent> & { id: string; kind: MonitorEvent["kind"] }): MonitorEvent {
  return {
    seq: 1,
    ts: "2026-08-14T10:00:00.000Z",
    topic: "",
    gateway_id: "GW01",
    symbol: "AAPL",
    order_id: null,
    detail: "",
    ...patch,
  };
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  useMonitorStore.setState({
    orders: {},
    lastSeq: {},
    snapshotAt: Date.now(),
    events: [
      ev({ id: "1", kind: "FILL", order_id: "o1", detail: "40 @ 150", symbol: "AAPL", gateway_id: "GW01" }),
      ev({ id: "2", kind: "REJECT", order_id: "o2", detail: "collar breach", symbol: "MSFT", gateway_id: "GW02" }),
      ev({ id: "3", kind: "SESSION", order_id: null, detail: "→ CONTINUOUS", symbol: null, gateway_id: null }),
    ],
  });
});

describe("AdminMonitorPage (§15.9)", () => {
  it("renders all events by default", () => {
    wrap(<AdminMonitorPage />);
    expect(screen.getByText("40 @ 150")).toBeTruthy();
    expect(screen.getByText("collar breach")).toBeTruthy();
    expect(screen.getByText("→ CONTINUOUS")).toBeTruthy();
  });

  it("filters by event kind", () => {
    wrap(<AdminMonitorPage />);
    fireEvent.change(screen.getByLabelText("Filter event type"), { target: { value: "REJECT" } });
    expect(screen.queryByText("40 @ 150")).toBeNull();
    expect(screen.getByText("collar breach")).toBeTruthy();
  });

  it("filters by gateway", () => {
    wrap(<AdminMonitorPage />);
    fireEvent.change(screen.getByLabelText("Filter gateway"), { target: { value: "GW02" } });
    expect(screen.getByText("collar breach")).toBeTruthy();
    expect(screen.queryByText("40 @ 150")).toBeNull();
  });

  it("opens the cross-gateway audit drill-down when an order row is clicked", async () => {
    wrap(<AdminMonitorPage />);
    fireEvent.click(screen.getByText("40 @ 150"));
    await waitFor(() =>
      expect(apiFetchMock.mock.calls.some(([p]) => String(p).startsWith("/api/v1/admin/orders/o1"))).toBe(true),
    );
    // The audit event's topic renders in the modal.
    await waitFor(() => expect(screen.getByText("order.ack.GW01")).toBeTruthy());
  });
});
