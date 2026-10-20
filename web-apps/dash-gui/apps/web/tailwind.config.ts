import type { Config } from "tailwindcss";

/**
 * Colors are CSS variables (see src/index.css) so the same class names produce
 * the dark or light palette depending on the `.dark` class on <html>. Same
 * approach as log-gui and book-gui; token names follow design §12.5.
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
        // Brand wordmark version number only (TopBar).
        "brand-version": "var(--brand-version)",

        live: "var(--live)",
        offline: "var(--offline)",

        /*
         * Health (design §12.5). `ok`, `error` and `warning` are book-gui's
         * alias names, pointed at the health tokens rather than adding a
         * second set of names for the same meaning.
         */
        ok: "var(--ok)",
        error: "var(--crit)",
        warning: "var(--warn)",
        "error-bg": "var(--crit-bg)",
        hung: "var(--hung)",
        missing: "var(--missing)",
        stopped: "var(--stopped)",
        info: "var(--info)",
        // Lines and areas only, never text (>= 3:1, not 4.5:1).
        "series-1": "var(--series-1)",
        "series-2": "var(--series-2)",
        "series-3": "var(--series-3)",
        "series-4": "var(--series-4)",
        "series-5": "var(--series-5)",
        "series-6": "var(--series-6)",
        "series-7": "var(--series-7)",
        "series-8": "var(--series-8)",

        // book-gui's aliases for the base tokens, kept so shared markup reads the same.
        muted: "var(--bg-inset)",
        surface: "var(--bg-raised)",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
