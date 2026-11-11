// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { useAuthStore, type Role } from "@/store/useAuthStore";
import { example, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG9 accessibility: axe-core on every screen with data loaded, plus the
 * behaviours axe cannot see -- sorting by keyboard, sort order announced,
 * state given in text and not only in colour.
 *
 * `color-contrast` is off: jsdom does not lay out or paint, so axe cannot
 * measure it here (the palette is trader-gui's, checked there by eye).
 */
const C = "/api/v1/clearing";

function api() {
  stubApi({
    "/api/v1/status": example("/api/v1/status"),
    "/api/v1/symbols": example("/api/v1/symbols"),
    [`${C}/summary`]: example(`${C}/summary`),
    [`${C}/health`]: example(`${C}/health`),
    [`${C}/participants`]: example(`${C}/participants`),
    [`${C}/participants/TRADER01`]: example(`${C}/participants/{gateway_id}`),
    [`${C}/positions`]: example(`${C}/positions`),
    [`${C}/exposure`]: example(`${C}/exposure`),
    [`${C}/trades`]: example(`${C}/trades`),
    [`${C}/daily`]: example(`${C}/daily`),
    [`${C}/close-snapshots`]: example(`${C}/close-snapshots`),
    [`${C}/symbols`]: example(`${C}/symbols`),
    [`${C}/session-events`]: example(`${C}/session-events`),
    [`${C}/gateway-sessions`]: example(`${C}/gateway-sessions`),
    [`${C}/settlements`]: example(`${C}/settlements`),
    [`${C}/balances`]: example(`${C}/balances`),
  });
}

async function violations(): Promise<string[]> {
  const result = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useAuthStore.getState().logout();
});

const SCREENS: [Role | null, string, string][] = [
  [null, "/login", "EduMatcher Clearing"],
  ["ADMIN", "/overview", "Clearing Overview"],
  ["ADMIN", "/participants/TRADER01", "Participant TRADER01"],
  ["ADMIN", "/symbols", "Symbol Activity"],
  ["ADMIN", "/events", "Events"],
  ["ADMIN", "/gateway-sessions", "Gateway Sessions"],
  ["ADMIN", "/reconciliation", "Reconciliation"],
  ["ADMIN", "/eod", "EOD Settlement"],
  ["TRADER", "/me/positions", "My Positions"],
  ["TRADER", "/me/trades", "My Trades"],
  ["TRADER", "/me/history", "Daily & Close History"],
  ["TRADER", "/me/settlement", "EOD Settlement"],
  ["MARKET_MAKER", "/me/obligations", "My Quote Obligations"],
];

describe.each(SCREENS)("%s %s", (role, path, heading) => {
  it("has no axe violations once its data is shown", async () => {
    if (role) signIn(role, role === "ADMIN" ? "OPS01" : role === "MARKET_MAKER" ? "MM01" : "TRADER01");
    api();
    renderApp(path);
    await screen.findByRole("heading", { name: heading });
    await waitFor(() => expect(document.querySelector("[aria-busy=true]")).toBeNull());
    expect(await violations()).toEqual([]);
  });
});

describe("keyboard and announcements", () => {
  it("sorts a table from the keyboard and announces the order", async () => {
    signIn("TRADER", "TRADER01");
    api();
    renderApp("/me/positions");
    const table = await screen.findByRole("table", { name: "My positions" });
    const button = within(table).getByRole("button", { name: "Net qty" });
    button.focus();
    expect(document.activeElement).toBe(button);
    fireEvent.click(button); // Enter/Space on a <button> fire click
    const header = button.closest("th")!;
    expect(header.getAttribute("aria-sort")).toBe("descending");
    const first = within(table).getAllByRole("row")[1]!;
    expect(within(first).getAllByRole("cell")[0]!.textContent).toBe("AAPL"); // 110 before -20
    fireEvent.click(button);
    expect(header.getAttribute("aria-sort")).toBe("ascending");
  });

  it("gives every status in text, not only colour", async () => {
    signIn("ADMIN", "OPS01");
    api();
    renderApp("/overview");
    const health = await screen.findByRole("region", { name: "Health" });
    await waitFor(() => expect(health.textContent).toMatch(/OK.*Database/));
    expect(screen.getByText(/^API (connected|unreachable)$|^API: no request yet$/)).toBeTruthy();
  });
});
