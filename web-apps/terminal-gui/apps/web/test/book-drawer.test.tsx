// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
const company = vi.fn();
/** Every nullable field of a CompanyProfile, as the gateway sends it when the database has nothing. */
const COMPANY_FIELDS = [
  "headquarters",
  "purpose",
  "key_market",
  "market_position",
  "origin",
  "founders",
  "founder_story",
  "founded_year",
  "ipo_year",
  "ipo_valuation_musd",
  "ceo_name",
  "ceo_since",
  "ceo_industry_years",
  "employees",
  "fiscal_year",
  "revenue_musd",
  "net_income_musd",
  "revenue_growth_pct",
  "operating_margin_pct",
  "free_cash_flow_musd",
  "market_cap_musd",
  "dividend_yield_pct",
  "debt_to_equity",
  "credit_rating",
  "competitors",
  "key_risk",
  "years_in_business",
  "ceo_tenure_years",
  "pe_ratio",
  "ps_ratio",
  "net_margin_pct",
];
vi.mock("../src/lib/api.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/lib/api.js")>()),
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
    company: (...args: unknown[]) => company(...args),
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
      {
        ts: "2026-07-30T10:00:05Z",
        trade_id: "1",
        symbol: "AAPL",
        price: 150,
        quantity: 10,
        buy_gateway_id: null,
        sell_gateway_id: null,
      },
    ],
  });
  useLiveStore.getState().applyFrame(hello);
  useLiveStore
    .getState()
    .applyFrame({
      type: "top",
      sym: "AAPL",
      seq: 1,
      ts: "t",
      last: 150.12,
      bid: 150.1,
      bidSz: 200,
      ask: 150.15,
      askSz: 300,
    });
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

  it("shows the company profile on the COMPANY tab and the figures again on OVERVIEW", async () => {
    company.mockResolvedValue({
      ...Object.fromEntries(COMPANY_FIELDS.map((f) => [f, null])),
      symbol: "AAPL",
      name: "Apple Inc",
      sector: "TECH",
      industry: "Hardware",
      market_cap_musd: 3000000,
    });
    show();
    await userEvent.click(await screen.findByText("AAPL"));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByRole("tab", { name: "OVERVIEW" }).getAttribute("aria-selected")).toBe("true");

    await userEvent.click(within(drawer).getByRole("tab", { name: "COMPANY" }));
    expect(await within(drawer).findByRole("heading", { name: "Apple Inc" })).toBeDefined();
    expect(within(drawer).getByText("3,000,000 M$")).toBeDefined();
    expect(within(drawer).queryByLabelText("Book figures")).toBeNull();
    expect(company).toHaveBeenCalledWith("AAPL");

    await userEvent.click(within(drawer).getByRole("tab", { name: "OVERVIEW" }));
    expect(within(drawer).getByLabelText("Book figures")).toBeDefined();
  });

  it("explains the COMPANY tab's values in tips that open on focus", async () => {
    company.mockResolvedValue({
      ...Object.fromEntries(COMPANY_FIELDS.map((f) => [f, null])),
      symbol: "AAPL",
      name: "Apple Inc",
      sector: "TECH",
      industry: "Hardware",
      key_risk: "China",
    });
    show();
    await userEvent.click(await screen.findByText("AAPL"));
    const drawer = await screen.findByRole("dialog");
    await userEvent.click(within(drawer).getByRole("tab", { name: "COMPANY" }));
    await within(drawer).findByRole("heading", { name: "Apple Inc" });

    fireEvent.focus(within(drawer).getByRole("button", { name: "P/E help" }));
    expect(within(drawer).getByRole("tooltip").textContent).toMatch(/market cap ÷ net income/);
    // Prose lines carry a tip too, not only the figure boxes.
    expect(within(drawer).getByRole("button", { name: "Key risk help" })).toBeDefined();
  });

  it("says so when the company database is not available", async () => {
    const { HttpError } = await import("../src/lib/api.js");
    company.mockRejectedValue(new HttpError("down", 503));
    show();
    await userEvent.click(await screen.findByText("AAPL"));
    const drawer = await screen.findByRole("dialog");
    await userEvent.click(within(drawer).getByRole("tab", { name: "COMPANY" }));
    expect(await within(drawer).findByText(/company database is not available/)).toBeDefined();
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
