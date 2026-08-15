import { useRef, useCallback } from "react";
import { env } from "@/lib/env.js";

const FLASH_DURATION = parseInt(env("VITE_FLASH_DURATION_MS", "500"), 10) || 500;

/**
 * Returns a ref and a trigger function. Call `flash(newValue, el)` whenever
 * the value changes; the element receives the appropriate CSS class for the
 * flash duration.
 */
export function useFlash<V extends number | null>(): {
  prevRef: React.MutableRefObject<V | null>;
  flash: (newValue: V | null, el: HTMLElement | null) => void;
} {
  const prevRef = useRef<V | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flash = useCallback((newValue: V | null, el: HTMLElement | null) => {
    if (el === null || newValue === null) return;
    const prev = prevRef.current;
    prevRef.current = newValue;

    if (prev === null || newValue === prev) return;

    // Clear any running animation.
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      el.classList.remove("flash-up", "flash-down");
    }

    const cls = newValue > prev ? "flash-up" : "flash-down";
    // Force a reflow so re-adding the class restarts the animation.
    void el.offsetWidth;
    el.classList.add(cls);

    timerRef.current = setTimeout(() => {
      el.classList.remove(cls);
      timerRef.current = null;
    }, FLASH_DURATION);
  }, []);

  return { prevRef, flash };
}
