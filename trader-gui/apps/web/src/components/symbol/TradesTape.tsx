import { useMemo } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useBookStore } from "@/store/useBookStore.js";
import { useHistoryTradesQuery } from "@/queries/index.js";
import { formatPrice, formatQty, formatTime } from "@/lib/formatters.js";
import type { HistoryTrade } from "@/types/index.js";

const TAPE_LIMIT = 50;

/** A tape row normalised from either the history REST rows or the live tape. */
interface TapeRow {
  id: string;
  epochSec: number;
  price: number;
  quantity: number;
  aggressor: "BUY" | "SELL" | "AUCTION";
}

function fromHistory(t: HistoryTrade): TapeRow {
  return {
    id: t.trade_id,
    epochSec: Math.floor(Date.parse(t.ts) / 1000),
    price: t.price,
    quantity: t.quantity,
    aggressor: t.aggressor_side,
  };
}

interface TradesTapeProps {
  symbol: string;
  tickDecimals: number;
}

/**
 * Scrolling tape of recent prints (§16.4). Seeded from `GET /history/trades`
 * and topped with the live tape the book store accumulates from the `trade`
 * channel; the two are merged and de-duplicated by trade id so the seam
 * between "loaded at open" and "arrived live" is invisible. Price cell is
 * green when the aggressor was a buyer, red when a seller.
 */
export function TradesTape({ symbol, tickDecimals }: TradesTapeProps) {
  const historyQuery = useHistoryTradesQuery(symbol, TAPE_LIMIT);
  const live = useBookStore((s) => s.books[symbol]?.recentTrades);

  const rows = useMemo<TapeRow[]>(() => {
    const merged = new Map<string, TapeRow>();
    // History first, then live overwrites by id — live is the fresher copy.
    for (const t of historyQuery.data?.trades ?? []) merged.set(t.trade_id, fromHistory(t));
    for (const t of live ?? []) {
      merged.set(t.id, {
        id: t.id,
        epochSec: t.timestamp,
        price: t.price,
        quantity: t.quantity,
        aggressor: t.aggressor_side,
      });
    }
    return [...merged.values()].sort((a, b) => b.epochSec - a.epochSec).slice(0, TAPE_LIMIT);
  }, [historyQuery.data, live]);

  if (rows.length === 0) {
    return (
      <p className="text-xs text-[#505070] py-4 text-center">
        {historyQuery.isLoading ? "Loading trades…" : `No trades yet for ${symbol}.`}
      </p>
    );
  }

  return (
    <div className="overflow-auto max-h-[420px]">
      <table className="w-full text-xs font-mono border-collapse">
        <thead className="sticky top-0 bg-[#12121a] text-[10px] text-[#505070]">
          <tr>
            <th scope="col" className="text-left font-medium px-2 py-1">Time</th>
            <th scope="col" className="text-right font-medium px-2 py-1">Price</th>
            <th scope="col" className="text-right font-medium px-2 py-1">Qty</th>
            <th scope="col" className="text-center font-medium px-2 py-1">Aggr</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const buy = r.aggressor === "BUY";
            const sell = r.aggressor === "SELL";
            return (
              <tr key={r.id} className="border-b border-[#1a1a28]">
                <td className="px-2 py-0.5 text-[#9090b0]">{formatTime(r.epochSec)}</td>
                <td
                  className={`px-2 py-0.5 text-right ${
                    buy ? "text-bid" : sell ? "text-ask" : "text-[#9090b0]"
                  }`}
                >
                  {formatPrice(r.price, tickDecimals)}
                </td>
                <td className="px-2 py-0.5 text-right text-[#9090b0]">{formatQty(r.quantity)}</td>
                <td className="px-2 py-0.5">
                  <span className="flex items-center justify-center">
                    {buy && <ArrowUp size={11} className="text-bid" aria-label="buy aggressor" />}
                    {sell && (
                      <ArrowDown size={11} className="text-ask" aria-label="sell aggressor" />
                    )}
                    {!buy && !sell && <span className="text-[#505070]">A</span>}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
