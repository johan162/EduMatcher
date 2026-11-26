// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { useAuthStore } from "@/store/useAuthStore";
import { useExplainStore } from "@/store/useExplainStore";
import { currentPath, example, renderApp, signIn, stubApi, type ApiStub } from "./helpers";

/**
 * CG30: who traded with whom (ADMIN Overview, Explain mode), from
 * `GET /clearing/flows`: a buyer × seller grid with the value written in
 * each cell, and the pair list.
 */
const C = "/api/v1/clearing";

function api(flows: unknown = example(`${C}/flows`)): ApiStub {
  return stubApi({
    [`${C}/summary`]: example(`${C}/summary`),
    [`${C}/health`]: example(`${C}/health`),
    [`${C}/participants`]: example(`${C}/participants`),
    [`${C}/participants/TRADER01`]: example(`${C}/participants/{gateway_id}`),
    [`${C}/positions`]: example(`${C}/positions`),
    [`${C}/exposure`]: example(`${C}/exposure`),
    [`${C}/session-events`]: example(`${C}/session-events`),
    [`${C}/netting`]: example(`${C}/netting`),
    [`${C}/flows`]: flows,
  });
}

/** The Overview's panel; `stubbed` when the test set up its own reply. */
async function panel(stubbed = false): Promise<HTMLElement> {
  if (!stubbed) api();
  signIn("ADMIN");
  renderApp("/overview");
  return waitFor(() => screen.getByRole("region", { name: "Who traded with whom" }));
}

function grid(region: HTMLElement): HTMLElement {
  return within(region).getByRole("table", { name: "Value bought, by buyer (rows) from seller (columns)" });
}

/** The grid cell of `buyer`'s row under `seller`'s column. */
function cell(table: HTMLElement, buyer: string, seller: string): string {
  const headers = [...table.querySelectorAll("thead th")].map((th) => th.textContent);
  const row = [...table.querySelectorAll("tbody tr")].find((tr) => tr.querySelector("th")?.textContent === buyer)!;
  return row.children[headers.indexOf(seller)]!.textContent ?? "";
}

beforeEach(() => {
  useExplainStore.setState({ explain: true });
  useAuthStore.getState().logout();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("who traded with whom", () => {
  it("writes each pair's value into its cell, and lists the pairs", async () => {
    const region = await panel();
    const table = await waitFor(() => grid(region));
    expect(cell(table, "TRADER01", "MM01")).toBe("28,100.00");
    expect(cell(table, "MM01", "TRADER01")).toBe("1,085.00");
    expect(cell(table, "TRADER01", "TRADER01")).toBe("");
    expect(region.textContent).toContain("On 2026-08-28, 2 gateways traded with each other in 2 buyer–seller pairs.");
    expect(region.textContent).toContain("nets each gateway's buys against its sells");
    const pairs = within(region).getByRole("table", { name: "Trades by pair" });
    expect(pairs.querySelectorAll("tbody tr")).toHaveLength(2);
  });

  it("opens a gateway's drawer from its header", async () => {
    const region = await panel();
    const table = await waitFor(() => grid(region));
    fireEvent.click(within(table.querySelector("tbody")!).getAllByRole("link", { name: "TRADER01" })[0]!);
    expect(currentPath()).toBe("/participants/TRADER01");
  });

  it("draws the 20 largest gateways and gathers the rest as others", async () => {
    const pairs = Array.from({ length: 24 }, (_, i) => ({
      buyer: `B${String(i).padStart(2, "0")}`,
      seller: `S${String(i).padStart(2, "0")}`,
      trades: 1,
      quantity: 10,
      value: 1000 - i,
    }));
    api({ trade_date: "2026-08-28", symbol: null, trades_retained: true, pairs });
    const region = await panel(true);
    const table = await waitFor(() => grid(region));
    const rows = [...table.querySelectorAll("tbody tr")].map((tr) => tr.querySelector("th")?.textContent);
    expect(rows).toHaveLength(21);
    expect(rows.at(-1)).toBe("others");
    expect(region.textContent).toContain("The 20 gateways that traded most are drawn; the other 28 are gathered as others.");
    expect(within(region).getByRole("table", { name: "Trades by pair" }).textContent).toContain("B23");
  });

  it("says when the day's raw trades are no longer kept", async () => {
    api({ trade_date: "2026-08-28", symbol: null, trades_retained: false, pairs: [] });
    const region = await panel(true);
    await waitFor(() => expect(region.textContent).toContain("Raw trades for 2026-08-28 are no longer kept"));
  });

  it("is not there, and not asked for, with Explain off", async () => {
    useExplainStore.setState({ explain: false });
    const stub = api();
    signIn("ADMIN");
    renderApp("/overview");
    await screen.findByRole("table", { name: "Recent session events" });
    expect(screen.queryByRole("region", { name: "Who traded with whom" })).toBeNull();
    expect(stub.calls(`${C}/flows`)).toHaveLength(0);
  });

  it("passes axe", async () => {
    const region = await panel();
    await waitFor(() => grid(region));
    const result = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
