import type { OrderType } from "@/types/index.js";

/**
 * Which conditional fields an order-type tab shows (§12.3). Symbol, Qty, and
 * SMP are always shown, so they are not part of this map; `tif` is here because
 * IOC hides it. The order ticket reads this to render the right inputs and to
 * decide which fields to include in the submitted payload.
 */
export interface FieldVisibility {
  price: boolean;
  stop_price: boolean;
  visible_qty: boolean;
  trail_offset: boolean;
  tif: boolean;
}

const FIELD_MAP: Record<OrderType, FieldVisibility> = {
  MARKET: { price: false, stop_price: false, visible_qty: false, trail_offset: false, tif: true },
  LIMIT: { price: true, stop_price: false, visible_qty: false, trail_offset: false, tif: true },
  STOP: { price: false, stop_price: true, visible_qty: false, trail_offset: false, tif: true },
  STOP_LIMIT: { price: true, stop_price: true, visible_qty: false, trail_offset: false, tif: true },
  FOK: { price: true, stop_price: false, visible_qty: false, trail_offset: false, tif: true },
  ICEBERG: { price: true, stop_price: false, visible_qty: true, trail_offset: false, tif: true },
  // IOC hides TIF — it is implicitly immediate-or-cancel (§12.3).
  IOC: { price: true, stop_price: false, visible_qty: false, trail_offset: false, tif: false },
  TRAILING_STOP: {
    price: false,
    stop_price: false,
    visible_qty: false,
    trail_offset: true,
    tif: true,
  },
};

/** Field visibility for an order-type tab (§12.3). Pure lookup — safe to call in render. */
export function useOrderFields(type: OrderType): FieldVisibility {
  return FIELD_MAP[type];
}
