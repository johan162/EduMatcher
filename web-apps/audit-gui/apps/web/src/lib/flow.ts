/**
 * The signed flow strip (design §9.4): aggressive volume per time bin,
 * buyer-initiated positive, seller-initiated negative. A trade without an
 * aggressor (an auction print) has no direction: it is counted, not signed.
 */
import type { EventT } from "@/api/schemas";
import { nsToMs } from "@/lib/ns";

export interface Trade {
  ms: number;
  priceTicks: number;
  qty: number;
  aggressor: "BUY" | "SELL" | null;
  auction: boolean;
  tradeId: string;
}

export function toTrade(e: EventT): Trade | null {
  const f = e.fields;
  const price = f["price_ticks"];
  const qty = f["quantity"];
  if (typeof price !== "number" || typeof qty !== "number") return null;
  const side = f["aggressor_side"];
  const match = f["match_type"];
  return {
    ms: nsToMs(e.receipt_ns),
    priceTicks: price,
    qty,
    aggressor: side === "BUY" || side === "SELL" ? side : null,
    auction: typeof match === "string" && match !== "CONTINUOUS",
    tradeId: typeof f["id"] === "string" ? f["id"] : e.key,
  };
}

export interface FlowBin {
  startMs: number;
  endMs: number;
  signed: number;
  unsigned: number;
}

/** Trades in [startMs, endMs) summed per bin of `binMs`. */
export function flowBins(trades: Trade[], startMs: number, endMs: number, binMs: number): FlowBin[] {
  const n = Math.max(1, Math.ceil((endMs - startMs) / binMs));
  const bins: FlowBin[] = Array.from({ length: n }, (_, i) => ({
    startMs: startMs + i * binMs,
    endMs: Math.min(startMs + (i + 1) * binMs, endMs),
    signed: 0,
    unsigned: 0,
  }));
  for (const t of trades) {
    if (t.ms < startMs || t.ms >= endMs) continue;
    const bin = bins[Math.floor((t.ms - startMs) / binMs)]!;
    if (t.aggressor === null) bin.unsigned += t.qty;
    else bin.signed += t.aggressor === "BUY" ? t.qty : -t.qty;
  }
  return bins;
}
