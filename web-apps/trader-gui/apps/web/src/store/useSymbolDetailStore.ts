import { create } from "zustand";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";

/**
 * Controls the Symbol Detail right-panel overlay (§16).
 *
 * The overlay is deliberately gated on its own `isOpen` flag rather than on
 * `activeSymbol` alone: the Trading Workspace (phase 5) sets the active symbol
 * without wanting the overlay, so opening is an explicit action taken by the
 * Market Overview row click. `open` also sets the active symbol so the panel's
 * live cells and the focus subscription bind atomically.
 */
interface SymbolDetailStore {
  isOpen: boolean;
  open: (symbol: string) => void;
  close: () => void;
}

export const useSymbolDetailStore = create<SymbolDetailStore>((set) => ({
  isOpen: false,
  open: (symbol) => {
    useActiveSymbolStore.getState().setActiveSymbol(symbol);
    set({ isOpen: true });
  },
  close: () => set({ isOpen: false }),
}));
