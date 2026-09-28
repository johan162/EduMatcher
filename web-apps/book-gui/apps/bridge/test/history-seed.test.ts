import { describe, expect, it } from "vitest";
import { HistoryClient, HistoryError } from "../src/session/history-seed.js";

type Route = (url: URL) => { status?: number; body: unknown };

function client(route: Route, calls: string[] = []) {
  const fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input));
    calls.push(url.pathname + url.search);
    expect((init?.headers as Record<string, string>)["Authorization"]).toBe("Bearer k");
    const { status = 200, body } = route(url);
    return new Response(JSON.stringify(body), { status });
  }) as typeof fetch;
  return new HistoryClient({ baseUrl: "http://gw:8081/", apiKey: "k", fetchImpl });
}

describe("HistoryClient", () => {
  it("reads the session timezone and trading date", async () => {
    const c = client(() => ({ body: { session_timezone: "Asia/Kolkata", session_date: "2026-09-27" } }));
    expect(await c.session()).toEqual({ timezone: "Asia/Kolkata", date: "2026-09-27" });
  });

  it("follows the trades cursor to the last page", async () => {
    const calls: string[] = [];
    const row = (id: string) => ({
      ts: "2026-09-27T09:00:00.000+00:00",
      trade_id: id,
      price: 1,
      quantity: 1,
    });
    const c = client((url) => {
      const after = url.searchParams.get("after");
      if (!after) return { body: { trades: [row("a")], has_more: true, next_cursor: "c1" } };
      if (after === "c1") return { body: { trades: [row("b")], has_more: true, next_cursor: "c2" } };
      return { body: { trades: [row("c")], has_more: false } };
    }, calls);

    expect((await c.trades("AAPL", "2026-09-27")).map((t) => t.id)).toEqual(["a", "b", "c"]);
    expect(calls).toHaveLength(3);
    expect(calls[0]).toBe("/api/v1/history/trades?symbol=AAPL&date=2026-09-27&limit=5000");
  });

  it("takes the newest non-null close strictly before the session date", async () => {
    const calls: string[] = [];
    const c = client(
      () => ({
        body: {
          daily: [
            { date: "2026-09-24", close_price: 90 },
            { date: "2026-09-25", close_price: 95 },
            { date: "2026-09-26", close_price: null },
            { date: "2026-09-27", close_price: 99 },
          ],
        },
      }),
      calls,
    );
    expect(await c.previousClose("AAPL", "2026-09-27")).toBe(95);
    expect(calls[0]).toBe("/api/v1/history/daily?symbol=AAPL&from=2026-09-13");
  });

  it("has no previous close for a symbol listed today", async () => {
    const c = client(() => ({ body: { daily: [{ date: "2026-09-27", close_price: 5 }] } }));
    expect(await c.previousClose("NEW", "2026-09-27")).toBeUndefined();
  });

  it("reads the symbol universe with each symbol's precision", async () => {
    const c = client(() => ({ body: { symbols: [{ symbol: "A", tick_decimals: 4 }, { symbol: 3 }] } }));
    expect(await c.symbols()).toEqual([{ symbol: "A", tickDecimals: 4 }]);
  });

  it("turns HTTP errors and unreachable upstreams into HistoryError", async () => {
    await expect(client(() => ({ status: 503, body: {} })).session()).rejects.toBeInstanceOf(HistoryError);
    const down = new HistoryClient({
      baseUrl: "http://gw",
      apiKey: "k",
      fetchImpl: (() => Promise.reject(new Error("ECONNREFUSED"))) as typeof fetch,
    });
    await expect(down.symbols()).rejects.toThrow(/unreachable/);
    await expect(client(() => ({ body: {} })).session()).rejects.toThrow(/malformed/);
  });
});
