import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "apps/web/src"),
    },
  },
  test: {
    include: ["apps/*/test/**/*.test.{ts,tsx}"],
    // Node for pure-function suites; component suites opt into jsdom with a
    // `@vitest-environment jsdom` docblock (same convention as trader-gui).
    environment: "node",
    setupFiles: ["./test/setup-dom.ts"],
  },
});
