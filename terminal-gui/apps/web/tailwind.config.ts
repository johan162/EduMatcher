import type { Config } from "tailwindcss";

/**
 * Colors are CSS variables (see src/index.css) so the same class names produce
 * the dark or light palette depending on the `.dark` class on <html>. Same
 * approach as log-gui; token names follow design §15.
 */
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        "bg-subtle": "var(--bg-subtle)",
        "bg-inset": "var(--bg-inset)",
        "bg-raised": "var(--bg-raised)",
        border: "var(--border)",
        "border-strong": "var(--border-strong)",
        fg: "var(--fg)",
        "fg-subtle": "var(--fg-subtle)",
        "fg-faint": "var(--fg-faint)",
        accent: "var(--accent)",
        "accent-fg": "var(--accent-fg)",

        up: "var(--up)",
        down: "var(--down)",
        halt: "var(--halt)",
        "halt-bg": "var(--halt-bg)",
        auction: "var(--auction)",
        "auction-bg": "var(--auction-bg)",
        live: "var(--live)",
        offline: "var(--offline)",

        /*
         * Aliases, not new palette entries.
         *
         * These four names were already in use across the views — `bg-muted`
         * on table headers and bar tracks, `text-ok`/`text-error` on the halt
         * corridor marker, `text-warning` on the closing-backstop notice — but
         * were never declared here, so every one of them resolved to nothing
         * and the elements rendered unstyled.
         *
         * Each maps onto the token that already carries that meaning rather
         * than introducing a colour of its own: retuning the palette in
         * index.css must not leave a second, divergent set behind.
         */
        muted: "var(--bg-inset)",
        ok: "var(--up)",
        error: "var(--down)",
        // Amber. The backstop notice is a caution about how a price was
        // arrived at, which is the same register as a halt.
        warning: "var(--halt)",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
