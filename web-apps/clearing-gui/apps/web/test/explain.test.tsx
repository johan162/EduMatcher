// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { useAuthStore } from "@/store/useAuthStore";
import { useExplainStore } from "@/store/useExplainStore";
import { example, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG25 (D7): Explain mode, "how this number is made" per position, the P&L
 * split, words beside signs, and empty tables that teach.
 *
 * The positions example: AAPL long 110 at 187.3333, mark 188.00, realized
 * 26.67, unrealized 73.33; MSFT short 20 at 412.10, mark 411.50, unrealized
 * 12.00.
 */
const C = "/api/v1/clearing";

type Row = Record<string, unknown>;

function positions(rows?: Row[]) {
  const reply = example<{ positions: Row[]; count: number; has_more: boolean }>(`${C}/positions`);
  if (rows) {
    reply.positions = rows;
    reply.count = rows.length;
  }
  return reply;
}

function api(overrides: Record<string, unknown> = {}) {
  return stubApi({
    [`${C}/summary`]: example(`${C}/summary`),
    [`${C}/health`]: example(`${C}/health`),
    [`${C}/participants/TRADER01`]: example(`${C}/participants/{gateway_id}`),
    [`${C}/participants`]: example(`${C}/participants`),
    [`${C}/positions`]: positions(),
    [`${C}/exposure`]: example(`${C}/exposure`),
    [`${C}/session-events`]: example(`${C}/session-events`),
    ...overrides,
  });
}

function explainButton(symbol: string): HTMLElement {
  return screen.getByRole("button", { name: `Explain ${symbol}` });
}

beforeEach(() => {
  localStorage.clear();
  useExplainStore.setState({ explain: true });
  useAuthStore.getState().logout();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the Explain toggle", () => {
  it("is in the top bar, on by default, and remembered", async () => {
    useExplainStore.persist.clearStorage();
    useExplainStore.setState(useExplainStore.getInitialState());
    api();
    signIn("TRADER");
    renderApp("/me/positions");
    const toggle = await screen.findByRole("button", { name: "Explain" });
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(JSON.parse(localStorage.getItem("clearing-explain") ?? "{}").state.explain).toBe(false);
  });
});

describe("how a position's number is made", () => {
  it("writes out a long's unrealized P&L with the row's own values", async () => {
    api();
    signIn("TRADER");
    renderApp("/me/positions");
    const button = await waitFor(() => explainButton("AAPL"));
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    const card = screen.getByRole("region", { name: "How AAPL's P&L is made" });
    expect(card.textContent).toContain(
      "Long 110 at average 187.3333, mark 188.00: (188.00 − 187.3333) × 110 = 73.33 gain",
    );
    expect(within(card).getByRole("img", { name: /average 187\.3333.*mark 188\.00/ })).toBeTruthy();
  });

  it("writes out a short's the other way round", async () => {
    api();
    signIn("TRADER");
    renderApp("/me/positions");
    fireEvent.click(await waitFor(() => explainButton("MSFT")));
    const card = screen.getByRole("region", { name: "How MSFT's P&L is made" });
    expect(card.textContent).toContain(
      "Short 20 at average 412.10, mark 411.50: (412.10 − 411.50) × 20 = 12.00 gain",
    );
  });

  it("splits the total into realized and unrealized parts that add up", async () => {
    api();
    signIn("TRADER");
    renderApp("/me/positions");
    fireEvent.click(await waitFor(() => explainButton("AAPL")));
    const card = screen.getByRole("region", { name: "How AAPL's P&L is made" });
    expect(card.textContent).toContain("Realized 26.67 gain + unrealized 73.33 gain = total 100.00 gain");
    const parts = card.querySelectorAll<HTMLElement>("[data-pnl-part]");
    expect([...parts].map((p) => p.dataset.pnlPart)).toEqual(["realized", "unrealized"]);
  });

  it("explains a flat position and one without a mark", async () => {
    const [aapl, msft] = positions().positions as [Row, Row];
    api({
      [`${C}/positions`]: positions([
        { ...aapl, net_qty: 0, avg_cost: 0, avg_cost_ticks: 0, unrealized_pnl: 0, unrealized_pnl_ticks: 0, realized_pnl: 50, realized_pnl_ticks: 5000 },
        { ...msft, mark_price: null, mark_price_ticks: null, unrealized_pnl: 0, unrealized_pnl_ticks: 0 },
      ]),
    });
    signIn("TRADER");
    renderApp("/me/positions");
    fireEvent.click(await waitFor(() => explainButton("AAPL")));
    fireEvent.click(explainButton("MSFT"));
    expect(screen.getByRole("region", { name: "How AAPL's P&L is made" }).textContent).toContain(
      "Flat: no shares are held, so nothing is unrealized. The realized 50.00 gain stays: it was locked in by the trades that closed the position.",
    );
    expect(screen.getByRole("region", { name: "How MSFT's P&L is made" }).textContent).toContain(
      "No mark yet: unrealized P&L needs a price to value the position at.",
    );
  });

  it("has no card, picture or explain line when Explain is off", async () => {
    useExplainStore.setState({ explain: false });
    api();
    signIn("TRADER");
    renderApp("/me/positions");
    await screen.findByRole("table", { name: "My positions" });
    expect(screen.queryByRole("button", { name: /^Explain [A-Z]/ })).toBeNull();
    expect(document.querySelector("[data-explain]")).toBeNull();
  });

  it("passes axe with a card open", async () => {
    api();
    signIn("TRADER");
    renderApp("/me/positions");
    fireEvent.click(await waitFor(() => explainButton("AAPL")));
    const result = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});

describe("words beside signs", () => {
  it("says long, short, gain and loss in the cells, whatever the Explain setting", async () => {
    useExplainStore.setState({ explain: false });
    const [aapl, msft] = positions().positions as [Row, Row];
    api({ [`${C}/positions`]: positions([aapl, { ...msft, unrealized_pnl: -12, unrealized_pnl_ticks: -1200 }]) });
    signIn("TRADER");
    renderApp("/me/positions");
    const table = await screen.findByRole("table", { name: "My positions" });
    const text = table.textContent ?? "";
    expect(text).toContain("110 long");
    expect(text).toContain("-20 short");
    expect(text).toContain("100.00 gain");
    expect(text).toContain("-12.00 loss");
  });

  it("says gain or loss in per-participant P&L columns: participants and closes", async () => {
    api({
      [`${C}/close-snapshots`]: example(`${C}/close-snapshots`),
      [`${C}/daily`]: example(`${C}/daily`),
      "/api/v1/symbols": example("/api/v1/symbols"),
    });
    signIn("ADMIN");
    renderApp("/participants");
    const participants = await screen.findByRole("table", { name: "Participants" });
    expect(participants.textContent).toMatch(/\d (gain|loss)/);
    cleanup();
    renderApp("/participants/TRADER01/history");
    const closes = await screen.findByRole("table", { name: "Closes by day" });
    expect(closes.textContent).toMatch(/\d (gain|loss)/);
  });

  it("says gain or loss on a participant's P&L tiles", async () => {
    api();
    signIn("ADMIN");
    renderApp("/participants/TRADER01");
    await screen.findByText("Total P&L");
    const tiles = [...document.querySelectorAll("[data-stat-label]")].map((l) => l.parentElement!.textContent ?? "");
    // The example's total is 112.00.
    expect(tiles.find((t) => t.startsWith("Total P&L"))).toContain("112.00 gain");
  });
});

describe("explain lines on tiles", () => {
  it("puts each tile's explanation under it when on, and none when off", async () => {
    api();
    signIn("ADMIN");
    renderApp("/overview");
    await screen.findByText("Open positions");
    const labels = document.querySelectorAll("[data-stat-label]");
    expect(document.querySelectorAll("[data-explain]").length).toBe(labels.length);
    const open = [...labels].find((l) => l.textContent === "Open positions")!;
    expect(open.parentElement!.querySelector("[data-explain]")!.textContent).toBe(open.getAttribute("title"));
    fireEvent.click(screen.getByRole("button", { name: "Explain" }));
    expect(document.querySelector("[data-explain]")).toBeNull();
  });
});

describe("empty tables that teach", () => {
  const empty = {
    [`${C}/positions`]: { positions: [], count: 0, has_more: false },
    [`${C}/trades`]: { trades: [], count: 0, has_more: false, next_cursor: null, retained_from: null },
    [`${C}/close-snapshots`]: { snapshots: [], count: 0, has_more: false },
    [`${C}/daily`]: { daily: [], count: 0, has_more: false },
    [`${C}/settlements`]: { settlements: [], runs: [], count: 0, has_more: false, eod_db_available: true },
    [`${C}/balances`]: example(`${C}/balances`),
    [`${C}/gateway-sessions`]: { sessions: [], count: 0, has_more: false },
    "/api/v1/symbols": example("/api/v1/symbols"),
  };

  const CASES: [string, RegExp, string][] = [
    ["/me/positions", /a position appears when one of your orders trades/, "Positions and P&L"],
    ["/me/trades", /a trade appears here when one of your orders is filled/, "Positions and P&L"],
    ["/me/history", /clearing takes a snapshot of your positions at each session close/, "Positions and P&L"],
    ["/me/history", /a daily row is written for each day and symbol in which you traded/, "Positions and P&L"],
    ["/me/settlement", /pm-eod settles each trading day after the close/, "Your End-of-Day Statement"],
    ["/me/sessions", /a session appears when your gateway connects/, "Clearing GUI"],
  ];

  it.each(CASES)("%s says what would fill it (%s) and names the guide chapter", async (path, text, chapter) => {
    api(empty);
    signIn("TRADER");
    renderApp(path);
    const hint = await screen.findByText(text);
    expect(hint.textContent).toContain(`Participant Guide, “${chapter}”`);
  });
});
