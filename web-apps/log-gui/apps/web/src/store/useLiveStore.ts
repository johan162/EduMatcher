/**
 * Zustand store — synchronous, in-memory, ephemeral live state (design §15).
 * Server-cached state (history, aggregates, issues baseline) lives in
 * TanStack Query instead; this store only holds what the WS stream drives.
 */

import { create } from "zustand";
import type { CounterWindow, LogRow, ServerState } from "@edumatcher/log-types";
import type { WsStatus } from "../lib/ws.js";

const TAIL_MAX_ROWS = 2000;

export type SourceState = "LIVE" | "RECONNECTING" | "LOG_SERVER_DOWN" | "HISTORY_UNAVAILABLE";

interface LiveStore {
  wsStatus: WsStatus;
  serverState: ServerState | null;
  logDbHealthy: boolean;
  counters: CounterWindow | null;
  tail: LogRow[];
  tailPaused: boolean;
  newRowsWhilePaused: number;
  processLastSeen: Record<string, string>;

  setWsStatus: (status: WsStatus) => void;
  setServerState: (state: ServerState) => void;
  setLogDbHealthy: (healthy: boolean) => void;
  setCounters: (counters: CounterWindow) => void;
  pushRow: (row: LogRow) => void;
  setTailPaused: (paused: boolean) => void;
  clearNewRowsWhilePaused: () => void;

  connectionState: () => SourceState;
}

export const useLiveStore = create<LiveStore>((set, get) => ({
  wsStatus: "connecting",
  serverState: null,
  logDbHealthy: true,
  counters: null,
  tail: [],
  tailPaused: false,
  newRowsWhilePaused: 0,
  processLastSeen: {},

  setWsStatus: (status) => set({ wsStatus: status }),
  setServerState: (state) => set({ serverState: state }),
  setLogDbHealthy: (healthy) => set({ logDbHealthy: healthy }),
  setCounters: (counters) => set({ counters }),

  pushRow: (row) =>
    set((s) => {
      const processLastSeen = { ...s.processLastSeen, [row.process]: row.client_ts };
      if (s.tailPaused) {
        return { processLastSeen, newRowsWhilePaused: s.newRowsWhilePaused + 1 };
      }
      const tail = [row, ...s.tail].slice(0, TAIL_MAX_ROWS);
      return { tail, processLastSeen };
    }),

  setTailPaused: (paused) => set({ tailPaused: paused, newRowsWhilePaused: paused ? get().newRowsWhilePaused : 0 }),
  clearNewRowsWhilePaused: () => set({ newRowsWhilePaused: 0 }),

  connectionState: () => {
    const s = get();
    if (!s.logDbHealthy) return "HISTORY_UNAVAILABLE";
    if (s.serverState?.state === "DOWN") return "LOG_SERVER_DOWN";
    if (s.wsStatus === "reconnecting" || s.wsStatus === "connecting") return "RECONNECTING";
    return "LIVE";
  },
}));
