/**
 * What the dashboard rows share (design §12.3, D3): the dashboard-wide
 * loads (threshold rules, the event log's catch-up), threshold lookup, and the pure computations behind two panels --
 * the connection lanes and count, and the reject ratio -- kept here so they are
 * tested on their own.
 */

import { useEffect, useMemo } from "react";
import type { ActiveBreach, BridgeStatus, EventsResponse, HealthEvent, ParticipantStats, Point, ProcessHealth, ThresholdsResponse } from "@edumatcher/dash-types";
import type { Lane, Segment, Mark, TimeRangeMs } from "../../components/widgets/StateTimeline.js";
import { getJson, query } from "../../lib/api.js";
import { MIN_REQUESTS } from "../../lib/metrics.js";
import { REFRESH_MS } from "../../lib/range.js";
import { fromRule, type Level, type Thresholds } from "../../lib/thresholds.js";
import { useDashStore } from "../../store/useDashStore.js";

/** `pm-api-gwy/desk@host` -> `pm-api-gwy/desk`: the host is the same for all on one box. */
export function shortKey(key: string): string {
  const at = key.lastIndexOf("@");
  return at > 0 ? key.slice(0, at) : key;
}

/** Processes with a beacon (not MISSING), the exchange's own, by key. */
export function liveExchangeProcesses(processes: readonly ProcessHealth[]): ProcessHealth[] {
  return processes.filter((p) => p.group === "EXCHANGE" && p.host !== "").sort((a, b) => a.key.localeCompare(b.key));
}

/** States in which beacons still arrive (HUNG: the loop is stuck, the reporter is not). */
const BEACONING = new Set(["HEALTHY", "DEGRADED", "HUNG"]);

/**
 * Whether a process's figures are current. pm-monitor keeps the last
 * beacon's figures in a SILENT, DEAD or STOPPED process's record, so they
 * must not be drawn as live (I118).
 */
export function beaconing(p: ProcessHealth): boolean {
  return p.host !== "" && BEACONING.has(p.state);
}

/** "1 DEGRADED, 2 HUNG" for the processes not HEALTHY, worst first; "" when all are. */
export function stateSummary(processes: readonly ProcessHealth[]): string {
  const order = ["DEAD", "SILENT", "MISSING", "HUNG", "STOPPED", "DEGRADED"];
  const counts = new Map<string, number>();
  for (const p of processes) if (p.state !== "HEALTHY") counts.set(p.state, (counts.get(p.state) ?? 0) + 1);
  return order
    .filter((s) => counts.has(s))
    .map((s) => `${counts.get(s)} ${s}`)
    .join(", ");
}

/**
 * Each time the bridge connection opens: the threshold rules, the
 * cross-app links, and the events the log is missing -- the picker's range
 * at first, after the last seq held once there are some (a reconnect). The
 * rules and links are asked again every refresh interval, so a redeployed
 * artifact shows without a reload (I118).
 */
export function useDashboardLoads(): void {
  const socket = useDashStore((s) => s.socket);
  const refresh = useDashStore((s) => s.refresh);
  useEffect(() => {
    if (socket !== "OPEN") return;
    const ctl = new AbortController();
    const { addEvents, events, range } = useDashStore.getState();
    const last = events.at(-1)?.seq;
    const q = last === undefined ? query({ range, limit: 500 }) : query({ after_seq: last, limit: 1000 });
    getJson<EventsResponse>(`/api/events?${q}`, ctl.signal).then(
      (r) => addEvents(r.events),
      () => undefined, // live events still arrive
    );
    return () => ctl.abort();
  }, [socket]);
  useEffect(() => {
    if (socket !== "OPEN") return;
    const ctl = new AbortController();
    const { setThresholds, setLinks } = useDashStore.getState();
    const load = () => {
      getJson<ThresholdsResponse>("/api/thresholds", ctl.signal).then(
        (r) => setThresholds(r.rules),
        () => undefined, // without rules the widgets draw no bands; the bridge logs why
      );
      getJson<BridgeStatus>("/api/bridge/status", ctl.signal).then(
        (r) => setLinks(r.links),
        () => undefined, // no cross-links
      );
    };
    load();
    const every = REFRESH_MS[refresh];
    const timer = every === null ? undefined : setInterval(load, every);
    return () => {
      ctl.abort();
      clearInterval(timer);
    };
  }, [socket, refresh]);
}

/** The widget thresholds of rule `name`, once the rules are loaded. */
export function useRule(name: string): Thresholds | undefined {
  const rule = useDashStore((s) => s.thresholds?.[name]);
  return useMemo(() => (rule ? fromRule(rule) : undefined), [rule]);
}

/**
 * The level pm-monitor gives `rule` right now -- on `subject`, or the worst
 * over every subject when none is named -- from the snapshot's active
 * breaches: OK when none, undefined before a snapshot. Every coloured figure
 * takes its level from here rather than judging the value itself, since
 * pm-monitor also applies hysteresis, minimum samples and which subjects
 * it judges at all (a book with too few heap entries, a process that is not
 * live), and the dashboard must not disagree with it (I118). The rule's
 * thresholds still draw the bands and the hover text.
 */
export function useBreachLevel(rule: string, subject?: string): Level | undefined {
  return useDashStore((s) => (s.snapshot ? breachLevel(s.snapshot.thresholds, rule, subject) : undefined));
}

/**
 * The snapshot's active breaches, as the same array until they change: the
 * snapshot is new every second, and a table's columns built on a new array
 * every second would redraw every row (I123).
 */
