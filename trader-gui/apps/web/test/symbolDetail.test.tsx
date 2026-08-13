// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// Lightweight Charts needs real canvas/layout that jsdom lacks; stub it so the
// Chart tab mounts without touching a canvas.
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

// The network boundary. Every endpoint funnels through apiFetch; returning an
// empty object is safe because every consumer guards with optional chaining.
vi.mock("@/api/apiFetch", () => ({
  apiFetch: vi.fn(async () => ({})),
  ApiError: class ApiError extends Error {
    status = 0;
  },
}));

import { SymbolDetailPanel } from "@/components/symbol/SymbolDetailPanel";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore";
import { useSymbolDetailStore } from "@/store/useSymbolDetailStore";
import { useBookStore } from "@/store/useBookStore";
import { useSymbolStore } from "@/store/useSymbolStore";
import { useSessionStore } from "@/store/useSessionStore";
import { useTicketPrefillStore } from "@/store/useTicketPrefillStore";
import type { BookEntry } from "@/store/useBookStore";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

function seedBook(): void {
  const entry: BookEntry = {
    symbol: "AAPL",
    bids: [
      { price: 150.0, qty: 100, count: 1 },
      { price: 149.9, qty: 50, count: 2 },
    ],
    asks: [
      { price: 150.1, qty: 80, count: 1 },
      { price: 150.2, qty: 120, count: 3 },
    ],
    depth: null,
    lastPrice: 150.05,
    lastQty: 10,
    lastBuyPrice: 150.05,
    lastSellPrice: 149.95,
    recentTrades: [],
    liveVolume: 0,
    tickDecimals: 2,
    auction: null,
    updatedAt: Date.now(),
  };
  useBookStore.setState({ books: { AAPL: entry } });
}

function renderPanel(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  render(<SymbolDetailPanel />, { wrapper: Wrapper });
}

beforeEach(() => {
  cleanup();
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  useSymbolStore.setState({
    symbols: [
      { symbol: "AAPL", tick_decimals: 2, prev_close: null, reference_price: null, level: null },
    ],
  });
  useSessionStore.setState({
    phase: "CONTINUOUS",
    prevPhase: null,
    phaseSince: null,
    nextTransitionAt: null,
  });
  seedBook();
  useTicketPrefillStore.setState({ prefill: null });
  useActiveSymbolStore.setState({ activeSymbol: "AAPL" });
  useSymbolDetailStore.setState({ isOpen: true });
});

describe("SymbolDetailPanel", () => {
  it("does not render when closed", () => {
    useSymbolDetailStore.setState({ isOpen: false });
    renderPanel();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders the header and all five tabs when open", () => {
    renderPanel();
    const panel = screen.getByRole("dialog", { name: /AAPL detail/i });
    expect(panel).toBeTruthy();
    for (const label of ["Chart", "Depth", "Trades", "Stats", "Auction"]) {
      expect(screen.getByRole("tab", { name: new RegExp(label) })).toBeTruthy();
    }
    // Live last price from the seeded book.
    expect(screen.getByText("150.05")).toBeTruthy();
  });

  it("defaults to the Chart tab", () => {
    renderPanel();
    expect(screen.getByRole("tab", { name: /Chart/ }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("symbol-chart")).toBeTruthy();
  });

  it("switches to the Depth tab and shows the ladder", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("tab", { name: /Depth/ }));
    // The bid level's click-to-trade button is titled by its suggested action.
    expect(screen.getByTitle("Sell at 150.00")).toBeTruthy();
    expect(screen.getByTitle("Buy at 150.10")).toBeTruthy();
  });

  it("prefills a SELL at the bid price when a bid level is clicked", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("tab", { name: /Depth/ }));
    fireEvent.click(screen.getByTitle("Sell at 150.00"));
    const prefill = useTicketPrefillStore.getState().prefill;
    expect(prefill).toMatchObject({ symbol: "AAPL", price: 150.0, side: "SELL" });
  });

  it("prefills a BUY at the ask price when an ask level is clicked", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("tab", { name: /Depth/ }));
    fireEvent.click(screen.getByTitle("Buy at 150.10"));
    expect(useTicketPrefillStore.getState().prefill).toMatchObject({
      symbol: "AAPL",
      price: 150.1,
      side: "BUY",
    });
  });

  it("shows an amber dot on the Auction tab during a call phase", () => {
    useSessionStore.setState({ phase: "OPENING_AUCTION" });
    renderPanel();
    const auctionTab = screen.getByRole("tab", { name: /Auction/ });
    expect(auctionTab.querySelector('[aria-label="auction in progress"]')).not.toBeNull();
  });

  it("closes when the close button is clicked", () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText("Close symbol detail"));
    expect(useSymbolDetailStore.getState().isOpen).toBe(false);
  });
});
