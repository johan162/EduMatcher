/**
 * Viewer table preferences, persisted to localStorage — as dash-gui keeps its
 * Participants page size. Client-only display state, not credentials.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

/** Row counts offered by the paged tables, as in dash-gui; 0 is all of them. */
export const PAGE_SIZES = [10, 30, 50, 100, 0] as const;

interface PrefsStore {
  /** Participants per page on the Participants page. See `PAGE_SIZES`. */
  participantsPageSize: number;
  setParticipantsPageSize: (rows: number) => void;
}

export const usePrefsStore = create<PrefsStore>()(
  persist(
    (set) => ({
      participantsPageSize: 30,
      setParticipantsPageSize: (participantsPageSize) => set({ participantsPageSize }),
    }),
    { name: "trader-prefs" },
  ),
);
