import { useEffect, useRef, useState } from "react";
import { useBookStore } from "@/store/useBookStore.js";
import { envInt } from "@/lib/env.js";

const DEFAULT_INTERVAL_MS = envInt("VITE_MARKET_THROTTLE_MS", 250);

/**
 * A snapshot of the book store that changes identity at most every
 * `intervalMs` (§17.3.4).
 *
 * The engine republishes a full book per symbol roughly twice a second, so a
 * 100-symbol wildcard subscription is ~200 store writes per second. Rendering
 * a sortable, filterable table off the raw store would re-run the whole row
 * model that often. Throttling the *source of truth for layout* while leaving
 * the store itself untouched keeps sorting and filtering coherent (they see
 * one consistent snapshot) and bounds render work to 1/intervalMs, which is
 * still well inside the 500ms flash window so no price change is missed.
 */
export function useThrottledBooks(intervalMs = DEFAULT_INTERVAL_MS) {
  const [snapshot, setSnapshot] = useState(() => useBookStore.getState().books);
  const pending = useRef(false);

  useEffect(() => {
    // Leading-edge publish so the first frame after mount is not blank.
    setSnapshot(useBookStore.getState().books);

    const unsubscribe = useBookStore.subscribe(() => {
      if (pending.current) return;
      pending.current = true;
      setTimeout(() => {
        pending.current = false;
        setSnapshot(useBookStore.getState().books);
      }, intervalMs);
    });
    return unsubscribe;
  }, [intervalMs]);

  return snapshot;
}
