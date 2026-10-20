/**
 * metrics.db history (WP-C2.3/C2.4) against a fixture written by pm-monitor's
 * own MetricsStore (fixtures/make_metrics_db.py documents its timeline).
 */

import { chmodSync, copyFileSync, existsSync, mkdtempSync, renameSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
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
import { utcOffsetSec } from "../src/session-time.js";
import { frames, snapshot, startRig, type Rig } from "./harness.js";
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

/** A writable copy of the fixture, changed by `edit` before the test reads it. */
function variant(edit: (db: DatabaseSync) => void): string {
  const out = join(mkdtempSync(join(tmpdir(), "dash-variant-")), "metrics.db");
  copyFileSync(path, out);
  const db = new DatabaseSync(out);
  edit(db);
  db.close();
  return out;
}

async function get<T>(query: string, status = 200, on: Rig = rig): Promise<T> {
  const res = await fetch(`http://127.0.0.1:${on.port}${query}`);
  const body = (await res.json()) as T;
  expect(res.status, JSON.stringify(body)).toBe(status);
  return body;
}

describe("/api/series", () => {
  it("reads every sample while the 10 s rows cover the range", async () => {
    const r = await get<SeriesResponse>(`/api/series?name=host.cpu_pct&from=${iso(T0)}&to=${iso(T0 + HOUR)}`);
    expect(r).toMatchObject({ name: "host.cpu_pct", label: "", source: "host", resolution: "raw", bucketSec: 10 });
    expect(r.points).toHaveLength(360);
    expect(r.points[0]).toEqual([T0, 10]);
    expect(r.points[6]).toEqual([T0 + MIN, 11]); // minute 1 -> 10 + 1
    expect(r.points.at(-1)![0]).toBe(T0 + HOUR - 10_000);
  });

  it("buckets to at most 1000 points", async () => {
    const r = await get<SeriesResponse>(`/api/series?name=host.cpu_pct&range=7d`);
    // Retention never ran on the fixture: its raw rows reach back as far as
    // its minutes do, so even 7 d is answered from them.
    expect(r.resolution).toBe("raw");
    expect(r.bucketSec % 10).toBe(0);
    expect(r.points.length).toBeLessThanOrEqual(MAX_POINTS);
    expect(r.points.length).toBeGreaterThan(0);
    for (const [, v] of r.points) expect(v).toBeGreaterThanOrEqual(10);
    const six = await get<SeriesResponse>(`/api/series?name=host.cpu_pct&range=6h`);
    expect(six).toMatchObject({ resolution: "raw", bucketSec: 30 });
    expect(six.points).toHaveLength(240);
  });

  it("uses the minute table when retention has thinned the start of the range", () => {
    // Raw rows kept for the last hour only, as raw_hours: 1 would leave them.
    const db = new MetricsDb(variant((w) => w.prepare("DELETE FROM samples_raw WHERE ts < ?").run(iso(T0 + HOUR))));
    const two = db.series("host.cpu_pct", "", undefined, { fromMs: T0, toMs: T0 + 2 * HOUR }, 0);
    expect(two.resolution).toBe("1m");
    expect(two.points[0]).toEqual([T0, 10]); // not truncated to the last hour
    expect(db.series("host.cpu_pct", "", undefined, { fromMs: T0 + HOUR, toMs: T0 + 2 * HOUR }, 0).resolution).toBe("raw");
    db.close();
  });

  it("uses the raw rows when the range's older part has no data at all (a restart after a gap)", () => {
    // Found live (I105): retention removed old raw rows but kept that day's
    // minutes; a 5 min range after the restart must not go to the minute table.
    const db = new MetricsDb(
      variant((w) => {
        w.prepare("DELETE FROM samples_raw WHERE ts < ?").run(iso(T0 + HOUR));
        w.prepare("DELETE FROM samples_1m WHERE ts >= ? AND ts < ?").run(iso(T0 + 30 * MIN), iso(T0 + HOUR + MIN));
      }),
    );
    const recent = db.series("host.cpu_pct", "", undefined, { fromMs: T0 + 55 * MIN, toMs: T0 + 2 * HOUR }, 0);
    expect(recent.resolution).toBe("raw");
    expect(recent.points[0]![0]).toBe(T0 + HOUR);
    // Reaching back into minutes the raw rows lack: the minute table.
    expect(db.series("host.cpu_pct", "", undefined, { fromMs: T0, toMs: T0 + 2 * HOUR }, 0).resolution).toBe("1m");
    db.close();
  });

  it("uses the raw rows when the series began late in its first minute (I110)", () => {
    // First sample at :55 of a minute: that minute's row is stamped :00, the
    // first raw row is written at the next flush, up to 70 s later. Found
    // end to end: a 15 min chart went to a minute table not yet flushed.
    const db = new MetricsDb(variant((w) => w.prepare("DELETE FROM samples_raw WHERE ts < ?").run(iso(T0 + 65_000))));
    const r = db.series("engine.orders_in", "GW01", undefined, { fromMs: T0 - 5 * MIN, toMs: T0 + 10 * MIN }, 0);
    expect(r.resolution).toBe("raw");
    db.close();
  });

  it("uses the raw rows while no minute is written yet (pm-monitor just started)", () => {
    const db = new MetricsDb(variant((w) => w.exec("DELETE FROM samples_1m")));
    const r = db.series("host.cpu_pct", "", undefined, { fromMs: T0 - HOUR, toMs: T0 + 2 * HOUR }, 0);
    expect(r.resolution).toBe("raw");
    expect(r.points.length).toBeGreaterThan(0);
    db.close();
  });

  it("a window with no data at all is empty", async () => {
    const r = await get<SeriesResponse>(`/api/series?name=host.cpu_pct&from=${iso(T0 - 24 * HOUR)}&to=${iso(T0 - 23 * HOUR)}`);
    expect(r.points).toEqual([]);
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
    expect(all.series.map((s) => s.source)).toEqual(["pm-engine@h1", "pm-engine@h1"]);
  });

  it("one label from several processes, on the same bucket starts (TimeSeries' contract)", async () => {
    const r = await get<MultiSeriesResponse>(`/api/series/multi?name=proc.rss_bytes&sources=pm-engine@h1,pm-engine@h2&range=1h`);
    expect(r.series.map((s) => [s.source, s.points[0]![1]])).toEqual([
      ["pm-engine@h1", 1_000_000],
      ["pm-engine@h2", 2_000_000],
    ]);
    const ts = r.series.map((s) => s.points.map(([t]) => t));
    expect(ts[0]).toEqual(ts[1]);
    expect(r).toMatchObject({ resolution: "raw", bucketSec: 10 });
  });

  it("if one process needs the minute table, every series of the chart is read from it", () => {
    // h2's raw rows thinned by retention: h1 alone could be raw, h2 cannot.
    const file = variant((w) =>
      w.prepare("DELETE FROM samples_raw WHERE ts < ? AND series IN (SELECT id FROM series WHERE source = 'pm-engine@h2')").run(iso(T0 + HOUR)),
    );
    const db = new MetricsDb(file);
    expect(db.series("proc.rss_bytes", "", "pm-engine@h1", { fromMs: T0, toMs: T0 + 2 * HOUR }, 0).resolution).toBe("raw");
    expect(db.series("proc.rss_bytes", "", "pm-engine@h2", { fromMs: T0, toMs: T0 + 2 * HOUR }, 0).resolution).toBe("1m");
    db.close();
  });

  it("...and the route answers both from the minute table, on the same bucket starts", async () => {
    const file = variant((w) =>
      w.prepare("DELETE FROM samples_raw WHERE ts < ? AND series IN (SELECT id FROM series WHERE source = 'pm-engine@h2')").run(iso(T0 + HOUR)),
    );
    const other = await startRig({ metricsDbPath: file }, { connect: false, now: () => T0 + 2 * HOUR });
    try {
      const r = await get<MultiSeriesResponse>(
        `/api/series/multi?name=proc.rss_bytes&sources=pm-engine@h1,pm-engine@h2&from=${iso(T0)}&to=${iso(T0 + 2 * HOUR)}`,
        200,
        other,
      );
      expect(r).toMatchObject({ resolution: "1m", bucketSec: 60 });
      expect(r.series[0]!.points.map(([t]) => t)).toEqual(r.series[1]!.points.map(([t]) => t));
      expect(r.series[0]!.points).toHaveLength(120);
    } finally {
      await other.stop();
    }
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

describe("buckets on the session clock", () => {
  it("an hour is an hour of the exchange's day where the zone is not whole hours from UTC", async () => {
    // Asia/Kolkata is UTC+05:30: its hours start at :30 UTC. The fixture's
    // two hours from 08:00Z fall into 07:30-08:30 (half), 08:30-09:30 and
    // 09:30-10:30 (half), 90 orders a minute.
    const other = await startRig({ metricsDbPath: path }, { connect: false, now: () => T0 + 2 * HOUR });
    try {
      other.bridge.uplink.handle(frames("health.snapshot", snapshot(1, "Asia/Kolkata")));
      const r = await get<RateResponse>(
        `/api/rate?name=engine.orders_in&bucket=1h&from=${iso(T0)}&to=${iso(T0 + 2 * HOUR)}`,
        200,
        other,
      );
      expect(r.points).toEqual([
        [T0 - 30 * MIN, 2700],
        [T0 + 30 * MIN, 5400],
        [T0 + 90 * MIN, 2700],
      ]);
    } finally {
      await other.stop();
    }
  });

  it("without a snapshot the zone pm-monitor pinned in metrics.db is used", async () => {
    const status = await get<BridgeStatus>("/api/bridge/status");
    expect(status.sessionTz).toBe("Europe/Stockholm");
  });

  it("utcOffsetSec", () => {
    const summer = Date.parse("2026-07-01T12:00:00Z");
    const winter = Date.parse("2026-12-01T12:00:00Z");
    expect(utcOffsetSec("UTC", summer)).toBe(0);
    expect(utcOffsetSec("Europe/Stockholm", summer)).toBe(7200);
    expect(utcOffsetSec("Europe/Stockholm", winter)).toBe(3600);
    expect(utcOffsetSec("America/New_York", winter)).toBe(-5 * 3600);
    expect(utcOffsetSec("Asia/Kolkata", winter)).toBe(19800);
    expect(utcOffsetSec("Asia/Kathmandu", winter)).toBe(20700);
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
    ["/api/series?name=host.cpu_pct&from=2026-10-19T08:00:00", "bad_time"], // no zone: whose 08:00?
    ["/api/series?name=host.cpu_pct&from=2026-10-19", "bad_time"],
    ["/api/series?name=host.cpu_pct&range=1h&name=host.cpu_pct", "bad_param"],
    ["/api/events?range=1h&kind=HALT&kind=RESUME", "bad_param"],
    ["/api/series?name=host.cpu_pct&range=2h", "bad_range"],
    ["/api/series?name=host.cpu_pct&range=1h&from=1", "bad_range"],
    [`/api/series?name=${"x".repeat(65)}&range=1h`, "bad_name"],
    ["/api/series/multi?name=engine.orders_in&range=1h&labels=" + Array.from({ length: 51 }, (_, i) => `L${i}`).join(","), "too_many_series"],
    ["/api/series/multi?name=proc.rss_bytes&range=1h&sources=" + Array.from({ length: 51 }, (_, i) => `p${i}`).join(","), "too_many_series"],
    ["/api/series/multi?name=proc.rss_bytes&range=1h&sources=a&labels=b", "bad_param"],
    ["/api/series/multi?name=proc.rss_bytes&range=1h&sources=a&source=b", "bad_param"],
    ["/api/series/multi?name=proc.rss_bytes&range=1h&sources=,", "missing_param"],
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

  it("an ISO time with an offset is the same instant as its Z form", async () => {
    const z = await get<SeriesResponse>(`/api/series?name=host.cpu_pct&from=${iso(T0)}&to=${iso(T0 + HOUR)}`);
    const offset = await get<SeriesResponse>(
      `/api/series?name=host.cpu_pct&from=${encodeURIComponent("2026-10-19T10:00:00+02:00")}&to=${encodeURIComponent("2026-10-19T11:00:00+02:00")}`,
    );
    expect(offset.points).toEqual(z.points);
  });

  it("names reach SQL only as parameters", async () => {
    const r = await get<ApiError>(`/api/series?name=${encodeURIComponent("x' OR '1'='1")}&range=1h`, 400);
    expect(r.error).toBe("unknown_metric");
  });
});

describe("the database handle", () => {
  it("is read-only", () => {
    const db = new MetricsDb(path);
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

  it("a file SQLite cannot read is a 503 and unhealthy, not a 500", async () => {
    const bad = join(mkdtempSync(join(tmpdir(), "dash-bad-")), "metrics.db");
    writeFileSync(bad, "not a database at all, but long enough to have a header....".repeat(20));
    const other = await startRig({ metricsDbPath: bad });
    try {
      const err = await get<ApiError>("/api/series?name=x&range=1h", 503, other);
      expect(err).toMatchObject({ error: "metrics_db_unavailable" });
      expect(err.message).toContain("cannot be read");
      const status = await get<BridgeStatus>("/api/bridge/status", 200, other);
      expect(status.metricsDb.ok).toBe(false);
    } finally {
      await other.stop();
    }
  });

  it("follows a metrics.db replaced under it (pm-opctl-cli clear --all), not the deleted file", () => {
    const live = variant(() => undefined);
    const db = new MetricsDb(live);
    expect(db.events({ afterSeq: 0, limit: 10 })).toHaveLength(5);
    const fresh = variant((w) => w.exec("DELETE FROM events"));
    renameSync(fresh, live); // a new file at the same path
    expect(db.events({ afterSeq: 0, limit: 10 })).toEqual([]);
    db.close();
  });

  // Root ignores directory permissions, so the read-only mount cannot be
  // imitated with chmod there.
  it.skipIf(process.getuid?.() === 0)(
    "with pm-monitor stopped and a read-only directory it reads the file immutable, until a -wal appears (I105)",
    () => {
      const file = variant(() => undefined);
      const dir = dirname(file);
      expect(existsSync(`${file}-wal`)).toBe(false); // a clean close, as pm-monitor's
      chmodSync(dir, 0o555);
      const db = new MetricsDb(file);
      let writer: DatabaseSync | undefined;
      try {
        expect(db.events({ afterSeq: 0, limit: 10 })).toHaveLength(5);
        expect(db.health.detail).toContain("immutable");
        chmodSync(dir, 0o755);
        writer = new DatabaseSync(file); // pm-monitor starts: its WAL appears
        writer.prepare("INSERT INTO events(seq, ts, kind, severity, subject, detail) VALUES (6, ?, 'SESSION', 'INFO', 'x', '')").run(iso(T0));
        expect(existsSync(`${file}-wal`)).toBe(true);
        expect(db.events({ afterSeq: 0, limit: 10 })).toHaveLength(6);
        expect(db.health.detail).toBe("open (read-only)");
      } finally {
        chmodSync(dir, 0o755);
        writer?.close();
        db.close();
      }
    },
  );

  it("buckets widen in multiples of the native spacing", () => {
    expect(bucketFor({ fromMs: 0, toMs: HOUR }, 10)).toBe(10);
    expect(bucketFor({ fromMs: 0, toMs: 6 * HOUR }, 10)).toBe(30);
    expect(bucketFor({ fromMs: 0, toMs: 7 * 24 * HOUR }, 60)).toBe(660);
  });
});
