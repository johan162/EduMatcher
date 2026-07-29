/** UI preferences persisted to localStorage (design §7.5, §14.4, §19). */

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Density = "comfortable" | "standard" | "compact";

interface PrefsStore {
  operatorName: string;
  density: Density;
  setOperatorName: (name: string) => void;
  setDensity: (density: Density) => void;
}

export const usePrefsStore = create<PrefsStore>()(
  persist(
    (set) => ({
      operatorName: "",
      density: "standard",
      setOperatorName: (operatorName) => set({ operatorName }),
      setDensity: (density) => set({ density }),
    }),
    { name: "log-ui-prefs" },
  ),
);
