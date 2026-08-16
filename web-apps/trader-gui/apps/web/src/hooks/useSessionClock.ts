import { useEffect, useState } from "react";
import { useSessionStore } from "@/store/useSessionStore.js";
import type { SessionState } from "@/types/index.js";

export interface SessionClock {
  /** Unix ms, re-read once a second. */
  now: number;
  phase: SessionState;
  /** Milliseconds since the current phase started, or null if unknown. */
  elapsedMs: number | null;
  /** Milliseconds until the next transition, or null when no target is known. */
  countdownMs: number | null;
  /** Phase the countdown is counting towards. */
  nextState: SessionState | null;
}

/**
 * One-second ticking view of the session clock for the top bar (§9.2).
 *
 * Falls back to elapsed-time when no countdown target is available — a venue
 * with `sessions_enabled: false`, or a partial `schedule:` block, is ordinary
 * configuration rather than an error, and the badge must still be useful.
 */
export function useSessionClock(): SessionClock {
  const [now, setNow] = useState(() => Date.now());
  const phase = useSessionStore((s) => s.phase);
  const phaseSince = useSessionStore((s) => s.phaseSince);
  const countdownTarget = useSessionStore((s) => s.countdownTarget);

  useEffect(() => {
    // Aligned to the next whole second so the display does not skip a value
    // when the mount happens mid-second.
    let interval: ReturnType<typeof setInterval> | undefined;
    const align = setTimeout(
      () => {
        setNow(Date.now());
        interval = setInterval(() => setNow(Date.now()), 1000);
      },
      1000 - (Date.now() % 1000),
    );
    return () => {
      clearTimeout(align);
      if (interval !== undefined) clearInterval(interval);
    };
  }, []);

  const target = countdownTarget(now);

  return {
    now,
    phase,
    elapsedMs: phaseSince === null ? null : Math.max(0, now - phaseSince),
    countdownMs: target === null ? null : Math.max(0, target.at - now),
    nextState: target?.toState ?? null,
  };
}
