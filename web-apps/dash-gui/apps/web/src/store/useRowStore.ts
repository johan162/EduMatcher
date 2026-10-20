/**
 * Which dashboard rows are collapsed, remembered per browser (design §12.1;
 * lib/storage.ts, so a refusing localStorage only forgets).
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { prefsStorage } from "../lib/storage.js";

interface RowStore {
  collapsed: Record<string, boolean>;
  toggle: (id: string) => void;
}

export const useRowStore = create<RowStore>()(
  persist(
    (set, get) => ({
      collapsed: {},
      toggle: (id) => set({ collapsed: { ...get().collapsed, [id]: !get().collapsed[id] } }),
    }),
    { name: "dash-rows", storage: prefsStorage },
  ),
);
