/**
 * What the dashboard rows share (design §12.3, D3): the dashboard-wide
 * loads (threshold rules, the event log's catch-up), threshold lookup,
 * annotations from events, and the pure computations behind two panels --
 * the connection timeline and the reject ratio -- kept here so they are
 * tested on their own.
 */

import { useEffect, useMemo } from "react";
import type { EventsResponse, HealthEvent, ParticipantStats, Point, ProcessHealth, ThresholdsResponse } from "@edumatcher/dash-types";
import type { Annotation } from "../../components/widgets/TimeSeries.js";
import type { Lane, Segment, Mark, TimeRangeMs } from "../../components/widgets/StateTimeline.js";
import { getJson, query } from "../../lib/api.js";
import { MIN_REQUESTS } from "../../lib/metrics.js";
import { SEVERITY } from "../../lib/status.js";
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
 * Each time the bridge connection opens: the threshold rules, and the
 * events the log is missing -- the picker's range at first, after the last
 * seq held once there are some (a reconnect).
 */
export function useDashboardLoads(): void {
  const socket = useDashStore((s) => s.socket);
  useEffect(() => {
    if (socket !== "OPEN") return;
    const ctl = new AbortController();
    const { setThresholds, addEvents, events, range } = useDashStore.getState();
    getJson<ThresholdsResponse>("/api/thresholds", ctl.signal).then(
      (r) => setThresholds(r.rules),
      () => undefined, // without rules the widgets draw no bands; the bridge logs why
    );
    const last = events.at(-1)?.seq;
    const q = last === undefined ? query({ range, limit: 500 }) : query({ after_seq: last, limit: 1000 });
    getJson<EventsResponse>(`/api/events?${q}`, ctl.signal).then(
      (r) => addEvents(r.events),
      () => undefined, // live events still arrive
    );
    return () => ctl.abort();
  }, [socket]);
}

/** The widget thresholds of rule `name`, once the rules are loaded. */
export function useRule(name: string): Thresholds | undefined {
  const rule = useDashStore((s) => s.thresholds?.[name]);
  return useMemo(() => (rule ? fromRule(rule) : undefined), [rule]);
}

/**
 * The level pm-monitor gives `rule` right now, from the snapshot's active
 * breaches (any subject); OK when none, undefined before a snapshot. For
 * rules judged on a window ("any increase over 5 min"), which a tile's
 * since-start or today figure cannot be compared against.
 */
export function useBreachLevel(rule: string): Level | undefined {
  return useDashStore((s) => {
    if (!s.snapshot) return undefined;
    const levels = s.snapshot.thresholds.filter((b) => b.rule === rule).map((b) => b.level);
    return levels.includes("CRIT") ? "CRIT" : levels.includes("WARN") ? "WARN" : "OK";
  });
}

/** The kinds that mark the charts (§12.1): state changes, not the connect/disconnect stream. */
const MARKED = new Set(["PROCESS_STATUS", "THRESHOLD", "SESSION", "HALT", "RESUME"]);

/** Events as chart annotations, coloured by severity. */
export function useAnnotations(): readonly Annotation[] {
  const events = useDashStore((s) => s.events);
  return useMemo(
    () =>
      events
        .filter((e) => MARKED.has(e.kind))
        .map((e) => ({ ts: Date.parse(e.ts), label: `${e.kind} ${e.subject}`, color: SEVERITY[e.severity].color })),
    [events],
  );
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
