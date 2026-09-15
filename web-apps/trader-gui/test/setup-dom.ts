/**
 * Vitest global setup file.
 *
 * Loaded in every environment via vitest.config.ts `setupFiles`. No-ops
 * outside jsdom; inside jsdom it installs a working `localStorage`.
 *
 * It installs unconditionally, and the reason is worth recording because the
 * obvious guard is a trap twice over.
 *
 * Node defines its own experimental Web Storage `localStorage` global in
 * recent versions. vitest's jsdom environment copies jsdom's globals onto
 * `globalThis`, but skips any key that already exists there and is not on its
 * own list — and `localStorage` is not on it. So on a Node that defines the
 * global, jsdom's implementation never reaches `globalThis` and the bare
 * identifier resolves to Node's stub, which is why this file exists at all.
 *
 * The guard this replaced read `localStorage.constructor.name === "Storage"`
 * to tell Node's stub from jsdom's real one. That never discriminated
 * anything: jsdom's own `localStorage` reports the same constructor name, so
 * the mock was installed on every Node regardless. Worse, *reading* the global
 * is what invokes Node's getter, and that emits an ExperimentalWarning once
 * per worker — fifteen lines of noise per run to answer a question whose
 * answer was always the same.
 *
 * `configurable` matters: setup files run once per test file, and a worker
 * handles several. A non-configurable property would throw on the second.
 */
import { beforeEach } from "vitest";

if (typeof window !== "undefined" && typeof document !== "undefined") {
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
  Object.defineProperty(window, "localStorage", {
    value: mock,
    configurable: true,
    writable: true,
  });

  beforeEach(() => {
    localStorage.clear();
  });
}
