/**
 * Price and candle utilities.
 */

/** Round a price to the nearest tick (tickDecimals decimal places). */
export function roundToTick(price: number, tickDecimals: number): number {
  const factor = Math.pow(10, tickDecimals);
  return Math.round(price * factor) / factor;
}

/** Convert a difference in price to ticks. */
export function priceToTicks(price: number, tickDecimals: number): number {
  const tick = Math.pow(10, -tickDecimals);
  return Math.round(price / tick);
}

/** Compute spread in ticks between ask and bid. */
export function spreadTicks(bid: number, ask: number, tickDecimals: number): number {
  return priceToTicks(ask - bid, tickDecimals);
}

/**
 * Bucket an epoch-seconds timestamp into the start of the candle bar for the
 * given timeframe.
 *
 * @param epochSec  Unix timestamp in seconds
 * @param tf        Timeframe: "1m" | "5m" | "1h" | "1D"
 * @returns         Unix timestamp (seconds) of the bar's start
 */
export function bucketTimestamp(epochSec: number, tf: "1m" | "5m" | "1h" | "1D"): number {
  const MINUTE = 60;
  const HOUR = 3600;
  const DAY = 86400;

  switch (tf) {
    case "1m":
      return Math.floor(epochSec / MINUTE) * MINUTE;
    case "5m":
      return Math.floor(epochSec / (5 * MINUTE)) * (5 * MINUTE);
    case "1h":
      return Math.floor(epochSec / HOUR) * HOUR;
    case "1D":
      return Math.floor(epochSec / DAY) * DAY;
  }
}

/** Build a flatten order payload for a net position (§13.6). */
export function flattenPayload(
  symbol: string,
  netQty: number,
): Record<string, unknown> | null {
  if (netQty === 0) return null;
  return {
    symbol,
    side: netQty > 0 ? "SELL" : "BUY",
    order_type: "MARKET",
    quantity: Math.abs(netQty),
    tif: "DAY",
  };
}

/**
 * Clsx-like utility: merge Tailwind class names.
 * Prefers `clsx` via direct import when available; otherwise joins truthy values.
 */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}
