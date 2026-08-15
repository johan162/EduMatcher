// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const REFERENCE = {
  symbols: [
    { symbol: "AAPL", tick_decimals: 2, level: null, collar: { static_band_pct: 10, dynamic_band_pct: 5 } },
  ],
  risk: { default_level: null, levels: [] },
  indexes: [],
  schedule: { sessions_enabled: true, country: "US", schedule: null },
  config_version: "v1",
};

let indexDaily503 = false;

const apiFetchMock = vi.fn(async (path: string) => {
  if (path === "/api/v1/reference") return REFERENCE;
  if (path === "/api/v1/admin/indexes") {
    return {
      indexes: [{ id: "SPX", description: "Big Cap", base_value: 1000, constituents: ["AAPL", "MSFT"] }],
      config_version: "v1",
    };
  }
  if (path.startsWith("/api/v1/history/index-daily")) {
    if (indexDaily503) {
      const { ApiError } = await import("@/api/apiFetch");
      throw new ApiError(503, "STATS_DB", "no stats db");
    }
    return {
      daily: [{ date: "2026-08-13", open_level: 1000, high_level: 1010, low_level: 995, close_level: 1005, close_session_state: "CLOSED" }],
      count: 1,
      has_more: false,
    };
  }
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

import { AdminSymbolsPage } from "@/pages/AdminSymbolsPage";
import { AdminIndexesPage } from "@/pages/AdminIndexesPage";

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  indexDaily503 = false;
});

describe("AdminSymbolsPage (§15.2)", () => {
  it("renders symbols read-only with disabled Add/Edit and a prerequisite note", async () => {
    wrap(<AdminSymbolsPage />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Add symbol (unsupported)" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Edit AAPL (unsupported)" })).toHaveProperty("disabled", true);
    expect(screen.getByText(/requires a backend extension/)).toBeTruthy();
  });
});

describe("AdminIndexesPage (§15.3)", () => {
  it("renders configured indexes read-only (no write control)", async () => {
    wrap(<AdminIndexesPage />);
    await waitFor(() => expect(screen.getByText("SPX")).toBeTruthy());
    expect(screen.getByText("Big Cap")).toBeTruthy();
    // No rebalance/write button — assert an accurate note instead.
    expect(screen.getByText(/not surfaced as a UI control/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /rebalance/i })).toBeNull();
  });

  it("loads recorded levels for the selected index", async () => {
    wrap(<AdminIndexesPage />);
    await waitFor(() => expect(screen.getByText("SPX")).toBeTruthy());
    fireEvent.click(screen.getByText("SPX"));
    await waitFor(() => expect(screen.getByText("2026-08-13")).toBeTruthy());
    expect(screen.getByText("1005.00")).toBeTruthy(); // close_level formatted
  });

  it("degrades gracefully when the stats DB is unavailable (503)", async () => {
    indexDaily503 = true;
    wrap(<AdminIndexesPage />);
    await waitFor(() => expect(screen.getByText("SPX")).toBeTruthy());
    fireEvent.click(screen.getByText("SPX"));
    await waitFor(() => expect(screen.getByText(/stats database is not running/)).toBeTruthy());
  });
});
