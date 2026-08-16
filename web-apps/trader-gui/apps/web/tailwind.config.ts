import type { Config } from "tailwindcss";

/**
 * Dark trading-terminal palette (§22.3 of the design).
 * All values are hard-coded here (not CSS variables) to keep shadcn/ui
 * compatibility straightforward; colours can be migrated to CSS variables
 * later if a light-mode variant is needed.
 */
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // ── Backgrounds ────────────────────────────────────────────────────
        bg: {
          primary: "#0a0a0f", // near-black main background
          secondary: "#12121a", // panel background
          tertiary: "#1a1a28", // table row / input background
          elevated: "#20203a", // modal / dialog background
        },
        // ── Borders ────────────────────────────────────────────────────────
        border: {
          subtle: "#2a2a45",
          strong: "#3a3a60",
        },
        // ── Text ───────────────────────────────────────────────────────────
        text: {
          primary: "#e8e8f0",
          secondary: "#9090b0",
          muted: "#505070",
        },
        // ── Semantic trading colours ───────────────────────────────────────
        bid: "#22c55e", // green — buy/bid / BUY action button
        ask: "#ef4444", // red   — sell/ask / SELL action button
        flash: {
          up: "rgba(34, 197, 94, 0.4)",
          down: "rgba(239, 68, 68, 0.4)",
        },
        // ── Status colours (re-used from design) ──────────────────────────
        up: "#22c55e",
        down: "#ef4444",
        halt: "#f59e0b",
        auction: "#f59e0b",
        live: "#22c55e",
        offline: "#ef4444",
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
