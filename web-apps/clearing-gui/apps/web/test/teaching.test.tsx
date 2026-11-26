// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { useAuthStore } from "@/store/useAuthStore";
import { useExplainStore } from "@/store/useExplainStore";
import { example, renderApp, signIn, stubApi, type ApiStub } from "./helpers";

/**
 * CG27: the venue-level teaching pictures, each in Explain mode only (D7)
 * and each with its numbers in a table (D12):
 *
 * - longs against shorts per symbol (Symbol Activity);
 * - netting: the day's trades against what each gateway is left with
 *   (Overview; a participant's Settlement), worded apart from pm-eod's
 *   settlement, which moves P&L;
 * - money in and out by day (History);
 * - gains and losses add up to zero (Participants).
 */
const C = "/api/v1/clearing";

type Netting = {
  trade_date: string | null;
  trades_retained: boolean;
  trade_count: number | null;
  gateways: { gateway_id: string; net_amount: number }[];
  [k: string]: unknown;
};

function netting(): Netting {
  return example<Netting>(`${C}/netting`);
}

/** TRADER01's own netting: its one row of the venue example. */
function ownNetting(): Netting {
  const venue = netting();
  return {
    ...venue,
    gross_value: 29185,
    payment_count: 1,
    net_paid: 27015,
    net_received: 0,
    gateways: venue.gateways.filter((g) => g.gateway_id === "TRADER01"),
  };
}

function api(overrides: Record<string, unknown> = {}): ApiStub {
  return stubApi({
    "/api/v1/symbols": example("/api/v1/symbols"),
    [`${C}/summary`]: example(`${C}/summary`),
    [`${C}/health`]: example(`${C}/health`),
    [`${C}/participants`]: example(`${C}/participants`),
    [`${C}/participants/TRADER01`]: example(`${C}/participants/{gateway_id}`),
    [`${C}/exposure`]: example(`${C}/exposure`),
    [`${C}/session-events`]: example(`${C}/session-events`),
    [`${C}/symbols`]: example(`${C}/symbols`),
    [`${C}/daily`]: example(`${C}/daily`),
    [`${C}/close-snapshots`]: example(`${C}/close-snapshots`),
    [`${C}/settlements`]: example(`${C}/settlements`),
    [`${C}/balances`]: example(`${C}/balances`),
    [`${C}/netting`]: netting(),
    ...overrides,
  });
}

function region(name: string): HTMLElement {
  return screen.getByRole("region", { name });
}

