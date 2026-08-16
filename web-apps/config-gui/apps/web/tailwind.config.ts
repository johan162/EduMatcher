import type { Config } from "tailwindcss";

/**
 * Colors are driven by CSS variables (see src/index.css) so the same class
 * names produce the light or dark palette depending on the `.dark` class on
 * <html>. Semantic roles mirror design §6.
 */
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: "var(--color-bg)",
        surface: "var(--color-surface)",
        "surface-raised": "var(--color-surface-raised)",
        border: "var(--color-border)",
        muted: "var(--color-muted)",
        fg: "var(--color-fg)",
        "fg-subtle": "var(--color-fg-subtle)",
        accent: "var(--color-accent)",
        "accent-fg": "var(--color-accent-fg)",
        required: "var(--color-required)",
        "optional-set": "var(--color-optional-set)",
        "optional-default": "var(--color-optional-default)",
        warning: "var(--color-warning)",
        error: "var(--color-error)",
        linked: "var(--color-linked)",
        success: "var(--color-success)",
      },
    },
  },
  plugins: [],
};

export default config;
