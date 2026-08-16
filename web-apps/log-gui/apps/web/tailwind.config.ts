import type { Config } from "tailwindcss";

/**
 * Colors driven by CSS variables (see src/index.css) so the same class names
 * produce the dark or light palette depending on the `.dark` class on
 * <html>. Token names mirror design §14.1/§14.2.
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
        border: "var(--border)",
        fg: "var(--fg)",
        "fg-subtle": "var(--fg-subtle)",
        accent: "var(--accent)",

        "level-debug": "var(--level-debug)",
        "level-info": "var(--level-info)",
        "level-warning": "var(--level-warning)",
        "level-error": "var(--level-error)",
        "level-critical": "var(--level-critical)",
        "level-critical-bg": "var(--level-critical-bg)",
      },
    },
  },
  plugins: [],
};

export default config;
