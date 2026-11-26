// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { apiError, currentPath, example, renderApp, signIn, stubApi } from "./helpers";

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

  describe("stale-write warning (review R1)", () => {
    beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
    afterEach(() => vi.useRealTimers());

    async function phaseShown(state: string) {
      await waitFor(() =>
        expect(screen.getByText("Session phase").closest("div")!.textContent).toContain(state),
      );
    }

    it("appears once writes stop during continuous trading, with the page left open", async () => {
      // Recent at load; then every poll returns the same, unchanged summary.
      api({ [SUMMARY]: summary(1_000) });
      renderApp("/overview");
      await phaseShown("CONTINUOUS");
      expect(screen.queryByText(/No new clearing write/)).toBeNull();
      await vi.advanceTimersByTimeAsync(35_000);
      const warning = await screen.findByText(/No new clearing write for at least \d+ s/);
      expect(warning.textContent).toMatch(/no trade has arrived, or clearing is not writing/);
    });

    it("does not appear while writes keep coming, whatever the browser's clock says", async () => {
      // The server's clock two hours behind the browser's: only change counts.
      let write = 0;
      api({ [SUMMARY]: () => summary(2 * 3_600_000 - 1_000 * write++) });
      renderApp("/overview");
      await phaseShown("CONTINUOUS");
      await vi.advanceTimersByTimeAsync(60_000);
      expect(screen.queryByText(/No new clearing write/)).toBeNull();
    });

    it("the phase tile says when the phase is only last-known (review R4)", async () => {
      let calls = 0;
      api({
        [SESSION]: () => (calls++ === 0 ? session("CONTINUOUS") : apiError(504, "ENGINE_TIMEOUT")),
      });
      renderApp("/overview");
      await phaseShown("CONTINUOUS");
      await vi.advanceTimersByTimeAsync(31_000);
      await waitFor(() =>
        expect(screen.getByText("Session phase").closest("div")!.textContent).toMatch(/last known.*did not answer/),
      );
    });

    it("does not appear outside continuous trading", async () => {
      api({ [SESSION]: session("CLOSED"), [SUMMARY]: summary(1_000) });
      renderApp("/overview");
      await phaseShown("CLOSED");
      await vi.advanceTimersByTimeAsync(60_000);
      expect(screen.queryByText(/No new clearing write/)).toBeNull();
    });
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

  it("a new exchange without an EOD ledger is calm: no warning colour, no attention item", async () => {
    api({
      [SESSION]: session("CLOSED"),
      [SUMMARY]: summary(2_000, { eod_db_status: "not_run", last_eod_run: null, last_trade_ts_ns: null }),
    });
    renderApp("/overview");
    const tile = (await screen.findByText("no EOD run yet")) as HTMLElement;
    expect(tile.className).not.toMatch(/text-halt/);
    await waitFor(() => expect(screen.getByText("Session phase").closest("div")!.textContent).toMatch(/CLOSED/));
    expect(screen.queryByText(/is closed but not settled/)).toBeNull();
  });

  it("an unreadable EOD ledger is flagged on the tile", async () => {
    api({ [SUMMARY]: summary(2_000, { eod_db_status: "unreadable", last_eod_run: null }) });
    renderApp("/overview");
    expect(((await screen.findByText("EOD ledger unreadable")) as HTMLElement).className).toMatch(/text-halt/);
  });

  it("a closed day with trades but no EOD ledger is still unsettled", async () => {
    api({ [SESSION]: session("CLOSED"), [SUMMARY]: summary(2_000, { eod_db_status: "not_run", last_eod_run: null }) });
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
