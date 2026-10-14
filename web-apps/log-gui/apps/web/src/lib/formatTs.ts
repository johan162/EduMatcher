/**
 * Row timestamp rendering.
 *
 * Events are stored and shipped in UTC; the operator reads them in the
 * exchange's session timezone (`engine.locale.session_timezone`, served by
 * `GET /api/ui-config`), so every caller must pass that zone in rather than
 * slicing the ISO string or trusting the browser's locale.
 */

const formatters = new Map<string, Intl.DateTimeFormat>();

function parts(ts: string, timeZone: string): Record<string, string> {
  let fmt = formatters.get(timeZone);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat("en-GB", {
      timeZone,
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    formatters.set(timeZone, fmt);
  }
  return Object.fromEntries(fmt.formatToParts(new Date(ts)).map((p) => [p.type, p.value]));
}

/** "2026-04-09T07:00:14.469Z" in Europe/Stockholm -> "09 Apr 09:00:14" (no year). */
export function formatRowTs(ts: string, timeZone: string, withMillis = false): string {
  const p = parts(ts, timeZone);
  const stamp = `${p["day"]} ${p["month"]} ${p["hour"]}:${p["minute"]}:${p["second"]}`;
  if (!withMillis) return stamp;
  return `${stamp}.${String(new Date(ts).getUTCMilliseconds()).padStart(3, "0")}`;
}

/** "2026-04-09T07:00:14.469Z" in Europe/Stockholm -> "09:00:14". */
export function formatClock(ts: string, timeZone: string): string {
  const p = parts(ts, timeZone);
  return `${p["hour"]}:${p["minute"]}:${p["second"]}`;
}

/** "2026-04-09T07:00:14.469Z" in Europe/Stockholm -> "09:00". */
export function formatHm(ts: string, timeZone: string): string {
  const p = parts(ts, timeZone);
  return `${p["hour"]}:${p["minute"]}`;
}
