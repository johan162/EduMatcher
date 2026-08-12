import { create } from "zustand";
import type { SessionState } from "@/types/index.js";
import { nextScheduledTransition, type ScheduleInfo } from "@/lib/schedule.js";

/** `session.next` as it arrives on the wire. */
export interface NextTransitionEvent {
  to_state: SessionState;
  at: string; // ISO-8601
}

export interface SessionStoreState {
  phase: SessionState;
  prevPhase: SessionState | null;
  /** Unix ms when the current phase started — for elapsed-time display. */
  phaseSince: number | null;
  /** Unix ms of the next scheduled transition — for countdown display. */
  nextTransitionAt: number | null;
  /** Phase the countdown is counting towards, when known. */
  nextState: SessionState | null;
  /** Configured venue calendar; drives the countdown when `next` is absent. */
  schedule: ScheduleInfo | null;
  setPhase: (
    phase: SessionState,
    prev: SessionState | null,
    next?: NextTransitionEvent | null,
  ) => void;
  setSchedule: (schedule: ScheduleInfo | null) => void;
  /**
   * Resolve the countdown target at `nowMs`.
   *
   * `session.next` is preferred and authoritative: the engine only sends it
   * on a scheduler-driven transition, and it already accounts for holidays
   * and manual overrides. It is used only while it is still in the future —
   * a stale target would otherwise pin the countdown at 00:00 after an
   * admin-forced transition. The configured schedule is the fallback, and
   * when neither is available the top bar degrades to elapsed-time only
   * (§9.2).
   */
  countdownTarget: (nowMs: number) => { toState: SessionState; at: number } | null;
}

export const useSessionStore = create<SessionStoreState>((set, get) => ({
  phase: "CLOSED",
  prevPhase: null,
  phaseSince: null,
  nextTransitionAt: null,
  nextState: null,
  schedule: null,

  setPhase: (phase, prev, next) => {
    const at = next?.at ? new Date(next.at).getTime() : NaN;
    set({
      phase,
      prevPhase: prev,
      phaseSince: Date.now(),
      nextTransitionAt: Number.isFinite(at) ? at : null,
      nextState: next?.to_state ?? null,
    });
  },

  setSchedule: (schedule) => set({ schedule }),

  countdownTarget: (nowMs) => {
    const { nextTransitionAt, nextState, schedule } = get();
    if (nextTransitionAt !== null && nextTransitionAt > nowMs && nextState !== null) {
      return { toState: nextState, at: nextTransitionAt };
    }
    const derived = nextScheduledTransition(schedule, nowMs);
    return derived === null ? null : { toState: derived.toState, at: derived.at };
  },
}));
