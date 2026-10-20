/**
 * Live dashboard state fed by the bridge WebSocket (design §11.1).
 *
 * The latest `health.snapshot` as pm-monitor sent it, and the recent
 * `health.event`s. Nothing here derives a figure: the rows (WP-D3) read the
 * snapshot as is.
 *
 * When pm-monitor or the socket goes away the snapshot is kept, not
 * dropped: the panels dim and the banner says when the data froze (its
 * `ts`, on the session clock — §12.2, D1.4). `connection()` says whether it
 * is live. `sessionTz` is what every displayed time is shown in
 * (lib/time.ts).
 *
 * `range` is the time picker's window for every history panel; the URL's
 * `?from=` is its source (AppShell copies it in). `refresh` is how often
 * those panels ask the bridge again.
 */

import { create } from "zustand";
import type { CrossAppLinks, HealthEvent, HealthSnapshot, MonitorState, ServerFrame, ThresholdRule } from "@edumatcher/dash-types";
import { liveSample, pushRecent, type LiveSample } from "../lib/live.js";
import { DEFAULT_RANGE, DEFAULT_REFRESH, rangeFromParam, type RangeName, type RefreshName } from "../lib/range.js";

/** The tab's own socket to the bridge. */
export type SocketState = "CONNECTING" | "OPEN" | "CLOSED";

/** Whether the figures on screen are live: that needs both the socket and pm-monitor. */
export type ConnectionState = "LIVE" | "NO_MONITOR" | "OFFLINE";

/** Events kept for the event log, newest last. */
export const MAX_EVENTS = 500;

/**
 * The page's `?from=` when the store is created, so the first render
 * already asks for the linked range rather than the default and then again
 * (AppShell keeps the two in step from then on).
 */
function rangeAtLoad(): RangeName {
  try {
    return rangeFromParam(new URLSearchParams(globalThis.location?.search ?? "").get("from")) ?? DEFAULT_RANGE;
  } catch {
    return DEFAULT_RANGE;
  }
}

interface DashStore {
  socket: SocketState;
  monitor: MonitorState | null;
  bridgeVersion: string | null;
  sessionTz: string;
  snapshot: HealthSnapshot | null;
  events: HealthEvent[];
  range: RangeName;
  refresh: RefreshName;
  /** The last minute of sparkline figures, one per snapshot (lib/live.ts). */
  recent: LiveSample[];
  /** The rules pm-monitor judges by, from /api/thresholds; null until loaded. */
  thresholds: Record<string, ThresholdRule> | null;
  /** log-gui's and book-gui's base URLs, from /api/bridge/status; null until loaded. */
  links: CrossAppLinks | null;

  setSocket: (socket: SocketState) => void;
  apply: (frame: ServerFrame) => void;
  /** Events fetched from `/api/events` (catch-up after a reconnect), merged by seq. */
  addEvents: (batch: HealthEvent[]) => void;
  connection: () => ConnectionState;
  setRange: (range: RangeName) => void;
  setRefresh: (refresh: RefreshName) => void;
  setThresholds: (rules: Record<string, ThresholdRule>) => void;
  setLinks: (links: CrossAppLinks) => void;
}

export const useDashStore = create<DashStore>()((set, get) => ({
  socket: "CONNECTING",
  monitor: null,
  bridgeVersion: null,
  sessionTz: "UTC",
  snapshot: null,
  events: [],
  range: rangeAtLoad(),
  refresh: DEFAULT_REFRESH,
  recent: [],
  thresholds: null,
  links: null,

  // A dropped socket leaves pm-monitor's state unknown; the snapshot stays, frozen.
  setSocket: (socket) => set(socket === "CLOSED" ? { socket, monitor: null } : { socket }),
  apply: (frame) => {
    switch (frame.type) {
      case "hello":
        set({ monitor: frame.monitor, bridgeVersion: frame.version, sessionTz: frame.sessionTz });
        break;
      case "snapshot":
        set({
          snapshot: frame.data,
          sessionTz: frame.data.exchange.session_timezone || get().sessionTz,
          recent: pushRecent(get().recent, liveSample(frame.data)),
        });
        break;
      case "event": {
        const events = get().events;
        const last = events.at(-1);
        const seq = frame.data.seq;
        // pm-monitor stores an event before it publishes it, so a catch-up
        // from /api/events can bring an event before its live frame does:
        // one already held is a duplicate (I118).
        if (events.some((e) => e.seq === seq)) break;
        // The bridge sends each event once, live, in seq order. An older seq
        // not held means the numbering began again (a new metrics.db): what
        // this tab holds belongs to the old one.
        if (last && seq < last.seq) set({ events: [frame.data] });
        else set({ events: [...events, frame.data].slice(-MAX_EVENTS) });
        break;
      }
      case "monitor_state":
        set({ monitor: frame.monitor });
        break;
    }
  },
  // A catch-up may answer after live events newer than it have arrived:
  // merge by seq rather than append.
  addEvents: (batch) => {
    const bySeq = new Map(get().events.map((e) => [e.seq, e]));
    for (const e of batch) bySeq.set(e.seq, e);
    set({ events: [...bySeq.values()].sort((a, b) => a.seq - b.seq).slice(-MAX_EVENTS) });
  },
  connection: () => {
    const { socket, monitor } = get();
    if (socket !== "OPEN") return "OFFLINE";
    return monitor === "UP" ? "LIVE" : "NO_MONITOR";
  },
  setRange: (range) => set({ range }),
  setRefresh: (refresh) => set({ refresh }),
  setThresholds: (thresholds) => set({ thresholds }),
  setLinks: (links) => set({ links }),
}));
