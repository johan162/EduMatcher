/** The pure computations behind the rows (views/rows/common.ts, hooks/history.ts). */

import { describe, expect, it } from "vitest";
import type { HealthEvent, ParticipantStats, Point, ProcessHealth } from "@edumatcher/dash-types";
import { appendLive } from "../src/hooks/history.js";
import {
  beaconing,
  breachLevel,
  CONNECTED,
  connectedCount,
  connectionLanes,
  disconnectedMs,
  HEARTBEAT,
  heartbeatTimes,
  rejectRatio,
  shortKey,
  stateSummary,
} from "../src/views/rows/common.js";
import { liveValues } from "../src/views/rows/ProcessSeriesChart.js";
import { CAPTURED } from "./fixtures/snapshots.js";

const T0 = Date.parse("2026-10-20T08:00:00Z");
const MIN = 60_000;
const RANGE = { fromMs: T0, toMs: T0 + 60 * MIN };

const participant = (id: string, connected: boolean): ParticipantStats => ({ ...CAPTURED.participants[0]!, id, connected });
const ev = (seq: number, kind: "CONNECT" | "DISCONNECT", subject: string, minute: number, detail = ""): HealthEvent => ({
  seq,
  ts: new Date(T0 + minute * MIN).toISOString(),
  kind,
  severity: "INFO",
  subject,
  detail,
});

describe("connection lanes", () => {
  it("connected from a CONNECT to the next DISCONNECT, and on to now while connected", () => {
    const [lane] = connectionLanes([participant("T1", true)], [ev(1, "CONNECT", "T1", 5), ev(2, "DISCONNECT", "T1", 20, "logout"), ev(3, "CONNECT", "T1", 30)], RANGE, T0 + 50 * MIN);
    expect(lane!.segments).toEqual([
      { from: T0 + 5 * MIN, to: T0 + 20 * MIN, state: CONNECTED },
      { from: T0 + 30 * MIN, to: T0 + 50 * MIN, state: CONNECTED },
    ]);
    expect(lane!.marks).toEqual([]);
  });

  it("a first DISCONNECT means connected since before the range; a heartbeat timeout is marked", () => {
    const [lane] = connectionLanes([participant("T1", false)], [ev(1, "DISCONNECT", "T1", 10, "heartbeat_timeout")], RANGE, T0 + 50 * MIN);
    expect(lane!.segments).toEqual([{ from: T0, to: T0 + 10 * MIN, state: CONNECTED }]);
    expect(lane!.marks).toEqual([{ ts: T0 + 10 * MIN, kind: HEARTBEAT }]);
  });

  it("no events: the whole range if connected now, nothing if not; lanes sorted by id", () => {
    const lanes = connectionLanes([participant("B", false), participant("A", true)], [], RANGE, T0 + 50 * MIN);
    expect(lanes.map((l) => [l.id, l.segments.length])).toEqual([
      ["A", 1],
      ["B", 0],
    ]);
  });

  it("a last CONNECT the snapshot no longer believes (it disconnected since) is not drawn to now", () => {
    const [lane] = connectionLanes([participant("T1", false)], [ev(1, "CONNECT", "T1", 5)], RANGE, T0 + 50 * MIN);
    expect(lane!.segments).toEqual([]);
  });
});

describe("connected count and time disconnected", () => {
  const NOW = T0 + 50 * MIN;
  const seg = (from: number, to: number) => ({ from: T0 + from * MIN, to: T0 + to * MIN, state: CONNECTED });
  const lanes = [
    { id: "A", segments: [seg(-10, 20), seg(30, 50)], marks: [{ ts: T0 + 20 * MIN, kind: HEARTBEAT }] },
    { id: "B", segments: [seg(10, 50)], marks: [{ ts: T0 - MIN, kind: HEARTBEAT }] },
    { id: "C", segments: [] },
  ];

  it("steps at each change, from the range's start to the held step; a lane still connected does not drop at now", () => {
    expect(connectedCount(lanes, RANGE, NOW, NOW)).toEqual([
      [T0, 1],
      [T0 + 10 * MIN, 2],
      [T0 + 20 * MIN, 1],
      [T0 + 30 * MIN, 2],
      [NOW, 2],
    ]);
  });

  it("nobody connected: zero across the range so far", () => {
    expect(connectedCount([], RANGE, NOW, NOW)).toEqual([
      [T0, 0],
      [NOW, 0],
    ]);
  });

  it("a change after the held step still shows; then nothing is held past it", () => {
    const late = [{ id: "A", segments: [seg(0, 50.5)] }];
    expect(connectedCount(late, RANGE, NOW + MIN, NOW)).toEqual([
      [T0, 1],
      [T0 + 50.5 * MIN, 0],
    ]);
  });

  it("time disconnected counts up to now, within the range", () => {
    expect(lanes.map((l) => disconnectedMs(l, RANGE, NOW))).toEqual([10 * MIN, 10 * MIN, 50 * MIN]);
  });

  it("heartbeat timeouts of every lane inside the range, in time order", () => {
    expect(heartbeatTimes(lanes, RANGE)).toEqual([T0 + 20 * MIN]);
  });
});

