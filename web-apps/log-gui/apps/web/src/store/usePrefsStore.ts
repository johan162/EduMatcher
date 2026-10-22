/** UI preferences persisted to localStorage (design §7.5, §14.4, §19). */

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface PrefsStore {
  operatorName: string;
  setOperatorName: (name: string) => void;
}

export const usePrefsStore = create<PrefsStore>()(
  persist(
    (set) => ({
      operatorName: "",
      setOperatorName: (operatorName) => set({ operatorName }),
    }),
    { name: "log-ui-prefs" },
  ),
);
