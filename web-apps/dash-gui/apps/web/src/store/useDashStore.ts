/**
 * Live dashboard state fed by the bridge WebSocket (design §11.1).
 *
 * WP-C1 scaffold: the connection and the uplink state. WP-C2/D3 add the
 * snapshot, events and history.
 */

import { create } from "zustand";
import type { MonitorState, ServerFrame } from "@edumatcher/dash-types";

/** The tab's own socket to the bridge. */
export type SocketState = "CONNECTING" | "OPEN" | "CLOSED";

/** What the top bar shows: LIVE needs both the socket and pm-monitor. */
export type ConnectionState = "LIVE" | "NO_MONITOR" | "OFFLINE";

interface DashStore {
  socket: SocketState;
  monitor: MonitorState | null;
  bridgeVersion: string | null;
  sessionTz: string;

  setSocket: (socket: SocketState) => void;
  apply: (frame: ServerFrame) => void;
  connection: () => ConnectionState;
}

export const useDashStore = create<DashStore>()((set, get) => ({
  socket: "CONNECTING",
  monitor: null,
  bridgeVersion: null,
  sessionTz: "UTC",

  setSocket: (socket) => set(socket === "CLOSED" ? { socket, monitor: null } : { socket }),
  apply: (frame) => {
    switch (frame.type) {
      case "hello":
        set({ monitor: frame.monitor, bridgeVersion: frame.version, sessionTz: frame.sessionTz });
        break;
      case "monitor_state":
        set({ monitor: frame.monitor });
        break;
    }
  },
  connection: () => {
    const { socket, monitor } = get();
    if (socket !== "OPEN") return "OFFLINE";
    return monitor === "UP" ? "LIVE" : "NO_MONITOR";
  },
}));
