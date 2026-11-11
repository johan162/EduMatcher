// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { formatMinor, type Minor } from "@/lib/money";
import { useAuthStore } from "@/store/useAuthStore";
import { example, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG8: EOD settlement and balance (minor units, never ticks), and the market
 * maker's configured obligation settings (configuration, not observed
 * compliance).
 */
const C = "/api/v1/clearing";
const SETTLEMENTS = `${C}/settlements`;
const BALANCES = `${C}/balances`;
const SYMBOLS = "/api/v1/symbols";

interface SettlementBody {
  settlements: { account: string; amount_minor: number; amount: string; trade_date: string }[];
  count: number;
  has_more: boolean;
  runs: Record<string, unknown>[];
}

/** The contract example as a participant receives it: own rows, runs without steps. */
function ownSettlements(gateway = "TRADER01"): SettlementBody {
  const body = example<SettlementBody>(SETTLEMENTS);
  body.settlements = body.settlements.filter((s) => s.account === gateway);
  body.count = body.settlements.length;
  body.runs = body.runs.map(({ steps: _steps, ...run }) => run);
  return body;
}

/** All accounts of one day, the rounding residual included (ADMIN). */
function venueSettlements(): SettlementBody {
  const body = example<SettlementBody>(SETTLEMENTS);
  body.settlements.push({
    ...body.settlements[0]!,
    account: "EXCHANGE",
    amount_minor: 1,
    amount: "0.01",
  });
  body.count = body.settlements.length;
  return body;
}

