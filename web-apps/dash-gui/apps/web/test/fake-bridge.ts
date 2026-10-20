/**
 * A fake bridge REST API for the app tests: answers each path the rows and
 * drawers ask for, from the captured snapshot's time, and records every
 * request. Installed as the global `fetch`.
 */

import { vi } from "vitest";
import type { CrossAppLinks, ThresholdRule } from "@edumatcher/dash-types";
import { CAPTURED } from "./fixtures/snapshots.js";

export const NOW = Date.parse(CAPTURED.ts);
const rule = (warn: number, crit: number | null, invert = false): ThresholdRule => ({ warn, crit, invert, configurable: crit !== null });

export interface FakeBridge {
  calls: string[];
  /** Requests whose path and query start with `prefix`. */
  count: (prefix: string) => number;
}

export function fakeBridge(links: CrossAppLinks = { logGui: null, bookGui: null }): FakeBridge {
  const calls: string[] = [];
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://bridge");
    calls.push(`${url.pathname}?${url.searchParams.toString()}`);
    const q = url.searchParams;
    switch (url.pathname) {
      case "/api/bridge/status":
        return json({ links });
      case "/api/thresholds":
        return json({
          source: "defaults",
          path: "",
          rules: {
            host_cpu_pct: rule(80, 95),
            host_mem_pct: rule(80, 92),
            disk_free_pct: rule(15, 5, true),
            engine_handle_p99_us: rule(2000, 10000),
            reject_pct_5m: rule(10, 30),
            heap_garbage_pct: rule(50, 80),
            loop_age_ms: rule(1000, null),
          },
        });
      case "/api/events": {
        const events = [
          { seq: 1, ts: new Date(NOW - 60_000).toISOString(), kind: "CONNECT", severity: "INFO", subject: "TRADER01", detail: "" },
          { seq: 2, ts: new Date(NOW - 50_000).toISOString(), kind: "HALT", severity: "WARN", subject: "AAPL", detail: "volatility" },
        ];
        return json({ events: events.filter((e) => !q.has("subject") || e.subject === q.get("subject")) });
      }
      case "/api/series":
        return json({
          name: q.get("name"),
          label: q.get("label") ?? "",
          source: q.get("source") ?? "",
          resolution: "raw",
          bucketSec: 10,
          points: [[NOW - 20_000, 1], [NOW - 10_000, 2]],
        });
      case "/api/series/multi":
        return json({
          name: q.get("name"),
          resolution: "raw",
          bucketSec: 10,
          series: (q.get("sources") ?? "").split(",").map((source) => ({ label: "", source, points: [[NOW - 20_000, 1], [NOW - 10_000, 2]] })),
        });
      case "/api/rate/by-label":
        return json({ name: q.get("name"), bucket: "1m", series: [{ label: "TRADER01", points: [[NOW - 60_000, 8]] }, { label: "TRADER02", points: [[NOW - 60_000, 3]] }] });
      case "/api/rate":
        return json({ name: q.get("name") ?? q.get("names"), label: q.get("label"), bucket: "1m", points: [[NOW - 60_000, 30]] });
      default:
        return new Response(JSON.stringify({ error: "not_found", message: url.pathname }), { status: 404 });
    }
  });
  vi.stubGlobal("fetch", fetcher);
  return { calls, count: (prefix: string) => calls.filter((c) => c.startsWith(prefix)).length };
}
