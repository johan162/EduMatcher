/**
 * Explain mode, one choice for the whole app, persisted to localStorage
 * (as in clearing-gui). On by default: the audit GUI is used in teaching.
 * On, figures show how they are made (formulas, explain lines, pictures);
 * off, the screens are the compact operator view. Words beside signs and the
 * teaching empty states do not depend on it.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ExplainStore {
  explain: boolean;
  setExplain: (explain: boolean) => void;
}

export const useExplainStore = create<ExplainStore>()(
  persist(
    (set) => ({
      explain: true,
      setExplain: (explain) => set({ explain }),
    }),
    { name: "audit-explain" },
  ),
);
