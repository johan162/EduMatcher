// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { usePageSizeStore } from "@/store/usePageSizeStore";
import { apiError, example, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG6: the participant's own clearing record. Every request is self-scoped by
 * the server, so the pages never send a `gateway` parameter; every money cell
 * is formatted from its tick value with its own row's precision; an error is
 * never shown as an empty table; and no screen shows a measure the system
 * does not compute (margin, equity, buying power, collateral).
 */
const POSITIONS = "/api/v1/clearing/positions";
const EXPOSURE = "/api/v1/clearing/exposure";
const TRADES = "/api/v1/clearing/trades";
const DAILY = "/api/v1/clearing/daily";
const CLOSES = "/api/v1/clearing/close-snapshots";

function current() {
  return { [POSITIONS]: example(POSITIONS) };
}

beforeEach(() => {
  useAuthStore.getState().logout();
  signIn("TRADER", "TRADER01");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** The cells of the row whose first cell is `first`, in table `name`. */
function rowCells(name: string, first: string): string[] {
  const table = screen.getByRole("table", { name });
  const row = within(table)
    .getAllByRole("row")
    .find((r) => within(r).queryAllByRole("cell")[0]?.textContent === first);
  expect(row, `${name}: no row ${first}`).toBeDefined();
  return within(row!).getAllByRole("cell").map((c) => c.textContent ?? "");
}

/** Headings, column headers and stat labels: where a measure would be named. */
function namedMeasures(): string {
  const parts = [
    ...screen.queryAllByRole("heading"),
    ...screen.queryAllByRole("columnheader"),
    ...document.querySelectorAll("[data-stat-label]"),
  ];
  return parts.map((p) => p.textContent ?? "").join(" | ");
}

function noForeignGateway(requests: string[]): void {
  for (const r of requests) expect(r).not.toMatch(/[?&]gateway=/);
}

describe("My Positions", () => {
  it("shows each position with its own precision, signed, self-scoped", async () => {
    const api = stubApi(current());
    renderApp("/me/positions");
    await screen.findByRole("table", { name: "My positions" });
    const aapl = rowCells("My positions", "AAPL");
    // CG25: a word beside every sign.
    expect(aapl).toEqual(expect.arrayContaining(["110 long", "187.3333", "188.00", "26.67 gain", "73.33 gain"]));
    expect(rowCells("My positions", "MSFT")).toContain("-20 short");
    noForeignGateway(api.requests);
    expect(api.calls(POSITIONS).length).toBeGreaterThan(0);
  });

  it("CG20: one table, with each row's notional and total P&L, and no separate exposure", async () => {
    const api = stubApi(current());
    renderApp("/me/positions");
    await screen.findByRole("table", { name: "My positions" });
    expect(screen.queryByRole("table", { name: "My exposure" })).toBeNull();
    // Net qty × mark, its absolute value, realized + unrealized -- as the
    // exposure query computes them from the same row.
    const aapl = rowCells("My positions", "AAPL");
    expect(aapl.filter((c) => c === "20,680.00")).toHaveLength(2);
    expect(aapl).toContain("100.00 gain");
    const msft = rowCells("My positions", "MSFT");
    expect(msft).toEqual(expect.arrayContaining(["-8,230.00", "8,230.00", "12.00 gain"]));
    const headers = within(screen.getByRole("table", { name: "My positions" }))
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual(
      expect.arrayContaining(["Net notional", "Gross notional", "Total P&L"]),
    );
    expect(api.calls(EXPOSURE)).toHaveLength(0);
  });

  it("CG20: a position without a mark has no notional, not a zero", async () => {
    const body = example<{ positions: Record<string, unknown>[] }>(POSITIONS);
    body.positions[1] = { ...body.positions[1], mark_price: null, mark_price_ticks: null };
    stubApi({ [POSITIONS]: body });
    renderApp("/me/positions");
    await screen.findByRole("table", { name: "My positions" });
    const msft = rowCells("My positions", "MSFT");
    expect(msft).not.toContain("-8,230.00");
    expect(msft.filter((c) => c === "—").length).toBeGreaterThanOrEqual(3); // mark, net, gross
  });

  it("says when the data was committed and that fills lag by a flush", async () => {
    stubApi(current());
    renderApp("/me/positions");
    const line = await screen.findByText(/Committed by clearing at/);
    expect(line.textContent).toMatch(/\d\d:\d\d:\d\d UTC/);
    expect(line.textContent).toMatch(/up to 5 s/);
  });

  it("no positions is a true zero", async () => {
    stubApi({ [POSITIONS]: { positions: [], count: 0, has_more: false } });
    renderApp("/me/positions");
    expect(await screen.findByText("No positions")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("an unavailable ledger is an error, never an empty table", async () => {
    stubApi({ [POSITIONS]: apiError(503, "CLEARING_DB", "Clearing ledger unavailable: not found") });
    renderApp("/me/positions");
    await waitFor(() => expect(screen.getAllByRole("alert").length).toBeGreaterThan(0));
    expect(screen.getAllByRole("alert")[0]!.textContent).toContain("CLEARING_DB");
    expect(screen.queryByText("No positions")).toBeNull();
  });

  it("shows no margin, equity or buying-power measure", async () => {
    stubApi(current());
    renderApp("/me/positions");
    await screen.findByRole("table", { name: "My positions" });
    expect(namedMeasures()).not.toMatch(/margin|equity|buying power|collateral/i);
  });
});

describe("My Trades", () => {
  it("shows exchange and clearing times apart, and the retention window", async () => {
    stubApi({ ...current(), [TRADES]: example(TRADES) });
    renderApp("/me/trades");
    const table = await screen.findByRole("table", { name: "My retained trades" });
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(expect.arrayContaining(["Exchange time", "Clearing ingest"]));
    const cells = rowCells("My retained trades", "000007-000000412");
    expect(cells).toEqual(expect.arrayContaining(["188.00", "SELL", "CONTINUOUS"]));
    expect(screen.getByText(/Raw trades are kept from 2026-06-01/)).toBeTruthy();
  });

  it("filters are applied on submit and never name a gateway", async () => {
    const api = stubApi({ ...current(), [TRADES]: example(TRADES) });
    renderApp("/me/trades");
    await screen.findByRole("table", { name: "My retained trades" });
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "aapl" } });
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-08-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(api.calls(TRADES).some((u) => u.searchParams.get("symbol") === "AAPL")).toBe(true),
    );
    const filtered = api.calls(TRADES).find((u) => u.searchParams.get("symbol") === "AAPL")!;
    expect(filtered.searchParams.get("from")).toBe("2026-08-01");
    noForeignGateway(api.requests);
  });

  describe("CG20 pager over the server's pages", () => {
    /** 200 trades and a cursor, then 30 more and none: newest first. */
    function serverPages() {
      const page = example<{ trades: Record<string, unknown>[]; next_cursor: string | null }>(TRADES);
      const one = page.trades[0]!;
      const trades = (from: number, n: number) =>
        Array.from({ length: n }, (_, i) => ({ ...one, trade_id: `T${String(from + i).padStart(4, "0")}` }));
      return (url: URL) =>
        url.searchParams.get("after") === "c1"
          ? { ...page, trades: trades(201, 30), next_cursor: null }
          : { ...page, trades: trades(1, 200), next_cursor: "c1" };
    }

    beforeEach(() => usePageSizeStore.setState({ pageSize: 100 }));

    it("fetches the next server page only when Next needs it, and then shows it", async () => {
      const api = stubApi({ ...current(), [TRADES]: serverPages() });
      renderApp("/me/trades");
      await screen.findByText("Page 1/2+");
      expect(screen.getByText("Rows 1–100 of 200+")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Next page" }));
      expect(screen.getByText("Page 2/2+")).toBeTruthy();
      expect(api.calls(TRADES).some((u) => u.searchParams.has("after"))).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "Next page" }));
      await screen.findByText("Rows 201–230 of 230");
      expect(screen.getByText("Page 3/3")).toBeTruthy();
      expect(rowCells("My retained trades", "T0201")).toBeTruthy();
      expect(api.calls(TRADES).filter((u) => u.searchParams.get("after") === "c1")).toHaveLength(1);
      expect((screen.getByRole("button", { name: "Next page" }) as HTMLButtonElement).disabled).toBe(true);
    });

    it("keeps the server's newest-first order: no header sorts, and says so", async () => {
      stubApi({ ...current(), [TRADES]: serverPages() });
      renderApp("/me/trades");
      const table = await screen.findByRole("table", { name: "My retained trades" });
      // No sort buttons in the header (rows may have CG31's "Follow trade").
      expect(within(table.querySelector("thead")!).queryAllByRole("button")).toHaveLength(0);
      expect(screen.getByText(/Newest first/)).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    });
  });
});

