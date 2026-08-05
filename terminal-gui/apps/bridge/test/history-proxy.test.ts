import Fastify, { type FastifyInstance } from "fastify";
import { afterEach, describe, expect, it, vi } from "vitest";
import { registerHistoryRoutes } from "../src/history-proxy.js";

const apps: FastifyInstance[] = [];

afterEach(async () => {
  for (const app of apps.splice(0)) await app.close();
});

/** Build a bridge exposing only the proxy, with upstream `fetch` stubbed. */
async function proxyApp(fetchImpl: typeof fetch) {
  const app = Fastify({ logger: false });
  apps.push(app);
  registerHistoryRoutes(app, {
    baseUrl: "http://api-gwy.test:8080",
    apiKey: "read-only-key",
    fetchImpl,
    timeoutMs: 200,
  });
  await app.ready();
  return app;
}

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** A spy with `fetch`'s real signature, so its recorded args stay typed. */
const spyFetch = (body: unknown, status = 200) =>
  vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => jsonResponse(body, status));

describe("history proxy", () => {
  it("forwards to the versioned upstream path", async () => {
    const upstream = spyFetch({ daily: [], count: 0, has_more: false });
    const app = await proxyApp(upstream as unknown as typeof fetch);

    await app.inject({ method: "GET", url: "/api/history/daily?symbol=AAPL" });

    expect(upstream).toHaveBeenCalledOnce();
    expect(String(upstream.mock.calls[0]?.[0])).toBe(
      "http://api-gwy.test:8080/api/v1/history/daily?symbol=AAPL",
    );
  });

  it("attaches the bridge's key so the browser never needs one", async () => {
    const upstream = spyFetch({});
    const app = await proxyApp(upstream as unknown as typeof fetch);

    await app.inject({ method: "GET", url: "/api/history/daily" });

    const init = upstream.mock.calls[0]?.[1];
    expect((init?.headers as Record<string, string>)["Authorization"]).toBe("Bearer read-only-key");
  });

  it("returns the upstream body unmodified", async () => {
    const payload = { daily: [{ symbol: "AAPL", close_price: 150.12 }], count: 1, has_more: false };
    const app = await proxyApp((async () => jsonResponse(payload)) as unknown as typeof fetch);

    const res = await app.inject({ method: "GET", url: "/api/history/daily?symbol=AAPL" });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual(payload);
  });

  it("passes the full query string through, including aliased params", async () => {
    const upstream = spyFetch({});
    const app = await proxyApp(upstream as unknown as typeof fetch);

    await app.inject({
      method: "GET",
      url: "/api/history/trades?symbol=AAPL&from=2026-07-30T09:00:00Z&limit=1000&after=abc",
    });

    expect(String(upstream.mock.calls[0]?.[0])).toContain("from=2026-07-30T09:00:00Z&limit=1000&after=abc");
  });

  it.each(["daily", "trades", "price-snapshots", "index-daily", "index-snapshots", "index-events"])(
    "exposes /api/history/%s",
    async (endpoint) => {
      const app = await proxyApp((async () => jsonResponse({})) as unknown as typeof fetch);
      const res = await app.inject({ method: "GET", url: `/api/history/${endpoint}` });
      expect(res.statusCode).toBe(200);
    },
  );

  it("does not expose /api/symbols, which needs a trading credential", async () => {
    // Design §22 open question 1 — deliberately not wired in yet.
    const app = await proxyApp((async () => jsonResponse({})) as unknown as typeof fetch);
    expect((await app.inject({ method: "GET", url: "/api/symbols" })).statusCode).toBe(404);
  });

  it("propagates the 503 pm-api-gwy returns when the stats DB is unavailable", async () => {
    const body = { detail: { error: { code: "STATS_DB", message: "missing" } } };
    const app = await proxyApp((async () => jsonResponse(body, 503)) as unknown as typeof fetch);

    const res = await app.inject({ method: "GET", url: "/api/history/daily" });

    expect(res.statusCode).toBe(503);
    expect(res.json()).toEqual(body);
  });

  it("propagates a 422 validation error rather than masking it", async () => {
    const app = await proxyApp((async () =>
      jsonResponse({ detail: "bad date" }, 422)) as unknown as typeof fetch);
    expect((await app.inject({ method: "GET", url: "/api/history/daily?date=today" })).statusCode).toBe(422);
  });

  it("propagates a 401, which means the bridge's own key is wrong", async () => {
    const app = await proxyApp((async () =>
      jsonResponse({ detail: "unknown key" }, 401)) as unknown as typeof fetch);
    expect((await app.inject({ method: "GET", url: "/api/history/daily" })).statusCode).toBe(401);
  });

  it("answers 502 when pm-api-gwy is unreachable, distinct from its own 503", async () => {
    const app = await proxyApp((async () => {
      throw new Error("ECONNREFUSED");
    }) as unknown as typeof fetch);

    const res = await app.inject({ method: "GET", url: "/api/history/daily" });

    expect(res.statusCode).toBe(502);
    expect(res.json().error.code).toBe("UPSTREAM_UNAVAILABLE");
  });

  it("answers 502 rather than hanging when upstream never responds", async () => {
    const app = await proxyApp(((_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new Error("aborted")));
      });
    }) as unknown as typeof fetch);

    const res = await app.inject({ method: "GET", url: "/api/history/daily" });
    expect(res.statusCode).toBe(502);
  });
});
