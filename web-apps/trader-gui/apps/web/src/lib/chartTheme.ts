import type { ThemePreference } from "@/store/useThemeStore.js";

/**
 * Chart libraries paint to canvas/SVG attributes and cannot read the CSS
 * variables the rest of the UI themes with, so their colours live here as
 * literals. Values mirror the tokens in index.css.
 */
export interface ChartColors {
  background: string;
  text: string;
  grid: string;
  border: string;
  up: string;
  down: string;
  line: string;
  marker: string;
}

export const CHART_COLORS: Record<ThemePreference, ChartColors> = {
  dark: {
    background: "#0a0a0f",
    text: "#9090b0",
    grid: "#1a1a28",
    border: "#2a2a45",
    up: "#22c55e",
    down: "#ef4444",
    line: "#6ea8fe",
    marker: "#f59e0b",
  },
  light: {
    background: "#ffffff",
    text: "#55606f",
    grid: "#eaeef3",
    border: "#d5dbe3",
    up: "#15803d",
    down: "#dc2626",
    line: "#0b5fce",
    marker: "#b45309",
  },
};
