import { useMemo, useState } from "react";
import { useBookStore } from "@/store/useBookStore.js";
import { useTicketPrefillStore } from "@/store/useTicketPrefillStore.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";
import type { Side } from "@/types/index.js";

const LEVEL_OPTIONS = [5, 10, 20] as const;
type LevelCount = (typeof LEVEL_OPTIONS)[number];

export interface DepthLadderProps {
  symbol: string;
  tickDecimals: number;
  /**
   * Click-to-trade handler (§16.3). Defaults to writing the click into the
   * ticket-prefill store; the Trading Workspace (phase 5) passes its own so
   * the shared ladder can drive different tickets.
   */
  onPriceClick?: (price: number, side: Side) => void;
}

/**
 * Order-book depth ladder (§16.3.1): bids left, asks right, a bar behind the
 * qty column proportional to that level's share of the deepest level in view.
 * The `book` snapshot carries the full multi-level arrays, so the ladder reads
 * them directly rather than inferring depth from top-of-book.
 */
export function DepthLadder({ symbol, tickDecimals, onPriceClick }: DepthLadderProps) {
  const [levels, setLevels] = useState<LevelCount>(10);
  const setPrefill = useTicketPrefillStore((s) => s.setPrefill);
  const entry = useBookStore((s) => s.books[symbol]);

  const handleClick = (price: number, side: Side) => {
    if (onPriceClick) onPriceClick(price, side);
    else setPrefill({ symbol, price, side });
  };

  const bids = useMemo(() => entry?.bids.slice(0, levels) ?? [], [entry?.bids, levels]);
  const asks = useMemo(() => entry?.asks.slice(0, levels) ?? [], [entry?.asks, levels]);
  const maxQty = useMemo(() => {
    const qtys = [...bids, ...asks].map((l) => l.qty);
    return qtys.length ? Math.max(...qtys) : 0;
  }, [bids, asks]);

  const empty = bids.length === 0 && asks.length === 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-xs text-[#9090b0]">Depth</span>
        <div className="ml-auto flex rounded border border-[#2a2a45] overflow-hidden">
          {LEVEL_OPTIONS.map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setLevels(n)}
              aria-pressed={levels === n}
              className={`px-2 py-0.5 text-xs font-mono ${
                levels === n ? "bg-[#20203a] text-[#e8e8f0]" : "text-[#9090b0] hover:bg-[#1a1a28]"
              }`}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {empty ? (
        <p className="text-xs text-[#505070] py-4 text-center">No resting depth for {symbol}.</p>
      ) : (
        <div className="grid grid-cols-2 gap-2 text-xs font-mono">
          {/* Bid side */}
          <div>
            <div className="flex justify-between text-[10px] text-[#505070] px-1 pb-1">
              <span>Cnt</span>
              <span>Qty</span>
              <span>Bid</span>
            </div>
            {bids.map((lvl, i) => (
              <button
                key={`${lvl.price}-${i}`}
                type="button"
                onClick={() => handleClick(lvl.price, "SELL")}
                title={`Sell at ${formatPrice(lvl.price, tickDecimals)}`}
                className="relative w-full flex justify-between px-1 py-0.5 hover:bg-[#1a1a28]"
              >
                <span
                  className="absolute inset-y-0 right-0 bg-bid/15"
                  style={{ width: maxQty ? `${(lvl.qty / maxQty) * 100}%` : "0%" }}
                  aria-hidden="true"
                />
                <span className="relative text-[#505070]">{lvl.count}</span>
                <span className="relative text-[#9090b0]">{formatQty(lvl.qty)}</span>
                <span className="relative text-bid">{formatPrice(lvl.price, tickDecimals)}</span>
              </button>
            ))}
          </div>

          {/* Ask side */}
          <div>
            <div className="flex justify-between text-[10px] text-[#505070] px-1 pb-1">
              <span>Ask</span>
              <span>Qty</span>
              <span>Cnt</span>
            </div>
            {asks.map((lvl, i) => (
              <button
                key={`${lvl.price}-${i}`}
                type="button"
                onClick={() => handleClick(lvl.price, "BUY")}
                title={`Buy at ${formatPrice(lvl.price, tickDecimals)}`}
                className="relative w-full flex justify-between px-1 py-0.5 hover:bg-[#1a1a28]"
              >
                <span
                  className="absolute inset-y-0 left-0 bg-ask/15"
                  style={{ width: maxQty ? `${(lvl.qty / maxQty) * 100}%` : "0%" }}
                  aria-hidden="true"
                />
                <span className="relative text-ask">{formatPrice(lvl.price, tickDecimals)}</span>
                <span className="relative text-[#9090b0]">{formatQty(lvl.qty)}</span>
                <span className="relative text-[#505070]">{lvl.count}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <p className="text-[10px] text-[#505070]">
        Click a bid to pre-fill a SELL, an ask to pre-fill a BUY.
      </p>
    </div>
  );
}
