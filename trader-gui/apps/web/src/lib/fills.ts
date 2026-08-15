import type { Fill, OrderHistoryEvent, Side } from "@/types/index.js";

/** A display row for the Trade History / Fills panel (§13.5.2). */
export interface FillRow {
  key: string;
  /** ISO timestamp, or null for a live row with no server timestamp. */
  ts: string | null;
  symbol: string;
  side: Side | null;
  fillQty: number | null;
  fillPrice: number | null;
  remaining: number | null;
  /** First trade id composing this fill; null when the fill had no trade. */
  tradeId: string | null;
  /** Number of *additional* trade ids beyond the first (drives a "+N" badge). */
  extraTradeCount: number;
  orderId: string;
  /** True for a row appended live from `order.fill` this session. */
  live: boolean;
}

function coerceSide(side: string | null | undefined): Side | null {
  return side === "BUY" || side === "SELL" ? side : null;
}

/** Map a durable stats `order_events` FILL row to a display row. */
export function fillRowFromHistory(e: OrderHistoryEvent): FillRow {
  return {
    key: `h-${e.order_id}-${e.seq}`,
    ts: e.ts,
    symbol: e.symbol,
    side: coerceSide(e.side),
    fillQty: e.fill_qty,
    fillPrice: e.fill_price,
    remaining: e.remaining_qty,
    tradeId: e.trade_id,
    extraTradeCount: 0,
    orderId: e.order_id,
    live: false,
  };
}

/**
 * Map a live `order.fill` event to a display row. The private event carries a
 * `trade_ids` array (usually one; several for a swept VWAP fill, `[]` for a
 * fill with no trade behind it — §13.5.1), so the Trade ID reads `trade_ids[0]`
 * and badges "+N" when there is more than one.
 */
export function fillRowFromEvent(f: Fill, receivedAtMs = Date.now()): FillRow {
  const ids = f.trade_ids ?? [];
  const first = ids[0] ?? null;
  return {
    key: `l-${f.order_id}-${first ?? "none"}-${receivedAtMs}`,
    ts: new Date(receivedAtMs).toISOString(),
    symbol: f.symbol ?? "",
    side: coerceSide(f.side),
    fillQty: f.fill_qty,
    fillPrice: f.fill_price,
    remaining: f.remaining_qty,
    tradeId: first,
    extraTradeCount: Math.max(0, ids.length - 1),
    orderId: f.order_id,
    live: true,
  };
}

/**
 * Merge live rows ahead of historical rows, dropping any live row whose trade
 * id already appears in the historical set (so a refetch that catches up does
 * not double-count). Live rows with no trade id are always kept.
 */
export function mergeFillRows(live: FillRow[], history: FillRow[]): FillRow[] {
  const historyTradeIds = new Set(history.map((r) => r.tradeId).filter((id): id is string => !!id));
  const dedupedLive = live.filter((r) => !(r.tradeId && historyTradeIds.has(r.tradeId)));
  return [...dedupedLive, ...history];
}

/** Apply the client-side Side filter (§13.5.3). */
export function filterFillRowsBySide(rows: FillRow[], side: Side | "ALL"): FillRow[] {
  return side === "ALL" ? rows : rows.filter((r) => r.side === side);
}
