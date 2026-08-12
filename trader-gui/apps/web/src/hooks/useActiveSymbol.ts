import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";
import { subscribeMarketData } from "@/ws/WebSocketManager.js";

/**
 * Returns [activeSymbol, setActiveSymbol].
 * Setting a new symbol also ensures it is subscribed on the focused channels
 * (book, trades, depth, auction).
 */
export function useActiveSymbol(): [string | null, (sym: string) => void] {
  const activeSymbol = useActiveSymbolStore((s) => s.activeSymbol);
  const rawSet = useActiveSymbolStore((s) => s.setActiveSymbol);

  const setActiveSymbol = (sym: string) => {
    rawSet(sym);
    // Ensure this symbol has depth + auction subscriptions.
    subscribeMarketData([{ symbols: [sym], channels: ["book", "trades", "depth", "auction"] }]);
  };

  return [activeSymbol, setActiveSymbol];
}
