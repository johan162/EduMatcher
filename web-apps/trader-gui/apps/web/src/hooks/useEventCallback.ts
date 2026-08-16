import { useCallback, useLayoutEffect, useRef } from "react";

/**
 * Returns a function whose identity is stable across renders but which always
 * invokes the *latest* version of `fn` — the "latest ref" (a.k.a. `useEvent`)
 * pattern. The returned callback never changes, yet calling it runs the most
 * recent closure, so it never captures stale props or state.
 *
 * Use it for handlers passed to subscription-style APIs that bind or memoise
 * the callback once. In particular `react-hotkeys-hook` freezes a *stale*
 * closure when it is given a dependency array (it only tracks the latest
 * callback when deps are omitted); wrapping the handler here makes correctness
 * independent of that footgun instead of relying on remembering to omit deps.
 */
export function useEventCallback<A extends unknown[], R>(
  fn: (...args: A) => R,
): (...args: A) => R {
  const ref = useRef(fn);
  useLayoutEffect(() => {
    ref.current = fn;
  });
  return useCallback((...args: A) => ref.current(...args), []);
}
