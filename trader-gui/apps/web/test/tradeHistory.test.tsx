// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { WsEnvelope, WsEventType, WsDataByType } from "@/types/index";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

// Capture WS handlers so the test can drive a live order.fill.
const wsHandlers: Partial<Record<string, (env: unknown) => void>> = {};
vi.mock("@/hooks/useWsEvent", () => ({
  useWsEvent: <T extends WsEventType>(
    type: T,
    handler: (env: WsEnvelope<WsDataByType[T]>) => void,
  ) => {
    wsHandlers[type] = handler as (env: unknown) => void;
  },
}));

const apiFetchMock = vi.fn(async (path: string) => {
  if (path.startsWith("/api/v1/history/fills")) {
    return {
      count: 2,
      has_more: false,
      events: [
        {
          seq: 1,
          ts: "2026-07-27T10:00:00.000Z",
          event_type: "FILL",
          order_id: "buy-order-1",
          gateway_id: "GW1",
          symbol: "AAPL",
          side: "BUY",
          fill_qty: 40,
          fill_price: 150.5,
          remaining_qty: 60,
          trade_id: "t-1",
        },
        {
          seq: 2,
          ts: "2026-07-27T10:01:00.000Z",
          event_type: "FILL",
          order_id: "sell-order-2",
          gateway_id: "GW1",
          symbol: "AAPL",
          side: "SELL",
          fill_qty: 25,
          fill_price: 151.0,
          remaining_qty: 0,
          trade_id: "t-2",
        },
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

import { TradeHistoryPage } from "@/pages/TradeHistoryPage";
import { useSymbolStore } from "@/store/useSymbolStore";
import { useBookStore } from "@/store/useBookStore";
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
  for (const k of Object.keys(wsHandlers)) delete wsHandlers[k];
  useSymbolStore.setState({ symbols: SYMBOLS });
  useBookStore.setState({ books: {} });
});

describe("TradeHistoryPage (§13.5)", () => {
  it("renders fill rows from GET /history/fills", async () => {
    wrap(<TradeHistoryPage />);
    await waitFor(() => expect(screen.getByText("t-1")).toBeTruthy());
    expect(screen.getByText("t-2")).toBeTruthy();
    // Order IDs render as short (8-char) links.
    expect(screen.getByText("buy-orde")).toBeTruthy();
  });

  it("filters by side client-side", async () => {
    wrap(<TradeHistoryPage />);
    await waitFor(() => expect(screen.getByText("t-1")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Filter side"), { target: { value: "SELL" } });
    expect(screen.queryByText("t-1")).toBeNull(); // the BUY fill is filtered out
    expect(screen.getByText("t-2")).toBeTruthy();
  });

  it("prepends a live order.fill row with a +N badge for a swept fill", async () => {
    wrap(<TradeHistoryPage />);
    await waitFor(() => expect(screen.getByText("t-1")).toBeTruthy());
    act(() => {
      wsHandlers["order.fill"]!({
        data: {
          gateway_id: "GW1",
          order_id: "live-order-9",
          symbol: "AAPL",
          side: "BUY",
          fill_qty: 10,
          fill_price: 150.0,
          remaining_qty: 0,
          status: "FILLED",
          trade_ids: ["t-live-a", "t-live-b"],
        },
      });
    });
    await waitFor(() => expect(screen.getByText("live-ord")).toBeTruthy());
    expect(screen.getByText("+1")).toBeTruthy(); // 2 trade ids → +1 badge
  });
});
