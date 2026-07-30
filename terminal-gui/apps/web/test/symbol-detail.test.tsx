// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuctionResultFrame, ClientFrame, ServerFrame } from "@edumatcher/terminal-types";

const sent: ClientFrame[] = [];
vi.mock("../src/lib/useTerminalStream.js", () => ({
  sendControl: (frame: ClientFrame) => sent.push(frame),
  useTerminalStream: () => undefined,
}));

// Lightweight Charts needs a real canvas, which jsdom has not got. The chart's
// data preparation is covered directly in bars.test.ts, so the panel itself is
// stubbed to a marker here.
vi.mock("../src/components/PriceChart.js", () => ({
  PriceChart: () => <div data-testid="price-chart" />,
}));

vi.mock("../src/lib/api.js", () => ({
  api: {
    dailyForSymbol: async () => ({
      daily: [
        {
          date: "2026-07-30",
          symbol: "AAPL",
          open_price: 149.7,
          high_price: 152.05,
          low_price: 148.1,
          close_price: 149.7,
          vwap: 149.94,
          volume: 184300,
          trade_count: 1204,
        },
      ],
    }),
    trades: async () => ({ trades: [] }),
    dailyRange: async () => ({ daily: [] }),
    priceSnapshots: async () => ({ snapshots: [] }),
  },
}));

const { useLiveStore } = await import("../src/store/useLiveStore.js");
const { SymbolDetailView } = await import("../src/views/SymbolDetail.js");

const apply = (...frames: ServerFrame[]) => {
  for (const frame of frames) useLiveStore.getState().applyFrame(frame);
};

function show(path = "/symbol/AAPL") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/symbol" element={<SymbolDetailView />} />
          <Route path="/symbol/:sym" element={<SymbolDetailView />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  sent.length = 0;
  useLiveStore.getState().reset();
});
afterEach(cleanup);

describe("subscription lifetimes", () => {
  it("subscribes to CB for as long as the view is open", () => {
    // Halt detail is relevant to the instrument generally, not just its ladder.
    show();
    expect(sent).toEqual([{ t: "subscribe", ch: "CB", sym: "AAPL" }]);
  });

  it("releases CB on unmount", () => {
    show().unmount();
    expect(sent).toContainEqual({ t: "unsubscribe", ch: "CB", sym: "AAPL" });
  });

  it("does not subscribe to DEPTH until asked", async () => {
    // DEPTH is the heaviest channel and costs a real upstream subscription.
    show();
    expect(sent.filter((f) => "ch" in f && f.ch === "DEPTH")).toEqual([]);
  });

  it("subscribes to DEPTH when the toggle goes on", async () => {
    const user = userEvent.setup();
    show();

    await user.click(screen.getByLabelText("Depth"));

    expect(sent).toContainEqual({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });
  });

  it("releases DEPTH when the toggle goes off again, keeping CB", async () => {
    const user = userEvent.setup();
    show();

    await user.click(screen.getByLabelText("Depth"));
    await user.click(screen.getByLabelText("Depth"));

    expect(sent).toContainEqual({ t: "unsubscribe", ch: "DEPTH", sym: "AAPL" });
    expect(sent).not.toContainEqual({ t: "unsubscribe", ch: "CB", sym: "AAPL" });
  });

  it("swaps subscriptions when the symbol changes", () => {
    const view = show("/symbol/AAPL");
    view.unmount();
    show("/symbol/MSFT");

    expect(sent).toContainEqual({ t: "unsubscribe", ch: "CB", sym: "AAPL" });
    expect(sent).toContainEqual({ t: "subscribe", ch: "CB", sym: "MSFT" });
  });
});

describe("symbol picker", () => {
  it("offers the gateway's symbols when none is chosen", () => {
    apply({ type: "hello", symbols: ["AAPL", "MSFT"], indexes: [], calf: "ACTIVE", gateway: "gw" });
    show("/symbol");

    expect(screen.getByRole("button", { name: "AAPL" })).toBeDefined();
    expect(screen.getByRole("button", { name: "MSFT" })).toBeDefined();
  });

  it("says so before the symbol list has arrived", () => {
    show("/symbol");
    expect(screen.getByText(/Awaiting the symbol list/)).toBeDefined();
  });

  it("takes out no subscription while still picking", () => {
    show("/symbol");
    expect(sent).toEqual([]);
  });
});

