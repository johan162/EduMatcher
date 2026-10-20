/**
 * Number formatting for every figure on the dashboard (design §13, D2.7).
 *
 * Written out by hand: `toLocaleString` would group digits by the browser's
 * locale (and test/time.test.ts keeps it out of the source). Large counts
 * are grouped with a thin space, which reads as one number in every locale.
 *
 * Every formatter shows {@link NO_VALUE} for NaN or an infinity (a 0/0 in a
 * derived figure) rather than "NaN TiB", and never prints a negative zero.
 */

const THIN = "\u2009";

/** What a figure that is not a number shows. */
export const NO_VALUE = "—";

/** -0 and anything that rounds to it are plain 0. */
function noNegativeZero(n: number): number {
  return n === 0 ? 0 : n;
}

/** 184302 -> "184 302" (thin spaces); rounded to an integer. */
export function formatCount(n: number): string {
  if (!Number.isFinite(n)) return NO_VALUE;
  const r = noNegativeZero(Math.round(n));
  const digits = String(Math.abs(r)).replace(/\B(?=(\d{3})+(?!\d))/g, THIN);
  return r < 0 ? `-${digits}` : digits;
}

/**
 * Three significant figures, never in exponent form: 1.00, 12.3, 412.
 * Rounded first, so 99.99 is "100" and 9.999 is "10.0", not "100.0"/"10.00".
 */
function sig3(n: number): string {
  const r = noNegativeZero(Number(n.toPrecision(3)));
  const abs = Math.abs(r);
  if (abs >= 100) return formatCount(r);
  const text = r.toFixed(abs >= 10 ? 1 : 2);
  // Anything that prints as zero ("-0.00", "0.00") is plain "0".
  return Number(text) === 0 ? "0" : text;
}

/** Below a million grouped in full; above it 1.21 M, 3.40 G. */
export function formatCompact(n: number): string {
  if (!Number.isFinite(n)) return NO_VALUE;
  const abs = Math.abs(n);
  if (abs >= 999_500_000) return `${sig3(n / 1e9)} G`;
  if (abs >= 999_999.5) return `${sig3(n / 1e6)} M`;
  return formatCount(n);
}

const BYTE_UNITS = ["B", "KiB", "MiB", "GiB", "TiB"];

/** Binary units: 1023 -> "1023 B", 1024 -> "1.00 KiB", 1.5 GiB -> "1.50 GiB". */
export function formatBytes(n: number): string {
  if (!Number.isFinite(n)) return NO_VALUE;
  if (Math.abs(Math.round(n)) < 1024) return `${noNegativeZero(Math.round(n))} B`;
  let value = n;
  let unit = 0;
  // Next unit once the figure would print as 1000 or more ("1.00 MiB", not "1024 KiB").
  while (unit < BYTE_UNITS.length - 1 && Math.abs(Number(value.toPrecision(3))) >= 1000) {
    value /= 1024;
    unit += 1;
  }
  return `${sig3(value)} ${BYTE_UNITS[unit]}`;
}

/** Microseconds, auto-scaled: 999 -> "999 µs", 1000 -> "1.00 ms", 1.5e6 -> "1.50 s". */
export function formatMicros(us: number): string {
  if (!Number.isFinite(us)) return NO_VALUE;
  if (Math.abs(Math.round(us)) < 1000) return `${noNegativeZero(Math.round(us))} µs`;
  if (Math.abs(Number((us / 1000).toPrecision(3))) < 1000) return `${sig3(us / 1000)} ms`;
  return `${sig3(us / 1e6)} s`;
}

/** Milliseconds (loop age, lag), on the same scale as {@link formatMicros}. */
export function formatMillis(ms: number): string {
  return formatMicros(ms * 1000);
}

/** A rate per second, minute or hour: "212 /s", "4.20 /min", "3 071 /min". */
export function formatRate(value: number, per: "s" | "min" | "h"): string {
  if (!Number.isFinite(value)) return NO_VALUE;
  return `${Math.abs(value) >= 999.5 ? formatCount(value) : sig3(value)} /${per}`;
}

/** Percent, one decimal below 100: "0%", "0.3%", "14.2%", "130%". */
export function formatPercent(pct: number): string {
  if (!Number.isFinite(pct)) return NO_VALUE;
  const r = noNegativeZero(Math.round(pct * 10) / 10);
  if (r === 0) return "0%";
  return `${Math.abs(r) >= 100 ? formatCount(r) : r.toFixed(1)}%`;
}

/** A duration as HH:MM, with whole days in front past 24 h: "05:12", "3d 05:12". */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds)) return NO_VALUE;
  const total = Math.max(0, Math.floor(seconds / 60));
  const days = Math.floor(total / 1440);
  const hh = String(Math.floor((total % 1440) / 60)).padStart(2, "0");
  const mm = String(total % 60).padStart(2, "0");
  return days > 0 ? `${days}d ${hh}:${mm}` : `${hh}:${mm}`;
}
