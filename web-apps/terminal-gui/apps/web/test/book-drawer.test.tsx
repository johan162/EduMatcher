// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ServerFrame } from "@edumatcher/terminal-types";

vi.mock("../src/components/MinuteBars.js", () => ({
  MinuteBars: ({ label, points }: { label: string; points: unknown[] }) => (
    <figure aria-label={label} data-points={points.length} />
  ),
}));
const trades = vi.fn();
vi.mock("../src/lib/api.js", () => ({
  api: {
    dailyBars: () =>
      Promise.resolve({
        daily: [
          {
            date: "2026-07-30",
            symbol: "AAPL",
            open_price: 149.7,
            volume: 184300,
            close_price: null,
            high_price: null,
            low_price: null,
            vwap: 150,
            trade_count: 321,
          },
        ],
      }),
    dailyWindow: () => Promise.resolve({ daily: [] }),
    trades: (...args: unknown[]) => trades(...args),
  },
}));

const { useLiveStore } = await import("../src/store/useLiveStore.js");
const { OverviewView } = await import("../src/views/Overview.js");

const hello: ServerFrame = {
  type: "hello",
  symbols: ["AAPL", "MSFT"],
  tickDecimals: {},
  indexes: [],
  sessionTimezone: "Europe/Stockholm",
  calf: "ACTIVE",
  gateway: "md-gwy01",
};

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <OverviewView />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  useLiveStore.getState().reset();
  trades.mockResolvedValue({
    trades: [
      { ts: "2026-07-30T10:00:05Z", trade_id: "1", symbol: "AAPL", price: 150, quantity: 10, buy_gateway_id: null, sell_gateway_id: null },
    ],
  });
  useLiveStore.getState().applyFrame(hello);
  useLiveStore
    .getState()
    .applyFrame({ type: "top", sym: "AAPL", seq: 1, ts: "t", last: 150.12, bid: 150.1, bidSz: 200, ask: 150.15, askSz: 300 });
});
afterEach(cleanup);

describe("the book drawer", () => {
  it("opens from a row with the symbol's figures and its per-minute charts", async () => {
    show();
    await userEvent.click(await screen.findByText("AAPL"));

    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByRole("heading", { name: "AAPL" })).toBeDefined();
    const figures = within(drawer).getByLabelText("Book figures");
    expect(within(figures).getByText("150.12")).toBeDefined();
    expect(within(figures).getByText("150.10 × 200")).toBeDefined();
    expect(within(figures).getByText("150.15 × 300")).toBeDefined();
    await waitFor(() => expect(within(figures).getByText("321")).toBeDefined());
    await waitFor(() =>
      expect(within(drawer).getByLabelText("Trades per minute").getAttribute("data-points")).toBe("1"),
    );
    expect(within(drawer).getByLabelText("Traded value per minute")).toBeDefined();
  });

  it("leaves out the operator figures", async () => {
    show();
    await userEvent.click(await screen.findByText("AAPL"));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).queryByText(/heap garbage/i)).toBeNull();
    expect(within(drawer).queryByLabelText(/events/i)).toBeNull();
    expect(within(drawer).queryByText(/memory/i)).toBeNull();
  });

  it("shows another symbol when another row is clicked, and closes on Escape", async () => {
    show();
    await userEvent.click(await screen.findByText("AAPL"));
    await userEvent.click(screen.getByText("MSFT"));
    expect(within(await screen.findByRole("dialog")).getByRole("heading", { name: "MSFT" })).toBeDefined();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("pinning a row does not open the drawer", async () => {
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Pin AAPL" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