beforeEach(() => {
  useExplainStore.setState({ explain: true });
  useAuthStore.getState().logout();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("longs against shorts", () => {
  it("draws each symbol's two equal sides and lists them in a table", async () => {
    api();
    signIn("ADMIN");
    renderApp("/symbols");
    const panel = await waitFor(() => region("Longs against shorts"));
    expect(panel.textContent).toContain("Every share held long was sold by someone who is now short");
    const table = within(panel).getByRole("table", { name: "Long and short positions" });
    const row = within(table).getAllByRole("row").find((r) => r.textContent?.startsWith("AAPL"))!;
    expect(within(row).getAllByRole("cell").map((c) => c.textContent)).toEqual(["AAPL", "110", "1", "110", "1"]);
    const bars = panel.querySelectorAll<HTMLElement>("[data-bar]");
    expect([...bars].map((b) => b.dataset.bar)).toEqual(["left", "right"]);
    expect(bars[0]!.style.width).toBe(bars[1]!.style.width);
  });
});

describe("netting", () => {
  it("tells the venue's day in one sentence on the Overview, apart from settlement", async () => {
    const stub = api();
    signIn("ADMIN");
    renderApp("/overview");
    const panel = await waitFor(() => region("Netting"));
    await waitFor(() => expect(panel.textContent).toContain("3 trades"));
    expect(panel.textContent).toContain(
      "On 2026-08-28, 3 trades worth 29,185.00 net to 2 amounts: the gateways that bought more than they sold pay 27,015.00 in all, and those that sold more receive 27,015.00.",
    );
    expect(panel.textContent).toContain("not pm-eod's settlement");
    const table = within(panel).getByRole("table", { name: "Netting by gateway" });
    expect(table.textContent).toContain("receive 27,015.00");
    expect(table.textContent).toContain("pay 27,015.00");
    expect(stub.calls(`${C}/netting`)[0]!.searchParams.has("gateway")).toBe(false);
  });

  it("says when the day's raw trades are no longer kept", async () => {
    api({ [`${C}/netting`]: { ...netting(), trades_retained: false, trade_count: null } });
    signIn("ADMIN");
    renderApp("/overview");
    const panel = await waitFor(() => region("Netting"));
    await waitFor(() => expect(panel.textContent).toContain("Raw trades for this day are no longer kept"));
    expect(panel.textContent).toContain("On 2026-08-28, the day's trades worth 29,185.00 net to 2 amounts");
  });

  it("tells a participant what it pays, on My Settlement", async () => {
    const stub = api({ [`${C}/netting`]: ownNetting() });
    signIn("TRADER");
    renderApp("/me/settlement");
    const panel = await waitFor(() => region("Netting"));
    await waitFor(() =>
      expect(panel.textContent).toContain("On 2026-08-28 you bought 28,100.00 and sold 1,085.00: you pay 27,015.00."),
    );
    expect(stub.calls(`${C}/netting`)[0]!.searchParams.has("gateway")).toBe(false);
  });

  it("tells an ADMIN one gateway's, in its drawer", async () => {
    const stub = api({ [`${C}/netting`]: ownNetting() });
    signIn("ADMIN");
    renderApp("/participants/TRADER01/settlement");
    const panel = await waitFor(() => region("Netting"));
    await waitFor(() =>
      expect(panel.textContent).toContain(
        "On 2026-08-28 this gateway bought 28,100.00 and sold 1,085.00: it pays 27,015.00.",
      ),
    );
    expect(stub.calls(`${C}/netting`)[0]!.searchParams.get("gateway")).toBe("TRADER01");
  });
});

describe("money in and out", () => {
  it("sums each day's buys and sells and says what is left", async () => {
    api();
    signIn("TRADER");
    renderApp("/me/history");
    const panel = await waitFor(() => region("Money in and out by day"));
    const table = within(panel).getByRole("table", { name: "Money by day" });
    const row = within(table).getAllByRole("row").find((r) => r.textContent?.startsWith("2026-08-29"))!;
    expect(within(row).getAllByRole("cell").map((c) => c.textContent)).toEqual([
      "2026-08-29",
      "0.00",
      "7,520.00",
      "receive 7,520.00",
    ]);
  });

  it("leaves out a day the 1 000-row bound may have cut (CG32 review R5)", async () => {
    const daily = example<{ daily: Record<string, unknown>[]; has_more: boolean }>(`${C}/daily`);
    const newest = daily.daily[0]!;
    daily.daily = [newest, { ...newest, trade_date: "2026-08-28", symbol: "MSFT" }];
    daily.has_more = true;
    api({ [`${C}/daily`]: daily });
    signIn("TRADER");
    renderApp("/me/history");
    const panel = await waitFor(() => region("Money in and out by day"));
    const table = within(panel).getByRole("table", { name: "Money by day" });
    expect(table.textContent).toContain("2026-08-29");
    expect(table.textContent).not.toContain("2026-08-28");
    expect(panel.textContent).toContain("2026-08-28 is left out: more daily rows match than were sent");
  });
});

describe("gains and losses add up to zero", () => {
  it("draws each gateway's total and their sum", async () => {
    api();
    signIn("ADMIN");
    renderApp("/participants");
    const panel = await waitFor(() => region("Gains and losses add up to zero"));
    expect(panel.textContent).toContain("Sum over all gateways: 0.00");
    expect(panel.querySelectorAll("[data-bar]")).toHaveLength(2);
  });
});

describe("Explain off", () => {
  it.each([
    ["ADMIN", "/symbols", "Symbol activity"],
    ["ADMIN", "/overview", "Recent session events"],
    ["ADMIN", "/participants", "Participants"],
    ["TRADER", "/me/history", "Daily activity"],
    ["TRADER", "/me/settlement", "My settlements"],
  ] as const)("%s %s has no picture and asks for no netting", async (role, path, table) => {
    useExplainStore.setState({ explain: false });
    const stub = api();
    signIn(role);
    renderApp(path);
    await screen.findByRole("table", { name: table });
    expect(document.querySelector("[data-bar]")).toBeNull();
    expect(screen.queryByRole("region", { name: /Netting|Longs|Money in|add up/ })).toBeNull();
    expect(stub.calls(`${C}/netting`)).toHaveLength(0);
  });
});

describe("accessibility", () => {
  it.each([
    ["ADMIN", "/symbols", "Longs against shorts"],
    ["ADMIN", "/overview", "Netting"],
    ["ADMIN", "/participants", "Gains and losses add up to zero"],
    ["TRADER", "/me/history", "Money in and out by day"],
  ] as const)("%s %s passes axe with its picture", async (role, path, name) => {
    api();
    signIn(role);
    renderApp(path);
    await waitFor(() => region(name));
    const result = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
