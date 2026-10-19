/**
 * metrics.db history (WP-C2.3/C2.4) against a fixture written by pm-monitor's
 * own MetricsStore (fixtures/make_metrics_db.py documents its timeline).
 */

import { DatabaseSync } from "node:sqlite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type {
  ApiError,
  BridgeStatus,
  DailyResponse,
  EventsResponse,
  MultiSeriesResponse,
  RateResponse,
  SeriesResponse,
} from "@edumatcher/dash-types";
import { bucketFor, MAX_POINTS, MetricsDb } from "../src/metrics-db.js";
import { startRig, type Rig } from "./harness.js";
import { buildMetricsFixture, HOUR, MIN, T0 } from "./metrics-fixture.js";

let path: string;
let rig: Rig;

beforeAll(async () => {
  path = buildMetricsFixture();
  rig = await startRig({ metricsDbPath: path }, { connect: false, now: () => T0 + 2 * HOUR });
}, 60_000);
afterAll(async () => {
  await rig?.stop();
});

const iso = (ms: number) => new Date(ms).toISOString();

async function get<T>(query: string, status = 200): Promise<T> {
  const res = await fetch(`http://127.0.0.1:${rig.port}${query}`);
  const body = (await res.json()) as T;
  expect(res.status, JSON.stringify(body)).toBe(status);
  return body;
}

describe("/api/series", () => {
  it("reads every sample for a range within raw_hours", async () => {
    const r = await get<SeriesResponse>(`/api/series?name=host.cpu_pct&from=${iso(T0)}&to=${iso(T0 + HOUR)}`);
    expect(r).toMatchObject({ name: "host.cpu_pct", label: "", source: "host", resolution: "raw", bucketSec: 10 });
    expect(r.points).toHaveLength(360);
    expect(r.points[0]).toEqual([T0, 10]);
    expect(r.points[6]).toEqual([T0 + MIN, 11]); // minute 1 -> 10 + 1
    expect(r.points.at(-1)![0]).toBe(T0 + HOUR - 10_000);
  });

  it("buckets to at most 1000 points, and uses the minute table beyond raw_hours", async () => {
    const r = await get<SeriesResponse>(`/api/series?name=host.cpu_pct&range=7d`);
    expect(r.resolution).toBe("1m");
    expect(r.bucketSec % 60).toBe(0);
    expect(r.points.length).toBeLessThanOrEqual(MAX_POINTS);
    expect(r.points.length).toBeGreaterThan(0);
    for (const [, v] of r.points) expect(v).toBeGreaterThanOrEqual(10);
    const six = await get<SeriesResponse>(`/api/series?name=host.cpu_pct&range=6h`);
    expect(six).toMatchObject({ resolution: "raw", bucketSec: 30 });
    expect(six.points).toHaveLength(240);
  });

  it("falls back to the minute table when raw rows are gone", async () => {
    // A 1 h window a day before the fixture's raw rows existed has no raw
    // data; it is not in the minute table either, so the answer is empty.
    const r = await get<SeriesResponse>(`/api/series?name=host.cpu_pct&from=${iso(T0 - 24 * HOUR)}&to=${iso(T0 - 23 * HOUR)}`);
    expect(r).toMatchObject({ resolution: "1m", points: [] });
  });

  it("selects a label, and requires source= when two processes record the name", async () => {
    const r = await get<SeriesResponse>(`/api/series?name=engine.orders_in&label=GW02&range=1h`);
    expect(r.source).toBe("pm-engine@h1");
    // The last 10 s bucket holds the 09:59:50 row (7192) and the shutdown
    // flush at 09:59:58 (7200): a bucket is the mean of its rows.
    expect(r.points.at(-1)).toEqual([T0 + 2 * HOUR - 10_000, 7196]);
    const err = await get<ApiError>(`/api/series?name=proc.rss_bytes&range=1h`, 400);
    expect(err.error).toBe("ambiguous_source");
    expect(err.message).toContain("pm-engine@h1, pm-engine@h2");
    const h2 = await get<SeriesResponse>(`/api/series?name=proc.rss_bytes&source=pm-engine@h2&range=1h`);
    expect(h2.points[0]![1]).toBe(2_000_000);
  });

  it("several labels of one metric", async () => {
    const r = await get<MultiSeriesResponse>(`/api/series/multi?name=engine.orders_in&labels=GW01,GW02&range=15m`);
    expect(r.series.map((s) => s.label)).toEqual(["GW01", "GW02"]);
    expect(r.series[1]!.points.at(-1)![1]).toBe(2 * r.series[0]!.points.at(-1)![1]);
    const all = await get<MultiSeriesResponse>(`/api/series/multi?name=engine.orders_in&range=15m`);
    expect(all.series.map((s) => s.label)).toEqual(["GW01", "GW02"]);
  });
});

describe("/api/rate", () => {
  it("increments per minute, summed over labels unless one is given", async () => {
    const all = await get<RateResponse>(`/api/rate?name=engine.orders_in&from=${iso(T0)}&to=${iso(T0 + 10 * MIN)}`);
    expect(all.points).toHaveLength(10);
    expect(all.points.every(([, v]) => v === 90)).toBe(true);
    expect(all.points[0]![0]).toBe(T0);
    const one = await get<RateResponse>(`/api/rate?name=engine.orders_in&label=GW01&from=${iso(T0)}&to=${iso(T0 + 10 * MIN)}`);
    expect(one.points.every(([, v]) => v === 30)).toBe(true);
  });

  it("per hour", async () => {
    const r = await get<RateResponse>(`/api/rate?name=engine.orders_in&bucket=1h&from=${iso(T0)}&to=${iso(T0 + 2 * HOUR)}`);
    expect(r.points).toEqual([
      [T0, 5400],
      [T0 + HOUR, 5400],
    ]);
  });
});

