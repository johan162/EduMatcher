// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { useAuthStore } from "@/store/useAuthStore";
import { useExplainStore } from "@/store/useExplainStore";
import { example, renderApp, signIn, stubApi, type ApiStub } from "./helpers";

/**
 * CG29: the position replay in the GUI. The position card (CG25) and, in
 * Explain mode, each daily History row open how the position was built
 * that day, fill by fill, from `GET /clearing/position-replay` (CG28): a
 * step chart, a table of the fills, and the selected fill written out.
 */
const C = "/api/v1/clearing";
const DAY = "2026-11-10";

type Step = Record<string, unknown>;

function step(
  n: number,
  side: "BUY" | "SELL",
  quantity: number,
  price: number,
  kind: string,
  netQty: number,
  avg: number,
  realized: number,
  realizedDay: number,
): Step {
  return {
    trade_id: `000007-00000000${n}`,
    ts_ns: 1788013800000000000 + n * 1_000_000_000,
    side,
    quantity,
    kind,
    net_qty: netQty,
    tick_decimals: 2,
    price,
    price_ticks: price * 100,
    avg_cost: avg,
    avg_cost_ticks: avg * 100,
    realized_delta: realized,
    realized_delta_ticks: realized * 100,
    realized_day: realizedDay,
    realized_day_ticks: realizedDay * 100,
    unrealized: netQty * (price - avg),
    unrealized_ticks: netQty * (price - avg) * 100,
  };
}

/** Every kind of step, from flat: the CG28 hand-made day. */
const STEPS = [
  step(1, "BUY", 100, 10, "open", 100, 10, 0, 0),
  step(2, "BUY", 100, 12, "add", 200, 11, 0, 0),
  step(3, "SELL", 50, 13, "reduce", 150, 11, 100, 100),
  step(4, "SELL", 150, 9, "close", 0, 0, -300, -200),
  step(5, "SELL", 30, 8, "open", -30, 8, 0, -200),
  step(6, "BUY", 50, 7, "flip", 20, 7, 30, -170),
];

function replay(overrides: Record<string, unknown> = {}) {
  return {
    gateway_id: "TRADER01",
    symbol: "AAPL",
    trade_date: DAY,
    trades_retained: true,
    has_more: false,
    start: { net_qty: 0, tick_decimals: 2, avg_cost: 0, avg_cost_ticks: 0 },
    steps: STEPS,
    matches_daily_row: true,
    matches_position: true,
    daily_row: {
      end_net_qty: 20,
      tick_decimals: 2,
      end_avg_cost: 7,
      end_avg_cost_ticks: 700,
      realized_pnl: -170,
      realized_pnl_ticks: -17000,
    },
    ...overrides,
  };
}

function api(reply: unknown = replay()): ApiStub {
  return stubApi({
    "/api/v1/symbols": example("/api/v1/symbols"),
    [`${C}/positions`]: example(`${C}/positions`),
    [`${C}/daily`]: example(`${C}/daily`),
    [`${C}/close-snapshots`]: example(`${C}/close-snapshots`),
    [`${C}/position-replay`]: reply,
  });
}

/** My Positions → Explain AAPL → Show how this position was built. */
async function openReplay(): Promise<HTMLElement> {
  signIn("TRADER");
  renderApp("/me/positions");
  fireEvent.click(await screen.findByRole("button", { name: "Explain AAPL" }));
  fireEvent.click(screen.getByRole("button", { name: "Show how this position was built" }));
  return screen.findByRole("region", { name: "How AAPL was built" });
}

function fillsTable(panel: HTMLElement): HTMLElement {
  return within(panel).getByRole("table", { name: `Fills of AAPL on ${DAY}` });
}

function selectStep(panel: HTMLElement, n: number): string {
  const rows = fillsTable(panel).querySelectorAll<HTMLElement>("tbody tr[data-row-key]");
  fireEvent.click(rows[n - 1]!);
  return within(panel).getByRole("status").textContent ?? "";
}

