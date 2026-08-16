// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const apiFetchMock = vi.fn(async (path: string) => {
  if (path.startsWith("/api/v1/quotes/bootstrap")) {
    return {
      quotes: [
        {
          quote_id: "mm-aapl-1",
          gateway_id: "MM",
          symbol: "AAPL",
          state: "ACTIVE",
          bid_order_id: "b1",
          ask_order_id: "a1",
          bid_price: 149.9,
          ask_price: 150.1,
          bid_qty: 500,
          ask_qty: 500,
          bid_remaining_qty: 300,
          ask_remaining_qty: 500,
          bid_status: "RESTING",
          ask_status: "RESTING",
        },
      ],
    };
  }
  if (path.startsWith("/api/v1/quotes/legs")) {
    return {
      // A full QuoteLeg (engine path) plus a degraded quote-level cache dict.
      legs: [
        {
          quote_id: "mm-aapl-1",
          order_id: "b1",
          symbol: "AAPL",
          leg_side: "BUY",
          qty: 500,
          remaining: 300,
          filled: 200,
          status: "PARTIAL",
          quote_status: "ACTIVE",
          price: 149.9,
        },
        { quote_id: "mm-msft-1", accepted: true, reason: "", bid_order_id: "b", ask_order_id: "a", status: "ACTIVE" },
      ],
      show_requested: "ACTIVE",
      complete: true,
      recent: [],
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

import { QuoteBootstrapPage } from "@/pages/QuoteBootstrapPage";
import { useSymbolStore } from "@/store/useSymbolStore";
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
});

describe("QuoteBootstrapPage (§14.3)", () => {
  it("renders the ActiveQuote row with per-side price/qty/remaining", async () => {
    wrap(<QuoteBootstrapPage />);
    // The combined "price × qty" cell is unique to the bootstrap table.
    await waitFor(() => expect(screen.getByText(/149\.90 × 500/)).toBeTruthy());
    expect(screen.getByText(/300 rem/)).toBeTruthy();
    expect(screen.getAllByText("mm-aapl-1").length).toBeGreaterThan(0);
  });

  it("renders full leg rows and flags the degraded quote-level rows", async () => {
    wrap(<QuoteBootstrapPage />);
    await waitFor(() => expect(screen.getByText("b1")).toBeTruthy()); // leg order id
    // The warm-cache quote-level row produces the explanatory note.
    expect(screen.getByText(/quote-level status only/)).toBeTruthy();
  });
});
