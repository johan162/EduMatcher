// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
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

let current: typeof REFERENCE = REFERENCE;

const apiFetchMock = vi.fn(async (path: string) => {
  if (path === "/api/v1/reference") return current;
  if (path === "/api/v1/reference/risk") return { ...current.risk, config_version: "abc123" };
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
import { useBookStore } from "@/store/useBookStore";

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  cleanup();
  current = REFERENCE;
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

  it("shows tick decimals, CB level count and live top-of-book per symbol", async () => {
    useBookStore.setState({
      books: {
        AAPL: { symbol: "AAPL", bids: [{ price: 149.5, quantity: 10 }], asks: [{ price: 150.25, quantity: 5 }] },
      },
    } as never);
    wrap(<AdminRiskPage />);
    await waitFor(() => expect(screen.getByText("149.50")).toBeTruthy());
    expect(screen.getByText("150.25")).toBeTruthy();
    expect(screen.getByText("Tick Dec.")).toBeTruthy();
  });

  it("renders the per-symbol circuit-breaker ladder with ns→duration formatting", async () => {
    wrap(<AdminRiskPage />);
    await waitFor(() => expect(screen.getByText("L1")).toBeTruthy());
    // 300e9 ns = 5m, 900e9 ns = 15m.
    expect(screen.getByText("5m")).toBeTruthy();
    expect(screen.getByText("15m")).toBeTruthy();
  });

  describe("paging", () => {
    const CB = {
      reference_window_ns: 60_000_000_000,
      levels: [
        { name: "L1", price_shift_pct: 5, halt_duration_ns: 300_000_000_000 },
        { name: "L2", price_shift_pct: 10, halt_duration_ns: 900_000_000_000 },
        { name: "L3", price_shift_pct: 15, halt_duration_ns: 1_800_000_000_000 },
      ],
    };
    const many = (n: number) => ({
      ...REFERENCE,
      symbols: Array.from({ length: n }, (_, i) => ({
        symbol: `S${String(i).padStart(2, "0")}`,
        tick_decimals: 2,
        level: null,
        circuit_breaker: CB,
      })),
    });
    const collarSymbols = () =>
      Array.from(document.querySelectorAll('section[aria-label="Collar settings"] tbody tr td:first-child')).map(
        (td) => td.textContent,
      );

    it("shows 15 symbols per page by default in both tables", async () => {
      current = many(40) as unknown as typeof REFERENCE;
      wrap(<AdminRiskPage />);
      await waitFor(() => expect(screen.getByText(/1–15 of 40/)).toBeTruthy());
      expect(collarSymbols()).toHaveLength(15);
      expect(document.querySelectorAll('[data-testid="cb-group"]')).toHaveLength(15);
      expect(screen.queryByText("S15")).toBeNull();
    });

    it("pages with Next/Prev and honours the page-size choice", async () => {
      current = many(40) as unknown as typeof REFERENCE;
      wrap(<AdminRiskPage />);
      await waitFor(() => expect(screen.getByText(/1–15 of 40/)).toBeTruthy());
      fireEvent.click(screen.getByText("Next"));
      expect(screen.getByText(/16–30 of 40/)).toBeTruthy();
      expect(collarSymbols()[0]).toBe("S15");
      fireEvent.click(screen.getByText("Prev"));
      expect(collarSymbols()[0]).toBe("S00");

      fireEvent.change(screen.getByLabelText("Symbols per page"), { target: { value: "30" } });
      expect(screen.getByText(/1–30 of 40/)).toBeTruthy();
      fireEvent.change(screen.getByLabelText("Symbols per page"), { target: { value: "50" } });
      expect(screen.getByText(/1–40 of 40/)).toBeTruthy();
      expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(true);
    });

    it("filters by symbol and returns to the first page", async () => {
      current = many(40) as unknown as typeof REFERENCE;
      wrap(<AdminRiskPage />);
      await waitFor(() => expect(screen.getByText(/1–15 of 40/)).toBeTruthy());
      fireEvent.click(screen.getByText("Next"));
      fireEvent.change(screen.getByLabelText("Filter symbol"), { target: { value: "s3" } });
      expect(screen.getByText(/1–10 of 10/)).toBeTruthy();
      expect(collarSymbols()[0]).toBe("S30");
      fireEvent.change(screen.getByLabelText("Filter symbol"), { target: { value: "ZZZ" } });
      expect(screen.getAllByText("No symbols match the filter.").length).toBe(2);
    });

    it("stripes the CB ladder per symbol, not per line", async () => {
      current = many(4) as unknown as typeof REFERENCE;
      wrap(<AdminRiskPage />);
      await waitFor(() => expect(document.querySelectorAll('[data-testid="cb-group"]').length).toBe(4));
      const groups = Array.from(document.querySelectorAll('[data-testid="cb-group"]'));
      expect(groups.map((g) => g.className.includes("bg-raised"))).toEqual([false, true, false, true]);
      for (const g of groups) expect(g.querySelectorAll("tr")).toHaveLength(3);
    });
  });
});
