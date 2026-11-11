import type { Config } from "tailwindcss";

/**
 * Colours are CSS variables holding RGB channels (src/index.css), the same
 * tokens trader-gui uses, so the two applications look alike. `bid`/`ask` are
 * used for positive/negative amounts here, never for buy/sell actions.
 */
const channel = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        app: channel("app"),
        panel: channel("panel"),
        raised: channel("raised"),
        elevated: channel("elevated"),
        line: channel("line"),
        fg: channel("fg"),
        "fg-dim": channel("fg-dim"),
        "fg-faint": channel("fg-faint"),
        link: channel("link"),
        bid: channel("bid"),
        ask: channel("ask"),
        halt: channel("halt"),
        accent: channel("accent"),
        "accent-fg": channel("accent-fg"),
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "ui-monospace", "SFMono-Regular", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
