// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { useAuthStore } from "@/store/useAuthStore";
import { example, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG22: Gateway, Symbol and Account filters are searchable lists (ARIA
 * combobox) of the values the venue has, instead of blind free text. A typed
 * value that is not listed still filters; empty is All.
 */
const C = "/api/v1/clearing";
const REFERENCE = "/api/v1/reference/symbols";

function api() {
  const balances = example<{ balances: Record<string, unknown>[] }>(`${C}/balances`);
  balances.balances.push({ ...balances.balances[0], account: "EXCHANGE" });
  return stubApi({
    [REFERENCE]: example(REFERENCE),
    [`${C}/participants`]: example(`${C}/participants`),
    [`${C}/trades`]: example(`${C}/trades`),
    [`${C}/daily`]: example(`${C}/daily`),
    [`${C}/close-snapshots`]: example(`${C}/close-snapshots`),
    [`${C}/gateway-sessions`]: example(`${C}/gateway-sessions`),
    [`${C}/settlements`]: example(`${C}/settlements`),
    [`${C}/balances`]: balances,
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

function combo(label: string): HTMLInputElement {
  return screen.getByRole("combobox", { name: label }) as HTMLInputElement;
}

function shownOptions(): string[] {
  return within(screen.getByRole("listbox")).getAllByRole("option").map((o) => o.textContent ?? "");
}

describe("searchable filters", () => {
  it("offers the venue's symbols, narrowed by what is typed, and picks one with the keyboard", async () => {
    signIn("TRADER", "TRADER01");
    const stub = api();
    renderApp("/me/trades");
    const input = (await screen.findByRole("combobox", { name: "Symbol" })) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "s" } });
    await waitFor(() => expect(shownOptions()).toEqual(["MSFT", "TSLA"]));
    expect(input.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).toBe(screen.getByRole("option", { name: "TSLA" }).id);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(input.value).toBe("TSLA");
    expect(screen.queryByRole("listbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(stub.calls(`${C}/trades`).some((u) => u.searchParams.get("symbol") === "TSLA")).toBe(true),
    );
  });

  it("matches case-insensitively and picks an option with the mouse", async () => {
    signIn("TRADER", "TRADER01");
    api();
    renderApp("/me/history");
    const input = (await screen.findByRole("combobox", { name: "Symbol" })) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "aa" } });
    await waitFor(() => expect(shownOptions()).toEqual(["AAPL"]));
    fireEvent.mouseDown(screen.getByRole("option", { name: "AAPL" }));
    expect(input.value).toBe("AAPL");
  });

  it("still filters by a value that is not listed", async () => {
    signIn("TRADER", "TRADER01");
    const stub = api();
    renderApp("/me/trades");
    const input = (await screen.findByRole("combobox", { name: "Symbol" })) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "zzz" } });
    expect(screen.queryByRole("listbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(stub.calls(`${C}/trades`).some((u) => u.searchParams.get("symbol") === "ZZZ")).toBe(true),
    );
  });

  it("Escape closes the list and keeps what was typed", async () => {
    signIn("TRADER", "TRADER01");
    api();
    renderApp("/me/trades");
    const input = (await screen.findByRole("combobox", { name: "Symbol" })) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "a" } });
    await screen.findByRole("listbox");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(input.value).toBe("a");
  });

  it("keeps the list open when its scrollbar is used (review R3)", async () => {
    signIn("TRADER", "TRADER01");
    api();
    renderApp("/me/trades");
    const input = (await screen.findByRole("combobox", { name: "Symbol" })) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "a" } });
    const list = await screen.findByRole("listbox");
    // A mousedown the list does not cancel would move focus off the input
    // and close the list: scrolling it with the mouse would be impossible.
    expect(fireEvent.mouseDown(list)).toBe(false);
  });

  it("Enter with nothing highlighted applies the filters and closes the list (review R3)", async () => {
    signIn("TRADER", "TRADER01");
    api();
    renderApp("/me/trades");
    const input = (await screen.findByRole("combobox", { name: "Symbol" })) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "a" } });
    await screen.findByRole("listbox");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("Enter with the list closed applies the filters, as before", async () => {
    signIn("TRADER", "TRADER01");
    const stub = api();
    renderApp("/me/trades");
    const input = (await screen.findByRole("combobox", { name: "Symbol" })) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "aapl" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.submit(input.form!);
    await waitFor(() =>
      expect(stub.calls(`${C}/trades`).some((u) => u.searchParams.get("symbol") === "AAPL")).toBe(true),
    );
  });

  it("offers the participants on Gateway Sessions", async () => {
    api();
    renderApp("/gateway-sessions");
    const input = await screen.findByRole("combobox", { name: "Gateway" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "m" } });
    await waitFor(() => expect(shownOptions()).toEqual(["MM01"]));
  });

  it("offers every account on EOD Settlement, EXCHANGE included", async () => {
    api();
    renderApp("/eod");
    const input = await screen.findByRole("combobox", { name: "Account" });
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    await waitFor(() => expect(shownOptions()).toEqual(["EXCHANGE", "TRADER01"]));
  });

  it("gives Reconciliation both a gateway and a symbol list", async () => {
    api();
    renderApp("/reconciliation");
    await screen.findByRole("combobox", { name: "Gateway" });
    expect(combo("Symbol")).toBeTruthy();
  });

  it("asks for the lists once, not on a poll", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const stub = api();
      renderApp("/gateway-sessions");
      await screen.findByRole("combobox", { name: "Gateway" });
      await vi.advanceTimersByTimeAsync(30_000);
      expect(stub.calls(`${C}/participants`)).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("has no axe violations with the list open", async () => {
    signIn("TRADER", "TRADER01");
    api();
    renderApp("/me/trades");
    const input = (await screen.findByRole("combobox", { name: "Symbol" })) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "a" } });
    await screen.findByRole("listbox");
    const result = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
