/**
 * Every time the dashboard shows is on the exchange's clock: the session
 * timezone (`exchange.session_timezone`, held as `useDashStore.sessionTz`),
 * never the browser's. An operator in another zone, and every chart axis,
 * the event log and the "data frozen at" banner all read the same clock as
 * the trading date in the snapshot.
 *
 * The bridge only ever sends instants — epoch ms, or ISO-8601 UTC with `Z`.
 * This module is the one place an instant becomes text; a test keeps every
 * other file off `toLocale*String`, the browser-local `Date` getters and
 * `Intl.DateTimeFormat` (I106).
 */

/** Epoch milliseconds, or ISO-8601 with `Z` or an offset. */
export type Instant = number | string;

export function toMs(t: Instant): number {
  return typeof t === "number" ? t : Date.parse(t);
}

const formatters = new Map<string, Intl.DateTimeFormat>();

/** One cached formatter per zone; a zone this browser does not know shows UTC. */
function formatter(tz: string): Intl.DateTimeFormat {
  let f = formatters.get(tz);
  if (!f) {
    const options: Intl.DateTimeFormatOptions = {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    };
    try {
      f = new Intl.DateTimeFormat("en-GB", { ...options, timeZone: tz });
    } catch {
      f = new Intl.DateTimeFormat("en-GB", { ...options, timeZone: "UTC" });
    }
    formatters.set(tz, f);
  }
  return f;
}

/** What an instant that is not one shows (Intl throws on an invalid date). */
export const NO_TIME = "—";

function parts(t: Instant, tz: string): Record<string, string> | null {
  const ms = toMs(t);
  if (!Number.isFinite(ms)) return null;
  return Object.fromEntries(
    formatter(tz)
      .formatToParts(ms)
      .map((p) => [p.type, p.value]),
  );
}

/** `HH:MM:SS` (or `HH:MM`) on the session clock. */
export function formatTime(t: Instant, tz: string, seconds = true): string {
  const p = parts(t, tz);
  if (!p) return NO_TIME;
  return seconds ? `${p.hour}:${p.minute}:${p.second}` : `${p.hour}:${p.minute}`;
}

/** `YYYY-MM-DD`: the session date the instant falls on. */
export function formatDate(t: Instant, tz: string): string {
  const p = parts(t, tz);
  if (!p) return NO_TIME;
  return `${p.year}-${p.month}-${p.day}`;
}

/** `YYYY-MM-DD HH:MM:SS` on the session clock. */
export function formatDateTime(t: Instant, tz: string): string {
  return Number.isFinite(toMs(t)) ? `${formatDate(t, tz)} ${formatTime(t, tz)}` : NO_TIME;
}

/**
 * A chart axis tick: the time of day while the range fits in a day, the
 * date as well beyond it ("10-19 14:00"), both on the session clock.
 */
export function formatAxisTime(t: Instant, tz: string, spanMs: number): string {
  if (!Number.isFinite(toMs(t))) return NO_TIME;
  if (spanMs <= 24 * 3600_000) return formatTime(t, tz, spanMs <= 15 * 60_000);
  return `${formatDate(t, tz).slice(5)} ${formatTime(t, tz, false)}`;
}
