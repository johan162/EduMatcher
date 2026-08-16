/**
 * Formatting utilities for prices, quantities, percentages, and timestamps.
 */

/**
 * Format a price with `tickDecimals` decimal places.
 * Falls back to 2 decimals when tickDecimals is undefined.
 */
export function formatPrice(price: number | null | undefined, tickDecimals = 2): string {
  if (price === null || price === undefined) return "—";
  return price.toFixed(tickDecimals);
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
  const d = new Date(epochSec * 1000);
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/** Format an ISO-8601 string as HH:MM:SS.mmm. */
export function formatIsoTime(iso: string): string {
  const d = new Date(iso);
  const hms = d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${hms}.${ms}`;
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

/** Convert epoch nanoseconds to a human-readable local date/time. */
export function formatNsTimestamp(ns: number | null | undefined): string {
  if (ns === null || ns === undefined) return "—";
  return new Date(ns / 1_000_000).toLocaleString();
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
