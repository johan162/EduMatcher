/**
 * Viewer font-size preference, persisted to localStorage — same pattern as
 * useThemeStore. Client-only display state, not credentials.
 *
 * The app's text is almost all set in fixed-pixel Tailwind classes
 * (text-[10px], text-[11px], ...), not rem, so a root font-size change alone
 * would leave most of the UI unaffected. Instead the whole app is scaled with
 * CSS `zoom` (applied to #root, see applyFontSizeToDocument), which resizes
 * text, icons, padding and borders together, uniformly, for every size.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type FontSize = "XS" | "S" | "M" | "L" | "XL" | "XXL";

/** XS is the app's current default size; the rest scale up from it. */
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
    { name: "trader-font-size" },
  ),
);

/**
 * Reflect the size onto #root via CSS zoom. Kept outside the store so the
 * store stays a pure data container that tests can drive without a DOM.
 */
export function applyFontSizeToDocument(fontSize: FontSize): void {
  const root = document.getElementById("root");
  if (root) root.style.zoom = String(FONT_SIZE_FACTOR[fontSize]);
}
