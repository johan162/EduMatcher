import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";

/**
 * Returns [activeSymbol, setActiveSymbol].
 *
 * Setting a symbol only writes the store: `useMarketDataSubscription`
 * (mounted at the app root) derives the focus subscription from the store and
 * diffs it. Subscribing here as a side effect of the setter was what let the
 * old focus set grow without bound — nothing ever unsubscribed the symbol
 * that had just been replaced.
 */
export function useActiveSymbol(): [string | null, (sym: string) => void] {
  const activeSymbol = useActiveSymbolStore((s) => s.activeSymbol);
  const setActiveSymbol = useActiveSymbolStore((s) => s.setActiveSymbol);
  return [activeSymbol, setActiveSymbol];
}
