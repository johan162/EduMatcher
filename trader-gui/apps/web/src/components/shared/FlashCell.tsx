import { useRef, useEffect } from "react";
import { env } from "@/lib/env.js";

const FLASH_DURATION = parseInt(env("VITE_FLASH_DURATION_MS", "500"), 10) || 500;

interface FlashCellProps {
  value: number | null;
  formatter?: (v: number) => string;
  className?: string;
}

/**
 * Renders a numeric value and applies a green (up) or red (down) flash
 * animation when the value changes (§17.3.3).
 */
export function FlashCell({ value, formatter, className = "" }: FlashCellProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const prevRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || value === null) return;

    const prev = prevRef.current;
    prevRef.current = value;

    if (prev === null || value === prev) return;

    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      el.classList.remove("flash-up", "flash-down");
    }

    const cls = value > prev ? "flash-up" : "flash-down";
    void el.offsetWidth; // force reflow to restart animation
    el.classList.add(cls);

    timerRef.current = setTimeout(() => {
      el.classList.remove(cls);
      timerRef.current = null;
    }, FLASH_DURATION);
  }, [value]);

  const display =
    value === null ? "—" : formatter ? formatter(value) : String(value);

  return (
    <span
      ref={ref}
      className={`price-cell transition-colors ${className}`}
    >
      {display}
    </span>
  );
}
