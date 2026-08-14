import { useMemo } from "react";
import { FlashCell } from "@/components/shared/FlashCell.js";
import { ChangeCell, WatchStar } from "@/components/market/Badges.js";
import { useDailyStatsQuery } from "@/queries/index.js";
import { useThrottledBooks } from "@/hooks/useThrottledBooks.js";
import { useActiveSymbol } from "@/hooks/useActiveSymbol.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useHaltStore } from "@/store/useHaltStore.js";
import { useWatchlistStore } from "@/store/useWatchlistStore.js";
import { useSymbolDetailStore } from "@/store/useSymbolDetailStore.js";
import { buildMarketRows } from "@/lib/marketRows.js";
import { formatPrice } from "@/lib/formatters.js";
import { EmptyState } from "@/components/shared/EmptyState.js";
import { Star } from "lucide-react";

/**
 * Watchlist panel (§20.4) — a compact board of the user's starred symbols. The
 * watchlist set also drives the market-data focus subscription (via
 * {@link useMarketDataSubscription}), so these rows receive `book`/`trades`/
 * `depth`/`auction` even when not the active symbol. Row click sets the active
 * symbol and opens Symbol Detail; the star removes the symbol.
 */
export function WatchlistPanel() {
  const symbols = useSymbolStore((s) => s.symbols);
  const halts = useHaltStore((s) => s.halts);
  const watchlist = useWatchlistStore((s) => s.symbols);
  const toggleWatch = useWatchlistStore((s) => s.toggle);
  const books = useThrottledBooks();
  const dailyQuery = useDailyStatsQuery();
  const [activeSymbol] = useActiveSymbol();
  const openDetail = useSymbolDetailStore((s) => s.open);

  const rows = useMemo(
    () =>
      buildMarketRows({ symbols, books, daily: dailyQuery.data ?? {}, halts, watchlist }).filter(
        (r) => r.watched,
      ),
    [symbols, books, dailyQuery.data, halts, watchlist],
  );

  if (watchlist.length === 0) {
    return (
      <EmptyState
        icon={Star}
        title="Your watchlist is empty"
        hint="Star symbols on Market Overview to add them here."
      />
    );
  }

  return (
    <div className="overflow-auto rounded border border-[#2a2a45]">
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 z-10 bg-[#12121a] text-[#9090b0]">
          <tr>
            <th className="w-7 px-2 py-1.5" />
            <th className="px-2 py-1.5 text-left font-medium">Symbol</th>
            <th className="px-2 py-1.5 text-right font-medium">Last</th>
            <th className="px-2 py-1.5 text-right font-medium">Chg %</th>
            <th className="px-2 py-1.5 text-right font-medium">Bid</th>
            <th className="px-2 py-1.5 text-right font-medium">Ask</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.symbol}
              onClick={() => openDetail(r.symbol)}
              aria-selected={r.symbol === activeSymbol}
              className={`cursor-pointer border-b border-[#1a1a28] ${
                r.symbol === activeSymbol ? "bg-[#20203a]" : "hover:bg-[#1a1a28]"
              }`}
            >
              <td className="px-2 py-1">
                <WatchStar symbol={r.symbol} watched onToggle={toggleWatch} />
              </td>
              <td className="px-2 py-1 font-mono font-medium">{r.symbol}</td>
              <td className="px-2 py-1 text-right">
                <FlashCell value={r.last} formatter={(v) => formatPrice(v, r.tickDecimals)} />
              </td>
              <td className="px-2 py-1 text-right">
                <ChangeCell pct={r.changePct} />
              </td>
              <td className="px-2 py-1 text-right font-mono text-bid">
                {formatPrice(r.bid, r.tickDecimals)}
              </td>
              <td className="px-2 py-1 text-right font-mono text-ask">
                {formatPrice(r.ask, r.tickDecimals)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
