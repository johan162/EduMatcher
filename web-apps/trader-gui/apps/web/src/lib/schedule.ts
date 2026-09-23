/**
 * Session-schedule arithmetic for the top-bar countdown (§9.2).
 *
 * `GET /reference/schedule` returns `{sessions_enabled, country, schedule}`,
 * where `schedule` is the fully-resolved weekly table (`mon`..`sun`,
 * `holidays`, plus the server-resolved `today`/`today_is_holiday`
 * convenience fields) — see `WeeklySchedule` below. Each day is either a
 * `SessionTimes` (five wall-clock **strings**, e.g. "09:00", "17:30:00") or
 * null for CLOSED. The engine only announces `session.next` on a
 * scheduler-driven transition, so the countdown needs a second source to
 * survive an admin-forced transition — that is what this module derives.
 *
 * Deliberately local-time: the clock times are the venue operator's own
 * wall-clock as written in their config, and the terminal runs beside the
 * venue in the classroom setup this is built for. A venue in another timezone
 * needs the schedule to carry one, which the wire format does not have.
 */
import type { SessionState } from "@/types/index.js";

/** One resolved day's five clock times. */
export interface SessionTimes {
  pre_open?: string | null;
  opening_auction_start?: string | null;
  continuous_start?: string | null;
  closing_auction_start?: string | null;
  closing_auction_end?: string | null;
}

/** The fully-resolved weekly table, as returned nested under `schedule`. */
export interface WeeklySchedule {
  mon?: SessionTimes | null;
  tue?: SessionTimes | null;
  wed?: SessionTimes | null;
  thu?: SessionTimes | null;
  fri?: SessionTimes | null;
  sat?: SessionTimes | null;
  sun?: SessionTimes | null;
  holidays?: SessionTimes | null;
  /** The entry actually in effect today — already holiday-resolved. */
  today?: SessionTimes | null;
  today_is_holiday?: boolean;
}

export interface ScheduleInfo {
  sessions_enabled: boolean;
  country?: string | null;
  schedule?: WeeklySchedule | null;
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

/** `Date#getDay()` (0 = Sunday) indexed to the matching `WeeklySchedule` key. */
const WEEKDAY_KEY_BY_JS_DAY: (keyof WeeklySchedule)[] = [
  "sun",
  "mon",
  "tue",
  "wed",
  "thu",
  "fri",
  "sat",
];

/**
 * Parse "HH:MM" or "HH:MM:SS" into seconds past midnight, or null if the
 * value is absent or malformed. A day that is scheduled at all always
 * carries all five times — the config loader rejects a partial day block —
 * so a missing/malformed value here just means that boundary doesn't fire.
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

/** `times`' boundaries, parsed and sorted — config order is the day's order, but
 * sorting guards a mis-ordered config rather than trusting it. */
function boundariesFor(
  times: SessionTimes | null | undefined,
): { toState: SessionState; sec: number }[] {
  if (!times) return [];
  const parsed: { toState: SessionState; sec: number }[] = [];
  for (const { key, toState } of BOUNDARIES) {
    const sec = parseClockTime(times[key]);
    if (sec !== null) parsed.push({ toState, sec });
  }
  parsed.sort((a, b) => a.sec - b.sec);
  return parsed;
}

/**
 * The next scheduled boundary strictly after `nowMs`, or null when sessions
 * are disabled, there is no schedule, or today (and tomorrow) turn out to
 * have nothing left.
 *
 * Uses the server-resolved `schedule.today` for today's boundaries — already
 * holiday-aware, so no client-side holiday calendar is needed. Rolling past
 * today's last boundary (or finding today CLOSED outright) looks at
 * tomorrow's plain weekday entry in the full table; this is the one place
 * this module reads `mon`..`sun` directly instead of `today`, because the
 * wire payload only resolves "is this a holiday" for *today*. If tomorrow
 * itself turns out to be a bank holiday, this uses tomorrow's ordinary
 * weekday entry instead of its holidays entry until the browser re-polls
 * after midnight and gets a fresh `today`/`today_is_holiday` — an accepted
 * small gap, matching how `session.next` countdowns already only ever carry
 * one known-good boundary rather than a full lookahead. Likewise, if
 * tomorrow is itself CLOSED (e.g. a weekend-only exchange on a weekday),
 * this does not search further ahead and returns null.
 */
export function nextScheduledTransition(
  info: ScheduleInfo | null | undefined,
  nowMs: number,
): ScheduledTransition | null {
  if (!info?.sessions_enabled) return null;
  const schedule = info.schedule;
  if (!schedule) return null;

  const now = new Date(nowMs);

  for (const b of boundariesFor(schedule.today)) {
    const at = atLocalTime(now, b.sec);
    if (at > nowMs) return { toState: b.toState, at };
  }

  const tomorrowKey = WEEKDAY_KEY_BY_JS_DAY[(now.getDay() + 1) % 7]!;
  const tomorrow = boundariesFor(schedule[tomorrowKey] as SessionTimes | null | undefined);
  if (tomorrow.length === 0) return null;
  const first = tomorrow[0]!;
  return { toState: first.toState, at: atLocalTime(now, first.sec, 1) };
}
