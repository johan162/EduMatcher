import { WatchlistPanel } from "@/components/watchlist/WatchlistPanel.js";
import { useWatchlistStore } from "@/store/useWatchlistStore.js";

/**
 * Watchlist screen (§20.4) — available to all roles. A thin wrapper around the
 * shared {@link WatchlistPanel}, which also drives the market-data focus set.
 */
export function WatchlistPage() {
  const count = useWatchlistStore((s) => s.symbols.length);
  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-[#e8e8f0]">Watchlist</h1>
        <span className="text-[11px] text-[#505070]">
          {count} {count === 1 ? "symbol" : "symbols"}
        </span>
      </div>
      <WatchlistPanel />
    </div>
  );
}
