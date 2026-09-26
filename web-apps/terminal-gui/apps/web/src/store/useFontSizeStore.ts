/**
 * Viewer font-size preference, persisted to localStorage — same pattern as
 * usePrefsStore's theme. Client-only display state, not credentials.
 *
 * The app's text is almost all set in fixed-pixel Tailwind classes, not rem,
 * so a root font-size change alone would leave most of the UI unaffected.
 * Instead the whole app is scaled with CSS `zoom` (applied to #root, see
 * applyFontSizeToDocument), which resizes text, icons, padding and borders
 * together, uniformly, for every size. `zoom` is only standard in
 * Chromium/WebKit (Chrome, Safari) — Firefox is not supported.
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
      fontSize: "XS",
      setFontSize: (fontSize) => set({ fontSize }),
    }),
    { name: "terminal-font-size" },
  ),
);

/**
 * Reflect the size onto #root via CSS zoom, and expose the same factor as
 * the `--zoom` custom property.
 *
 * `zoom` scales #root's rendered output, but #root's own box (and anything
 * sized off the real viewport, like `100vh`) still measures itself in
 * unscaled pixels — so a layout that fills exactly `100vh` at zoom 1 renders
 * `100vh * zoom` tall on screen at any other zoom, pushing a fixed-height
 * shell's bottom chrome past the visible window. AppShell corrects for this
 * by sizing itself to `calc(100vh / var(--zoom))` instead of a bare
 * `100vh`, so the zoomed render lands back on exactly `100vh`.
 */
export function applyFontSizeToDocument(fontSize: FontSize): void {
  const root = document.getElementById("root");
  if (!root) return;
  const factor = FONT_SIZE_FACTOR[fontSize];
  root.style.zoom = String(factor);
  root.style.setProperty("--zoom", String(factor));
}
