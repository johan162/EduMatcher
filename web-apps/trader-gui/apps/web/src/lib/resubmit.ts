import type { Order } from "@/types/index.js";

/**
 * Build the body for a best-effort "Undo" re-submission of a just-cancelled
 * order (§20.3 power-user mode). It re-creates an *equivalent* order for the
 * still-live quantity — priority is NOT preserved and the toast says so.
 *
 * Returns null when there is nothing meaningful to re-submit (no remaining
 * quantity), so the caller can tell the user the undo is a no-op rather than
 * sending a zero-size order the engine would reject.
 *
 * Only the fields the original carried are included, so a LIMIT keeps its
 * price, a STOP its stop price, an ICEBERG its visible qty, etc.; a MARKET
 * (which never rests, so is an unusual undo target) simply carries no price.
 */
export function buildResubmitOrder(order: Order): Record<string, unknown> | null {
  const quantity = order.remaining_qty > 0 ? order.remaining_qty : 0;
  if (quantity <= 0) return null;

  const body: Record<string, unknown> = {
    symbol: order.symbol,
    side: order.side,
    order_type: order.order_type,
    quantity,
    tif: order.tif,
  };
  if (order.price != null) body.price = order.price;
  if (order.stop_price != null) body.stop_price = order.stop_price;
  if (order.visible_qty != null) body.visible_qty = order.visible_qty;
  if (order.trail_offset != null) body.trail_offset = order.trail_offset;
  if (order.smp_action != null) body.smp_action = order.smp_action;
  return body;
}
