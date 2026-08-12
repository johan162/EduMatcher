/**
 * Vitest global setup file.
 *
 * Loaded in every environment via vitest.config.ts `setupFiles`.
 * No-ops outside jsdom; inside jsdom it installs a working localStorage
 * that prevents test failures caused by Node 22.4+ defining (but not
 * implementing) the global.
 */
import { beforeEach } from "vitest";

if (typeof window !== "undefined" && typeof document !== "undefined") {
  // We are inside a jsdom environment. Patch localStorage if it is the inert
  // Node-built-in stub rather than jsdom's own implementation.
  const isInert =
    typeof localStorage === "undefined" ||
    localStorage?.constructor?.name === "Storage";

  if (isInert) {
    const store: Record<string, string> = {};
    const mock: Storage = {
      get length() {
        return Object.keys(store).length;
      },
      key: (i) => Object.keys(store)[i] ?? null,
      getItem: (k) => store[k] ?? null,
      setItem: (k, v) => {
        store[k] = String(v);
      },
      removeItem: (k) => {
        delete store[k];
      },
      clear: () => {
        for (const k of Object.keys(store)) delete store[k];
      },
    };
    Object.defineProperty(window, "localStorage", { value: mock });
  }

  beforeEach(() => {
    localStorage.clear();
  });
}
