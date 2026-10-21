/**
 * Session indicator (EduMatcher-GUI-Apps-Improvements WP-UI01): the exchange
 * session phase, the next phase and the time left to it, and the exchange
 * clock — the reading pm-trader's top bar gives, in the same colours, so
 * every EduMatcher GUI shows the session the same way.
 *
 *     [Continuous]  → Closing Auction in 03:08  12:51:37
 *
 * The countdown is shown only while a future transition is known. "No
 * transition scheduled" is a real state (a manually driven session), and a
 * countdown to zero would assert a transition that is not coming.
 *
 * The same component lives in pm-dash, pm-book, pm-log and pm-terminal; the
 * copies differ only in their text colour tokens and clock formatter. Change
 * them together.
 */

import { useEffect, useState } from "react";
import { formatClock } from "../lib/formatTs.js";

/** pm-trader's SESSION_PHASE_META labels and badge colours. */
const PHASES: Record<string, { label: string; badge: string }> = {
  PRE_OPEN: { label: "Pre-Open", badge: "bg-slate-500 text-white" },
  OPENING_AUCTION: {
    label: "Opening Auction",
    badge: "bg-amber-500 text-black",
  },
  CONTINUOUS: { label: "Continuous", badge: "bg-emerald-500 text-black" },
  CLOSING_AUCTION: {
    label: "Closing Auction",
    badge: "bg-amber-500 text-black",
  },
  CLOSED: { label: "Closed", badge: "bg-red-600 text-white" },
};
const UNKNOWN = { label: "Unknown", badge: "bg-zinc-600 text-white" };

export function phaseMeta(state: string | null | undefined): {
  label: string;
  badge: string;
} {
  return (state && PHASES[state]) || UNKNOWN;
}

/** `MM:SS`, or `HH:MM:SS` from one hour — pm-trader's formatCountdown. */
export function formatCountdown(remainingMs: number): string {
  if (remainingMs <= 0) return "00:00";
  const totalSec = Math.floor(remainingMs / 1000);
  const h = Math.floor(totalSec / 3600);
  const mm = String(Math.floor((totalSec % 3600) / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  return h > 0 ? `${String(h).padStart(2, "0")}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** Unix ms, re-read on every whole second. */
function useSecondClock(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
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
  return now;
}

export interface SessionIndicatorProps {
  /** Engine session state (`CONTINUOUS`, …); null or `UNKNOWN` until known. */
  state: string | null;
  nextState: string | null;
  /** ISO-8601 time of the next transition. */
  nextAt: string | null;
  /** IANA exchange session timezone for the clock. */
  timeZone: string;
}

export function SessionIndicator({
  state,
  nextState,
  nextAt,
  timeZone,
}: SessionIndicatorProps) {
  const now = useSecondClock();
  const meta = phaseMeta(state);
  const known = meta !== UNKNOWN;
  const target = nextAt ? Date.parse(nextAt) : NaN;
  const countdown = known && nextState && target > now ? target - now : null;

  return (
    <span
      className="flex items-center gap-3 text-xs"
      data-testid="session-indicator"
    >
      <span
        className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${meta.badge}`}
        aria-label="session phase"
      >
        {meta.label}
      </span>
      {countdown !== null && nextState && (
        <>
          <span className="text-fg-subtle">→</span>
          <span className="text-fg-subtle">{phaseMeta(nextState).label}</span>
          <span
            className="font-mono text-fg"
            aria-label="time to next session phase"
          >
            in {formatCountdown(countdown)}
          </span>
        </>
      )}
      <span
        className="font-mono text-fg-subtle"
        aria-label="exchange clock"
        title={timeZone}
      >
        {formatClock(new Date(now).toISOString(), timeZone)}
      </span>
    </span>
  );
}
