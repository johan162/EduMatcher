// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ServerFrame } from "@edumatcher/terminal-types";

const dailyBars = vi.fn();
const dailyWindow = vi.fn();
vi.mock("../src/lib/api.js", () => ({
  api: { dailyBars: () => dailyBars(), dailyWindow: () => dailyWindow() },
}));

const { useLiveStore } = await import("../src/store/useLiveStore.js");
const { MoversView } = await import("../src/views/Movers.js");

const apply = (...frames: ServerFrame[]) => {
  for (const frame of frames) useLiveStore.getState().applyFrame(frame);
};

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MoversView />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useLiveStore.getState().reset();
  dailyBars.mockResolvedValue({
    daily: [
      {
        date: "2026-07-30",
        symbol: "AAPL",
        open_price: 149.7,
        volume: 184300,
        close_price: null,
        high_price: null,
        low_price: null,
        vwap: null,
        trade_count: null,
      },
    ],
  });
  dailyWindow.mockResolvedValue({
    daily: [
      {
        date: "2026-07-29",
        symbol: "AAPL",
        open_price: 147.0,
        close_price: 148.0,
        high_price: 149.0,
        low_price: 146.5,
        vwap: 147.8,
        volume: 150000,
        trade_count: 900,
      },
      {
        date: "2026-07-30",
        symbol: "AAPL",
        open_price: 149.7,
        close_price: null,
        high_price: null,
        low_price: null,
        vwap: null,
        volume: 184300,
        trade_count: null,
      },
    ],
  });
});
afterEach(cleanup);

describe("outage banner", () => {
  it("stays quiet while both history feeds are healthy", async () => {
    apply({ type: "hello", symbols: ["AAPL"], tickDecimals: {}, indexes: [], calf: "ACTIVE", gateway: "gw" });
    apply({ type: "top", sym: "AAPL", seq: 1, ts: "t", last: 150.12 });
    show();

    await screen.findByText("AAPL");
    expect(screen.queryByText(/history service is not reachable/)).toBeNull();
  });

  it("banners when the daily rollup fails", async () => {
    dailyBars.mockRejectedValue(new Error("upstream unavailable"));
    apply({ type: "hello", symbols: ["AAPL"], tickDecimals: {}, indexes: [], calf: "ACTIVE", gateway: "gw" });
    apply({ type: "top", sym: "AAPL", seq: 1, ts: "t", last: 150.12 });
    show();

    await waitFor(() => expect(screen.getByText(/history service is not reachable/)).toBeDefined());
  });

  it("says the ranking changed meaning when only the previous-close window fails", async () => {
    // Regression for T-H1: every ranking here silently switches to the open
    // baseline when this feed goes down. "Unavailable" would be false — the
    // list is still there, it is just a different list, and the header that
    // names the baseline has to follow it.
    dailyWindow.mockRejectedValue(new Error("upstream unavailable"));
    apply({ type: "hello", symbols: ["AAPL"], tickDecimals: {}, indexes: [], calf: "ACTIVE", gateway: "gw" });
    apply({ type: "top", sym: "AAPL", seq: 1, ts: "t", last: 150.12 });
    show();

    await waitFor(() => expect(screen.getByText(/previous closes are unavailable/)).toBeDefined());
    expect(screen.getByText("vs today's open")).toBeDefined();
    expect(screen.queryByText("vs previous close")).toBeNull();
  });
});
