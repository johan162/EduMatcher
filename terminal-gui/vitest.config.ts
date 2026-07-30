import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["packages/*/test/**/*.test.ts", "apps/*/test/**/*.test.{ts,tsx}"],
    // Node is right for the protocol and bridge suites, which are the
    // majority; the handful of component tests opt into jsdom with a
    // `@vitest-environment` docblock rather than paying for it everywhere.
    environment: "node",
  },
});
