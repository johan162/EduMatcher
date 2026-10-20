/**
 * Number formatting for every figure on the dashboard (design §13, D2.7).
 *
 * Written out by hand: `toLocaleString` would group digits by the browser's
 * locale (and test/time.test.ts keeps it out of the source). Large counts
 * are grouped with a thin space, which reads as one number in every locale.
 */

const THIN = " ";

/** 184302 -> "184 302" (thin spaces); rounded to an integer. */
export function formatCount(n: number): string {
  const sign = n < 0 ? "-" : "";
  const digits = String(Math.round(Math.abs(n)));
  return sign + digits.replace(/\B(?=(\d{3})+(?!\d))/g, THIN);
}

/** Three significant figures, never in exponent form: 1.00, 12.3, 412; zero is "0". */
function sig3(n: number): string {
  const abs = Math.abs(n);
  if (abs === 0) return "0";
  if (abs >= 100) return formatCount(n);
  return n.toFixed(abs >= 10 ? 1 : 2);
}

/** Below a million grouped in full; above it 1.21 M, 3.40 G. */
export function formatCompact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${sig3(n / 1e9)} G`;
  if (abs >= 1e6) return `${sig3(n / 1e6)} M`;
  return formatCount(n);
}

const BYTE_UNITS = ["KiB", "MiB", "GiB", "TiB"];

/** Binary units: 1023 -> "1023 B", 1024 -> "1.00 KiB", 1.5 GiB -> "1.50 GiB". */
export function formatBytes(n: number): string {
  if (Math.abs(n) < 1024) return `${Math.round(n)} B`;
  let value = n;
  let unit = "B";
  for (const next of BYTE_UNITS) {
    if (Math.abs(value) < 1024) break;
    value /= 1024;
    unit = next;
  }
  // 1023.9 KiB would print as "1024 KiB": take the next unit instead.
  if (Math.abs(value) >= 999.5 && unit !== "TiB") {
    value /= 1024;
    unit = BYTE_UNITS[BYTE_UNITS.indexOf(unit) + 1]!;
  }
  return `${sig3(value)} ${unit}`;
}

/** Microseconds, auto-scaled: 999 -> "999 µs", 1000 -> "1.00 ms", 1.5e6 -> "1.50 s". */
export function formatMicros(us: number): string {
  const abs = Math.abs(us);
  if (Math.round(abs) < 1000) return `${Math.round(us)} µs`;
  if (abs < 999_500) return `${sig3(us / 1000)} ms`;
  return `${sig3(us / 1e6)} s`;
}

/** Milliseconds (loop age, lag), on the same scale as {@link formatMicros}. */
export function formatMillis(ms: number): string {
  return formatMicros(ms * 1000);
}

/** A rate per second, minute or hour: "212 /s", "4.20 /min", "3 071 /min". */
export function formatRate(value: number, per: "s" | "min" | "h"): string {
  return `${Math.abs(value) >= 1000 ? formatCount(value) : sig3(value)} /${per}`;
}

/** Percent, one decimal below 100: "0%", "0.3%", "14.2%", "130%". */
export function formatPercent(pct: number): string {
  if (pct === 0) return "0%";
  return `${Math.abs(pct) >= 99.95 ? formatCount(pct) : pct.toFixed(1)}%`;
}

/** A duration as HH:MM, with whole days in front past 24 h: "05:12", "3d 05:12". */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds / 60));
  const days = Math.floor(total / 1440);
  const hh = String(Math.floor((total % 1440) / 60)).padStart(2, "0");
  const mm = String(total % 60).padStart(2, "0");
  return days > 0 ? `${days}d ${hh}:${mm}` : `${hh}:${mm}`;
}
