// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ServerFrame } from "@edumatcher/terminal-types";

const dailyBars = vi.fn();
vi.mock("../src/lib/api.js", () => ({ api: { dailyBars: () => dailyBars() } }));

const { useLiveStore } = await import("../src/store/useLiveStore.js");
const { usePrefsStore } = await import("../src/store/usePrefsStore.js");
const { OverviewView } = await import("../src/views/Overview.js");

const apply = (...frames: ServerFrame[]) => {
  for (const frame of frames) useLiveStore.getState().applyFrame(frame);
};

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OverviewView />
    </QueryClientProvider>,
  );
}

const hello = (symbols: string[]): ServerFrame => ({
  type: "hello",
  symbols,
  indexes: [],
  calf: "ACTIVE",
  gateway: "md-gwy01",
});

beforeEach(() => {
  localStorage.clear();
  useLiveStore.getState().reset();
  usePrefsStore.setState({ density: "standard", watchlist: [], overviewFilter: "all", pageDelaySec: null });
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
});
afterEach(cleanup);

describe("grid content", () => {
  it("lists the gateway's symbols", async () => {
    apply(hello(["AAPL", "MSFT"]));
    show();

    expect(await screen.findByText("AAPL")).toBeDefined();
    expect(screen.getByText("MSFT")).toBeDefined();
  });

  it("shows the last price from the top-of-book frame", async () => {
    apply(hello(["AAPL"]), { type: "top", sym: "AAPL", seq: 1, ts: "t", last: 150.12 });
    show();

    expect(await screen.findByText("150.12")).toBeDefined();
  });

  it("computes change against the open from the history row", async () => {
    apply(hello(["AAPL"]), { type: "top", sym: "AAPL", seq: 1, ts: "t", last: 150.12 });
    show();

    expect(await screen.findByText("+0.42")).toBeDefined();
    expect(screen.getByText("+0.28%")).toBeDefined();
  });

  it("dashes change for a symbol with no history row rather than showing zero", async () => {
    apply(hello(["MSFT"]), { type: "top", sym: "MSFT", seq: 1, ts: "t", last: 421 });
    show();

    await screen.findByText("MSFT");
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("badges a halted symbol", async () => {
    apply(hello(["TSLA"]), { type: "state", sym: "TSLA", seq: 1, ts: "t", session: "HALTED" });
    show();

    expect(await screen.findByText("HALT")).toBeDefined();
  });

  it("keeps live prices when the history service is unreachable", async () => {
    dailyBars.mockRejectedValue(new Error("upstream unavailable"));
    apply(hello(["AAPL"]), { type: "top", sym: "AAPL", seq: 1, ts: "t", last: 150.12 });
    show();

    expect(await screen.findByText("150.12")).toBeDefined();
    await waitFor(() => expect(screen.getByText(/history service is not reachable/)).toBeDefined());
  });
});

describe("watchlist", () => {
  it("pins a symbol and persists it", async () => {
    const user = userEvent.setup();
    apply(hello(["AAPL", "MSFT"]));
    show();

    await user.click(await screen.findByLabelText("Pin AAPL"));

    expect(usePrefsStore.getState().watchlist).toEqual(["AAPL"]);
    expect(localStorage.getItem("terminal-prefs")).toContain("AAPL");
  });

  it("unpins on a second click", async () => {
    const user = userEvent.setup();
    apply(hello(["AAPL"]));
    show();

    await user.click(await screen.findByLabelText("Pin AAPL"));
    await user.click(await screen.findByLabelText("Unpin AAPL"));

    expect(usePrefsStore.getState().watchlist).toEqual([]);
  });

  it("narrows the grid to pinned symbols", async () => {
    const user = userEvent.setup();
    usePrefsStore.setState({ watchlist: ["MSFT"] });
    apply(hello(["AAPL", "MSFT"]));
    show();

    await user.click(screen.getByRole("button", { name: /☆ 1/ }));

    expect(screen.queryByText("AAPL")).toBeNull();
    expect(screen.getByText("MSFT")).toBeDefined();
  });

  it("explains an empty watchlist rather than showing a blank grid", async () => {
    const user = userEvent.setup();
    apply(hello(["AAPL"]));
    show();

    await user.click(screen.getByRole("button", { name: /☆ 0/ }));

    expect(screen.getByText(/No symbols pinned yet/)).toBeDefined();
  });
});

describe("density", () => {
  it("drops to four columns for a lobby display", async () => {
    usePrefsStore.setState({ density: "lobby" });
    apply(hello(["AAPL"]));
    show();

    await screen.findByText("AAPL");
    expect(screen.queryByText("Bid")).toBeNull();
    expect(screen.getByText("Volume")).toBeDefined();
  });

  it("shows bid and ask at standard density", async () => {
    apply(hello(["AAPL"]));
    show();

    expect(await screen.findByText("Bid")).toBeDefined();
    expect(screen.getByText("Ask")).toBeDefined();
  });
});

describe("paging controls", () => {
  it("reports a single page for a small symbol list", async () => {
    apply(hello(["AAPL", "MSFT"]));
    show();

    expect(await screen.findByText("Page 1/1")).toBeDefined();
    expect(screen.getByText("single page")).toBeDefined();
  });

  it("pauses and resumes on the control", async () => {
    const user = userEvent.setup();
    apply(hello(["AAPL"]));
    show();

    await user.click(await screen.findByLabelText("Pause paging"));
    expect(screen.getByLabelText("Resume paging")).toBeDefined();
  });
});
