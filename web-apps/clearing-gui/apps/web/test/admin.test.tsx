// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { currentPath, example, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG7: the ADMIN operations screens. They show only what the API returns --
 * freshness, GAP evidence, the two health dimensions, events, sessions and
 * reconciliation with its retained-data limit -- and never a venue-wide
 * exposure, equity, margin or open-interest figure.
 */
const C = "/api/v1/clearing";
const SUMMARY = `${C}/summary`;
const HEALTH = `${C}/health`;
const PARTICIPANTS = `${C}/participants`;
const EVENTS = `${C}/session-events`;
const SESSIONS = `${C}/gateway-sessions`;
const RECON = `${C}/reconciliation`;
const SYMBOLS = `${C}/symbols`;

function overview(): Record<string, unknown> {
  return {
    [SUMMARY]: example(SUMMARY),
    [HEALTH]: example(HEALTH),
    [PARTICIPANTS]: example(PARTICIPANTS),
    [EVENTS]: example(EVENTS),
  };
}

beforeEach(() => {
  useAuthStore.getState().logout();
  signIn("ADMIN", "OPS01");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function region(name: string): HTMLElement {
  return screen.getByRole("region", { name });
}

describe("Clearing Overview", () => {
  it("states freshness, the flush qualifier and the last EOD run", async () => {
    stubApi(overview());
    renderApp("/overview");
    const line = await screen.findByText(/Last clearing write/);
    expect(line.textContent).toMatch(/\d\d:\d\d:\d\d UTC/);
    expect(line.textContent).toMatch(/up to 5 s/);
    const eod = await screen.findByText(/Last EOD run/);
    expect(eod.closest("div")!.textContent).toMatch(/2026-08-28.*ok/);
  });

  it("raises an unmistakable GAP alarm with the interval and missing count", async () => {
    stubApi(overview());
    renderApp("/overview");
    const alarm = await screen.findByRole("alert", { name: /Feed gap/ });
    expect(alarm.textContent).toMatch(/2 trades? missing/);
    expect(alarm.textContent).toMatch(/398.*401/);
    expect(alarm.textContent).toMatch(/does not prove/i);
  });

  it("shows no alarm, but still the caveat, when no gap was seen", async () => {
    const summary = example<Record<string, unknown>>(SUMMARY);
    summary["gap_count"] = 0;
    summary["latest_gap"] = null;
    stubApi({ ...overview(), [SUMMARY]: summary });
    renderApp("/overview");
    expect(await screen.findByText(/No feed gap seen on/)).toBeTruthy();
    expect(screen.queryByRole("alert", { name: /Feed gap/ })).toBeNull();
  });

  it("reports database and process health separately", async () => {
    const health = example<{ database: Record<string, unknown>; process: Record<string, unknown> }>(HEALTH);
    health.process["alive"] = false;
    health.process["detail"] = "no reply within 500ms";
    stubApi({ ...overview(), [HEALTH]: health });
    renderApp("/overview");
    const panel = await screen.findByRole("region", { name: "Health" });
    await waitFor(() => expect(panel.textContent).toMatch(/Database.*readable/));
    expect(panel.textContent).toMatch(/pm-clearing process.*not answering.*no reply within 500ms/);
  });

  it("lists participants with links to their drill-down", async () => {
    stubApi(overview());
    renderApp("/overview");
    const table = await screen.findByRole("table", { name: "Participants" });
    const link = within(table).getByRole("link", { name: "TRADER01" });
    expect(link.getAttribute("href")).toBe("/participants/TRADER01");
  });

  it("shows recent PHASE and EOD events", async () => {
    stubApi(overview());
    renderApp("/overview");
    const recent = await screen.findByRole("table", { name: "Recent session events" });
    expect(within(recent).getByText(/CLOSED/)).toBeTruthy();
  });

  it("polls summary at 5 s and health at 30 s, never reconciliation", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const api = stubApi(overview());
      renderApp("/overview");
      await screen.findByRole("table", { name: "Participants" });
      await vi.advanceTimersByTimeAsync(31_000);
      expect(api.calls(SUMMARY).length).toBeGreaterThanOrEqual(6);
      expect(api.calls(HEALTH).length).toBe(2);
      expect(api.calls(RECON).length).toBe(0);
      expect(api.calls(EVENTS).length).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("names no venue-wide exposure, equity, margin or open interest", async () => {
    stubApi(overview());
    renderApp("/overview");
    await screen.findByRole("table", { name: "Participants" });
    const named = [
      ...screen.getAllByRole("heading"),
      ...screen.getAllByRole("columnheader"),
      ...document.querySelectorAll("[data-stat-label]"),
    ]
      .map((e) => e.textContent)
      .join(" | ");
    expect(named).not.toMatch(/equity|margin|open interest|notional/i);
  });
});

describe("Participant drill-down", () => {
  it("shows the gateway's totals and positions, asking for that gateway", async () => {
    const api = stubApi({
      [`${C}/participants/TRADER01`]: example(`${C}/participants/{gateway_id}`),
      [`${C}/positions`]: example(`${C}/positions`),
      [`${C}/exposure`]: example(`${C}/exposure`),
    });
    renderApp("/participants/TRADER01");
    expect(await screen.findByRole("heading", { name: "Participant TRADER01" })).toBeTruthy();
    await screen.findByRole("table", { name: "TRADER01 positions" });
    expect(api.calls(`${C}/positions`).every((u) => u.searchParams.get("gateway") === "TRADER01")).toBe(true);
    const tabs = screen.getByRole("navigation", { name: "Participant views" });
    expect(within(tabs).getAllByRole("link").map((l) => l.textContent)).toEqual([
      "Positions",
      "Trades",
      "History",
      "Settlement",
      "Sessions",
    ]);
  });

  it("opens the trade audit tab for that gateway", async () => {
    const api = stubApi({
      [`${C}/participants/TRADER01`]: example(`${C}/participants/{gateway_id}`),
      [`${C}/trades`]: example(`${C}/trades`),
    });
    renderApp("/participants/TRADER01/trades");
    await screen.findByRole("table", { name: "TRADER01 retained trades" });
    expect(api.calls(`${C}/trades`)[0]!.searchParams.get("gateway")).toBe("TRADER01");
  });
});

describe("Symbols, events and sessions", () => {
  it("presents symbols as activity, not open interest", async () => {
    stubApi({ [SYMBOLS]: example(SYMBOLS) });
    renderApp("/symbols");
    expect(await screen.findByRole("heading", { name: "Symbol Activity" })).toBeTruthy();
    const table = await screen.findByRole("table", { name: "Symbol activity" });
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent).join("|");
    expect(headers).not.toMatch(/open interest/i);
    expect(screen.getByText(/not open interest/i)).toBeTruthy();
  });

  it("filters events by type and shows a GAP's missing count", async () => {
    const api = stubApi({ [EVENTS]: example(EVENTS) });
    renderApp("/events");
    await screen.findByRole("table", { name: "Session events" });
    expect(screen.getByText(/2 missing \(ids 398 → 401\)/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "GAP" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(api.calls(EVENTS).some((u) => u.searchParams.get("type") === "GAP")).toBe(true));
    expect(screen.getByText(/when clearing observed/i)).toBeTruthy();
  });

  it("filters gateway sessions by gateway and open sessions only", async () => {
    const api = stubApi({ [SESSIONS]: example(SESSIONS) });
    renderApp("/gateway-sessions");
    await screen.findByRole("table", { name: "Gateway sessions" });
    fireEvent.change(screen.getByLabelText("Gateway"), { target: { value: "trader01" } });
    fireEvent.click(screen.getByLabelText("Connected only"));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(
        api.calls(SESSIONS).some(
          (u) => u.searchParams.get("gateway") === "TRADER01" && u.searchParams.get("connected_only") === "true",
        ),
      ).toBe(true),
    );
  });

  it("a participant's own sessions never name a gateway", async () => {
    signIn("TRADER", "TRADER01");
    const api = stubApi({ [SESSIONS]: example(SESSIONS) });
    renderApp("/me/sessions");
    await screen.findByRole("table", { name: "My gateway sessions" });
    expect(api.requests.every((r) => !r.includes("gateway="))).toBe(true);
  });
});

describe("Reconciliation", () => {
  it("does nothing until run, then compares the explicit range", async () => {
    const api = stubApi({ [RECON]: example(RECON) });
    renderApp("/reconciliation");
    await screen.findByRole("heading", { name: "Reconciliation" });
    expect(api.calls(RECON).length).toBe(0);
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-08-28" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-08-29" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    const table = await screen.findByRole("table", { name: "Discrepancies" });
    expect(within(table).getByText("1,875.00")).toBeTruthy();
    const call = api.calls(RECON)[0]!;
    expect([call.searchParams.get("from"), call.searchParams.get("to")]).toEqual(["2026-08-28", "2026-08-29"]);
    expect(screen.getByText(/Compared 2026-08-28 to 2026-08-29/)).toBeTruthy();
  });

  it("an empty result is 'no discrepancy in the queried retained data', not 'verified'", async () => {
    stubApi({
      [RECON]: {
        discrepancies: [],
        count: 0,
        has_more: false,
        retained_from: "2026-06-01",
        compared_from: "2026-08-28",
        compared_to: "2026-08-29",
      },
    });
    renderApp("/reconciliation");
    fireEvent.change(await screen.findByLabelText("From"), { target: { value: "2026-08-28" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-08-29" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(await screen.findByText("No discrepancy in the queried retained data.")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/verified/i);
    expect(screen.getByText(/raw trades are kept from 2026-06-01/i)).toBeTruthy();
  });

  it("says when nothing in the range could be compared", async () => {
    stubApi({
      [RECON]: { discrepancies: [], count: 0, has_more: false, retained_from: "2026-08-29", compared_from: null, compared_to: null },
    });
    renderApp("/reconciliation");
    fireEvent.change(await screen.findByLabelText("From"), { target: { value: "2026-01-01" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-01-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(await screen.findByText(/Nothing was compared/)).toBeTruthy();
  });

  it("is never refetched by itself", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const api = stubApi({ [RECON]: example(RECON) });
      renderApp("/reconciliation");
      fireEvent.change(await screen.findByLabelText("From"), { target: { value: "2026-08-28" } });
      fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-08-29" } });
      fireEvent.click(screen.getByRole("button", { name: "Run" }));
      await screen.findByRole("table", { name: "Discrepancies" });
      await vi.advanceTimersByTimeAsync(60_000);
      window.dispatchEvent(new Event("focus"));
      expect(api.calls(RECON).length).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("ADMIN navigation", () => {
  it("offers every venue screen", async () => {
    stubApi(overview());
    renderApp("/overview");
    const nav = await screen.findByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getAllByRole("link").map((l) => l.textContent)).toEqual([
      "Overview",
      "Participants",
      "Symbols",
      "Events",
      "Gateway Sessions",
      "Reconciliation",
      "EOD Settlement",
    ]);
    fireEvent.click(within(nav).getByRole("link", { name: "Participants" }));
    await waitFor(() => expect(currentPath()).toBe("/participants"));
  });
});
