/**
 * Conversions for the bus's integer-nanosecond timestamps (`ts_ns`).
 *
 * The engine publishes match times as integer Unix epoch nanoseconds, unscaled
 * (`spec/messages/trade.yaml`). A JS `number` is a float64, so a nanosecond
 * epoch — ~1.76e18 today — sits well above `Number.MAX_SAFE_INTEGER` (9.01e15)
 * and `JSON.parse` rounds it to the nearest representable value. That rounding
 * is ~256 ns at present magnitudes: far below anything this UI renders (we
 * display to the millisecond and bucket candles to the second), but it does
 * mean a `ts_ns` that has been through `JSON.parse` is NOT exact and must not
 * be used as an identity or equality key. Use the trade `id` for that.
 *
 * Convert once, at the boundary where a wire payload enters the UI, and keep
 * epoch seconds internally — which is what the chart and tape types expect.
 */

const NS_PER_SEC = 1_000_000_000;
const NS_PER_MS = 1_000_000;

/** Epoch nanoseconds → epoch seconds (fractional). */
export function nsToEpochSec(ts_ns: number): number {
  return ts_ns / NS_PER_SEC;
}

/** Epoch nanoseconds → epoch milliseconds, for `new Date(...)`. */
export function nsToEpochMs(ts_ns: number): number {
  return ts_ns / NS_PER_MS;
}
