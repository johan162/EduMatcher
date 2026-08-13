// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("lightweight-charts", () => {
  const series = { setData: vi.fn(), update: vi.fn() };
  const chart = {
    addSeries: vi.fn(() => series),
    removeSeries: vi.fn(),
    applyOptions: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    remove: vi.fn(),
  };
  return {
    createChart: vi.fn(() => chart),
    CandlestickSeries: "Candlestick",
    LineSeries: "Line",
    ColorType: { Solid: "solid" },
    CrosshairMode: { Normal: 0 },
  };
});

vi.mock("@/api/apiFetch", () => ({
  apiFetch: vi.fn(async () => ({})),
  ApiError: class ApiError extends Error {
    status = 0;
    code = "UNKNOWN";
  },
}));

import { TradingWorkspacePage } from "@/pages/TradingWorkspacePage";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore";
import { useBookStore } from "@/store/useBookStore";
import { useSymbolStore } from "@/store/useSymbolStore";
import { useTicketPrefillStore } from "@/store/useTicketPrefillStore";
import type { BookEntry } from "@/store/useBookStore";
import type { Symbol } from "@/types/index";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const SYMBOLS: Symbol[] = [
  { symbol: "AAPL", tick_decimals: 2, prev_close: null, collar_reference_price: null, level: null },
  { symbol: "MSFT", tick_decimals: 2, prev_close: null, collar_reference_price: null, level: null },
];

function bookEntry(symbol: string): BookEntry {
  return {
    symbol,
    bids: [{ price: 150.0, qty: 100, count: 1 }],
    asks: [{ price: 150.1, qty: 80, count: 2 }],
    depth: null,
    lastPrice: 150.05,
    lastQty: 10,
    lastBuyPrice: null,
    lastSellPrice: null,
    recentTrades: [],
    liveVolume: 0,
    tickDecimals: 2,
    auction: null,
    updatedAt: Date.now(),
  };
}

function renderWorkspace(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  render(<TradingWorkspacePage />, { wrapper: Wrapper });
}

beforeEach(() => {
  cleanup();
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  useSymbolStore.setState({ symbols: SYMBOLS });
  useBookStore.setState({ books: { AAPL: bookEntry("AAPL"), MSFT: bookEntry("MSFT") } });
  useTicketPrefillStore.setState({ prefill: null });
  useActiveSymbolStore.setState({ activeSymbol: "AAPL" });
});

describe("TradingWorkspacePage", () => {
  it("renders all four quadrants bound to the active symbol", () => {
    renderWorkspace();
    expect(screen.getByLabelText("Price chart")).toBeTruthy();
    expect(screen.getByLabelText("Depth of market")).toBeTruthy();
    expect(screen.getByLabelText("Order ticket")).toBeTruthy();
    expect(screen.getByLabelText("Working orders")).toBeTruthy();
    // Ticket action buttons.
    expect(screen.getByRole("button", { name: "BUY" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "SELL" })).toBeTruthy();
  });

  it("pre-fills the ticket price when a DOM bid level is clicked (§11.4)", () => {
    renderWorkspace();
    // The bid level offers a SELL (you hit the bid).
    fireEvent.click(screen.getByTitle("Sell at 150.00"));
    const price = screen.getByLabelText("Price") as HTMLInputElement;
    expect(price.value).toBe("150.00");
    // Suggested side is SELL — its button is highlighted.
    expect(screen.getByRole("button", { name: "SELL" }).className).toContain("ring-2");
  });

  it("pre-fills a BUY at the ask price when an ask level is clicked", () => {
    renderWorkspace();
    fireEvent.click(screen.getByTitle("Buy at 150.10"));
    const price = screen.getByLabelText("Price") as HTMLInputElement;
    expect(price.value).toBe("150.10");
    expect(useTicketPrefillStore.getState().prefill).toMatchObject({
      symbol: "AAPL",
      price: 150.1,
      side: "BUY",
    });
  });

  it("re-binds every panel when the active symbol changes", () => {
    renderWorkspace();
    fireEvent.change(screen.getByLabelText("Active symbol"), { target: { value: "MSFT" } });
    expect(useActiveSymbolStore.getState().activeSymbol).toBe("MSFT");
  });

  it("adopts the first symbol when none is active", () => {
    useActiveSymbolStore.setState({ activeSymbol: null });
    renderWorkspace();
    expect(useActiveSymbolStore.getState().activeSymbol).toBe("AAPL");
  });
});
