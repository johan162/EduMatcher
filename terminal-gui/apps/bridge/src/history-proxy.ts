/**
 * REST history proxy (design §17.2).
 *
 * CALF is live-only at every protocol version, so historical bars, midpoints
 * and index levels come from `pm-api-gwy`. This is the bridge's *only*
 * touchpoint with that service, and the only place any credential exists: the
 * read-only key lives here, server-side, and is never serialised to a browser
 * (design §18).
 *
 * Responses pass through unmodified, so the frontend's history code stays
 * interchangeable with `pm-trading-ui`'s.
 *
 * `GET /symbols` is deliberately absent. It requires a *trading* credential
 * (`require_trading` in `api_gateway/routers/reference.py`), which would mean
 * the bridge holding a second, higher-privilege key to read a tick size —
 * design §22's open question 1, to be resolved before it is wired in.
 */

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

/**
 * Endpoints proxied verbatim under `/api/history/`.
 *
 * `index-events` is the odd one out upstream: it round-trips live to pm-index
 * over ZMQ rather than reading pm-stats' SQLite, and paginates with
 * `max_records` instead of the others' cursor. Passed through as-is rather
 * than normalised, so its own contract stays visible to the caller.
 */
const HISTORY_ENDPOINTS = [
  "daily",
  "trades",
  "price-snapshots",
  "index-daily",
  "index-snapshots",
  "index-events",
] as const;

export interface HistoryProxyOptions {
  baseUrl: string;
  apiKey: string;
  /** Injectable for tests; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

export function registerHistoryRoutes(app: FastifyInstance, opts: HistoryProxyOptions): void {
  const doFetch = opts.fetchImpl ?? fetch;
  const timeoutMs = opts.timeoutMs ?? 10_000;
  const base = opts.baseUrl.replace(/\/+$/, "");

  for (const endpoint of HISTORY_ENDPOINTS) {
    app.get(`/api/history/${endpoint}`, async (request: FastifyRequest, reply: FastifyReply) => {
      const query = request.url.includes("?") ? request.url.slice(request.url.indexOf("?")) : "";
      const target = `${base}/api/v1/history/${endpoint}${query}`;

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
        // The upstream being unreachable is a gateway-level failure, distinct
        // from the 503 it returns itself when the stats DB is missing.
        request.log.warn(`history proxy failed for ${endpoint}: ${String(err)}`);
        return reply.status(502).send({
          error: { code: "UPSTREAM_UNAVAILABLE", message: `pm-api-gwy unreachable for /${endpoint}` },
        });
      } finally {
        clearTimeout(timer);
      }
    });
  }
}
