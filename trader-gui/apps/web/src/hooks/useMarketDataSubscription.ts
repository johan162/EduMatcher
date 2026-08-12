import { useEffect } from "react";
import { setFocusSymbols } from "@/ws/WebSocketManager.js";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";
import { useWatchlistStore } from "@/store/useWatchlistStore.js";

/**
 * Keeps the market-data focus subscription in step with the UI (§17.3.1).
 *
 * The focus set is the active symbol plus the watchlist — the symbols the
 * heavy `depth`/`auction` channels are wanted for. The active symbol leads so
 * that when the set is capped it is the one thing guaranteed to survive.
 *
 * Mounted once at the app root; `setFocusSymbols` diffs against what the
 * gateway has been told, so re-running on every render of the watchlist is
 * cheap and sends nothing when the set is unchanged.
 */
export function useMarketDataSubscription(): void {
  const activeSymbol = useActiveSymbolStore((s) => s.activeSymbol);
  const watchlist = useWatchlistStore((s) => s.symbols);

  useEffect(() => {
    setFocusSymbols(activeSymbol ? [activeSymbol, ...watchlist] : watchlist);
  }, [activeSymbol, watchlist]);
}
