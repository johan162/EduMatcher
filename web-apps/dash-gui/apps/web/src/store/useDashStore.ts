/**
 * Live dashboard state fed by the bridge WebSocket (design §11.1).
 *
 * The latest `health.snapshot` as pm-monitor sent it, and the recent
 * `health.event`s. Nothing here derives a figure: the rows (WP-D3) read the
 * snapshot as is.
 */

import { create } from "zustand";
import type { HealthEvent, HealthSnapshot, MonitorState, ServerFrame } from "@edumatcher/dash-types";

/** The tab's own socket to the bridge. */
export type SocketState = "CONNECTING" | "OPEN" | "CLOSED";

/** What the top bar shows: LIVE needs both the socket and pm-monitor. */
export type ConnectionState = "LIVE" | "NO_MONITOR" | "OFFLINE";

/** Events kept for the event log, newest last. */
export const MAX_EVENTS = 500;

interface DashStore {
  socket: SocketState;
  monitor: MonitorState | null;
  bridgeVersion: string | null;
  sessionTz: string;
  snapshot: HealthSnapshot | null;
  events: HealthEvent[];

  setSocket: (socket: SocketState) => void;
  apply: (frame: ServerFrame) => void;
  connection: () => ConnectionState;
}

export const useDashStore = create<DashStore>()((set, get) => ({
  socket: "CONNECTING",
  monitor: null,
  bridgeVersion: null,
  sessionTz: "UTC",
  snapshot: null,
  events: [],

  // A dropped socket makes the snapshot of unknown age: forget it.
  setSocket: (socket) => set(socket === "CLOSED" ? { socket, monitor: null, snapshot: null } : { socket }),
  apply: (frame) => {
    switch (frame.type) {
      case "hello":
        set({ monitor: frame.monitor, bridgeVersion: frame.version, sessionTz: frame.sessionTz });
        break;
      case "snapshot":
        set({ snapshot: frame.data, sessionTz: frame.data.exchange.session_timezone || get().sessionTz });
        break;
      case "event": {
        const events = get().events;
        // A reconnect may replay what this tab already has.
        if (events.length > 0 && frame.data.seq <= events[events.length - 1]!.seq) break;
        set({ events: [...events, frame.data].slice(-MAX_EVENTS) });
        break;
      }
      case "monitor_state":
        set(frame.monitor === "DOWN" ? { monitor: "DOWN", snapshot: null } : { monitor: frame.monitor });
        break;
    }
  },
  connection: () => {
    const { socket, monitor } = get();
    if (socket !== "OPEN") return "OFFLINE";
    return monitor === "UP" ? "LIVE" : "NO_MONITOR";
  },
}));
