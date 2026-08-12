import { create } from "zustand";
import type { SessionState } from "@/types/index.js";

export interface SessionStoreState {
  phase: SessionState;
  prevPhase: SessionState | null;
  /** Unix ms when the current phase started — for elapsed-time display. */
  phaseSince: number | null;
  /** Unix ms of the next scheduled transition — for countdown display. */
  nextTransitionAt: number | null;
  setPhase: (phase: SessionState, prev: SessionState | null, nextAt?: number | null) => void;
}

export const useSessionStore = create<SessionStoreState>((set) => ({
  phase: "CLOSED",
  prevPhase: null,
  phaseSince: null,
  nextTransitionAt: null,

  setPhase: (phase, prev, nextAt) =>
    set({
      phase,
      prevPhase: prev,
      phaseSince: Date.now(),
      nextTransitionAt: nextAt ?? null,
    }),
}));
