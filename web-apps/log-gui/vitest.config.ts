import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["packages/*/test/**/*.test.ts", "apps/*/test/**/*.test.{ts,tsx}"],
    // Component tests opt into jsdom with a `@vitest-environment` docblock; the
    // setup file gives them a working localStorage (see test/setup-dom.ts).
    setupFiles: ["./test/setup-dom.ts"],
  },
});
