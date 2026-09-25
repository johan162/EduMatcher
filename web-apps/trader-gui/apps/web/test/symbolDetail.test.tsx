// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useThemeStore } from "@/store/useThemeStore";

// Lightweight Charts needs real canvas/layout that jsdom lacks; stub it so the
// Chart tab mounts without touching a canvas. `chartSeries` is hoisted so
// tests can assert on `update`/`setData` -- SymbolChart's live-tick tests
// need to see what the chart itself was told.
const chartSeries = vi.hoisted(() => ({
  setData: vi.fn(),
  update: vi.fn(),
  applyOptions: vi.fn(),
}));
vi.mock("lightweight-charts", () => {
  const chart = {
    addSeries: vi.fn(() => chartSeries),
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
import {
  __marketDataMessageForTest as route,
  __setMarketDataSocketForTest,
} from "@/ws/WebSocketManager";

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
      { symbol: "AAPL", tick_decimals: 2, prev_close: null, collar_reference_price: null, level: null },
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
  __setMarketDataSocketForTest(null);
  chartSeries.update.mockClear();
});

function trade(id: string, tsNs: number, price: number) {
  return {
    type: "trade",
    topic: "trade.executed",
    ts: "2026-08-12T09:30:00Z",
    seq: 1,
    data: { id, symbol: "AAPL", price, quantity: 10, tick_decimals: 2, ts_ns: tsNs },
  };
}

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

  // H2 (docs-design/reviews/EduMatcher-Trader-GUI-Review.md): a replayed
  // print (reconnect, gap repair) can land in an already-closed earlier
  // bucket. lightweight-charts' series.update requires non-decreasing time
  // and throws "Cannot update oldest data" for one that doesn't -- which,
  // pre-fix, aborted every bus listener registered after the chart (emit
  // isn't exception-isolated either -- see the WebSocketManager unit below).
  it("live tick append (Chart tab, default 5m timeframe)", () => {
    renderPanel();
    // 5m bucket = floor(epochSec / 300) * 300; 1_000s -> bucket 900.
    route(trade("t1", 1_000_000_000_000, 150.5));
    expect(chartSeries.update).toHaveBeenCalledTimes(1);

    // A replayed print landing in an earlier, already-closed bucket (0s ->
    // bucket 0) must be ignored, not passed to series.update.
    route(trade("t2", 100_000_000_000, 149.0));
    expect(chartSeries.update).toHaveBeenCalledTimes(1);

    // A later tick in the same or a newer bucket still goes through.
    route(trade("t3", 1_100_000_000_000, 150.75));
    expect(chartSeries.update).toHaveBeenCalledTimes(2);
  });

  it("recolours the chart series when the theme flips", () => {
    useThemeStore.setState({ theme: "dark" });
    renderPanel();
    chartSeries.applyOptions.mockClear();

    act(() => useThemeStore.getState().toggleTheme());

    expect(chartSeries.applyOptions).toHaveBeenCalledWith(
      expect.objectContaining({ upColor: "#15803d", downColor: "#dc2626" }),
    );
    useThemeStore.setState({ theme: "dark" });
  });
});