describe("Daily & Close History", () => {
  it("lists daily rows and labels the chart close-to-close, not intraday", async () => {
    stubApi({ ...current(), [DAILY]: example(DAILY), [CLOSES]: example(CLOSES) });
    renderApp("/me/history");
    const daily = await screen.findByRole("table", { name: "Daily activity" });
    expect(within(daily).getByText("-7,520.00")).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Close-to-close cumulative P&L/ })).toBeTruthy();
    expect(screen.getByText(/one point per session close; there is no intraday history/i)).toBeTruthy();
  });

  it("sums each close in display currency, each row with its own precision", async () => {
    stubApi({ ...current(), [DAILY]: example(DAILY), [CLOSES]: example(CLOSES) });
    renderApp("/me/history");
    await screen.findByRole("table", { name: "Closes by day" });
    // 2026-08-29: AAPL realized 26.67 + unrealized 73.33 = 100.00.
    expect(rowCells("Closes by day", "2026-08-29")).toContain("100.00 gain");
    expect(rowCells("Closes by day", "2026-08-28")).toContain("25.00 gain");
  });

  it("history is fetched once, not at the polling cadence", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const api = stubApi({ ...current(), [DAILY]: example(DAILY), [CLOSES]: example(CLOSES) });
      renderApp("/me/history");
      await screen.findByRole("table", { name: "Daily activity" });
      await vi.advanceTimersByTimeAsync(16_000);
      expect(api.calls(DAILY).length).toBe(1);
      expect(api.calls(CLOSES).length).toBe(1);
      noForeignGateway(api.requests);
    } finally {
      vi.useRealTimers();
    }
  });

  it("refreshes history only after clearing commits something new", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let updated = 1788013804200000000;
      const positions = () => {
        const body = example<{ positions: { updated_ts_ns: number }[] }>(POSITIONS);
        for (const row of body.positions) row.updated_ts_ns = updated;
        return body;
      };
      const api = stubApi({
        [POSITIONS]: positions,
        [EXPOSURE]: example(EXPOSURE),
        [DAILY]: example(DAILY),
        [CLOSES]: example(CLOSES),
      });
      renderApp("/me/history");
      await screen.findByRole("table", { name: "Daily activity" });
      updated += 5_000_000_000;
      await vi.advanceTimersByTimeAsync(6_000);
      await waitFor(() => expect(api.calls(DAILY).length).toBe(2));
    } finally {
      vi.useRealTimers();
    }
  });
});
