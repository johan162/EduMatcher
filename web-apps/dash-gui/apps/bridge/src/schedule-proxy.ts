/**
 * `/api/reference/schedule`: pm-api-gwy's weekly session table and holiday
 * calendar, passed through unmodified for the Session schedule row
 * (terminal-gui's history proxy, cut down to this one endpoint).
 *
 * This is the bridge's only touchpoint with pm-api-gwy, and the read-only key
 * it needs lives here, server-side, and is never serialised to a browser.
 */

import type { FastifyInstance } from "fastify";

export interface ScheduleProxyOptions {
  baseUrl: string;
  apiKey: string;
  /** Injectable for tests; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

export function registerScheduleRoute(app: FastifyInstance, opts: ScheduleProxyOptions): void {
  const doFetch = opts.fetchImpl ?? fetch;
  const timeoutMs = opts.timeoutMs ?? 10_000;
  const target = `${opts.baseUrl.replace(/\/+$/, "")}/api/v1/reference/schedule`;

  app.get("/api/reference/schedule", async (request, reply) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const upstream = await doFetch(target, {
        headers: { Authorization: `Bearer ${opts.apiKey}` },
        signal: controller.signal,
      });
      const body = await upstream.text();
      return reply
        .status(upstream.status)
        .header("content-type", upstream.headers.get("content-type") ?? "application/json")
        .send(body);
    } catch (err) {
      request.log.warn(`schedule proxy failed: ${String(err)}`);
      return reply
        .status(502)
        .send({ error: "upstream_unavailable", message: `pm-api-gwy unreachable at ${opts.baseUrl}` });
    } finally {
      clearTimeout(timer);
    }
  });
}
