import type { Config } from "tailwindcss";

/**
 * Colours are CSS variables holding space-separated RGB channels (see
 * src/index.css), so the same class names produce the dark or light palette
 * depending on the `.dark` class on <html> -- and opacity modifiers such as
 * `bg-bid/15` keep working. Same mechanism as terminal-gui.
 */
const channel = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // ── Surfaces, darkest to lightest in the dark palette ──────────────
        app: channel("app"), // page background
        deep: channel("deep"), // order ticket / recessed areas
        panel: channel("panel"), // top bar, sidebar, cards, popovers
        raised: channel("raised"), // inputs, hovered rows
        elevated: channel("elevated"), // active tab / selected row
        elevated2: channel("elevated2"), // hover on an elevated surface
        line: channel("line"), // borders and dividers
        // ── Text ───────────────────────────────────────────────────────────
        fg: channel("fg"),
        "fg-soft": channel("fg-soft"),
        "fg-dim": channel("fg-dim"),
        "fg-mute": channel("fg-mute"),
        "fg-faint": channel("fg-faint"),
        link: channel("link"),
        // ── Semantic trading colours ───────────────────────────────────────
        bid: channel("bid"), // buy/bid / BUY action button
        ask: channel("ask"), // sell/ask / SELL action button
        flash: {
          up: "rgba(34, 197, 94, 0.4)",
          down: "rgba(239, 68, 68, 0.4)",
        },
        up: channel("bid"),
        down: channel("ask"),
        halt: channel("halt"),
        auction: channel("halt"),
        live: channel("bid"),
        offline: channel("ask"),
        // Brand wordmark version number only (TopBar) — kept apart from
        // the price-direction tokens above.
        "brand-version": channel("brand-version"),
      },
      // ── Typography ────────────────────────────────────────────────────────
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "ui-monospace", "SFMono-Regular", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      // ── Animation ─────────────────────────────────────────────────────────
      keyframes: {
        "flash-up": {
          "0%": { backgroundColor: "rgba(34, 197, 94, 0.4)" },
          "100%": { backgroundColor: "transparent" },
        },
        "flash-down": {
          "0%": { backgroundColor: "rgba(239, 68, 68, 0.4)" },
          "100%": { backgroundColor: "transparent" },
        },
        "fade-in": {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
      },
      animation: {
        "flash-up": "flash-up 500ms ease-out forwards",
        "flash-down": "flash-down 500ms ease-out forwards",
        "fade-in": "fade-in 150ms ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
