import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["packages/*/test/**/*.test.ts", "apps/*/test/**/*.test.{ts,tsx}"],
    // Node is right for the protocol and bridge suites, which are the
    // majority; the handful of component tests opt into jsdom with a
    // `@vitest-environment` docblock rather than paying for it everywhere.
    environment: "node",
    // Runs in every environment but no-ops outside jsdom, where it installs
    // the one `localStorage` every Node agrees on. Neither jsdom's nor Node's
    // own can be relied on: which of them the bare global resolves to depends
    // on the Node version, and Node's is inert without --localstorage-file.
    setupFiles: ["./test/setup-dom.ts"],
  },
});
