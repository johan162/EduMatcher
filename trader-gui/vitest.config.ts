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
    // Node is right for utility/store suites; component tests opt into jsdom
    // with a `@vitest-environment jsdom` docblock instead of paying for it everywhere.
    environment: "node",
    // Runs in every environment but no-ops outside jsdom. Ensures a working
    // localStorage global inside jsdom tests.
    setupFiles: ["./test/setup-dom.ts"],
  },
});