describe("reject ratio, as pm-monitor judges it", () => {
  const minutes = (values: number[]): Point[] => values.map((v, i) => [T0 + i * MIN, v]);

  it("rejects over requests across five minutes, in percent", () => {
    const out = new Map(rejectRatio(minutes([1, 0, 0, 0, 1, 0]), minutes([10, 10, 10, 10, 10, 10]), MIN));
    expect(out.has(T0)).toBe(false); // 10 requests so far: too few
    expect(out.get(T0 + MIN)).toBe(5); // 1 of 20
    expect(out.get(T0 + 4 * MIN)).toBe(4); // 2 of 50
    expect(out.get(T0 + 5 * MIN)).toBe(2); // 1 of 50: the first minute has left the window
  });

  it("no ratio below 20 requests: the line has a gap", () => {
    expect(rejectRatio(minutes([5]), minutes([19]), MIN)).toEqual([]);
    expect(rejectRatio(minutes([5]), minutes([20]), MIN)).toEqual([[T0, 25]]);
  });

  it("hourly buckets are judged on their own", () => {
    const H = 3600_000;
    expect(rejectRatio([[T0, 3], [T0 + H, 0]], [[T0, 30], [T0 + H, 30]], H)).toEqual([
      [T0, 10],
      [T0 + H, 0],
    ]);
  });
});

describe("live points, at the chart's resolution", () => {
  it("one point when a new bucket begins, on the data's own bucket starts", () => {
    const points: Point[] = [[T0, 1]];
    expect(appendLive(points, T0 + 5_000, 2, 10_000)).toBe(points); // same bucket: nothing
    expect(appendLive(points, T0 + 12_000, 2, 10_000)).toEqual([[T0, 1], [T0 + 10_000, 2]]);
    expect(appendLive(points, T0 + 35_000, 2, 10_000)).toEqual([[T0, 1], [T0 + 30_000, 2]]); // after a gap
    expect(appendLive([[T0 + 3_000, 1]], T0 + 14_000, 2, 10_000)).toEqual([[T0 + 3_000, 1], [T0 + 13_000, 2]]); // the data's grid
  });

  it("nothing for no value, and a first point on the grid without data", () => {
    const points: Point[] = [[T0, 1]];
    expect(appendLive(points, T0 + 20_000, null, 10_000)).toBe(points);
    expect(appendLive(points, T0 + 20_000, Number.NaN, 10_000)).toBe(points);
    expect(appendLive([], T0 + 7_000, 4, 10_000)).toEqual([[T0, 4]]);
  });
});

describe("process labels", () => {
  it("summarises the states that are not HEALTHY, worst first", () => {
    const p = (state: ProcessHealth["state"]) => ({ ...CAPTURED.processes[0]!, state });
    expect(stateSummary([p("HEALTHY"), p("DEGRADED"), p("DEAD"), p("DEGRADED")])).toBe("1 DEAD, 2 DEGRADED");
    expect(stateSummary([p("HEALTHY")])).toBe("");
  });

  it("drops the host from a key", () => {
    expect(shortKey("pm-api-gwy/desk@kappa1")).toBe("pm-api-gwy/desk");
    expect(shortKey("pm-index")).toBe("pm-index");
  });
});

describe("live figures only while beacons arrive (I118)", () => {
  const p = (state: ProcessHealth["state"], host = "kappa1") => ({ ...CAPTURED.processes[0]!, state, host });

  it("HEALTHY, DEGRADED and HUNG beacon; SILENT, DEAD, STOPPED and MISSING do not", () => {
    expect((["HEALTHY", "DEGRADED", "HUNG"] as const).map((s) => beaconing(p(s)))).toEqual([true, true, true]);
    expect((["SILENT", "DEAD", "STOPPED", "MISSING"] as const).map((s) => beaconing(p(s)))).toEqual([false, false, false, false]);
    expect(beaconing(p("HEALTHY", ""))).toBe(false);
  });

  it("a chart's live values: none for a process whose beacons stopped, or that is gone", () => {
    const [a, b] = CAPTURED.processes;
    const snap = { ...CAPTURED, processes: [a!, { ...b!, state: "DEAD" as const }] };
    expect(liveValues(snap, [a!.key, b!.key, "pm-gone@x"], (x) => x.rss_bytes)).toEqual([a!.rss_bytes, null, null]);
  });
});

describe("breach levels", () => {
  const breach = (rule: string, subject: string, level: "WARN" | "CRIT") => ({ rule, subject, level, value: 0, threshold: 0, since: "" });
  it("the worst for the rule, on the subject when one is named; OK without", () => {
    const all = [breach("heap_garbage_pct", "AAPL", "WARN"), breach("heap_garbage_pct", "MSFT", "CRIT"), breach("host_cpu_pct", "host", "WARN")];
    expect(breachLevel(all, "heap_garbage_pct")).toBe("CRIT");
    expect(breachLevel(all, "heap_garbage_pct", "AAPL")).toBe("WARN");
    expect(breachLevel(all, "heap_garbage_pct", "GOOGL")).toBe("OK");
    expect(breachLevel([], "host_cpu_pct", "host")).toBe("OK");
  });
});
