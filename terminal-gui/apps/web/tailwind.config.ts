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
        // A quieter divider than `border`, for the row rules inside a
        // table. Declared rather than written as `border-border/40`, which
        // compiles to nothing: these tokens are bare `var(--x)` and Tailwind
        // cannot synthesise an alpha channel from one (T-L2's sibling).
        "border-subtle": "var(--border-subtle)",
        fg: "var(--fg)",
        "fg-subtle": "var(--fg-subtle)",
        "fg-faint": "var(--fg-faint)",
        accent: "var(--accent)",
        "accent-fg": "var(--accent-fg)",

        up: "var(--up)",
        down: "var(--down)",
        // Semi-transparent fills for the depth ladder's cumulative bars,
        // carrying their own opacity for the same reason `halt-bg` does.
        "up-bg": "var(--up-bg)",
        "down-bg": "var(--down-bg)",
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
        // The fifth of that set, missed when the other four were declared
        // (T-L2). Used on the form controls in TradeTape and IndexView,
        // where it had been resolving to nothing and leaving them
        // transparent against the page.
        surface: "var(--bg-raised)",
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
