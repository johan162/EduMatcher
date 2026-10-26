/**
 * The session timetable the Session schedule row draws (a copy of
 * pm-terminal's; change them together): one trading day as six
 * phases, the calendar week around today, and the next bank holiday.
 *
 * Everything is in the exchange's session timezone, on calendar dates
 * written as ISO strings, so a viewer in another timezone sees the venue's
 * day rather than their own. Today's entry is resolved here from the weekly
 * table and the holiday list, not taken from the record's `today`, which the
 * engine computes once when it loads its config and does not refresh at
 * midnight.
 */

import type { DayKey, Holiday, SessionTimes, WeeklySchedule } from "@edumatcher/dash-types";
import { formatDate, formatTime } from "./time.js";

/** The day's phases in order. The day both starts and ends CLOSED. */
export const PHASE_FLOW = [
  "CLOSED",
  "PRE_OPEN",
  "OPENING_AUCTION",
  "CONTINUOUS",
  "CLOSING_AUCTION",
  "CLOSED",
] as const;

/** The boundary that opens each phase after the first. */
const BOUNDARIES: (keyof SessionTimes)[] = [
  "pre_open",
  "opening_auction_start",
  "continuous_start",
  "closing_auction_start",
  "closing_auction_end",
];

export const DAY_SEC = 86_400;

/** `Date#getUTCDay()` order. */
const DAY_KEYS: DayKey[] = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const DAY_NAMES: Record<DayKey, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** `HH:MM` or `HH:MM:SS` as seconds past midnight, or null. */
export function parseClock(value: string | null | undefined): number | null {
  const m = value ? /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(value.trim()) : null;
  if (!m) return null;
  const [h, min, s] = [Number(m[1]), Number(m[2]), Number(m[3] ?? 0)];
  if (h > 23 || min > 59 || s > 59) return null;
  return h * 3600 + min * 60 + s;
}

/** `08:00:00` → `08:00`; seconds are kept only when they say something. */
export function clockLabel(value: string): string {
  const trimmed = value.trim();
  return trimmed.length > 5 && trimmed.endsWith(":00") ? trimmed.slice(0, -3) : trimmed;
}

export interface Segment {
  phase: (typeof PHASE_FLOW)[number];
  /** Seconds past midnight. */
  start: number;
  end: number;
}

/**
 * The day as six segments covering 00:00 to 24:00, or null when a boundary
 * is missing or out of order. The config loader rejects both, so null only
 * guards against drawing nonsense from a record this client misreads.
 */
export function daySegments(times: SessionTimes): Segment[] | null {
  const bounds = BOUNDARIES.map((key) => parseClock(times[key]));
  if (bounds.some((b, i) => b === null || (i > 0 && b <= bounds[i - 1]!))) return null;
  const edges = [0, ...(bounds as number[]), DAY_SEC];
  return PHASE_FLOW.map((phase, i) => ({ phase, start: edges[i]!, end: edges[i + 1]! }));
}

/** The index of the segment holding `sec`. */
export function segmentAt(segments: Segment[], sec: number): number {
  const i = segments.findIndex((s) => sec >= s.start && sec < s.end);
  return i < 0 ? segments.length - 1 : i;
}

/** The transition times between the six phases, as written in the config. */
export function boundaryLabels(times: SessionTimes): string[] {
  return BOUNDARIES.map((key) => clockLabel(times[key] ?? ""));
}

export interface ExchangeNow {
  /** ISO calendar date. */
  date: string;
  /** Seconds past midnight. */
  sec: number;
}

/** The exchange's date and time of day at `nowMs`, on the session clock (lib/time.ts). */
export function exchangeNow(nowMs: number, timeZone: string): ExchangeNow {
  return { date: formatDate(nowMs, timeZone), sec: parseClock(formatTime(nowMs, timeZone)) ?? 0 };
}

const utc = (iso: string) => new Date(`${iso}T00:00:00Z`);

export function addDays(iso: string, days: number): string {
  return new Date(utc(iso).getTime() + days * DAY_SEC * 1000).toISOString().slice(0, 10);
}

export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((utc(toIso).getTime() - utc(fromIso).getTime()) / (DAY_SEC * 1000));
}

export const dayKeyOf = (iso: string): DayKey => DAY_KEYS[utc(iso).getUTCDay()]!;

/** `Fri 25 Dec`. */
export function dateLabel(iso: string): string {
  const d = utc(iso);
  return `${DAY_NAMES[dayKeyOf(iso)]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

export const dayName = (key: DayKey): string => DAY_NAMES[key];

export interface ResolvedDay {
  date: string;
  dayKey: DayKey;
  /** Null when the exchange is closed that day. */
  times: SessionTimes | null;
  /** Set when the day is a bank holiday, which runs on the holidays entry. */
  holiday?: Holiday;
}

/** Which entry applies on `iso`: the holidays one on a bank holiday. */
export function resolveDate(schedule: WeeklySchedule, iso: string): ResolvedDay {
  const dayKey = dayKeyOf(iso);
  const holiday = schedule.upcoming_holidays.find((h) => h.date === iso);
  return holiday
    ? { date: iso, dayKey, times: schedule.holidays, holiday }
    : { date: iso, dayKey, times: schedule[dayKey] };
}

/** Monday to Sunday of the week holding `todayIso`. */
export function weekOf(schedule: WeeklySchedule, todayIso: string): ResolvedDay[] {
  const monday = addDays(todayIso, -((utc(todayIso).getUTCDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, i) => resolveDate(schedule, addDays(monday, i)));
}

/** The first day from `fromIso` on that trades, looking two weeks ahead. */
export function nextTradingDay(schedule: WeeklySchedule, fromIso: string): ResolvedDay | null {
  for (let i = 0; i < 14; i++) {
    const day = resolveDate(schedule, addDays(fromIso, i));
    if (day.times && daySegments(day.times)) return day;
  }
  return null;
}

/**
 * The next bank holiday that changes trading: one on a day that would
 * otherwise trade. A holiday on a weekend the exchange is closed anyway
 * makes no difference to anyone watching this screen.
 */
export function nextHoliday(schedule: WeeklySchedule, todayIso: string): ResolvedDay | null {
  const holiday = schedule.upcoming_holidays.find(
    (h) => h.date >= todayIso && schedule[dayKeyOf(h.date)] !== null,
  );
  return holiday ? resolveDate(schedule, holiday.date) : null;
}

/**
 * Which of the six steps is the current one.
 *
 * The feed's phase is the truth; the clock only says which of the two CLOSED
 * steps it is, and only when it agrees with the feed. It may not: an operator
 * can move the session by hand, and a compressed simulation runs the
 * exchange's day faster than the wall clock. Without the clock, a CLOSED
 * reached from any trading phase is the evening one.
 *
 * `clockStep` is null when the drawn day is not today, in which case CLOSED
 * is the wait before that day's open.
 */
export function currentStep(
  phase: string | null,
  prev: string | null,
  clockStep: number | null,
): number | null {
  if (phase === null) return null;
  if (clockStep !== null && PHASE_FLOW[clockStep] === phase) return clockStep;
  if (phase === "CLOSED") return clockStep !== null && prev && prev !== "CLOSED" ? PHASE_FLOW.length - 1 : 0;
  const i = PHASE_FLOW.indexOf(phase as (typeof PHASE_FLOW)[number]);
  return i < 0 ? null : i;
}
