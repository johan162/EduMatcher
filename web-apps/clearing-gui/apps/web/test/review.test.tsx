// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { z } from "zod";
import { apiFetch } from "@/api/apiFetch";
import { ContractError } from "@/api/errors";
import { formatCurrency, formatTicks, type Ticks } from "@/lib/money";
import { useAuthStore } from "@/store/useAuthStore";
import { currentPath, example, newQueryClient, renderApp, signIn, stubApi } from "./helpers";

/**
 * Regressions from the holistic review of CG5-CG9 (workplan §5, F14-F20).
 */
const C = "/api/v1/clearing";

beforeEach(() => {
  useAuthStore.getState().logout();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("review regressions", () => {
  it("F14: a new gateway filter never shows the previous gateway's rows", async () => {
    signIn("ADMIN", "OPS01");
    stubApi({
      [`${C}/gateway-sessions`]: (url: URL) =>
        url.searchParams.get("gateway") === "MM01" ? new Promise(() => {}) : example(`${C}/gateway-sessions`),
    });
    renderApp("/gateway-sessions");
    const table = await screen.findByRole("table", { name: "Gateway sessions" });
    expect(table.textContent).toContain("TRADER01");
    fireEvent.change(screen.getByLabelText("Gateway"), { target: { value: "MM01" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    // MM01's sessions have not arrived: TRADER01's must not stand in for them.
    await waitFor(() => expect(screen.queryByRole("table", { name: "Gateway sessions" })).toBeNull());
    expect(screen.queryByText("TRADER01")).toBeNull();
  });

  it("F15: logging out empties the query cache", async () => {
    signIn("TRADER", "TRADER01");
    stubApi({ [`${C}/positions`]: example(`${C}/positions`), [`${C}/exposure`]: example(`${C}/exposure`) });
    const client = newQueryClient();
    renderApp("/me/positions", client);
    await screen.findByRole("table", { name: "My positions" });
    expect(client.getQueryCache().getAll().length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Log out" }));
    await waitFor(() => expect(currentPath()).toBe("/login"));
    expect(client.getQueryCache().getAll()).toEqual([]);
  });

  it("F16: a 2xx reply that is not JSON is a contract error, not a crash", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<!doctype html><html></html>", { status: 200 })),
    );
    const err = await apiFetch(`${C}/positions`, z.object({})).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ContractError);
    expect((err as ContractError).message).toMatch(/not JSON/);
  });

  it("F17: Run with the same range runs the reconciliation again", async () => {
    signIn("ADMIN", "OPS01");
    const api = stubApi({ [`${C}/reconciliation`]: example(`${C}/reconciliation`) });
    renderApp("/reconciliation");
    fireEvent.change(await screen.findByLabelText("From"), { target: { value: "2026-08-28" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-08-29" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await screen.findByRole("table", { name: "Discrepancies" });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(api.calls(`${C}/reconciliation`).length).toBe(2));
  });

  it("F18: gaps counted without a latest gap still raise the alarm", async () => {
    signIn("ADMIN", "OPS01");
    const summary = example<Record<string, unknown>>(`${C}/summary`);
    summary["latest_gap"] = null;
    stubApi({
      [`${C}/summary`]: summary,
      [`${C}/health`]: example(`${C}/health`),
      [`${C}/participants`]: example(`${C}/participants`),
      [`${C}/session-events`]: example(`${C}/session-events`),
    });
    renderApp("/overview");
    expect((await screen.findByRole("alert", { name: /Feed gap/ })).textContent).toMatch(/1 gap seen/);
  });

  it("F19: the rounding account has no owes/owed direction", async () => {
    signIn("ADMIN", "OPS01");
    const settlements = example<{ settlements: Record<string, unknown>[] }>(`${C}/settlements`);
    settlements.settlements = [
      { ...settlements.settlements[0]!, account: "EXCHANGE", amount_minor: 1, amount: "0.01", detail: {} },
    ];
    stubApi({ [`${C}/settlements`]: settlements, [`${C}/balances`]: example(`${C}/balances`) });
    renderApp("/eod");
    const table = await screen.findByRole("table", { name: "Settlements" });
    expect(table.textContent).not.toMatch(/owes/);
    expect(table.textContent).toMatch(/rounding residual/);
  });

  it("F20: a value that rounds to zero is never shown as -0", () => {
    expect(formatTicks(-0.0001 as Ticks, 2)).toBe("0.00");
    expect(formatTicks(-0 as Ticks, 0)).toBe("0");
    expect(formatCurrency(-0.001)).toBe("0.00");
    expect(formatCurrency(-0.01)).toBe("-0.01");
  });
});
