/**
 * Session-schedule arithmetic for the top-bar countdown (§9.2).
 *
 * `GET /reference/schedule` returns five wall-clock **strings** ("09:00",
 * "17:30:00") plus `sessions_enabled`, nested as `{sessions_enabled, country,
 * schedule}`. The engine only announces `session.next` on a scheduler-driven
 * transition, so the countdown needs a second source to survive an
 * admin-forced transition — that is what this module derives.
 *
 * Deliberately local-time: the clock times are the venue operator's own
 * wall-clock as written in their config, and the terminal runs beside the
 * venue in the classroom setup this is built for. A venue in another timezone
 * needs the schedule to carry one, which the wire format does not have.
 */
import type { SessionState } from "@/types/index.js";

/** The five clock times, as returned nested under `schedule`. */
export interface SessionTimes {
  pre_open?: string | null;
  opening_auction_start?: string | null;
  continuous_start?: string | null;
  closing_auction_start?: string | null;
  closing_auction_end?: string | null;
}

export interface ScheduleInfo {
  sessions_enabled: boolean;
  country?: string | null;
  schedule?: SessionTimes | null;
}

export interface ScheduledTransition {
  toState: SessionState;
  /** Unix ms of the boundary. */
  at: number;
}

/** Boundary order through the trading day, and the phase each one opens. */
const BOUNDARIES: { key: keyof SessionTimes; toState: SessionState }[] = [
  { key: "pre_open", toState: "PRE_OPEN" },
  { key: "opening_auction_start", toState: "OPENING_AUCTION" },
  { key: "continuous_start", toState: "CONTINUOUS" },
  { key: "closing_auction_start", toState: "CLOSING_AUCTION" },
  { key: "closing_auction_end", toState: "CLOSED" },
];

/**
 * Parse "HH:MM" or "HH:MM:SS" into seconds past midnight, or null if the
 * value is absent or malformed. A partial `schedule:` block is legal config,
 * so a missing time is an ordinary outcome, not an error.
 */
export function parseClockTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(value.trim());
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  const sec = m[3] === undefined ? 0 : Number(m[3]);
  if (h > 23 || min > 59 || sec > 59) return null;
  return h * 3600 + min * 60 + sec;
}

/** Unix ms for `secondsPastMidnight` on the local day containing `now`, plus `dayOffset` days. */
function atLocalTime(now: Date, secondsPastMidnight: number, dayOffset = 0): number {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + dayOffset, 0, 0, 0, 0);
  return d.getTime() + secondsPastMidnight * 1000;
}

/**
 * The next scheduled boundary strictly after `nowMs`, or null when sessions
 * are disabled or no clock times are configured. Rolls to tomorrow's first
 * boundary once the day's last one has passed.
 */
export function nextScheduledTransition(
  info: ScheduleInfo | null | undefined,
  nowMs: number,
): ScheduledTransition | null {
  if (!info?.sessions_enabled) return null;
  const times = info.schedule;
  if (!times) return null;

  const now = new Date(nowMs);
  const parsed: { toState: SessionState; sec: number }[] = [];
  for (const { key, toState } of BOUNDARIES) {
    const sec = parseClockTime(times[key]);
    if (sec !== null) parsed.push({ toState, sec });
  }
  if (parsed.length === 0) return null;

  // Config order is the day's order; sorting guards a mis-ordered config
  // rather than trusting it.
  parsed.sort((a, b) => a.sec - b.sec);

  for (const b of parsed) {
    const at = atLocalTime(now, b.sec);
    if (at > nowMs) return { toState: b.toState, at };
  }
  const first = parsed[0]!;
  return { toState: first.toState, at: atLocalTime(now, first.sec, 1) };
}
