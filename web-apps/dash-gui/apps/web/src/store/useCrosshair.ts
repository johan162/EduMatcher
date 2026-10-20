/**
 * The hovered instant, shared by every time-series chart (design §13): one
 * chart is hovered, every chart in view draws the same vertical line.
 */

import { create } from "zustand";

interface Crosshair {
  /** Epoch ms under the pointer, or null. */
  ts: number | null;
  setTs: (ts: number | null) => void;
}

export const useCrosshair = create<Crosshair>()((set) => ({
  ts: null,
  setTs: (ts) => set({ ts }),
}));
