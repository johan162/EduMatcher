// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { useAuthStore } from "@/store/useAuthStore";
import { useExplainStore } from "@/store/useExplainStore";
import { example, renderApp, signIn, stubApi, type ApiStub } from "./helpers";

/**
 * CG31: follow one trade, in Explain mode, from a trade row: matched by the
 * engine → received by clearing → each visible side's position change (the
 * CG28 replay step) → the day's daily row → pm-eod's settlement of the day.
 * A participant sees its own side only.
 *
 * The trades example: TRADER01 sells 40 AAPL at 188.00 on 2026-08-29,
 * received 1.25 s after the print; a participant's copy hides the buyer.
 */
const C = "/api/v1/clearing";
const TRADE = "000007-000000412";
const DAY = "2026-08-29";

type Row = Record<string, unknown>;

function trades(buyer: string | null = null) {
  const page = example<{ trades: Row[] }>(`${C}/trades`);
  page.trades[0] = { ...page.trades[0], buy_gateway_id: buyer, buy_order_id: buyer ? "B1" : null };
  return { ...page, has_more: false, next_cursor: null };
}

/** One gateway's replay of the day, with the trade's fill as its only step. */
function replay(gateway: string, side: "BUY" | "SELL", before: number, after: number, realized: number) {
  return {
    gateway_id: gateway,
    symbol: "AAPL",
    trade_date: DAY,
    trades_retained: true,
    has_more: false,
    start: { net_qty: before, tick_decimals: 2, avg_cost: 187.3333, avg_cost_ticks: 18733.33 },
    steps: [
      {
        trade_id: TRADE,
        ts_ns: 1788013800000000000,
        side,
        quantity: 40,
        kind: "reduce",
        net_qty: after,
        tick_decimals: 2,
        price: 188,
        price_ticks: 18800,
        avg_cost: 187.3333,
        avg_cost_ticks: 18733.33,
        realized_delta: realized,
        realized_delta_ticks: realized * 100,
        realized_day: realized,
        realized_day_ticks: realized * 100,
        unrealized: 0,
        unrealized_ticks: 0,
      },
    ],
    matches_daily_row: true,
    matches_position: true,
    daily_row: {
      end_net_qty: after,
      tick_decimals: 2,
      end_avg_cost: 187.3333,
      end_avg_cost_ticks: 18733.33,
      realized_pnl: realized,
      realized_pnl_ticks: realized * 100,
    },
  };
}

const NOT_SETTLED = { settlements: [], runs: [], count: 0, has_more: false };

function settled() {
  const reply = example<{ settlements: Row[]; runs: Row[] }>(`${C}/settlements`);
  reply.settlements = reply.settlements.map((s) => ({ ...s, trade_date: DAY }));
  reply.runs = reply.runs.map((r) => ({ ...r, trade_date: DAY }));
  return reply;
}

function api(overrides: Record<string, unknown> = {}): ApiStub {
  return stubApi({
    "/api/v1/symbols": example("/api/v1/symbols"),
    [`${C}/participants`]: example(`${C}/participants`),
    [`${C}/participants/TRADER01`]: example(`${C}/participants/{gateway_id}`),
    [`${C}/trades`]: trades(),
    [`${C}/position-replay`]: (url: URL) =>
      url.searchParams.get("gateway") === "MM01"
        ? replay("MM01", "BUY", -150, -110, -26.67)
        : replay("TRADER01", "SELL", 150, 110, 26.67),
    [`${C}/settlements`]: NOT_SETTLED,
    ...overrides,
  });
}

async function follow(): Promise<HTMLElement> {
  fireEvent.click(await screen.findByRole("button", { name: `Follow trade ${TRADE}` }));
  return screen.findByRole("region", { name: `Trade ${TRADE}, step by step` });
}

beforeEach(() => {
  useExplainStore.setState({ explain: true });
  useAuthStore.getState().logout();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("a participant follows its own trade", () => {
  it("goes from the match to the settlement, on its own side only", async () => {
    const stub = api();
    signIn("TRADER");
    renderApp("/me/trades");
    const panel = await follow();
    await waitFor(() => expect(panel.textContent).toContain("Not settled yet"));
    const text = panel.textContent ?? "";
    expect(text).toContain("you sold 40 AAPL at 188.00 in continuous trading. The buyer is not shown to you.");
    expect(text).toContain("Received by clearing 1.25 s later");
    expect(text).toContain(
      "Sold 40 of a 150 long at 188.00: realized (188.00 − 187.3333) × 40 = 26.67 gain; average cost unchanged, now 110 long.",
    );
    expect(text).toContain(
      `At the end of ${DAY}, clearing's daily row for you in AAPL holds 110 long at average 187.3333, with 26.67 gain realized that day.`,
    );
    expect(text).toContain(`Not settled yet: pm-eod settles ${DAY} after the close.`);
    expect(text).not.toContain("MM01");
    const replays = stub.calls(`${C}/position-replay`);
    expect(replays.map((u) => [u.searchParams.get("gateway"), u.searchParams.get("symbol"), u.searchParams.get("date")])).toEqual([
      ["TRADER01", "AAPL", DAY],
    ]);
    expect(stub.calls(`${C}/settlements`).map((u) => u.searchParams.get("date"))).toEqual([DAY]);
  });
});

describe("an ADMIN follows a trade", () => {
  it("shows both sides and what pm-eod settled", async () => {
    const stub = api({ [`${C}/trades`]: trades("MM01"), [`${C}/settlements`]: settled() });
    signIn("ADMIN");
    renderApp("/participants/TRADER01/trades");
    const panel = await follow();
    await waitFor(() => expect(panel.textContent).toContain("owes the exchange"));
    const text = panel.textContent ?? "";
    expect(text).toContain("MM01 bought 40 AAPL from TRADER01 at 188.00 in continuous trading.");
    expect(text).toContain("Bought 40 of a 150 short at 188.00");
    expect(text).toContain("Sold 40 of a 150 long at 188.00");
    expect(text).toContain(`pm-eod settled ${DAY}: the exchange owes TRADER01 25.00.`);
    expect(text).toContain(`pm-eod settled ${DAY}: MM01 owes the exchange 25.00.`);
    expect(text).toContain("the day's change in P&L of all its positions, not this trade's value");
    expect(stub.calls(`${C}/position-replay`).map((u) => u.searchParams.get("gateway")).sort()).toEqual(["MM01", "TRADER01"]);
  });

  it("says when pm-eod's run for the day failed", async () => {
    const failed = { ...NOT_SETTLED, runs: settled().runs.map((r) => ({ ...r, status: "failed" })) };
    api({ [`${C}/settlements`]: failed });
    signIn("TRADER");
    renderApp("/me/trades");
    const panel = await follow();
    await waitFor(() => expect(panel.textContent).toContain(`pm-eod's run for ${DAY} failed: the day is not settled.`));
  });
});

describe("Explain", () => {
  it("has no follow button when off", async () => {
    useExplainStore.setState({ explain: false });
    api();
    signIn("TRADER");
    renderApp("/me/trades");
    await screen.findByRole("table", { name: "My retained trades" });
    expect(screen.queryByRole("button", { name: /^Follow trade/ })).toBeNull();
  });

  it("passes axe with a trade followed", async () => {
    api();
    signIn("TRADER");
    renderApp("/me/trades");
    const panel = await follow();
    await waitFor(() => expect(panel.textContent).toContain("Not settled yet"));
    const result = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
