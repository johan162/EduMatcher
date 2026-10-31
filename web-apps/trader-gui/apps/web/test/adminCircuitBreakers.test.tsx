// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const REFERENCE = {
  symbols: [
    {
      symbol: "AAPL",
      tick_decimals: 2,
      level: null,
      circuit_breaker: {
        levels: [
          { name: "L1", price_shift_pct: 5, halt_duration_ns: 300_000_000_000 },
          { name: "L2", price_shift_pct: 10, halt_duration_ns: 900_000_000_000 },
        ],
      },
    },
    { symbol: "MSFT", tick_decimals: 2, level: null },
  ],
  risk: { default_level: null, levels: [] },
  indexes: [],
  schedule: { sessions_enabled: true, country: "US", schedule: null },
  config_version: "v1",
};

const apiFetchMock = vi.fn(async (path: string, _init?: { body?: string }) => {
  if (path === "/api/v1/reference") return REFERENCE;
  if (path.startsWith("/api/v1/halts")) return { halted: [] };
  if (path === "/api/v1/admin/symbols/AAPL/halt") {
    return { accepted: true, symbol: "AAPL", reason: "", cancelled_quotes: 0 };
  }
  if (path === "/api/v1/admin/symbols/TSLA/resume") {
    return { accepted: true, symbol: "TSLA", reason: "" };
  }
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

import { AdminCircuitBreakersPage } from "@/pages/AdminCircuitBreakersPage";
import { useHaltStore } from "@/store/useHaltStore";

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const called = (path: string) => apiFetchMock.mock.calls.some(([p]) => String(p) === path);

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  vi.clearAllMocks();
  useHaltStore.setState({ halts: {} });
});

describe("AdminCircuitBreakersPage (§15.6)", () => {
  it("populates the level selector from the chosen symbol's ladder", async () => {
    wrap(<AdminCircuitBreakersPage />);
    await waitFor(() => expect(apiFetchMock.mock.calls.some(([p]) => p === "/api/v1/reference")).toBe(true));
    const symbolInput = screen.getByLabelText("Halt symbol");
    fireEvent.change(symbolInput, { target: { value: "AAPL" } });
    const levelSelect = screen.getByLabelText("Halt level") as HTMLSelectElement;
    expect(levelSelect.disabled).toBe(false);
    expect(within(levelSelect).getByRole("option", { name: /L1/ })).toBeTruthy();
    expect(within(levelSelect).getByRole("option", { name: /L2/ })).toBeTruthy();
  });

  it("disables the level selector for a symbol with no circuit breaker", async () => {
    wrap(<AdminCircuitBreakersPage />);
    await waitFor(() => expect(apiFetchMock.mock.calls.some(([p]) => p === "/api/v1/reference")).toBe(true));
    fireEvent.change(screen.getByLabelText("Halt symbol"), { target: { value: "MSFT" } });
    expect((screen.getByLabelText("Halt level") as HTMLSelectElement).disabled).toBe(true);
  });

  it("triggers a halt with the chosen level after confirmation", async () => {
    wrap(<AdminCircuitBreakersPage />);
    await waitFor(() => expect(apiFetchMock.mock.calls.some(([p]) => p === "/api/v1/reference")).toBe(true));
    fireEvent.change(screen.getByLabelText("Halt symbol"), { target: { value: "AAPL" } });
    fireEvent.change(screen.getByLabelText("Halt level"), { target: { value: "L1" } });
    fireEvent.click(screen.getByRole("button", { name: "Halt symbol" }));
    const dialog = screen.getByRole("dialog", { name: "Halt symbol?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Halt symbol" }));
    // D1: the symbol is the path segment; the body only carries the level.
    await waitFor(() => expect(called("/api/v1/admin/symbols/AAPL/halt")).toBe(true));
    const body = JSON.parse(
      apiFetchMock.mock.calls.find(([p]) => p === "/api/v1/admin/symbols/AAPL/halt")![1]!.body as string,
    );
    expect(body).toEqual({ level: "L1" });
  });

  it("reports an engine refusal (409 HALT_REJECTED) with the engine's reason", async () => {
    // WP-API01: refusals used to arrive as 403 ROLE_DENIED.
    const { ApiError } = await import("@/api/apiFetch");
    const { toast } = await import("sonner");
    wrap(<AdminCircuitBreakersPage />);
    await waitFor(() => expect(apiFetchMock.mock.calls.some(([p]) => p === "/api/v1/reference")).toBe(true));
    apiFetchMock.mockRejectedValueOnce(new ApiError(409, "HALT_REJECTED", "Unknown symbol: XYZ"));
    fireEvent.change(screen.getByLabelText("Halt symbol"), { target: { value: "AAPL" } });
    fireEvent.click(screen.getByRole("button", { name: "Halt symbol" }));
    const dialog = screen.getByRole("dialog", { name: "Halt symbol?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Halt symbol" }));
    await waitFor(() =>
      expect((toast.error as unknown as { mock: { calls: unknown[][] } }).mock.calls[0]![0]).toBe(
        "Rejected: Unknown symbol: XYZ",
      ),
    );
  });

  it("shows active halts and resumes one after confirmation", async () => {
    useHaltStore.setState({
      halts: { TSLA: { symbol: "TSLA", level: "L2", resume_at_ns: null, halt_source: "ADMIN" } },
    });
    wrap(<AdminCircuitBreakersPage />);
    expect(screen.getByText("TSLA")).toBeTruthy();
    expect(screen.getByText("indefinite")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear halt TSLA" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear halt" }));
    await waitFor(() => expect(called("/api/v1/admin/symbols/TSLA/resume")).toBe(true));
    const body = JSON.parse(
      apiFetchMock.mock.calls.find(([p]) => p === "/api/v1/admin/symbols/TSLA/resume")![1]!.body as string,
    );
    expect(body).toEqual({});
  });
});
