// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { useAuthStore, type Role } from "@/store/useAuthStore";
import { example, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG20: every column header and every stat tile on every screen explains
 * itself in a tooltip.
 */
const C = "/api/v1/clearing";

function api() {
  return stubApi({
    "/api/v1/symbols": example("/api/v1/symbols"),
    [`${C}/summary`]: example(`${C}/summary`),
    [`${C}/health`]: example(`${C}/health`),
    [`${C}/participants`]: example(`${C}/participants`),
    [`${C}/participants/TRADER01`]: example(`${C}/participants/{gateway_id}`),
    [`${C}/positions`]: example(`${C}/positions`),
    [`${C}/trades`]: example(`${C}/trades`),
    [`${C}/daily`]: example(`${C}/daily`),
    [`${C}/close-snapshots`]: example(`${C}/close-snapshots`),
    [`${C}/symbols`]: example(`${C}/symbols`),
    [`${C}/session-events`]: example(`${C}/session-events`),
    [`${C}/gateway-sessions`]: example(`${C}/gateway-sessions`),
    [`${C}/settlements`]: example(`${C}/settlements`),
    [`${C}/balances`]: example(`${C}/balances`),
    [`${C}/netting`]: example(`${C}/netting`),
    [`${C}/reconciliation`]: example(`${C}/reconciliation`),
  });
}

/** Role, path, and the tables the screen must show once loaded. */
const SCREENS: [Role, string, string[]][] = [
  ["ADMIN", "/overview", ["Recent session events"]],
  ["ADMIN", "/participants", ["Participants"]],
  ["ADMIN", "/participants/TRADER01", ["TRADER01 positions"]],
  ["ADMIN", "/participants/TRADER01/trades", ["TRADER01 retained trades"]],
  ["ADMIN", "/participants/TRADER01/history", ["Closes by day", "Close snapshots", "Daily activity"]],
  ["ADMIN", "/participants/TRADER01/settlement", ["TRADER01 settlements", "EOD runs"]],
  ["ADMIN", "/participants/TRADER01/sessions", ["TRADER01 gateway sessions"]],
  ["ADMIN", "/symbols", ["Symbol activity"]],
  ["ADMIN", "/events", ["Session events"]],
  ["ADMIN", "/gateway-sessions", ["Gateway sessions"]],
  ["ADMIN", "/eod", ["Balances", "Settlements", "EOD runs"]],
  ["TRADER", "/me/positions", ["My positions"]],
  ["TRADER", "/me/trades", ["My retained trades"]],
  ["TRADER", "/me/history", ["Closes by day", "Close snapshots", "Daily activity"]],
  ["TRADER", "/me/settlement", ["My settlements", "EOD runs"]],
  ["TRADER", "/me/sessions", ["My gateway sessions"]],
  ["MARKET_MAKER", "/me/obligations", ["Quote obligation settings"]],
];

beforeEach(() => useAuthStore.getState().logout());

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** Every header and stat label on screen that has no tooltip text. */
function unexplained(): string[] {
  const missing: string[] = [];
  for (const th of screen.queryAllByRole("columnheader")) {
    if (!th.getAttribute("title")?.trim()) missing.push(`column ${th.textContent}`);
  }
  for (const label of document.querySelectorAll("[data-stat-label]")) {
    if (!label.getAttribute("title")?.trim()) missing.push(`stat ${label.textContent}`);
  }
  return missing;
}

describe("tooltips", () => {
  it.each(SCREENS)("%s %s: every header and stat tile has one", async (role, path, tables) => {
    signIn(role, role === "ADMIN" ? "OPS01" : role === "MARKET_MAKER" ? "MM01" : "TRADER01");
    api();
    renderApp(path);
    for (const name of tables) await screen.findByRole("table", { name });
    // Stat tiles load with their own queries; wait until none is pending.
    await waitFor(() => expect(document.querySelector('[aria-busy="true"]')).toBeNull());
    expect(unexplained()).toEqual([]);
  });

  it("Reconciliation: every discrepancy column has one", async () => {
    signIn("ADMIN", "OPS01");
    api();
    renderApp("/reconciliation");
    fireEvent.change(await screen.findByLabelText("From"), { target: { value: "2026-08-28" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-08-29" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await screen.findByRole("table", { name: "Discrepancies" });
    expect(unexplained()).toEqual([]);
  });
});
