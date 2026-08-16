import type { Position, Side } from "@/types/index.js";

export interface FlattenOrder {
  symbol: string;
  side: Side;
  order_type: "MARKET";
  quantity: number;
  tif: "DAY";
}

/**
 * Build the MARKET closing order for a net position (§13.6): a long flattens
 * with a SELL, a short with a BUY, for `abs(net_qty)`. Returns null for a flat
 * (zero) position — there is nothing to close.
 */
export function buildFlattenOrder(position: Pick<Position, "symbol" | "net_qty">): FlattenOrder | null {
  if (!position.net_qty) return null;
  return {
    symbol: position.symbol,
    side: position.net_qty > 0 ? "SELL" : "BUY",
    order_type: "MARKET",
    quantity: Math.abs(position.net_qty),
    tif: "DAY",
  };
}
