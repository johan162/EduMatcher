/**
 * Display formatting.
 *
 * Absent values render as an em dash, never "0": "no bid" and "a bid of
 * zero" are different books. Times render in the exchange session timezone
 * the bridge reports, as pm-viewer does — not in the browser's own.
 */

export const ABSENT = "—";

export function price(value: number | undefined | null, decimals: number): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return ABSENT;
  return value.toFixed(decimals);
}

/** A signed price difference, at the symbol's precision. */
export function signedPrice(value: number | undefined, decimals: number): string {
  if (value === undefined || !Number.isFinite(value)) return ABSENT;
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}`;
}

export function pct(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) return ABSENT;
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function qty(value: number | undefined | null): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return ABSENT;
  return value.toLocaleString("en-US");
}

const partsCache = new Map<string, Intl.DateTimeFormat>();

function parts(ms: number, timeZone: string): Record<string, string> {
  let fmt = partsCache.get(timeZone);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat("en-GB", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    partsCache.set(timeZone, fmt);
  }
  return Object.fromEntries(fmt.formatToParts(ms).map((p) => [p.type, p.value]));
}

/** `HH:MM:SS` in `timeZone`. */
export function clock(ms: number, timeZone: string): string {
  const p = parts(ms, timeZone);
  return `${p["hour"]}:${p["minute"]}:${p["second"]}`;
}

/** `HH:MM` in `timeZone`. */
export function hhmm(ms: number, timeZone: string): string {
  return clock(ms, timeZone).slice(0, 5);
}

/** `YYYY-MM-DD` in `timeZone`. */
export function isoDate(ms: number, timeZone: string): string {
  const p = parts(ms, timeZone);
  return `${p["year"]}-${p["month"]}-${p["day"]}`;
}

/** `HH:MM:SS.mmm` in `timeZone` — pm-viewer's trade-time format. */
export function tradeTime(ms: number, timeZone: string): string {
  if (!Number.isFinite(ms) || ms <= 0) return ABSENT;
  return `${clock(ms, timeZone)}.${String(Math.floor(ms) % 1000).padStart(3, "0")}`;
}