describe("header", () => {
  it("shows the last price and change against the open", async () => {
    apply({ type: "top", sym: "AAPL", seq: 1, ts: "t", last: 150.12, bid: 150.1, ask: 150.14 });
    show();

    expect(await screen.findByText("+0.42 (+0.28%)")).toBeDefined();
  });

  it("dashes the change before any price is known", () => {
    show();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

describe("values table", () => {
  it("reads live quote fields from the book and session fields from history", async () => {
    apply({ type: "top", sym: "AAPL", seq: 1, ts: "t", last: 150.12, bid: 150.1, ask: 150.14 });
    show();

    // Wait on the value, not the cell: the row renders a dash immediately and
    // only fills once the history query settles.
    await screen.findByText("149.94");
    expect(screen.getByTestId("value-VWAP").textContent).toBe("149.94");
    expect(screen.getByTestId("value-Bid / Ask").textContent).toBe("150.10 / 150.14");
    expect(screen.getByTestId("value-Mid (live)").textContent).toBe("150.12");
  });

  it("dashes the midpoint when only one side is quoted", async () => {
    apply({ type: "top", sym: "AAPL", seq: 1, ts: "t", bid: 150.1 });
    show();

    expect((await screen.findByTestId("value-Mid (live)")).textContent).toBe("—");
  });
});

describe("halt context", () => {
  it("shows circuit-breaker detail for a halted symbol", async () => {
    apply(
      { type: "state", sym: "AAPL", seq: 1, ts: "t", session: "HALTED" },
      {
        type: "halt_context",
        sym: "AAPL",
        seq: 2,
        ts: "t",
        status: "HALTED",
        level: "L2",
        triggerPrice: 261.4,
      },
    );
    show();

    expect(await screen.findByText("Halted")).toBeDefined();
    expect(screen.getByText("Level L2")).toBeDefined();
    expect(screen.getByText(/Trigger 261.40/)).toBeDefined();
  });

  it("shows nothing extra for a symbol trading normally", () => {
    show();
    expect(screen.queryByText("Halted")).toBeNull();
  });
});

describe("auction banner", () => {
  const uncross = (sym: string): AuctionResultFrame => ({
    type: "auction_result",
    sym,
    seq: 1,
    ts: "2026-07-30T09:30:02.000Z",
    eqPrice: 149.85,
    eqQty: 12400,
    tradesCount: 38,
    imbalanceSide: "BUY",
    imbalanceQty: 1400,
  });

  it("announces this symbol's uncross", async () => {
    apply(uncross("AAPL"));
    show();

    expect(await screen.findByText("Auction uncrossed")).toBeDefined();
    expect(screen.getByText(/149.85 · 12,400 sh/)).toBeDefined();
  });

  it("names a circuit-breaker reopening rather than calling it a plain auction", async () => {
    // A reopening uncross and the scheduled closing uncross carry identical
    // fields; REASON is the only thing that distinguishes them.
    apply({ ...uncross("AAPL"), reason: "REOPEN" });
    show();

    expect(await screen.findByText("Reopening auction")).toBeDefined();
  });

  it("names the startup pass over restored GTC orders", async () => {
    apply({ ...uncross("AAPL"), reason: "RECOVERY" });
    show();

    expect(await screen.findByText("Startup uncross")).toBeDefined();
  });

  it("falls back to the generic wording when the gateway sends no reason", async () => {
    // An older gateway omits REASON entirely; the banner must still render.
    apply(uncross("AAPL"));
    show();

    expect(await screen.findByText("Auction uncrossed")).toBeDefined();
  });

  it("ignores an uncross for a different symbol", () => {
    apply(uncross("MSFT"));
    show();
    expect(screen.queryByText("Auction uncrossed")).toBeNull();
  });

  it("can be dismissed", async () => {
    const user = userEvent.setup();
    apply(uncross("AAPL"));
    show();

    await user.click(await screen.findByLabelText("Dismiss auction result"));
    expect(screen.queryByText("Auction uncrossed")).toBeNull();
  });
});

describe("depth panel", () => {
  it("explains the cost before the toggle is used", () => {
    show();
    expect(screen.getByText(/Enable the Depth toggle/)).toBeDefined();
  });

  it("waits for the first snapshot once subscribed", async () => {
    const user = userEvent.setup();
    show();

    await user.click(screen.getByLabelText("Depth"));

    expect(screen.getByText(/Awaiting the first depth snapshot/)).toBeDefined();
  });

  it("renders the ladder with per-level order counts", async () => {
    const user = userEvent.setup();
    show();
    await user.click(screen.getByLabelText("Depth"));

    apply({
      type: "depth",
      sym: "AAPL",
      seq: 1,
      ts: "t",
      levels: 10,
      bids: [
        [150.1, 1400, 4],
        [150.09, 800, 2],
      ],
      asks: [[150.12, 900, 2]],
    });

    expect(await screen.findByText("150.10")).toBeDefined();
    expect(screen.getByText("1,400")).toBeDefined();
  });

  it("does not show another symbol's ladder", async () => {
    const user = userEvent.setup();
    show();
    await user.click(screen.getByLabelText("Depth"));

    apply({ type: "depth", sym: "MSFT", seq: 1, ts: "t", levels: 10, bids: [[421, 300, 1]], asks: [] });

    expect(screen.queryByText("421.00")).toBeNull();
  });
});

describe("chart presets", () => {
  it("defaults to the intraday window", () => {
    show();
    expect(screen.getByRole("button", { name: "1D" })).toBeDefined();
  });

  it("offers every preset from the design", () => {
    show();
    for (const preset of ["1D", "5D", "1M", "3M", "YTD", "All", "Live"]) {
      expect(screen.getByRole("button", { name: preset })).toBeDefined();
    }
  });

  it("keeps series toggles independent of the timeframe", async () => {
    const user = userEvent.setup();
    show();

    await user.click(screen.getByLabelText("OHLC"));
    await user.click(screen.getByRole("button", { name: "5D" }));

    expect((screen.getByLabelText("OHLC") as HTMLInputElement).checked).toBe(false);
  });
});
