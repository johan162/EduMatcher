/**
 * Guarantee a working `localStorage` under the jsdom environment.
 *
 * `usePrefsStore` persists through zustand's `persist` middleware, which
 * resolves `window.localStorage` when the store module is first imported — so
 * something has to be there before any test file loads, and the persistence
 * tests ("survives a reload") need it to be a genuine round trip rather than
 * a no-op.
 *
 * jsdom's own implementation cannot be relied on. Recent Node ships an
 * experimental `globalThis.localStorage`, and vitest's jsdom environment skips
 * copying any jsdom global whose name already exists on `globalThis` and is
 * not on its own list — `localStorage` is not on it. So on a Node that defines
 * the global, jsdom's implementation never reaches `globalThis` at all and the
 * bare `localStorage` resolves to Node's, which is inert without
 * `--localstorage-file`. Whether a test saw jsdom's storage or Node's depended
 * on the developer's Node version, which is the worst kind of test failure.
 *
 * So this installs the in-memory shim unconditionally. That is the point: one
 * implementation on every Node, chosen without asking which one is in play.
 * Asking was the expensive part — *reading* `globalThis.localStorage` to probe
 * it is what invokes Node's getter, and that emits an ExperimentalWarning once
 * per worker. The probe cost five lines of noise per run to pick between two
 * storages that both simply have to work.
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

// Node-environment suites (the protocol and bridge majority) have no window
// and no business with storage, so leave them entirely alone.
if (typeof window !== "undefined") {
  const storage = memoryStorage();
  // `configurable` matters: setup files run once per test file and a worker
  // handles several, so this has to be redefinable.
  const descriptor = { value: storage, configurable: true, writable: true };
  Object.defineProperty(globalThis, "localStorage", descriptor);
  // Keep the two views of the same global in step — application code reads
  // the bare `localStorage`, test helpers sometimes reach through `window`.
  Object.defineProperty(window, "localStorage", descriptor);
}
