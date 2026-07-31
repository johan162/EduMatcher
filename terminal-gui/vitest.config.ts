import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["packages/*/test/**/*.test.ts", "apps/*/test/**/*.test.{ts,tsx}"],
    // Node is right for the protocol and bridge suites, which are the
    // majority; the handful of component tests opt into jsdom with a
    // `@vitest-environment` docblock rather than paying for it everywhere.
    environment: "node",
    // Runs in every environment but no-ops outside jsdom. Repairs a
    // `localStorage` global that Node 22.4+ defines and leaves inert, which
    // otherwise shadows jsdom's and makes the suite pass or fail depending on
    // the developer's Node version.
    setupFiles: ["./test/setup-dom.ts"],
  },
});
