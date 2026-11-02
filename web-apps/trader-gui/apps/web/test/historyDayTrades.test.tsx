// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("@/api/endpoints.js", () => ({ getHistoryTrades: vi.fn() }));

import * as api from "@/api/endpoints.js";
import { useHistoryDayTradesQuery } from "@/queries/index.js";

const trade = (id: string, ts: string) => ({
  ts,
  trade_id: id,
  symbol: "AAPL",
  price: 1,
  quantity: 1,
  tick_decimals: 2,
  aggressor_side: "BUY" as const,
});
const page = (trades: ReturnType<typeof trade>[], next: string | null) => ({
  trades,
  count: trades.length,
  has_more: next !== null,
  next_cursor: next,
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useHistoryDayTradesQuery", () => {
  beforeEach(() => vi.mocked(api.getHistoryTrades).mockReset());

  it("pages newest-first across the whole day, stops at the prior day, returns ascending", async () => {
    vi.mocked(api.getHistoryTrades)
      .mockResolvedValueOnce(
        page([trade("d", "2026-11-02T15:00:00+00:00"), trade("c", "2026-11-02T12:00:00+00:00")], "p2"),
      )
      .mockResolvedValueOnce(
        page([trade("b", "2026-11-02T08:30:00+00:00"), trade("a", "2026-11-01T15:00:00+00:00")], "p3"),
      );

    const { result } = renderHook(() => useHistoryDayTradesQuery("AAPL", "UTC"), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.data?.trades.map((t) => t.trade_id)).toEqual(["b", "c", "d"]);
    const calls = vi.mocked(api.getHistoryTrades).mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[0]?.[2]).toEqual({ order: "desc", after: undefined });
    expect(calls[1]?.[2]).toEqual({ order: "desc", after: "p2" });
  });
});
