/**
 * The venue's session timezone (IANA), once `GET /api/v1/session` has
 * answered; `null` until then, and times show in labelled UTC (lib/time.ts).
 * Set by `useVenueTimeZone` in the app shell; not persisted.
 */

import { create } from "zustand";

interface VenueTimeZoneStore {
  timeZone: string | null;
  setTimeZone: (timeZone: string | null) => void;
}

export const useVenueTimeZoneStore = create<VenueTimeZoneStore>()((set) => ({
  timeZone: null,
  setTimeZone: (timeZone) => set({ timeZone }),
}));
