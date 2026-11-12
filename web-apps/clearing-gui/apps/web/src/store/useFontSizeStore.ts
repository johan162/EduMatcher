/**
 * Viewer font-size preference, persisted to localStorage -- the same control
 * as trader-gui's. Text is set in fixed-pixel Tailwind classes, so the whole
 * app is scaled with CSS `zoom` on #root rather than via the root font-size.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type FontSize = "XS" | "S" | "M" | "L" | "XL" | "XXL";

export const FONT_SIZE_FACTOR: Record<FontSize, number> = {
  XS: 1,
  S: 1.15,
  M: 1.25,
  L: 1.4,
  XL: 1.55,
  XXL: 1.85,
};

export const FONT_SIZE_ORDER: FontSize[] = ["XS", "S", "M", "L", "XL", "XXL"];

interface FontSizeStore {
  fontSize: FontSize;
  setFontSize: (fontSize: FontSize) => void;
}

export const useFontSizeStore = create<FontSizeStore>()(
  persist(
    (set) => ({
      fontSize: "M",
      setFontSize: (fontSize) => set({ fontSize }),
    }),
    { name: "clearing-font-size" },
  ),
);

export function applyFontSizeToDocument(fontSize: FontSize): void {
  const root = document.getElementById("root");
  if (root) root.style.zoom = String(FONT_SIZE_FACTOR[fontSize]);
}
