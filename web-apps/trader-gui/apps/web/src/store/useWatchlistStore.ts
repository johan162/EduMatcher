import { create } from "zustand";

interface WatchlistStore {
  symbols: string[];
  add: (sym: string) => void;
  remove: (sym: string) => void;
  toggle: (sym: string) => void;
  contains: (sym: string) => boolean;
}

export const useWatchlistStore = create<WatchlistStore>((set, get) => ({
  symbols: [],

  add: (sym) =>
    set((s) => ({
      symbols: s.symbols.includes(sym) ? s.symbols : [...s.symbols, sym],
    })),

  remove: (sym) =>
    set((s) => ({
      symbols: s.symbols.filter((s2) => s2 !== sym),
    })),

  toggle: (sym) => {
    const store = get();
    store.contains(sym) ? store.remove(sym) : store.add(sym);
  },

  contains: (sym) => get().symbols.includes(sym),
}));
