import { create } from "zustand";

export interface ActiveSymbolStore {
  activeSymbol: string | null;
  /**
   * Set the active symbol. Consumers (WorkspaceChart, DOM, ticket, etc.) re-bind
   * atomically. Also adjusts the focus subscription on the market-data WebSocket.
   */
  setActiveSymbol: (symbol: string) => void;
  clearActiveSymbol: () => void;
}

export const useActiveSymbolStore = create<ActiveSymbolStore>((set) => ({
  activeSymbol: null,
  setActiveSymbol: (symbol) => set({ activeSymbol: symbol }),
  clearActiveSymbol: () => set({ activeSymbol: null }),
}));
