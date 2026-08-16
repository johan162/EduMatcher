// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const REFERENCE = {
  symbols: [
    {
      symbol: "AAPL",
      tick_decimals: 2,
      level: null,
      collar: { static_band_pct: 10, dynamic_band_pct: 5 },
      circuit_breaker: {
        reference_window_ns: 60_000_000_000,
        levels: [
          { name: "L1", price_shift_pct: 5, halt_duration_ns: 300_000_000_000 },
          { name: "L2", price_shift_pct: 10, halt_duration_ns: 900_000_000_000 },
        ],
      },
    },
    { symbol: "MSFT", tick_decimals: 2, level: "L_TIGHT" },
  ],
  risk: {
    default_level: "L_DEFAULT",
    levels: [
      { name: "L_DEFAULT", collar: { static_band_pct: 20, dynamic_band_pct: 8 } },
      { name: "L_TIGHT", collar: { static_band_pct: 3, dynamic_band_pct: 2 } },
    ],
  },
  indexes: [],
  schedule: { sessions_enabled: true, country: "US", schedule: null },
  config_version: "abc123",
};

const apiFetchMock = vi.fn(async (path: string) => {
  if (path === "/api/v1/reference") return REFERENCE;
  if (path === "/api/v1/reference/risk") return { ...REFERENCE.risk, config_version: "abc123" };
  return {};
});

vi.mock("@/api/apiFetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...(args as [string])),
  ApiError: class ApiError extends Error {
    constructor(public status = 0, public code = "UNKNOWN", message = "") {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { AdminRiskPage } from "@/pages/AdminRiskPage";

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
});

describe("AdminRiskPage (§15.5)", () => {
  it("renders risk levels with collar bands", async () => {
    wrap(<AdminRiskPage />);
    await waitFor(() => expect(screen.getByText("L_DEFAULT")).toBeTruthy());
    expect(screen.getByText("20.00%")).toBeTruthy(); // static band of L_DEFAULT
    expect(screen.getByText("Default level: L_DEFAULT")).toBeTruthy();
  });

  it("resolves a symbol's effective collar (own vs inherited level)", async () => {
    wrap(<AdminRiskPage />);
    // AAPL appears in both the collar table and the CB ladder.
    await waitFor(() => expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0));
    // AAPL has its own collar → profile "symbol" (unique to the collar table).
    expect(screen.getByText("symbol")).toBeTruthy();
    expect(screen.getAllByText("10.00%").length).toBeGreaterThan(0);
    // MSFT inherits L_TIGHT (appears in the risk-levels table and MSFT's profile).
    expect(screen.getAllByText("L_TIGHT").length).toBeGreaterThanOrEqual(2);
  });

  it("renders the per-symbol circuit-breaker ladder with ns→duration formatting", async () => {
    wrap(<AdminRiskPage />);
    await waitFor(() => expect(screen.getByText("L1")).toBeTruthy());
    // 300e9 ns = 5m, 900e9 ns = 15m.
    expect(screen.getByText("5m")).toBeTruthy();
    expect(screen.getByText("15m")).toBeTruthy();
  });
});
