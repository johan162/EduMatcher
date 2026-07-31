/**
 * Guarantee a working `localStorage` under the jsdom environment.
 *
 * Node 22.4+ ships its own experimental `globalThis.localStorage`, which is
 * inert unless the process was started with `--localstorage-file`. When that
 * global is present it shadows the one jsdom installs, so `localStorage` reads
 * back as `undefined` and every test that touches it fails — but only on Node
 * builds new enough to define it. The suite passed or failed depending on the
 * developer's Node version, which is the worst kind of test failure.
 *
 * This repairs the global before any test runs, preferring jsdom's real
 * implementation and falling back to an in-memory shim so the persistence
 * tests (`survives a reload`) still exercise a genuine round trip.
 */

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    removeItem: (key: string) => void map.delete(key),
    setItem: (key: string, value: string) => void map.set(key, String(value)),
  } as Storage;
}

function usable(candidate: unknown): candidate is Storage {
  if (!candidate) return false;
  try {
    const probe = "__edumatcher_probe__";
    (candidate as Storage).setItem(probe, "1");
    (candidate as Storage).removeItem(probe);
    return true;
  } catch {
    return false;
  }
}

// Node-environment suites (the protocol and bridge majority) have no window
// and no business with storage, so leave them entirely alone.
if (typeof window !== "undefined") {
  if (!usable(globalThis.localStorage)) {
    const replacement = usable(window.localStorage) ? window.localStorage : memoryStorage();
    Object.defineProperty(globalThis, "localStorage", {
      value: replacement,
      configurable: true,
      writable: true,
    });
    // Keep the two views of the same global in step — application code reads
    // the bare `localStorage`, test helpers sometimes reach through `window`.
    Object.defineProperty(window, "localStorage", {
      value: replacement,
      configurable: true,
      writable: true,
    });
  }
}
