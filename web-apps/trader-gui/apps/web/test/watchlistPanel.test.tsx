// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const apiFetchMock = vi.fn(async (path: string) => {
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

import { WatchlistPanel } from "@/components/watchlist/WatchlistPanel";
import { useSymbolStore } from "@/store/useSymbolStore";
import { useWatchlistStore } from "@/store/useWatchlistStore";
import { useSymbolDetailStore } from "@/store/useSymbolDetailStore";
import type { Symbol } from "@/types/index";

const SYMBOLS: Symbol[] = [
  { symbol: "AAPL", tick_decimals: 2, prev_close: 150, collar_reference_price: null, level: null },
  { symbol: "MSFT", tick_decimals: 2, prev_close: 410, collar_reference_price: null, level: null },
];

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  useSymbolStore.setState({ symbols: SYMBOLS });
  useWatchlistStore.setState({ symbols: [] });
});

describe("WatchlistPanel (§20.4)", () => {
  it("shows an empty state with guidance when nothing is starred", () => {
    wrap(<WatchlistPanel />);
    expect(screen.getByText(/Your watchlist is empty/)).toBeTruthy();
  });

  it("renders only the watched symbols", async () => {
    useWatchlistStore.setState({ symbols: ["AAPL"] });
    wrap(<WatchlistPanel />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeTruthy());
    expect(screen.queryByText("MSFT")).toBeNull();
    // The star reflects membership and can remove it.
    expect(screen.getByRole("button", { name: "Remove AAPL from watchlist" })).toBeTruthy();
  });

  it("clicking a row opens Symbol Detail for that symbol", async () => {
    useWatchlistStore.setState({ symbols: ["AAPL"] });
    wrap(<WatchlistPanel />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeTruthy());
    screen.getByText("AAPL").click();
    expect(useSymbolDetailStore.getState().isOpen).toBe(true);
  });
});
