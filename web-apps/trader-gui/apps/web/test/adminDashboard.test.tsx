// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const apiFetchMock = vi.fn(async (path: string) => {
  if (path.startsWith("/api/v1/admin/gateways")) {
    return {
      gateways: [
        { id: "GW01", role: "TRADER", connected: true, description: "Desk A" },
        { id: "MM", role: "MARKET_MAKER", connected: true, description: "House MM" },
        { id: "GW09", role: "ADMIN", connected: false, description: "Console" },
      ],
    };
  }
  if (path.startsWith("/api/v1/admin/halts")) return { halted: [{ symbol: "TSLA", level: "2" }] };
  if (path.startsWith("/api/v1/history/daily")) return { daily: [], has_more: false };
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

import { AdminDashboardPage } from "@/pages/AdminDashboardPage";
import { useMonitorStore } from "@/store/useMonitorStore";
import { useSymbolStore } from "@/store/useSymbolStore";
import { useSessionStore } from "@/store/useSessionStore";
import { useHaltStore } from "@/store/useHaltStore";
import type { Symbol } from "@/types/index";

const SYMBOLS: Symbol[] = [
  { symbol: "AAPL", tick_decimals: 2, prev_close: 150, collar_reference_price: null, level: null },
];

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  useSymbolStore.setState({ symbols: SYMBOLS });
  useSessionStore.setState({ phase: "CONTINUOUS" });
  useHaltStore.setState({ halts: {} });
  useMonitorStore.setState({
    orders: {
      o1: { order_id: "o1", gateway_id: "GW01", status: "NEW", symbol: "AAPL" },
      o2: { order_id: "o2", gateway_id: "GW02", status: "FILLED", symbol: "AAPL" },
    },
    events: [
      {
        id: "e1",
        seq: 5,
        ts: "2026-08-14T10:00:00.000Z",
        kind: "FILL",
        topic: "order.fill.GW01",
        gateway_id: "GW01",
        symbol: "AAPL",
        order_id: "o1",
        detail: "40 @ 150",
      },
    ],
    lastSeq: {},
    snapshotAt: Date.now(),
  });
});

describe("AdminDashboardPage (§15.1)", () => {
  it("renders the KPI cards", async () => {
    wrap(<AdminDashboardPage />);
    expect(screen.getByText("Active Orders (all gateways)")).toBeTruthy();
    expect(screen.getByText("Connected Gateways")).toBeTruthy();
    expect(screen.getByText("Active CB Halts")).toBeTruthy();
    // Connected gateways from /admin/gateways = 2 (GW01, MM; GW09 disconnected).
    await waitFor(() => expect(screen.getByText("2")).toBeTruthy());
  });

  it("shows the per-symbol summary with a non-terminal order count", () => {
    wrap(<AdminDashboardPage />);
    // AAPL appears in both the per-symbol table and the events feed.
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    // One non-terminal AAPL order (o1 NEW; o2 FILLED is terminal).
    const ordersCell = screen.getAllByText("1");
    expect(ordersCell.length).toBeGreaterThan(0);
  });

  it("renders the recent events feed", () => {
    wrap(<AdminDashboardPage />);
    expect(screen.getByText("40 @ 150")).toBeTruthy();
  });

  it("reconciles halts from GET /admin/halts", async () => {
    wrap(<AdminDashboardPage />);
    await waitFor(() => expect(useHaltStore.getState().halts.TSLA).toBeTruthy());
  });
});
