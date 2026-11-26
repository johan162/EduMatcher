// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { currentPath, example, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG21: the participant detail opens in a wide drawer over the live
 * Participants list, addressed by URL, from a row (mouse or keyboard) or
 * from any gateway id elsewhere on the ADMIN screens.
 */
const C = "/api/v1/clearing";

function api() {
  return stubApi({
    [`${C}/participants`]: example(`${C}/participants`),
    [`${C}/participants/TRADER01`]: example(`${C}/participants/{gateway_id}`),
    [`${C}/participants/MM01`]: { ...example<Record<string, unknown>>(`${C}/participants/{gateway_id}`), gateway_id: "MM01" },
    [`${C}/positions`]: example(`${C}/positions`),
    [`${C}/trades`]: example(`${C}/trades`),
    [`${C}/gateway-sessions`]: example(`${C}/gateway-sessions`),
    [`${C}/settlements`]: example(`${C}/settlements`),
    [`${C}/balances`]: example(`${C}/balances`),
    [`${C}/reconciliation`]: example(`${C}/reconciliation`),
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

function participantRow(gateway: string): HTMLElement {
  const table = screen.getByRole("table", { name: "Participants" });
  return within(table)
    .getAllByRole("row")
    .find((r) => within(r).queryAllByRole("cell")[0]?.textContent === gateway)!;
}

describe("Participants list", () => {
  it("says the rows open a participant, and the gateway cell is not a separate link", async () => {
    api();
    renderApp("/participants");
    const table = await screen.findByRole("table", { name: "Participants" });
    expect(screen.getByText(/Select a participant to open/)).toBeTruthy();
    expect(within(table).queryAllByRole("link")).toHaveLength(0);
  });

  it("opens the drawer over the list when a row is clicked", async () => {
    api();
    renderApp("/participants");
    await screen.findByRole("table", { name: "Participants" });
    fireEvent.click(participantRow("TRADER01"));
    const drawer = await screen.findByRole("dialog", { name: "Participant TRADER01" });
    expect(currentPath()).toBe("/participants/TRADER01");
    // The list stays, live, behind it.
    expect(screen.getByRole("table", { name: "Participants" })).toBeTruthy();
    await within(drawer).findByRole("table", { name: "TRADER01 positions" });
    expect(participantRow("TRADER01").getAttribute("aria-selected")).toBe("true");
    expect(participantRow("MM01").getAttribute("aria-selected")).toBe("false");
  });

  it("opens from the keyboard, and moves focus to the drawer's title", async () => {
    api();
    renderApp("/participants");
    await screen.findByRole("table", { name: "Participants" });
    const row = participantRow("TRADER01");
    expect(row.tabIndex).toBe(0);
    row.focus();
    fireEvent.keyDown(row, { key: "Enter" });
    const drawer = await screen.findByRole("dialog", { name: "Participant TRADER01" });
    await waitFor(() => expect(document.activeElement).toBe(within(drawer).getByRole("heading", { name: "Participant TRADER01" })));
  });

  it("closes with Escape, back to the list with focus on the row", async () => {
    api();
    renderApp("/participants/TRADER01");
    const drawer = await screen.findByRole("dialog", { name: "Participant TRADER01" });
    fireEvent.keyDown(within(drawer).getByRole("heading", { name: "Participant TRADER01" }), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(currentPath()).toBe("/participants");
    await waitFor(() => expect(document.activeElement).toBe(participantRow("TRADER01")));
  });

  it("closes with the close button", async () => {
    api();
    renderApp("/participants/TRADER01/trades");
    const drawer = await screen.findByRole("dialog", { name: "Participant TRADER01" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(currentPath()).toBe("/participants"));
  });

  it("a deep link shows the list and the drawer on the named tab", async () => {
    api();
    renderApp("/participants/TRADER01/trades");
    const drawer = await screen.findByRole("dialog", { name: "Participant TRADER01" });
    await within(drawer).findByRole("table", { name: "TRADER01 retained trades" });
    expect(await screen.findByRole("table", { name: "Participants" })).toBeTruthy();
  });

  it("keeps the list as it was (its sort) while the drawer opens and closes", async () => {
    api();
    renderApp("/participants");
    const table = await screen.findByRole("table", { name: "Participants" });
    const total = within(table).getByRole("button", { name: /Total P&L/ });
    fireEvent.click(total);
    expect(total.closest("th")!.getAttribute("aria-sort")).toBe("descending");
    fireEvent.click(participantRow("TRADER01"));
    const drawer = await screen.findByRole("dialog", { name: "Participant TRADER01" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(currentPath()).toBe("/participants"));
    const header = within(screen.getByRole("table", { name: "Participants" })).getByRole("columnheader", {
      name: /Total P&L/,
    });
    expect(header.getAttribute("aria-sort")).toBe("descending");
  });

  it("clicking another row puts that participant in the drawer", async () => {
    api();
    renderApp("/participants/TRADER01");
    await screen.findByRole("dialog", { name: "Participant TRADER01" });
    await screen.findByRole("table", { name: "Participants" });
    fireEvent.click(participantRow("MM01"));
    expect(await screen.findByRole("dialog", { name: "Participant MM01" })).toBeTruthy();
    expect(currentPath()).toBe("/participants/MM01");
  });
});

describe("gateway ids open the drawer", () => {
  async function linkIn(tableName: string, gateway: string): Promise<HTMLElement> {
    const table = await screen.findByRole("table", { name: tableName });
    return within(table).getAllByRole("link", { name: gateway })[0]!;
  }

  it("from Reconciliation", async () => {
    api();
    renderApp("/reconciliation");
    fireEvent.change(await screen.findByLabelText("From"), { target: { value: "2026-08-28" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-08-29" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    expect((await linkIn("Discrepancies", "TRADER01")).getAttribute("href")).toBe("/participants/TRADER01");
  });

  it("from Gateway Sessions", async () => {
    api();
    renderApp("/gateway-sessions");
    expect((await linkIn("Gateway sessions", "TRADER01")).getAttribute("href")).toBe("/participants/TRADER01");
  });

  it("from an EOD account, but not from EXCHANGE", async () => {
    const body = example<{ settlements: Record<string, unknown>[] }>(`${C}/settlements`);
    body.settlements.push({ ...body.settlements[0], account: "EXCHANGE", amount_minor: 1, amount: "0.01" });
    api();
    stubApi({
      [`${C}/settlements`]: body,
      [`${C}/balances`]: example(`${C}/balances`),
    });
    renderApp("/eod");
    expect((await linkIn("Settlements", "TRADER01")).getAttribute("href")).toBe("/participants/TRADER01");
    const table = screen.getByRole("table", { name: "Settlements" });
    expect(within(table).queryByRole("link", { name: /EXCHANGE/ })).toBeNull();
  });

  it("from a trade's buyer or seller in the drill-down", async () => {
    api();
    renderApp("/participants/TRADER01/trades");
    expect((await linkIn("TRADER01 retained trades", "TRADER01")).getAttribute("href")).toBe(
      "/participants/TRADER01",
    );
  });

  it("but not for a participant, who has no drill-down", async () => {
    useAuthStore.getState().logout();
    signIn("TRADER", "TRADER01");
    api();
    renderApp("/me/trades");
    const table = await screen.findByRole("table", { name: "My retained trades" });
    expect(within(table).queryAllByRole("link")).toHaveLength(0);
  });
});