describe("/api/daily", () => {
  it("the latest trading dates' totals, oldest first", async () => {
    const r = await get<DailyResponse>(`/api/daily?name=engine.orders_in`);
    expect(r.days).toEqual([
      { date: "2026-10-17", total: 3000 },
      { date: "2026-10-18", total: 3000 },
      { date: "2026-10-19", total: 10800 },
    ]);
    const gw01 = await get<DailyResponse>(`/api/daily?name=engine.orders_in&label=GW01&days=2`);
    expect(gw01.days).toEqual([
      { date: "2026-10-18", total: 1000 },
      { date: "2026-10-19", total: 3600 },
    ]);
  });
});

describe("/api/events", () => {
  const seqs = (r: EventsResponse) => r.events.map((e) => e.seq);
  it("by range, by kind, newest first under a limit, and after a seq", async () => {
    expect(seqs(await get<EventsResponse>(`/api/events?from=${iso(T0 + 15 * MIN)}&to=${iso(T0 + 45 * MIN)}`))).toEqual([2, 3, 4]);
    expect(seqs(await get<EventsResponse>(`/api/events?range=24h&kind=THRESHOLD,SESSION`))).toEqual([4, 5]);
    expect(seqs(await get<EventsResponse>(`/api/events?range=24h&limit=2`))).toEqual([4, 5]);
    expect(seqs(await get<EventsResponse>(`/api/events?after_seq=2`))).toEqual([3, 4, 5]);
    const e = (await get<EventsResponse>(`/api/events?after_seq=2&limit=1`)).events[0]!;
    expect(e).toEqual({
      seq: 3,
      ts: "2026-10-19T08:30:00.000Z",
      kind: "PROCESS_STATUS",
      severity: "CRIT",
      subject: "pm-engine@h1",
      detail: "HEALTHY -> HUNG",
    });
  });
});

describe("validation", () => {
  it.each([
    ["/api/series?range=1h", "missing_param"],
    ["/api/series?name=engine.orders_in", "missing_param"],
    ["/api/series?name=no.such&range=1h", "unknown_metric"],
    [`/api/series?name=host.cpu_pct&from=${iso(T0)}&to=${iso(T0 + 8 * 24 * HOUR)}`, "range_too_long"],
    [`/api/series?name=host.cpu_pct&from=${iso(T0)}&to=${iso(T0 - 1)}`, "bad_range"],
    ["/api/series?name=host.cpu_pct&from=yesterday", "bad_time"],
    ["/api/series?name=host.cpu_pct&range=2h", "bad_range"],
    ["/api/series?name=host.cpu_pct&range=1h&from=1", "bad_range"],
    [`/api/series?name=${"x".repeat(65)}&range=1h`, "bad_name"],
    ["/api/series/multi?name=engine.orders_in&range=1h&labels=" + Array.from({ length: 51 }, (_, i) => `L${i}`).join(","), "too_many_labels"],
    ["/api/rate?name=engine.orders_in&range=1h&bucket=5m", "bad_bucket"],
    ["/api/rate?name=engine.orders_in&range=7d&bucket=1m", "too_many_points"],
    ["/api/daily?name=engine.orders_in&days=0", "bad_param"],
    ["/api/daily?name=engine.orders_in&days=367", "bad_param"],
    ["/api/events?range=1h&kind=NOPE", "bad_kind"],
    ["/api/events?range=1h&limit=1001", "bad_param"],
    ["/api/events?after_seq=-1", "bad_param"],
    ["/api/events", "missing_param"],
  ])("%s -> 400 %s", async (query, code) => {
    expect((await get<ApiError>(query, 400)).error).toBe(code);
  });

  it("an unknown label or source is a 404", async () => {
    expect((await get<ApiError>("/api/series?name=engine.orders_in&label=GW99&range=1h", 404)).error).toBe("unknown_series");
  });

  it("names reach SQL only as parameters", async () => {
    const r = await get<ApiError>(`/api/series?name=${encodeURIComponent("x' OR '1'='1")}&range=1h`, 400);
    expect(r.error).toBe("unknown_metric");
  });
});

describe("the database handle", () => {
  it("is read-only", () => {
    const db = new MetricsDb(path, 6);
    expect(db.health.ok).toBe(true);
    const handle = (db as unknown as { db: DatabaseSync }).db;
    expect(() => handle.exec("DELETE FROM events")).toThrow(/readonly/i);
    db.close();
  });

  it("a missing file is a 503 and shows in the bridge status", async () => {
    const other = await startRig({ metricsDbPath: "/nonexistent/metrics.db" });
    try {
      const res = await fetch(`http://127.0.0.1:${other.port}/api/series?name=x&range=1h`);
      expect(res.status).toBe(503);
      expect(((await res.json()) as ApiError).error).toBe("metrics_db_unavailable");
      const status = (await (await fetch(`http://127.0.0.1:${other.port}/api/bridge/status`)).json()) as BridgeStatus;
      expect(status.metricsDb).toMatchObject({ path: "/nonexistent/metrics.db", ok: false });
      expect(status.metricsDb.detail).toContain("not found");
    } finally {
      await other.stop();
    }
  });

  it("buckets widen in multiples of the native spacing", () => {
    expect(bucketFor({ fromMs: 0, toMs: HOUR }, 10)).toBe(10);
    expect(bucketFor({ fromMs: 0, toMs: 6 * HOUR }, 10)).toBe(30);
    expect(bucketFor({ fromMs: 0, toMs: 7 * 24 * HOUR }, 60)).toBe(660);
  });
});