export function useBreaches(): readonly ActiveBreach[] {
  const key = useDashStore((s) => JSON.stringify(s.snapshot?.thresholds ?? []));
  return useMemo(() => JSON.parse(key) as ActiveBreach[], [key]);
}

export function breachLevel(breaches: readonly ActiveBreach[], rule: string, subject?: string): Level {
  const levels = breaches.filter((b) => b.rule === rule && (subject === undefined || b.subject === subject)).map((b) => b.level);
  return levels.includes("CRIT") ? "CRIT" : levels.includes("WARN") ? "WARN" : "OK";
}

export const CONNECTED = "CONNECTED";
export const HEARTBEAT = "HEARTBEAT_TIMEOUT";

/**
 * One lane per participant over `range`, from its CONNECT/DISCONNECT events
 * and the snapshot's present state: connected from a CONNECT to the next
 * DISCONNECT; connected from the range's start if its first event in range
 * is a DISCONNECT; still connected at `nowMs` if the snapshot says so. A
 * DISCONNECT for a heartbeat timeout is also a mark.
 */
export function connectionLanes(
  participants: readonly ParticipantStats[],
  events: readonly HealthEvent[],
  range: TimeRangeMs,
  nowMs: number,
): Lane[] {
  const byId = new Map<string, HealthEvent[]>();
  for (const e of events) {
    if (e.kind !== "CONNECT" && e.kind !== "DISCONNECT") continue;
    byId.set(e.subject, [...(byId.get(e.subject) ?? []), e]);
  }
  return [...participants]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map((p) => {
      const mine = (byId.get(p.id) ?? []).slice().sort((a, b) => a.seq - b.seq);
      const segments: Segment[] = [];
      const marks: Mark[] = [];
      let since: number | null = mine[0]?.kind === "DISCONNECT" ? range.fromMs : null;
      if (mine.length === 0 && p.connected) since = range.fromMs;
      for (const e of mine) {
        const ts = Date.parse(e.ts);
        if (e.kind === "CONNECT") {
          since ??= ts;
        } else {
          if (since !== null) segments.push({ from: since, to: ts, state: CONNECTED });
          since = null;
          if (e.detail.includes("heartbeat")) marks.push({ ts, kind: HEARTBEAT });
        }
      }
      if (since !== null && p.connected) segments.push({ from: since, to: nowMs, state: CONNECTED });
      return { id: p.id, segments, marks };
    });
}

/** The part of `range` up to `nowMs` during which `lane` was not connected, in ms. */
export function disconnectedMs(lane: Lane, range: TimeRangeMs, nowMs: number): number {
  const end = Math.min(nowMs, range.toMs);
  let up = 0;
  for (const seg of lane.segments) up += Math.max(0, Math.min(seg.to, end) - Math.max(seg.from, range.fromMs));
  return Math.max(0, end - range.fromMs - up);
}

/**
 * How many of `lanes` were connected over `range` up to `nowMs`, as steps: a
 * point at the range's start and one at each change (a lane still connected
 * ends its segment at `nowMs`, which is no change), then the count held to
 * `holdTo` when that is later. Holding to a whole step rather than to now
 * keeps the points the same between changes, so the chart is not redrawn by
 * every snapshot (I118).
 */
export function connectedCount(lanes: readonly Lane[], range: TimeRangeMs, nowMs: number, holdTo: number): Point[] {
  const end = Math.min(nowMs, range.toMs);
  const delta = new Map<number, number>([[range.fromMs, 0]]);
  for (const lane of lanes) {
    for (const seg of lane.segments) {
      const from = Math.max(seg.from, range.fromMs);
      if (!(seg.to > from) || from >= end) continue;
      delta.set(from, (delta.get(from) ?? 0) + 1);
      if (seg.to < end) delta.set(seg.to, (delta.get(seg.to) ?? 0) - 1);
    }
  }
  const out: Point[] = [];
  let n = 0;
  for (const ts of [...delta.keys()].sort((x, y) => x - y)) {
    n += delta.get(ts)!;
    out.push([ts, n]);
  }
  const hold = Math.min(holdTo, end);
  if (hold > out.at(-1)![0]) out.push([hold, n]);
  return out;
}

/** When `lanes` had a heartbeat timeout within `range`, in time order. */
export function heartbeatTimes(lanes: readonly Lane[], range: TimeRangeMs): number[] {
  return lanes
    .flatMap((l) => (l.marks ?? []).filter((m) => m.kind === HEARTBEAT && m.ts >= range.fromMs && m.ts <= range.toMs).map((m) => m.ts))
    .sort((x, y) => x - y);
}

/**
 * The reject ratio in percent per bucket, as pm-monitor judges it
 * (reject_pct_5m): rejects over requests across the last five minutes,
 * and only from 20 requests up (MIN_REQUESTS_5M) -- below that there is
 * no ratio, and the line has a gap. With hourly buckets, per hour.
 */
export function rejectRatio(rejects: readonly Point[], requests: readonly Point[], bucketMs: number): Point[] {
  const window = bucketMs === 60_000 ? 5 : 1;
  const rej = new Map(rejects);
  const req = new Map(requests);
  const out: Point[] = [];
  for (const ts of [...req.keys()].sort((a, b) => a - b)) {
    let n = 0;
    let r = 0;
    for (let k = 0; k < window; k++) {
      n += req.get(ts - k * bucketMs) ?? 0;
      r += rej.get(ts - k * bucketMs) ?? 0;
    }
    if (n >= MIN_REQUESTS) out.push([ts, (100 * r) / n]);
  }
  return out;
}
