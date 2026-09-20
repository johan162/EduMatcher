/** Small formatting helpers shared across panels. */

const MINUTE_NS = 60 * 1_000_000_000;

/**
 * Unit conversions for display. None of them rounds: a field must show the
 * value the file holds, and a rounded display (90 s shown as "2 min", 7.125 %
 * as "7.13") would be a different number from the one written. toPrecision(12)
 * only strips binary-float noise such as 0.07 * 100 = 7.000000000000001.
 */
const clean = (x: number): number => Number(x.toPrecision(12));

export function nsToMinutes(ns: number | null): number | null {
  if (ns === null) return null;
  return clean(ns / MINUTE_NS);
}

/** Minutes input -> integer nanoseconds; null for empty or non-positive input. */
export function minutesToNs(minutes: number | null): number | null {
  if (minutes === null || minutes <= 0) return null;
  return Math.round(minutes * MINUTE_NS);
}

/** Fraction (0.07) -> percent (7). */
export function fractionToPercent(fraction: number): number {
  return clean(fraction * 100);
}

/** Percent input (7) -> fraction (0.07). */
export function percentToFraction(percent: number): number {
  return clean(percent / 100);
}

/** Input step for a price field: one tick of the symbol's grid. */
export function tickStep(tickDecimals: number): number {
  return clean(Math.pow(10, -tickDecimals));
}

export function uppercaseId(value: string): string {
  return value.trim().toUpperCase();
}
