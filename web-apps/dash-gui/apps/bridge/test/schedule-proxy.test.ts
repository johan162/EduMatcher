import Fastify, { type FastifyInstance } from "fastify";
import { afterEach, describe, expect, it, vi } from "vitest";
import { registerScheduleRoute } from "../src/schedule-proxy.js";

const apps: FastifyInstance[] = [];

afterEach(async () => {
  for (const app of apps.splice(0)) await app.close();
});

/** A bridge exposing only the schedule route, with upstream `fetch` stubbed. */
async function proxyApp(fetchImpl: typeof fetch) {
  const app = Fastify({ logger: false });
  apps.push(app);
  registerScheduleRoute(app, {
    baseUrl: "http://api-gwy.test:8081/",
    apiKey: "read-only-key",
    fetchImpl,
    timeoutMs: 200,
  });
  await app.ready();
  return app;
}

describe("schedule proxy", () => {
  it("passes pm-api-gwy's schedule through with the read-only key", async () => {
    const body = { sessions_enabled: true, country: "Sweden", schedule: null };
    const upstream = vi.fn(
      async (_url: string | URL | Request, _init?: RequestInit) =>
        new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }),
    );
    const app = await proxyApp(upstream as unknown as typeof fetch);

    const res = await app.inject({ method: "GET", url: "/api/reference/schedule" });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual(body);
    expect(String(upstream.mock.calls[0]?.[0])).toBe("http://api-gwy.test:8081/api/v1/reference/schedule");
    const init = upstream.mock.calls[0]?.[1];
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer read-only-key");
  });

  it("passes an upstream error status through", async () => {
    const upstream = vi.fn(async () => new Response('{"detail":"bad key"}', { status: 401 }));
    const app = await proxyApp(upstream as unknown as typeof fetch);

    const res = await app.inject({ method: "GET", url: "/api/reference/schedule" });

    expect(res.statusCode).toBe(401);
  });

  it("answers 502 when pm-api-gwy is unreachable", async () => {
    const upstream = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    const app = await proxyApp(upstream as unknown as typeof fetch);

    const res = await app.inject({ method: "GET", url: "/api/reference/schedule" });

    expect(res.statusCode).toBe(502);
    expect(res.json()).toMatchObject({ error: "upstream_unavailable" });
  });
});
