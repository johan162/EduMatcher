import type { ActiveQuote, Side } from "@/types/index.js";

/** Index active quotes by symbol (one active quote per gateway+symbol, §14.1). */
export function quotesBySymbol(quotes: ActiveQuote[]): Record<string, ActiveQuote> {
  const out: Record<string, ActiveQuote> = {};
  for (const q of quotes) out[q.symbol] = q;
  return out;
}

/**
 * Per-leg fill progress for a quote card (§14.1.1). `filled = qty - remaining`,
 * clamped to [0, qty]; `pct` is 0..100. A zero-qty (e.g. MISSING) leg reads 0%.
 */
export function legFill(qty: number, remaining: number): { filled: number; pct: number } {
  if (!qty || qty <= 0) return { filled: 0, pct: 0 };
  const filled = Math.min(qty, Math.max(0, qty - remaining));
  return { filled, pct: (filled / qty) * 100 };
}

/**
 * Spread of a prospective quote (§14.2), in currency and ticks. Returns null
 * unless both prices are finite and ask > bid (the engine rejects bid >= ask).
 * `ticks` uses the symbol's tick size (10^-tick_decimals) and is rounded to the
 * nearest whole tick to absorb float noise.
 */
export function spreadInfo(
  bidPrice: number | null | undefined,
  askPrice: number | null | undefined,
  tickDecimals: number,
): { currency: number; ticks: number } | null {
  if (bidPrice == null || askPrice == null) return null;
  if (!Number.isFinite(bidPrice) || !Number.isFinite(askPrice)) return null;
  if (askPrice <= bidPrice) return null;
  const currency = askPrice - bidPrice;
  const tickSize = 10 ** -tickDecimals;
  const ticks = Math.round(currency / tickSize);
  return { currency, ticks };
}

/** Discriminated, display-ready row for the legs table (§14.3). */
export interface NormalizedLegRow {
  key: string;
  /** "leg": a full QuoteLeg (per side). "quote": a cache ack/status dict (per quote). */
  shape: "leg" | "quote";
  quote_id: string;
  symbol: string | null;
  order_id: string | null;
  leg_side: Side | null;
  price: number | null;
  qty: number | null;
  remaining: number | null;
  filled: number | null;
  status: string | null;
  quote_status: string | null;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
function str(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

/**
 * Normalize the dual-shaped `GET /quotes/legs` response (§14.3). Each element is
 * either a full pm-msgen QuoteLeg (engine path) or a per-quote ack/status dict
 * (warm-cache path). The presence of `leg_side` + `order_id` discriminates a
 * true leg; otherwise it is treated as a quote-level row with per-leg fields
 * blank. `filled` is taken as given, else derived from `qty - remaining`.
 */
export function normalizeQuoteLegRows(legs: unknown[]): NormalizedLegRow[] {
  const rows: NormalizedLegRow[] = [];
  legs.forEach((raw, i) => {
    if (raw === null || typeof raw !== "object") return;
    const r = raw as Record<string, unknown>;
    const quoteId = str(r.quote_id) ?? "";
    const legSide = r.leg_side === "BUY" || r.leg_side === "SELL" ? (r.leg_side as Side) : null;
    const orderId = str(r.order_id);
    const isLeg = legSide !== null && orderId !== null && "qty" in r;
    if (isLeg) {
      const qty = num(r.qty);
      const remaining = num(r.remaining);
      const filled = num(r.filled) ?? (qty !== null && remaining !== null ? Math.max(0, qty - remaining) : null);
      rows.push({
        key: `leg-${quoteId}-${orderId}-${i}`,
        shape: "leg",
        quote_id: quoteId,
        symbol: str(r.symbol),
        order_id: orderId,
        leg_side: legSide,
        price: num(r.price),
        qty,
        remaining,
        filled,
        status: str(r.status),
        quote_status: str(r.quote_status),
      });
    } else {
      // Warm-cache quote-level dict: {quote_id, accepted, reason, bid_order_id,
      // ask_order_id, status}. Only quote-level fields are meaningful.
      rows.push({
        key: `quote-${quoteId}-${i}`,
        shape: "quote",
        quote_id: quoteId,
        symbol: str(r.symbol),
        order_id: null,
        leg_side: null,
        price: null,
        qty: null,
        remaining: null,
        filled: null,
        status: str(r.status),
        quote_status: str(r.status),
      });
    }
  });
  return rows;
}
