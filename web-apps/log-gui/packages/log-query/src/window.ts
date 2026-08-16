/** Parses the small set of allow-listed window strings used across `/api/stats/*`. */

const WINDOW_SECONDS = {
  "5m": 5 * 60,
  "15m": 15 * 60,
  "1h": 60 * 60,
  "6h": 6 * 60 * 60,
  "24h": 24 * 60 * 60,
} as const;

/** The windows `/api/stats/*` accepts. Anything else falls back to the default. */
export type WindowKey = keyof typeof WINDOW_SECONDS;

const DEFAULT_WINDOW: WindowKey = "1h";

/**
 * Narrowing type guard, not just a boolean.
 *
 * Under `noUncheckedIndexedAccess` a bare `WINDOW_SECONDS[window]` is
 * `number | undefined` — and so was the `?? WINDOW_SECONDS["1h"]` fallback,
 * which is why the previous version could not be proven non-undefined. Making
 * this a predicate lets the lookup below narrow to a real `number` without a
 * cast or a non-null assertion.
 *
 * `Object.hasOwn`, not `in`: `in` walks the prototype chain, so
 * `isValidWindow("toString")` was true and `WINDOW_SECONDS["toString"]`
 * returned a *function*. `windowToIsoFrom` then computed `NaN` and
 * `new Date(NaN).toISOString()` threw `RangeError`. `window` arrives straight
 * from the `/api/stats/*` query string, so `?window=toString` was an
 * unauthenticated 500.
 */
export function isValidWindow(window: string): window is WindowKey {
  return Object.hasOwn(WINDOW_SECONDS, window);
}

export function windowToIsoFrom(window: string, now: Date = new Date()): string {
  const seconds = isValidWindow(window)
    ? WINDOW_SECONDS[window]
    : WINDOW_SECONDS[DEFAULT_WINDOW];
  return new Date(now.getTime() - seconds * 1000).toISOString().replace(/\.\d+Z$/, "Z");
}
