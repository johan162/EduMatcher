// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { currentPath, example, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG23: the Overview answers "is anything wrong right now?" -- the largest
 * losses and positions, the session phase with a stale-data warning, and
 * EOD that failed or has not settled a closed day -- and no longer repeats
 * the Participants screen.
 */
const C = "/api/v1/clearing";
const SESSION = "/api/v1/session";
const SUMMARY = `${C}/summary`;
const PARTICIPANTS = `${C}/participants`;
const EXPOSURE = `${C}/exposure`;

type Body = Record<string, unknown>;

function session(state: string): Body {
  return { ...example<Body>(SESSION), state };
}

/** A summary whose last clearing write was `ageMs` ago. */
function summary(ageMs: number, patch: Body = {}): Body {
  const ns = (Date.now() - ageMs) * 1_000_000;
  return { ...example<Body>(SUMMARY), last_flush_ts_ns: ns, last_trade_ts_ns: ns, ...patch };
}

function participants(totals: [string, number][]): Body {
  const one = example<{ participants: Body[] }>(PARTICIPANTS).participants[0]!;
  const rows = totals.map(([gateway_id, total_pnl]) => ({ ...one, gateway_id, total_pnl }));
  return { participants: rows, count: rows.length, has_more: false };
}

function api(overrides: Record<string, unknown> = {}) {
  return stubApi({
    [SESSION]: session("CONTINUOUS"),
    [SUMMARY]: summary(2_000),
    [`${C}/health`]: example(`${C}/health`),
    [PARTICIPANTS]: example(PARTICIPANTS),
    [EXPOSURE]: example(EXPOSURE),
    [`${C}/session-events`]: example(`${C}/session-events`),
    ...overrides,
  });
}

beforeEach(() => {
  useAuthStore.getState().logout();
  signIn("ADMIN", "OPS01");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function firstCells(name: string): string[] {
  return within(screen.getByRole("table", { name }))
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("cell")[0]!.textContent ?? "");
}

describe("Overview", () => {
  it("no longer repeats the Participants list; Reconciliation is linked from the header", async () => {
    api();
    renderApp("/overview");
    await screen.findByRole("table", { name: "Largest losses" });
    expect(screen.queryByRole("table", { name: "Participants" })).toBeNull();
    const link = screen.getByRole("link", { name: /Reconcile/ });
    expect(link.getAttribute("href")).toBe("/reconciliation");
  });

  it("lists only the participants at a loss, worst first, at most five", async () => {
    api({
      [PARTICIPANTS]: participants([
        ["A", 10],
        ["B", -5],
        ["C", 0],
        ["D", -50],
        ["E", 3],
        ["F", -1],
        ["G", 7],
      ]),
    });
    renderApp("/overview");
    await screen.findByRole("table", { name: "Largest losses" });
    expect(firstCells("Largest losses")).toEqual(["D", "B", "F"]);
  });

  it("says when nobody is at a loss", async () => {
    api({ [PARTICIPANTS]: participants([["A", 1]]) });
    renderApp("/overview");
    expect(await screen.findByText("No participant is at a loss")).toBeTruthy();
  });

  it("opens a participant's drawer from a loss row", async () => {
    api({ [PARTICIPANTS]: participants([["B", -5]]) });
    renderApp("/overview");
    const table = await screen.findByRole("table", { name: "Largest losses" });
    fireEvent.click(within(table).getByText("B").closest("tr")!);
    expect(currentPath()).toBe("/participants/B");
  });

  it("shows the five largest open positions, as the server ranks them by gross notional", async () => {
    const stub = api();
    renderApp("/overview");
    const table = await screen.findByRole("table", { name: "Largest positions" });
    const call = stub.calls(EXPOSURE)[0]!;
    expect(call.searchParams.get("limit")).toBe("5");
    expect(call.searchParams.get("sort")).toBe("gross_notional");
    expect(call.searchParams.has("gateway")).toBe(false);
    fireEvent.click(within(table).getAllByRole("row")[1]!);
    expect(currentPath()).toMatch(/^\/participants\/[A-Z0-9]+$/);
  });

  it("leaves flat positions out of the largest positions", async () => {
    const body = example<{ exposure: Body[] }>(EXPOSURE);
    const flat = body.exposure.map((r) => ({ ...r, net_qty: 0, net_notional_ticks: 0, gross_notional_ticks: 0 }));
    api({ [EXPOSURE]: { ...body, exposure: flat } });
    renderApp("/overview");
    expect(await screen.findByText("No open positions")).toBeTruthy();
  });

  it("shows the session phase", async () => {
    api({ [SESSION]: session("CLOSING_AUCTION") });
    renderApp("/overview");
    const label = await screen.findByText("Session phase");
    await waitFor(() => expect(label.closest("div")!.textContent).toMatch(/CLOSING_AUCTION/));
  });

  it("warns when clearing has not written for a while during continuous trading", async () => {
    api({ [SUMMARY]: summary(60_000) });
    renderApp("/overview");
    const warning = await screen.findByText(/No clearing write for \d+ s/);
    expect(warning.textContent).toMatch(/no trade has arrived, or clearing is not writing/);
  });

  it("does not warn about an old write when no trading is expected", async () => {
    api({ [SESSION]: session("CLOSED"), [SUMMARY]: summary(60_000) });
    renderApp("/overview");
    await screen.findByText("Session phase");
    await waitFor(() => expect(screen.getByText("Session phase").closest("div")!.textContent).toMatch(/CLOSED/));
    expect(screen.queryByText(/No clearing write for/)).toBeNull();
  });

  it("does not warn while writes are recent", async () => {
    api();
    renderApp("/overview");
    await waitFor(() => expect(screen.getByText("Session phase").closest("div")!.textContent).toMatch(/CONTINUOUS/));
    expect(screen.queryByText(/No clearing write for/)).toBeNull();
  });

  it("warns when the last EOD run failed", async () => {
    const failed = { ...(example<Body>(SUMMARY)["last_eod_run"] as Body), status: "failed" };
    api({ [SUMMARY]: summary(2_000, { last_eod_run: failed }) });
    renderApp("/overview");
    expect(await screen.findByText(/The last EOD run, for 2026-08-28, ended failed/)).toBeTruthy();
  });

  it("warns when a closed trading day has not been settled", async () => {
    // Summary example: trading day 2026-08-29, last EOD run for 2026-08-28.
    api({ [SESSION]: session("CLOSED") });
    renderApp("/overview");
    expect(await screen.findByText(/2026-08-29 is closed but not settled/)).toBeTruthy();
  });

  it("does not call an open trading day unsettled", async () => {
    api();
    renderApp("/overview");
    await waitFor(() => expect(screen.getByText("Session phase").closest("div")!.textContent).toMatch(/CONTINUOUS/));
    expect(screen.queryByText(/is closed but not settled/)).toBeNull();
  });

  it("explains every new tile and column", async () => {
    api();
    renderApp("/overview");
    await screen.findByRole("table", { name: "Largest positions" });
    for (const th of screen.getAllByRole("columnheader")) expect(th.getAttribute("title")).toBeTruthy();
    expect(screen.getByText("Session phase").getAttribute("title")).toBeTruthy();
  });
});