beforeEach(() => {
  useExplainStore.setState({ explain: true });
  useAuthStore.getState().logout();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the replay of a position", () => {
  it("asks for the row's gateway and symbol, and lists every fill", async () => {
    const stub = api();
    const panel = await openReplay();
    const url = stub.calls(`${C}/position-replay`)[0]!;
    expect(url.searchParams.get("symbol")).toBe("AAPL");
    expect(url.searchParams.get("gateway")).toBe("TRADER01");
    expect(url.searchParams.has("date")).toBe(false);
    await waitFor(() => fillsTable(panel));
    expect(panel.textContent).toContain(`At the start of ${DAY}: flat.`);
    const rows = fillsTable(panel).querySelectorAll("tbody tr[data-row-key]");
    expect(rows).toHaveLength(6);
    expect(rows[2]!.textContent).toContain("reduce");
    expect(rows[2]!.textContent).toContain("150 long");
    expect(rows[2]!.textContent).toContain("100.00 gain");
    expect(panel.querySelectorAll("[data-replay-point]")).toHaveLength(6);
  });

  it.each([
    [1, "Bought 100 at 10.00: opened a 100 long at average 10.00."],
    [2, "Bought 100 at 12.00 to a 100 long: now 200 long, at average (100 × 10.00 + 100 × 12.00) / 200 = 11.00."],
    [3, "Sold 50 of a 200 long at 13.00: realized (13.00 − 11.00) × 50 = 100.00 gain; average cost unchanged, now 150 long."],
    [4, "Sold 150 of a 150 long at 9.00: realized (9.00 − 11.00) × 150 = -300.00 loss; the position is now flat."],
    [5, "Sold 30 at 8.00: opened a 30 short at average 8.00."],
    [6, "Bought 50 against a 30 short at 7.00: closed the short, realizing (8.00 − 7.00) × 30 = 30.00 gain, and opened a 20 long at 7.00."],
  ])("writes out step %i", async (n, sentence) => {
    api();
    const panel = await openReplay();
    await waitFor(() => fillsTable(panel));
    expect(selectStep(panel, n)).toContain(sentence);
  });

  it("selects a step from the keyboard", async () => {
    api();
    const panel = await openReplay();
    await waitFor(() => fillsTable(panel));
    const rows = fillsTable(panel).querySelectorAll<HTMLElement>("tbody tr[data-row-key]");
    rows[0]!.focus();
    fireEvent.keyDown(rows[0]!, { key: "Enter" });
    expect(within(panel).getByRole("status").textContent).toContain("opened a 100 long");
    expect(rows[0]!.getAttribute("aria-selected")).toBe("true");
  });

  it("warns when the replay does not end where the ledger does", async () => {
    api(replay({ matches_daily_row: false, daily_row: { ...replay().daily_row, end_net_qty: 111 } }));
    const panel = await openReplay();
    const alert = await within(panel).findByRole("alert");
    expect(alert.textContent).toContain(
      "The replay ends at 20 long at average 7.00, but clearing's daily row holds 111 long at average 7.00: report this.",
    );
  });

  it.each([
    [{ trades_retained: false, steps: [], matches_daily_row: null }, `The raw trades of ${DAY} are no longer kept, so the day cannot be replayed.`],
    [{ steps: [], matches_daily_row: null }, `No fills on ${DAY}.`],
    [{ trade_date: null, steps: [], daily_row: null, matches_daily_row: null }, "Clearing has no trades of this gateway in AAPL."],
    [{ has_more: true, matches_daily_row: null }, "Only the first 5,000 fills are shown, so the replay is not checked against the ledger."],
  ])("says so when it cannot show the whole day (%#)", async (overrides, text) => {
    api(replay(overrides));
    const panel = await openReplay();
    await waitFor(() => expect(panel.textContent).toContain(text));
  });

  it("passes axe with a step selected", async () => {
    api();
    const panel = await openReplay();
    await waitFor(() => fillsTable(panel));
    selectStep(panel, 3);
    const result = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});

describe("from History", () => {
  it("opens a daily row's replay for its day", async () => {
    const stub = api();
    signIn("TRADER");
    renderApp("/me/history");
    fireEvent.click(await screen.findByRole("button", { name: "Replay AAPL on 2026-08-29" }));
    await screen.findByRole("region", { name: "How AAPL was built" });
    const url = stub.calls(`${C}/position-replay`)[0]!;
    expect([url.searchParams.get("symbol"), url.searchParams.get("date")]).toEqual(["AAPL", "2026-08-29"]);
  });

  it("has no replay buttons with Explain off", async () => {
    useExplainStore.setState({ explain: false });
    api();
    signIn("TRADER");
    renderApp("/me/history");
    await screen.findByRole("table", { name: "Daily activity" });
    expect(screen.queryByRole("button", { name: /^Replay / })).toBeNull();
  });
});
