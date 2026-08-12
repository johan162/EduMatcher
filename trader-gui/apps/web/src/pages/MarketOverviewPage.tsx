import { useEffect, useMemo, useState } from "react";
import type { SortingState } from "@tanstack/react-table";
import { Search, RefreshCw, Loader2 } from "lucide-react";
import { MarketTable } from "@/components/market/MarketTable.js";
import { useDailyStatsQuery, useSymbolsQuery } from "@/queries/index.js";
import { useThrottledBooks } from "@/hooks/useThrottledBooks.js";
import { useActiveSymbol } from "@/hooks/useActiveSymbol.js";
import { useBookStore } from "@/store/useBookStore.js";
import { useHaltStore } from "@/store/useHaltStore.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useWatchlistStore } from "@/store/useWatchlistStore.js";
import { buildMarketRows, filterRows, isAuctionPhase } from "@/lib/marketRows.js";

/**
 * Market Overview (§10) — the reference "board" view, available to all roles.
 *
 * Live prices come from the always-on broad `*` book/trades subscription; the
 * derived columns (change %, volume) come from the polled daily rollup. Row
 * click sets the global active symbol, which the Trading Workspace and the
 * order ticket follow (§18.1.6).
 */
export function MarketOverviewPage() {
  const symbolsQuery = useSymbolsQuery();
  const dailyQuery = useDailyStatsQuery();

  const setSymbols = useSymbolStore((s) => s.setSymbols);
  const symbols = useSymbolStore((s) => s.symbols);
  const halts = useHaltStore((s) => s.halts);
  const phase = useSessionStore((s) => s.phase);
  const watchlist = useWatchlistStore((s) => s.symbols);
  const toggleWatch = useWatchlistStore((s) => s.toggle);
  const books = useThrottledBooks();
  const [activeSymbol, setActiveSymbol] = useActiveSymbol();

  const [query, setQuery] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "symbol", desc: false }]);

  // `GET /symbols` carries tick_decimals and prev_close per caller; merge it
  // over whatever the login bootstrap seeded from the reference bundle so the
  // two sources cannot drift into separate symbol lists.
  const fetched = symbolsQuery.data?.symbols;
  useEffect(() => {
    if (!fetched) return;
    const existing = new Map(useSymbolStore.getState().symbols.map((s) => [s.symbol, s]));
    setSymbols(
      fetched.map((dto) => ({
        symbol: dto.symbol,
        tick_decimals: dto.tick_decimals,
        prev_close: dto.prev_close ?? null,
        reference_price: existing.get(dto.symbol)?.reference_price ?? null,
        level: existing.get(dto.symbol)?.level ?? null,
      })),
    );
  }, [fetched, setSymbols]);

  // A fresh rollup already contains every print up to its own query time, so
  // the live top-up accumulated since the previous one is spent.
  const dailyUpdatedAt = dailyQuery.dataUpdatedAt;
  useEffect(() => {
    if (dailyUpdatedAt > 0) useBookStore.getState().resetLiveVolume();
  }, [dailyUpdatedAt]);

  const rows = useMemo(
    () =>
      filterRows(
        buildMarketRows({
          symbols,
          books,
          daily: dailyQuery.data ?? {},
          halts,
          watchlist,
        }),
        query,
      ),
    [symbols, books, dailyQuery.data, halts, watchlist, query],
  );

  const loading = symbolsQuery.isLoading;
  const empty = !loading && symbols.length === 0;

  return (
    <div className="flex flex-col h-full gap-3">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-semibold text-[#e8e8f0]">Market Overview</h1>

        <div className="relative">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[#505070]" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter symbols…"
            aria-label="Filter symbols"
            className="bg-[#1a1a28] border border-[#2a2a45] rounded pl-7 pr-2 py-1 text-xs font-mono w-48 focus:outline-none focus:border-[#3a3a60]"
          />
        </div>

        <span className="text-xs text-[#505070]">
          {rows.length} {rows.length === 1 ? "symbol" : "symbols"}
        </span>

        {/* The rollup is optional data: a venue with no stats database still
            shows live prices, just without change % and volume. */}
        {dailyQuery.isError && (
          <span className="text-xs text-halt">Daily rollup unavailable — Chg %/Volume hidden</span>
        )}

        <button
          type="button"
          onClick={() => {
            void symbolsQuery.refetch();
            void dailyQuery.refetch();
          }}
          className="ml-auto flex items-center gap-1 text-xs text-[#9090b0] hover:text-[#e8e8f0]"
        >
          <RefreshCw size={12} />
          Refresh
        </button>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-[#9090b0]">
          <Loader2 size={14} className="animate-spin" />
          Loading symbols…
        </div>
      )}

      {empty && (
        <div className="flex flex-col items-start gap-2 border border-[#2a2a45] rounded p-6">
          <p className="text-sm text-[#9090b0]">No symbols available — is pm-api-gwy running?</p>
          {symbolsQuery.isError && (
            <p className="text-xs text-[#505070]">{String(symbolsQuery.error)}</p>
          )}
          <button
            type="button"
            onClick={() => void symbolsQuery.refetch()}
            className="mt-1 px-3 py-1 rounded bg-[#20203a] text-xs hover:bg-[#2a2a45]"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !empty && (
        <MarketTable
          rows={rows}
          sorting={sorting}
          onSortingChange={setSorting}
          activeSymbol={activeSymbol}
          showAuction={isAuctionPhase(phase)}
          onSelect={setActiveSymbol}
          onToggleWatch={toggleWatch}
        />
      )}
    </div>
  );
}
