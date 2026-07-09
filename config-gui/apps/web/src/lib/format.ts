/** Small formatting helpers shared across panels. */

const MINUTE_NS = 60 * 1_000_000_000;

export function nsToMinutes(ns: number | null): number | null {
  if (ns === null) return null;
  return Math.round(ns / MINUTE_NS);
}

export function minutesToNs(minutes: number | null): number | null {
  if (minutes === null || minutes <= 0) return null;
  return minutes * MINUTE_NS;
}

/** Fraction (0.07) -> percent display string ("7"). */
export function fractionToPercent(fraction: number): number {
  return Math.round(fraction * 10000) / 100;
}

/** Percent input (7) -> fraction (0.07). */
export function percentToFraction(percent: number): number {
  return Math.round((percent / 100) * 1_000_000) / 1_000_000;
}

export function uppercaseId(value: string): string {
  return value.trim().toUpperCase();
}
