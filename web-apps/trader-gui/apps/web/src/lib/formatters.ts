/**
 * Formatting utilities for prices, quantities, percentages, and timestamps.
 */
import { useSessionStore } from "@/store/useSessionStore.js";

/**
 * The exchange's session timezone, set at login. An unknown name (or none yet)
 * falls back to the browser's zone rather than throwing.
 */
function sessionZone(): string | undefined {
  return useSessionStore.getState().timezone ?? undefined;
}

function inSessionZone(date: Date, options: Intl.DateTimeFormatOptions): string {
  try {
    return new Intl.DateTimeFormat("en-GB", { ...options, timeZone: sessionZone() }).format(date);
  } catch {
    return new Intl.DateTimeFormat("en-GB", options).format(date);
  }
}

/** `HH:MM:SS` (or `HH:MM:SS.mmm`) in the session timezone. */
export function formatClock(date: Date | number, withMs = false): string {
  const d = typeof date === "number" ? new Date(date) : date;
  const hms = inSessionZone(d, { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
  return withMs ? `${hms}.${String(d.getMilliseconds()).padStart(3, "0")}` : hms;
}

/** `YYYY-MM-DD` in the session timezone. */
export function formatSessionDate(date: Date | number): string {
  const d = typeof date === "number" ? new Date(date) : date;
  const [dd, mm, yyyy] = inSessionZone(d, { day: "2-digit", month: "2-digit", year: "numeric" }).split("/");
  return `${yyyy}-${mm}-${dd}`;
}

/**
 * Format a price with `tickDecimals` decimal places.
 * Falls back to 2 decimals when tickDecimals is undefined.
 */
export function formatPrice(price: number | null | undefined, tickDecimals = 2): string {
  if (price === null || price === undefined) return "—";
  return price.toFixed(tickDecimals);
}

/** Format a signed money value with a leading + for gains. */
export function formatSignedPrice(
  price: number | null | undefined,
  tickDecimals = 2,
): string {
  if (price === null || price === undefined) return "—";
  const sign = price > 0 ? "+" : "";
  return `${sign}${price.toFixed(tickDecimals)}`;
}

/** Format a quantity as a whole integer with thousands separator. */
export function formatQty(qty: number | null | undefined): string {
  if (qty === null || qty === undefined) return "—";
  return qty.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/**
 * Format a price change percentage.
 * change% = (last - open) / open × 100  (canonical definition §10.3)
 */
export function formatChangePct(last: number | null, open: number | null): string {
  if (last === null || open === null || open === 0) return "—";
  const pct = ((last - open) / open) * 100;
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

/** Format an epoch-seconds timestamp as HH:MM:SS. */
export function formatTime(epochSec: number): string {
  return formatClock(epochSec * 1000);
}

/** Format an ISO-8601 string as HH:MM:SS.mmm. */
export function formatIsoTime(iso: string): string {
  return formatClock(new Date(iso), true);
}

/** Truncate a UUID/ID to 8 characters (display-only). */
export function shortId(id: string): string {
  return id.substring(0, 8);
}

/** Format a countdown duration (ms) as MM:SS or HH:MM:SS. */
export function formatCountdown(remainingMs: number): string {
  if (remainingMs <= 0) return "00:00";
  const totalSec = Math.floor(remainingMs / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  if (h > 0) return `${String(h).padStart(2, "0")}:${mm}:${ss}`;
  return `${mm}:${ss}`;
}

/** Convert epoch nanoseconds to a human-readable date/time in the session timezone. */
export function formatNsTimestamp(ns: number | null | undefined): string {
  if (ns === null || ns === undefined) return "—";
  const d = new Date(ns / 1_000_000);
  return `${formatSessionDate(d)} ${formatClock(d)}`;
}

/**
 * Format a *duration* in nanoseconds as a compact human string (e.g. "15m",
 * "1h 30m", "45s"). Used for circuit-breaker `halt_duration_ns` (§15.5.2).
 */
export function formatNsDuration(ns: number | null | undefined): string {
  if (ns === null || ns === undefined) return "—";
  const totalSec = Math.round(ns / 1_000_000_000);
  if (totalSec <= 0) return "0s";
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  const parts: string[] = [];
  if (h > 0) parts.push(`${h}h`);
  if (m > 0) parts.push(`${m}m`);
  if (s > 0 && h === 0) parts.push(`${s}s`);
  return parts.join(" ") || "0s";
}

/** Format a percentage value already expressed in percent units (e.g. 5 → "5.00%"). */
export function formatPct(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return "—";
  return `${pct.toFixed(2)}%`;
}
