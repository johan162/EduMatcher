// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const apiFetchMock = vi.fn(async (path: string, _init?: { body?: string }) => {
  if (path.startsWith("/api/v1/oco")) return { id: "oco-x", status: "PENDING", event: null };
  if (path.startsWith("/api/v1/combos")) return { id: "combo-x", status: "PENDING", event: null };
  return {};
});

vi.mock("@/api/apiFetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...(args as [string, { body?: string }])),
  ApiError: class ApiError extends Error {
    constructor(public status = 0, public code = "UNKNOWN", message = "") {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { OcoForm } from "@/components/orders/OcoForm";
import { ComboForm } from "@/components/orders/ComboForm";
import { useSymbolStore } from "@/store/useSymbolStore";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore";
import { useNotificationStore } from "@/store/useNotificationStore";
import type { Symbol } from "@/types/index";

const SYMBOLS: Symbol[] = [
  { symbol: "AAPL", tick_decimals: 2, prev_close: 150, collar_reference_price: null, level: null },
  { symbol: "MSFT", tick_decimals: 2, prev_close: 410, collar_reference_price: null, level: null },
];

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function bodyFor(pathPart: string): Record<string, unknown> {
  const call = apiFetchMock.mock.calls.find(([p]) => String(p).includes(pathPart)) as
    | [string, { body: string }]
    | undefined;
  return JSON.parse(call![1].body);
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  useSymbolStore.setState({ symbols: SYMBOLS });
  useActiveSymbolStore.setState({ activeSymbol: "AAPL" });
  useNotificationStore.setState({ entries: [], unread: 0 });
});

describe("OcoForm (§12.7)", () => {
  it("POSTs a two-leg OCO with the shared symbol/qty and per-leg prices", async () => {
    wrap(<OcoForm />);
    fireEvent.change(screen.getByLabelText("Leg 1 price"), { target: { value: "155" } });
    fireEvent.change(screen.getByLabelText("Leg 2 price"), { target: { value: "145" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit OCO" }));
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(apiFetchMock.mock.calls.at(-1)![0]).toBe("/api/v1/oco");
    const body = bodyFor("/api/v1/oco");
    expect(body).toMatchObject({
      symbol: "AAPL",
      quantity: 100,
      tif: "DAY",
      leg1: { side: "SELL", order_type: "LIMIT", price: 155 },
      leg2: { side: "SELL", order_type: "LIMIT", price: 145 },
    });
    expect(typeof body.oco_id).toBe("string");
    // The leg must not carry stray fields (StrictModel extra=forbid server-side).
    expect(body.leg1).not.toHaveProperty("stop_price");
  });

  it("reads the response `id` (not `oco_id`) into the Event Center", async () => {
    wrap(<OcoForm />);
    fireEvent.change(screen.getByLabelText("Leg 1 price"), { target: { value: "155" } });
    fireEvent.change(screen.getByLabelText("Leg 2 price"), { target: { value: "145" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit OCO" }));
    await waitFor(() => expect(useNotificationStore.getState().entries.length).toBe(1));
    expect(useNotificationStore.getState().entries[0]!.title).toContain("oco-x");
  });

  it("blocks a LIMIT leg with no price and shows an inline error", () => {
    wrap(<OcoForm />);
    // Leave leg prices empty.
    fireEvent.click(screen.getByRole("button", { name: "Submit OCO" }));
    expect(screen.getAllByText("Price required for a LIMIT leg").length).toBeGreaterThan(0);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("switches a leg to STOP and sends stop_price instead of price", async () => {
    wrap(<OcoForm />);
    fireEvent.change(screen.getByLabelText("Leg 1 type"), { target: { value: "STOP" } });
    fireEvent.change(screen.getByLabelText("Leg 1 stop price"), { target: { value: "140" } });
    fireEvent.change(screen.getByLabelText("Leg 2 price"), { target: { value: "160" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit OCO" }));
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    const body = bodyFor("/api/v1/oco");
    expect(body.leg1).toMatchObject({ order_type: "STOP", stop_price: 140 });
    expect(body.leg1).not.toHaveProperty("price");
  });
});

describe("ComboForm (§12.8)", () => {
  it("POSTs a combo with the leg list and combo-level tif/type", async () => {
    wrap(<ComboForm />);
    const prices = screen.getAllByLabelText(/Leg \d price/);
    fireEvent.change(prices[0]!, { target: { value: "150" } });
    fireEvent.change(prices[1]!, { target: { value: "410" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit Combo" }));
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(apiFetchMock.mock.calls.at(-1)![0]).toBe("/api/v1/combos");
    const body = bodyFor("/api/v1/combos");
    expect(body).toMatchObject({ combo_type: "AON", tif: "DAY" });
    expect(Array.isArray(body.legs)).toBe(true);
    expect((body.legs as unknown[]).length).toBe(2);
    expect(typeof body.combo_id).toBe("string");
  });

  it("adds and removes legs within the 2–10 bound", () => {
    wrap(<ComboForm />);
    expect(screen.getByText("2/10 legs")).toBeTruthy();
    // Remove is disabled at the 2-leg minimum.
    expect(screen.getByRole("button", { name: "Remove leg 1" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: /Add leg/ }));
    expect(screen.getByText("3/10 legs")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove leg 3" }));
    expect(screen.getByText("2/10 legs")).toBeTruthy();
  });

  it("blocks a LIMIT leg with no price", () => {
    wrap(<ComboForm />);
    fireEvent.click(screen.getByRole("button", { name: "Submit Combo" }));
    expect(screen.getAllByText("Price required for a LIMIT leg").length).toBeGreaterThan(0);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});