beforeEach(() => {
  useAuthStore.getState().logout();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function row(table: HTMLElement, text: string): HTMLElement {
  const found = within(table)
    .getAllByRole("row")
    .find((r) => (r.textContent ?? "").includes(text));
  expect(found, `no row with ${text}`).toBeDefined();
  return found!;
}

describe("My EOD settlement", () => {
  beforeEach(() => signIn("TRADER", "TRADER01"));

  it("shows the derived balance from its inputs, in minor units", async () => {
    const api = stubApi({ [SETTLEMENTS]: ownSettlements(), [BALANCES]: example(BALANCES) });
    renderApp("/me/settlement");
    const panel = await screen.findByRole("region", { name: "Derived balance" });
    await waitFor(() => expect(panel.textContent).toContain("10,025.00"));
    expect(panel.textContent).toContain("10,000.00"); // opening balance
    expect(panel.textContent).toContain("25.00"); // settlements to date
    expect(panel.textContent).toMatch(/derived/i);
    expect(api.requests.every((r) => !r.includes("gateway="))).toBe(true);
  });

  it("signs each settlement in words and formats it exactly", async () => {
    const body = ownSettlements();
    body.settlements.push({ ...body.settlements[0]!, trade_date: "2026-08-27", amount_minor: -1234, amount: "-12.34" });
    stubApi({ [SETTLEMENTS]: body, [BALANCES]: example(BALANCES) });
    renderApp("/me/settlement");
    const table = await screen.findByRole("table", { name: "My settlements" });
    expect(row(table, "2026-08-28").textContent).toMatch(/25\.00.*Exchange owes you/);
    expect(row(table, "2026-08-27").textContent).toMatch(/-12\.34.*You owe the exchange/);
    for (const s of body.settlements) expect(formatMinor(s.amount_minor as Minor)).toBe(s.amount);
    expect(row(table, "2026-08-28").textContent).toMatch(/ok/);
    expect(row(table, "2026-08-28").textContent).toContain("AAPL 25.0000000000002");
  });

  it("says a settlement is not margin or collateral", async () => {
    stubApi({ [SETTLEMENTS]: ownSettlements(), [BALANCES]: example(BALANCES) });
    renderApp("/me/settlement");
    await screen.findByRole("table", { name: "My settlements" });
    expect(screen.getByText(/not margin, collateral or a completed payment/)).toBeTruthy();
  });

  it("applies an as-of date to the balance", async () => {
    const api = stubApi({ [SETTLEMENTS]: ownSettlements(), [BALANCES]: example(BALANCES) });
    renderApp("/me/settlement");
    await screen.findByRole("region", { name: "Derived balance" });
    fireEvent.change(screen.getByLabelText("Balance as of"), { target: { value: "2026-08-28" } });
    fireEvent.click(screen.getByRole("button", { name: "Show balance" }));
    await waitFor(() => expect(api.calls(BALANCES).some((u) => u.searchParams.get("as_of") === "2026-08-28")).toBe(true));
  });

  it("an empty ledger day is a true zero, not an error", async () => {
    stubApi({
      [SETTLEMENTS]: { settlements: [], count: 0, has_more: false, runs: [] },
      [BALANCES]: example(BALANCES),
    });
    renderApp("/me/settlement");
    expect(await screen.findByText("No settlements")).toBeTruthy();
  });

  it("is not polled", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const api = stubApi({ [SETTLEMENTS]: ownSettlements(), [BALANCES]: example(BALANCES) });
      renderApp("/me/settlement");
      await screen.findByRole("table", { name: "My settlements" });
      await vi.advanceTimersByTimeAsync(30_000);
      expect(api.calls(SETTLEMENTS).length).toBe(1);
      expect(api.calls(BALANCES).length).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("EOD settlement (ADMIN)", () => {
  beforeEach(() => signIn("ADMIN", "OPS01"));

  it("shows every account, the EXCHANGE row labelled as the rounding residual", async () => {
    stubApi({ [SETTLEMENTS]: venueSettlements(), [BALANCES]: example(BALANCES) });
    renderApp("/eod");
    const table = await screen.findByRole("table", { name: "Settlements" });
    expect(row(table, "EXCHANGE").textContent).toMatch(/rounding residual/i);
    expect(row(table, "MM01").textContent).toContain("-25.00");
    const runs = await screen.findByRole("table", { name: "EOD runs" });
    expect(row(runs, "2026-08-28").textContent).toMatch(/settle.*ok/);
  });

  it("filters by date and account", async () => {
    const api = stubApi({ [SETTLEMENTS]: venueSettlements(), [BALANCES]: example(BALANCES) });
    renderApp("/eod");
    await screen.findByRole("table", { name: "Settlements" });
    fireEvent.change(screen.getByLabelText("Account"), { target: { value: "exchange" } });
    fireEvent.change(screen.getByLabelText("Date"), { target: { value: "2026-08-28" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(
        api.calls(SETTLEMENTS).some(
          (u) => u.searchParams.get("gateway") === "EXCHANGE" && u.searchParams.get("date") === "2026-08-28",
        ),
      ).toBe(true),
    );
  });

  it("the drill-down's settlement tab asks for that gateway", async () => {
    const api = stubApi({
      [`${C}/participants/TRADER01`]: example(`${C}/participants/{gateway_id}`),
      [SETTLEMENTS]: ownSettlements(),
      [BALANCES]: example(BALANCES),
    });
    renderApp("/participants/TRADER01/settlement");
    await screen.findByRole("table", { name: "TRADER01 settlements" });
    expect(api.calls(SETTLEMENTS)[0]!.searchParams.get("gateway")).toBe("TRADER01");
    expect(api.calls(BALANCES)[0]!.searchParams.get("gateway")).toBe("TRADER01");
  });

  it("an unavailable EOD ledger is an error naming it", async () => {
    stubApi({
      [SETTLEMENTS]: new Response(JSON.stringify({ error: { code: "EOD_DB", message: "EOD ledger unavailable: not found" } }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
      [BALANCES]: example(BALANCES),
    });
    renderApp("/eod");
    expect((await screen.findByRole("alert")).textContent).toContain("EOD_DB");
  });
});

describe("My Quote Obligations", () => {
  beforeEach(() => signIn("MARKET_MAKER", "MM01"));

  it("lists the resolved settings per symbol from the requester-scoped /symbols", async () => {
    const api = stubApi({ [SYMBOLS]: example(SYMBOLS) });
    renderApp("/me/obligations");
    const table = await screen.findByRole("table", { name: "Quote obligation settings" });
    const tsla = row(table, "TSLA");
    expect(tsla.textContent).toMatch(/Enforced/);
    expect(tsla.textContent).toContain("20 ticks (0.20)");
    expect(tsla.textContent).toContain("100");
    expect(row(table, "AAPL").textContent).toMatch(/Not configured/);
    expect(api.requests.every((r) => r.startsWith(SYMBOLS))).toBe(true);
    expect(api.requests.every((r) => !r.includes("gateway="))).toBe(true);
  });

  it("presents configuration, never observed compliance", async () => {
    stubApi({ [SYMBOLS]: example(SYMBOLS) });
    renderApp("/me/obligations");
    await screen.findByRole("table", { name: "Quote obligation settings" });
    const named = [
      ...screen.getAllByRole("heading"),
      ...screen.getAllByRole("columnheader"),
      ...document.querySelectorAll("[data-stat-label]"),
    ]
      .map((e) => e.textContent)
      .join(" | ");
    expect(named).not.toMatch(/presence|re-?quote|compliance|score/i);
    expect(screen.getByText(/configured enforcement parameters/i)).toBeTruthy();
    expect(screen.getByText(/not a measure of how you quoted/i)).toBeTruthy();
  });
});
