// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const apiFetchMock = vi.fn(async (path: string, _init?: { body?: string }) => {
  if (path.startsWith("/api/v1/positions")) {
    return {
      positions: [
        { symbol: "AAPL", net_qty: 500, last_price: 151.2 },
        { symbol: "MSFT", net_qty: -200, last_price: 410.0 },
      ],
    };
  }
  if (path.startsWith("/api/v1/orders")) {
    return { order_id: "flat-1", status: "PENDING", accepted: null, event: null };
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

import { PositionPanel } from "@/components/orders/PositionPanel";
import { useSessionStore } from "@/store/useSessionStore";
import { useSymbolStore } from "@/store/useSymbolStore";
import { useBookStore } from "@/store/useBookStore";
import { useSettingsStore } from "@/store/useSettingsStore";
import type { Symbol } from "@/types/index";

const SYMBOLS: Symbol[] = [
  { symbol: "AAPL", tick_decimals: 2, prev_close: 150, collar_reference_price: null, level: null },
  { symbol: "MSFT", tick_decimals: 2, prev_close: 410, collar_reference_price: null, level: null },
];

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function orderBody(): Record<string, unknown> {
  const call = apiFetchMock.mock.calls.find(([p]) => String(p).startsWith("/api/v1/orders")) as
    | [string, { body: string }]
    | undefined;
  return JSON.parse(call![1].body);
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  useSymbolStore.setState({ symbols: SYMBOLS });
  useBookStore.setState({ books: {} });
  useSessionStore.setState({ phase: "CONTINUOUS" });
  useSettingsStore.setState({ confirmCancellations: true });
});

describe("PositionPanel (§13.6)", () => {
  it("renders net positions with signed quantity", async () => {
    wrap(<PositionPanel />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeTruthy());
    expect(screen.getByText("+500")).toBeTruthy();
    expect(screen.getByText("-200")).toBeTruthy();
  });

  it("renders the empty state when there are no positions", async () => {
    apiFetchMock.mockImplementationOnce(async (path: string) => {
      if (path.startsWith("/api/v1/positions")) return { positions: [] };
      return {};
    });

    wrap(<PositionPanel />);
    await waitFor(() => expect(screen.getByText("No open positions.")).toBeTruthy());
    expect(screen.getByText(/0\s+symbols/)).toBeTruthy();
  });

  it("flatten a long submits a SELL MARKET for abs(qty) after confirmation", async () => {
    wrap(<PositionPanel />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Flatten AAPL" }));
    // Confirmation dialog spells out the resolved side/qty.
    expect(screen.getByText(/Flatten AAPL: SELL 500 MARKET/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Flatten" }));
    await waitFor(() =>
      expect(apiFetchMock.mock.calls.some(([p]) => String(p).startsWith("/api/v1/orders"))).toBe(
        true,
      ),
    );
    expect(orderBody()).toMatchObject({
      symbol: "AAPL",
      side: "SELL",
      order_type: "MARKET",
      quantity: 500,
      tif: "DAY",
    });
  });

  it("disables flatten actions outside CONTINUOUS", async () => {
    useSessionStore.setState({ phase: "CLOSED" });
    wrap(<PositionPanel />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Flatten AAPL" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Flatten All" })).toHaveProperty("disabled", true);
    expect(screen.getByText(/only accepted during continuous trading/)).toBeTruthy();
  });

  it("Flatten All always confirms, then submits a close per non-zero position", async () => {
    // Even in power-user mode (confirmations off), Flatten All must confirm.
    useSettingsStore.setState({ confirmCancellations: false });
    wrap(<PositionPanel />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Flatten All" }));
    const dialog = screen.getByRole("dialog", { name: "Flatten all positions?" });
    expect(within(dialog).getByText(/Flatten all positions/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Flatten All" }));
    await waitFor(() => {
      const orderCalls = apiFetchMock.mock.calls.filter(([p]) =>
        String(p).startsWith("/api/v1/orders"),
      );
      expect(orderCalls.length).toBe(2); // one MARKET close per non-zero position
    });
  });

  it("in power-user mode a per-row flatten fires immediately with no dialog", async () => {
    useSettingsStore.setState({ confirmCancellations: false });
    wrap(<PositionPanel />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Flatten AAPL" }));
    await waitFor(() =>
      expect(apiFetchMock.mock.calls.some(([p]) => String(p).startsWith("/api/v1/orders"))).toBe(
        true,
      ),
    );
    // No confirmation dialog text should have appeared.
    expect(screen.queryByText(/Flatten AAPL: SELL 500 MARKET/)).toBeNull();
  });
});
