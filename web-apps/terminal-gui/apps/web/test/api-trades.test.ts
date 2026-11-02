import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/lib/api.js";

const row = (id: string, ts: string) => ({
  ts,
  trade_id: id,
  symbol: "AAPL",
  price: 1,
  quantity: 1,
  buy_gateway_id: null,
  sell_gateway_id: null,
});
const reply = (trades: unknown[], next_cursor: string | null) =>
  ({ ok: true, json: async () => ({ trades, next_cursor }) }) as Response;

describe("api.trades", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("walks newest-first through every page and returns oldest-first", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply([row("c", "T3"), row("b", "T2")], "cur"))
      .mockResolvedValueOnce(reply([row("a", "T1")], null));
    vi.stubGlobal("fetch", fetchMock);

    const { trades } = await api.trades("AAPL", "2026-11-02T00:00:00.000Z");

    expect(trades.map((t) => t.trade_id)).toEqual(["a", "b", "c"]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const first = new URL(fetchMock.mock.calls[0]![0] as string, "http://x");
    expect(first.searchParams.get("order")).toBe("desc");
    expect(first.searchParams.get("from")).toBe("2026-11-02T00:00:00.000Z");
    expect(first.searchParams.get("after")).toBeNull();
    const second = new URL(fetchMock.mock.calls[1]![0] as string, "http://x");
    expect(second.searchParams.get("after")).toBe("cur");
  });
});
